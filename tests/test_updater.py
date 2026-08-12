from __future__ import annotations

import io
import hashlib
import json
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import Mock, patch

import yaml
from aiohttp import web
from aiohttp.test_utils import TestServer

from jvlei_update.company_package import verify_company_package
from jvlei_update.package import build_package, verify_package
from jvlei_update.updater import ApplicationInstaller, StateStore, UpdaterConfig, UpdaterError, UpdaterService


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


def build_installable_application_package(path: Path, version: str = "0.21.0") -> None:
    """Create the minimum valid application tree required by ApplicationInstaller."""

    payload = path.with_suffix(".payload.tar.gz")
    files = {
        "pyproject.toml": f'[project]\nname = "gateway"\nversion = "{version}"\n'.encode(),
        "src/gadget_msc_printer/__init__.py": b"",
        "src/jvlei_update/__init__.py": b"",
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
        self.package = self.root / "gateway.zip"
        self._build_company_package(self.package)
        self.downloads = 0
        self.reports: list[dict[str, object]] = []
        self.check_requests: list[dict[str, object]] = []
        self.terminal_requests: list[dict[str, object]] = []
        self.auto_upgrade = False
        self.has_update = True
        app = web.Application()
        app.router.add_post("/api/auto-update/report-terminal-info", self.report_terminal)
        app.router.add_post("/api/auto-update/check", self.check_update)
        app.router.add_get("/package.zip", self.download)
        app.router.add_post("/api/auto-update/report", self.report)
        app.router.add_post("/api/auto-update/rollback-report", self.report)
        self.server = TestServer(app)
        await self.server.start_server()

        application = self.root / "application"
        application.mkdir()
        (application / "VERSION").write_text("0.21.2\n", encoding="ascii")
        business_config = self.root / "gateway.yaml"
        business_config.write_text(
            "upload:\n"
            "  hospital_code: tejian01\n"
            "company_update:\n"
            "  hospital_id: H-021\n"
            "  hospital_area_code: AREA-01\n"
            "  hospital_area_id: CAMPUS-01\n"
            "  dept_code: DEPT-01\n"
            "  dept_id: D-01\n",
            encoding="utf-8",
        )
        self.config_path = self.root / "updater.yaml"
        config_data = {
            "center_url": str(self.server.make_url("/")).rstrip("/"),
            "business_config_file": str(business_config),
            "allow_unsigned_packages": True,
            "state_dir": str(self.root / "state"),
            "application_path": str(application),
            "release_root": str(self.root / "releases"),
            "updater_release_root": str(self.root / "updater-releases"),
            "updater_current_path": str(self.root / "updater-current"),
        }
        self.config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
        self.service = UpdaterService(self.config_path, UpdaterConfig.load(self.config_path))
        self.service._network_identity = lambda: {  # type: ignore[method-assign]
            "interface": "eth0",
            "ip": "192.168.20.144",
            "mac": "02:00:89:BD:16:D6",
        }

    async def asyncTearDown(self) -> None:
        await self.server.close()
        self.temp.cleanup()

    @staticmethod
    def _build_company_package(path: Path, *, product: str = "h618-report-gateway") -> None:
        files = {
            "pyproject.toml": b'[project]\nversion = "0.22.0"\n',
            "src/gadget_msc_printer/__init__.py": b"",
            "src/jvlei_update/__init__.py": b"",
            "scripts/apply_gadget_mode.sh": b"#!/bin/sh\n",
            "portal/portal/dist/index.html": b"<!doctype html>",
        }
        payload = path.with_suffix(".payload.tar.gz")
        with tarfile.open(payload, "w:gz") as archive:
            for name, content in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                member.mode = 0o755 if name.endswith(".sh") else 0o644
                archive.addfile(member, io.BytesIO(content))
        payload_bytes = payload.read_bytes()
        manifest = {
            "schemaVersion": 1,
            "packageType": "application",
            "appCode": "linux",
            "product": product,
            "version": "v0.22.0",
            "platform": "linux-arm64",
            "architecture": "arm64",
            "compatibleFrom": ["v0.21.2"],
            "releaseNote": "test",
            "payload": {
                "path": "payload.tar.gz",
                "format": "tar.gz",
                "size": len(payload_bytes),
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "fileCount": len(files),
            },
            "install": {
                "mode": "atomic_release",
                "requiresGadgetRestart": False,
                "requiresCupsRestart": False,
            },
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest).encode())
            archive.writestr("payload.tar.gz", payload_bytes)

    async def report_terminal(self, request: web.Request) -> web.Response:
        self.terminal_requests.append(await request.json())
        return web.json_response({"code": 200, "success": True, "data": True, "msg": "ok"})

    async def check_update(self, request: web.Request) -> web.Response:
        self.check_requests.append(await request.json())
        if not self.has_update:
            return web.json_response(
                {"code": 0, "success": True, "data": {"hasUpdate": False}, "msg": "ok"}
            )
        data = {
            "hasUpdate": True,
            "recordId": "2087387590501675010",
            "newVersion": "v0.22.0",
            "newVersionId": "2087373815128076290",
            "packageFileId": "2087373815128076290",
            "packageFileName": self.package.name,
            "packageSize": self.package.stat().st_size,
            "autoUpgrade": self.auto_upgrade,
            "downloadUrl": str(self.server.make_url("/package.zip")),
            "strategyId": "2087374148797542402",
            "releaseNote": "test",
        }
        return web.json_response({"code": 200, "success": True, "data": data, "msg": "ok"})

    async def download(self, request: web.Request) -> web.Response:
        self.downloads += 1
        return web.Response(body=self.package.read_bytes(), content_type="application/octet-stream")

    async def report(self, request: web.Request) -> web.Response:
        self.reports.append(await request.json())
        return web.json_response({"code": 200, "success": True, "data": True, "msg": "ok"})

    async def test_manual_strategy_checks_without_downloading_and_omits_empty_fields(self) -> None:
        status = await self.service.check_once()
        self.assertEqual(status["update"]["version"], "v0.22.0")
        self.assertIsNone(status["download"])
        self.assertEqual(self.downloads, 0)
        request = self.check_requests[-1]
        self.assertEqual(request["hospitalCode"], "tejian01")
        self.assertEqual(request["terminalIp"], "192.168.20.144")
        self.assertEqual(request["terminalMac"], "02:00:89:BD:16:D6")
        self.assertEqual(request["currentVersion"], "v0.21.2")
        self.assertNotIn("currentVersionId", request)
        self.assertEqual(request["hospitalId"], "H-021")
        self.assertEqual(request["hospitalAreaCode"], "AREA-01")
        self.assertEqual(request["deptCode"], "DEPT-01")
        terminal = self.terminal_requests[-1]
        self.assertEqual(terminal["campusCode"], "AREA-01")
        self.assertEqual(terminal["campusId"], "CAMPUS-01")
        self.assertEqual(terminal["deptId"], "D-01")

    async def test_company_configuration_is_saved_and_terminal_is_synchronized(self) -> None:
        status = await self.service.configure_company(
            str(self.server.make_url("" )).rstrip("/"),
            {
                "hospital_code": "new-hospital",
                "hospital_id": "H-NEW",
                "hospital_area_code": "AREA-NEW",
                "hospital_area_id": "CAMPUS-NEW",
                "dept_code": "DEPT-NEW",
                "dept_id": "D-NEW",
            },
        )
        self.assertEqual(status["organization"]["hospital_code"], "new-hospital")
        self.assertTrue(status["last_terminal_report_at"])
        saved = yaml.safe_load(Path(self.service.config.business_config_file).read_text(encoding="utf-8"))
        self.assertEqual(saved["upload"]["hospital_code"], "new-hospital")
        self.assertEqual(saved["company_update"]["hospital_area_id"], "CAMPUS-NEW")
        self.assertEqual(self.terminal_requests[-1]["hospitalCode"], "new-hospital")

    async def test_manual_download_verifies_company_zip_and_reports_statuses(self) -> None:
        await self.service.check_once()
        status = await self.service.download_update()
        self.assertTrue(status["download"]["ready"])
        self.assertEqual(self.downloads, 1)
        self.assertEqual([item["upgradeStatus"] for item in self.reports], [1, 2])
        info = verify_company_package(Path(status["download"]["path"]), expected_version="v0.22.0")
        info.cleanup()

    async def test_auto_upgrade_downloads_installs_and_accepts_string_ids(self) -> None:
        self.auto_upgrade = True
        with patch.object(
            self.service.installer,
            "install",
            return_value={"version": "0.22.0", "previous_version": "0.21.2"},
        ), patch.object(self.service, "_schedule_agent_restart"):
            status = await self.service.check_once()
        self.assertIsNone(status["download"])
        self.assertIsNone(status["update"])
        self.assertEqual(status["current_version_id"], "2087373815128076290")
        self.assertEqual([item["upgradeStatus"] for item in self.reports], [1, 2, 3, 4])

    async def test_business_code_zero_is_also_accepted(self) -> None:
        # Exercise the parser directly because aiohttp routers cannot be replaced after startup.
        with patch.object(self.service, "_request_json", return_value={"code": 0, "success": True, "data": None}):
            result = await self.service._check_company(report_terminal=False)  # noqa: SLF001
        self.assertIsNone(result)

    async def test_no_update_clears_stale_download(self) -> None:
        state = self.service.state_store.read()
        state["download"] = {"ready": True, "path": "stale.zip"}
        self.service.state_store.write(state)
        self.has_update = False
        status = await self.service.check_once()
        self.assertIsNone(status["update"])
        self.assertIsNone(status["download"])

    async def test_startup_reconciles_active_release_with_legacy_state(self) -> None:
        legacy_release = self.root / "releases" / "0.21.1"
        legacy_release.mkdir(parents=True)
        (legacy_release / "VERSION").write_text("0.21.1\n", encoding="ascii")
        state = self.service.state_store.read()
        state.update(current_release=str(legacy_release), current_version="0.21.1")
        self.service.state_store.write(state)
        refreshed = UpdaterService(self.config_path, UpdaterConfig.load(self.config_path))
        value = refreshed.state_store.read()
        self.assertEqual(value["current_version"], "0.21.2")
        self.assertEqual(value["previous_version"], "0.21.1")

    async def test_expired_download_url_is_refreshed_once(self) -> None:
        await self.service.check_once()
        original_download = self.service._download_to  # noqa: SLF001
        attempts = 0

        async def fail_once(url: str, partial: Path, expected_size: int) -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise UpdaterError("temporary link expired")
            await original_download(url, partial, expected_size)

        with patch.object(self.service, "_download_to", side_effect=fail_once):
            status = await self.service.download_update()
        self.assertTrue(status["download"]["ready"])
        self.assertEqual(attempts, 2)
        self.assertEqual(len(self.check_requests), 2)

    async def test_failed_status_report_is_queued_and_later_flushed(self) -> None:
        await self.service.check_once()
        with patch.object(self.service, "_request_json", side_effect=UpdaterError("offline")):
            await self.service._report_upgrade(1, "download")  # noqa: SLF001
        self.assertEqual(self.service.status()["pending_reports"], 1)
        await self.service._flush_reports()  # noqa: SLF001
        self.assertEqual(self.service.status()["pending_reports"], 0)


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


