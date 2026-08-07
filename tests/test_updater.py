from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

import yaml
from aiohttp import web
from aiohttp.test_utils import TestServer

from jvlei_update.package import build_package, sha256_file, verify_package
from jvlei_update.updater import ApplicationInstaller, StateStore, UpdaterConfig, UpdaterError, UpdaterService
from update_center.run import install_signal_handlers
from update_center.server import CenterStore


def supports_directory_symlinks() -> bool:
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            return link.is_symlink()
    except OSError:
        return False


SUPPORTS_DIRECTORY_SYMLINKS = supports_directory_symlinks()


class UpdateCenterRuntimeTests(unittest.TestCase):
    def test_windows_event_loop_without_signal_handlers_is_supported(self) -> None:
        class UnsupportedSignalLoop:
            def add_signal_handler(self, sig, callback) -> None:
                raise NotImplementedError

        self.assertFalse(install_signal_handlers(UnsupportedSignalLoop(), Mock()))


def build_test_package(
    path: Path,
    product: str = "h618-report-gateway",
    package_type: str = "application",
) -> None:
    payload = path.with_suffix(".payload.tar.gz")
    with tarfile.open(payload, "w:gz") as archive:
        content = b"application"
        member = tarfile.TarInfo("README.txt")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))
    build_package(
        payload,
        {
            "package_id": "h618-report-gateway-0.21.0-test",
            "package_type": package_type,
            "product": product,
            "version": "0.21.0",
            "arch": "all",
            "compatible_versions": ["0.20.0"],
            "created_at": "2026-08-06T00:00:00+00:00",
            "release_notes": "test",
            "git_commit": "0123456789abcdef",
            "migration_level": 0,
            "requires_gadget_restart": False,
            "requires_cups_restart": False,
        },
        path,
        allow_unsigned=True,
    )


def build_installable_application_package(path: Path, version: str = "0.21.0") -> None:
    """Create the minimum valid application tree required by ApplicationInstaller."""

    payload = path.with_suffix(".payload.tar.gz")
    files = {
        "pyproject.toml": f'[project]\nname = "gateway"\nversion = "{version}"\n'.encode(),
        "src/gadget_msc_printer/__init__.py": b"",
        "scripts/placeholder.py": b"",
        "scripts/apply_gadget_mode.sh": b"#!/bin/sh\nexit 0\n",
        "portal/portal/dist/index.html": b"<!doctype html>",
    }
    with tarfile.open(payload, "w:gz") as archive:
        for name, content in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    build_package(
        payload,
        {
            "package_id": f"h618-report-gateway-{version}-install-test",
            "package_type": "application",
            "product": "h618-report-gateway",
            "version": version,
            "arch": "all",
            "compatible_versions": ["0.20.0"],
            "created_at": "2026-08-06T00:00:00+00:00",
            "release_notes": "installer test",
            "git_commit": "0123456789abcdef",
            "migration_level": 0,
            "requires_gadget_restart": False,
            "requires_cups_restart": False,
        },
        path,
        allow_unsigned=True,
    )


class UpdaterServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / "gateway.jvpkg"
        build_test_package(self.package)
        self.downloads = 0
        self.reports: list[dict[str, object]] = []
        self.assignment = {
            "id": "assignment-1",
            "action": "download",
            "status": "queued",
            "package": {
                "id": "a" * 32,
                "package_id": "h618-report-gateway-0.21.0-test",
                "package_type": "application",
                "version": "0.21.0",
                "product": "h618-report-gateway",
                "arch": "all",
                "sha256": sha256_file(self.package),
                "size_bytes": self.package.stat().st_size,
                "signed": False,
            },
        }
        app = web.Application()
        app.router.add_post("/v1/devices/check-in", self.check_in)
        app.router.add_get("/v1/packages/{package_id}/download", self.download)
        app.router.add_post("/v1/jobs/{assignment_id}/status", self.report)
        self.server = TestServer(app)
        await self.server.start_server()

        token_path = self.root / "device.token"
        token_path.write_text("test-token\n", encoding="utf-8")
        self.config_path = self.root / "updater.yaml"
        config_data = {
            "center_url": str(self.server.make_url("/")).rstrip("/"),
            "agent_id": "h618-test-device",
            "token_file": str(token_path),
            "public_key_file": str(self.root / "missing.pem"),
            "allow_unsigned_packages": True,
            "state_dir": str(self.root / "state"),
            "application_path": str(self.root / "application"),
            "release_root": str(self.root / "releases"),
        }
        self.config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
        self.service = UpdaterService(self.config_path, UpdaterConfig.load(self.config_path))

    async def asyncTearDown(self) -> None:
        await self.server.close()
        self.temp.cleanup()

    async def check_in(self, request: web.Request) -> web.Response:
        self.assertEqual(request.headers.get("Authorization"), "Bearer test-token")
        return web.json_response({"ok": True, "assignment": self.assignment})

    async def download(self, request: web.Request) -> web.Response:
        self.downloads += 1
        return web.Response(body=self.package.read_bytes(), content_type="application/octet-stream")

    async def report(self, request: web.Request) -> web.Response:
        self.reports.append(await request.json())
        return web.json_response({"ok": True})

    async def test_download_is_verified_and_not_downloaded_twice(self) -> None:
        first = await self.service.check_once()
        self.assertTrue(first["download"]["ready"])
        self.assertEqual(self.downloads, 1)
        self.assertEqual(self.reports[-1]["status"], "downloaded")

        await self.service.check_once()
        self.assertEqual(self.downloads, 1)
        self.assertEqual(self.reports[-1]["status"], "downloaded")

    async def test_wrong_product_is_rejected_before_download(self) -> None:
        self.assignment["package"]["product"] = "different-product"
        with self.assertRaisesRegex(UpdaterError, "different product"):
            await self.service.check_once()
        self.assertEqual(self.downloads, 0)

    async def test_unsigned_center_driver_is_never_installed(self) -> None:
        build_test_package(self.package, package_type="printer_driver")
        self.assignment["package"].update(
            package_type="printer_driver",
            package_id="h618-report-gateway-0.21.0-test",
            sha256=sha256_file(self.package),
            size_bytes=self.package.stat().st_size,
        )
        await self.service.check_once()
        with self.assertRaisesRegex(UpdaterError, "must be signed"):
            await self.service.install_downloaded()