class ApplicationInstallerFailureRecoveryTests(unittest.TestCase):
    def test_service_stop_timeout_still_restarts_current_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = root / "application"
            application.mkdir()
            (application / "VERSION").write_text("0.20.0\n", encoding="ascii")
            config_dir = root / "config"
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text("mode: msc\n", encoding="utf-8")
            package_path = root / "gateway.jvpkg"
            build_installable_application_package(package_path)
            work_root = root / "work"
            work_root.mkdir()
            package = verify_package(package_path, public_key=None, allow_unsigned=True, work_root=work_root)
            commands: list[list[str]] = []

            def runner(command: list[str], timeout: int) -> CompletedProcess[str]:
                commands.append(command)
                if command[:2] == ["systemctl", "stop"]:
                    raise TimeoutExpired(command, timeout)
                return CompletedProcess(command, 0, "", "")

            config = UpdaterConfig(
                state_dir=str(root / "state"),
                application_path=str(application),
                release_root=str(root / "releases"),
                updater_release_root=str(root / "updater-releases"),
                updater_current_path=str(root / "updater-current"),
                config_dir=str(config_dir),
                active_task_wait_seconds=0,
            )
            installer = ApplicationInstaller(
                config,
                StateStore(root / "state" / "state.json"),
                command_runner=runner,
                prepare_runtime=False,
            )
            try:
                with self.assertRaisesRegex(UpdaterError, "timed out after 120 seconds"):
                    installer.install(package)
            finally:
                package.cleanup()

            self.assertTrue(application.is_dir())
            self.assertFalse(application.is_symlink())
            self.assertTrue(any(command[:2] == ["systemctl", "restart"] for command in commands))


@unittest.skipUnless(SUPPORTS_DIRECTORY_SYMLINKS, "directory symlink support is required for Linux release switching")
class ApplicationInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.application = self.root / "application"
        self.application.mkdir()
        (self.application / "VERSION").write_text("0.20.0\n", encoding="ascii")
        self.config_dir = self.root / "config"
        self.config_dir.mkdir()
        (self.config_dir / "config.yaml").write_text("mode: msc\n", encoding="utf-8")
        self.config = UpdaterConfig(
            state_dir=str(self.root / "state"),
            application_path=str(self.application),
            release_root=str(self.root / "releases"),
            config_dir=str(self.config_dir),
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