class ApplicationReleasePreparationTests(unittest.TestCase):
    def test_release_preparation_keeps_shell_scripts_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "gateway.jvpkg"
            build_installable_application_package(package_path)
            work_root = root / "work"
            work_root.mkdir()
            package = verify_package(package_path, public_key=None, allow_unsigned=True, work_root=work_root)
            config = UpdaterConfig(
                state_dir=str(root / "state"),
                application_path=str(root / "application"),
                release_root=str(root / "releases"),
            )
            installer = ApplicationInstaller(config, StateStore(root / "state" / "state.json"), prepare_runtime=False)
            with patch.object(Path, "chmod", autospec=True) as chmod:
                try:
                    release = installer._prepare_release(package)  # noqa: SLF001 - verifies extracted release contract.
                finally:
                    package.cleanup()
            self.assertTrue((release / "scripts" / "apply_gadget_mode.sh").is_file())
            chmod.assert_called_once()
            self.assertEqual(chmod.call_args.args[0].name, "apply_gadget_mode.sh")
            self.assertEqual(chmod.call_args.args[1] & 0o111, 0o111)

    def test_release_runtime_uses_system_packages_without_pip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package_path = root / "gateway.jvpkg"
            build_installable_application_package(package_path)
            work_root = root / "work"
            work_root.mkdir()
            package = verify_package(package_path, public_key=None, allow_unsigned=True, work_root=work_root)
            commands: list[list[str]] = []

            def runner(command: list[str], timeout: int) -> CompletedProcess[str]:
                commands.append(command)
                if command[:3] == ["python3", "-m", "venv"]:
                    site_packages = Path(command[-1]) / "lib" / "python3.11" / "site-packages"
                    site_packages.mkdir(parents=True)
                    return CompletedProcess(command, 0, "", "")
                if command[1:3] == ["-c", "import site; print(site.getsitepackages()[0])"]:
                    site_packages = Path(command[0]).parents[1] / "lib" / "python3.11" / "site-packages"
                    return CompletedProcess(command, 0, f"{site_packages}\n", "")
                return CompletedProcess(command, 1, "", "unexpected command")

            config = UpdaterConfig(
                state_dir=str(root / "state"),
                application_path=str(root / "application"),
                release_root=str(root / "releases"),
            )
            installer = ApplicationInstaller(
                config,
                StateStore(root / "state" / "state.json"),
                command_runner=runner,
            )
            try:
                release = installer._prepare_release(package)  # noqa: SLF001 - verifies offline runtime contract.
            finally:
                package.cleanup()
            site_packages = release / ".venv" / "lib" / "python3.11" / "site-packages"
            source_entry = (site_packages / "jvlei_gateway.pth").read_text(encoding="utf-8").strip()
            self.assertEqual((site_packages / source_entry).resolve(), (release / "src").resolve())
            self.assertFalse(any("pip" in command for command in commands))

    def test_updater_agent_release_is_prepared_from_application(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = root / "application"
            source = application / "src" / "jvlei_update"
            source.mkdir(parents=True)
            (source / "updater.py").write_text("VERSION = 'test'\n", encoding="utf-8")
            config = UpdaterConfig(
                state_dir=str(root / "state"),
                application_path=str(application),
                release_root=str(root / "releases"),
                updater_release_root=str(root / "updater-releases"),
                updater_current_path=str(root / "updater-current"),
            )
            installer = ApplicationInstaller(config, StateStore(root / "state" / "state.json"))
            release = installer._prepare_updater_release(application, "0.21.1")  # noqa: SLF001
            self.assertEqual((release / "VERSION").read_text(encoding="ascii"), "0.21.1\n")
            self.assertTrue((release / "jvlei_update" / "updater.py").is_file())


@unittest.skipUnless(SUPPORTS_DIRECTORY_SYMLINKS, "directory symlink support is required for Linux release switching")
class ApplicationInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.application = self.root / "application"
        self.application.mkdir()
        (self.application / "VERSION").write_text("0.20.0\n", encoding="ascii")
        self.config = UpdaterConfig(
            state_dir=str(self.root / "state"),
            application_path=str(self.application),
            release_root=str(self.root / "releases"),
            health_url="https://127.0.0.1/health",
        )
        self.commands: list[list[str]] = []

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _installer(self) -> ApplicationInstaller:
        def runner(command: list[str], timeout: int) -> CompletedProcess[str]:
            self.commands.append(command)
            return CompletedProcess(command, 0, "active\n" if command[1:2] == ["is-active"] else "", "")

        return ApplicationInstaller(
            self.config,
            StateStore(self.root / "state" / "state.json"),
            command_runner=runner,
            prepare_runtime=False,
        )

    def _package(self):
        package = self.root / "gateway.jvpkg"
        build_installable_application_package(package)
        work_root = self.root / "work"
        work_root.mkdir()
        return verify_package(package, public_key=None, allow_unsigned=True, work_root=work_root)

    def test_install_switches_to_release_and_retains_previous_version(self) -> None:
        installer = self._installer()
        installer._health_check = lambda expected_version: None  # type: ignore[method-assign]
        package = self._package()
        try:
            result = installer.install(package)
        finally:
            package.cleanup()

        self.assertEqual(result["version"], "0.21.0")
        self.assertTrue(self.application.is_symlink())
        self.assertEqual(self.application.resolve(), self.root / "releases" / "0.21.0")
        self.assertTrue((self.root / "releases" / "0.20.0").is_dir())
        self.assertTrue(any(command[:2] == ["systemctl", "stop"] for command in self.commands))

    def test_failed_health_check_restores_original_directory(self) -> None:
        installer = self._installer()

        def fail_health(expected_version: str) -> None:
            raise UpdaterError("health check failed")

        installer._health_check = fail_health  # type: ignore[method-assign]
        package = self._package()
        try:
            with self.assertRaisesRegex(UpdaterError, "health check failed"):
                installer.install(package)
        finally:
            package.cleanup()

        self.assertTrue(self.application.is_dir())
        self.assertFalse(self.application.is_symlink())
        self.assertEqual((self.application / "VERSION").read_text(encoding="ascii").strip(), "0.20.0")
        self.assertFalse((self.root / "releases" / "0.21.0").exists())


class UpdateCenterStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / "gateway.jvpkg"
        build_test_package(self.package)
        self.store = CenterStore(self.root / "center.sqlite3")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_downloaded_assignment_is_not_offered_again(self) -> None:
        self.assertTrue(self.store.consume_pair_code(self.store.create_pair_code(30, "test")))
        agent_id, _ = self.store.pair_device({"hostname": "test", "product": "h618-report-gateway"})
        package = self.store.add_package(
            {
                "package_id": "h618-report-gateway-0.21.0-test",
                "package_type": "application",
                "version": "0.21.0",
                "product": "h618-report-gateway",
                "arch": "all",
                "created_at": "2026-08-06T00:00:00+00:00",
                "release_notes": "test",
                "git_commit": "0123456789abcdef",
                "migration_level": 0,
                "requires_gadget_restart": False,
                "requires_cups_restart": False,
            },
            self.package,
            signed=False,
            packages_dir=self.root / "packages",
        )
        assignment = self.store.assign(agent_id, package["id"], "download")
        self.assertIsNotNone(self.store.pending_assignment(agent_id))
        self.store.update_assignment(assignment["id"], "downloaded", {"package_id": package["id"]})
        self.assertIsNone(self.store.pending_assignment(agent_id))
        self.store.set_device_group(agent_id, "测试医院")
        self.assertEqual(self.store.groups(), [{"group_name": "测试医院", "device_count": 1}])
        group_assignments = self.store.assign_group("测试医院", package["id"], "download")
        self.assertEqual(len(group_assignments), 1)
