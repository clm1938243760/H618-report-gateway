from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import random
import shutil
import socket
import sqlite3
import ssl
import subprocess
import tempfile
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import aiohttp
import yaml

from gadget_msc_printer.driver_manager import DriverError, DriverManager

from .package import PackageError, PackageInfo, safe_extract_payload, sha256_file, verify_package


LOGGER = logging.getLogger(__name__)
INSTALL_POLICIES = frozenset({"local_confirm", "remote_allowed"})


class UpdaterError(RuntimeError):
    pass


@dataclass
class UpdaterConfig:
    enabled: bool = True
    center_url: str = "https://update.jvlei.com"
    product: str = "h618-report-gateway"
    agent_id: str = ""
    token_file: str = "/etc/jvlei-updater/device.token"
    public_key_file: str = "/etc/jvlei-updater/update-public.pem"
    check_interval_seconds: int = 60
    max_backoff_seconds: int = 1800
    install_policy: str = "local_confirm"
    allow_unsigned_packages: bool = False
    keep_previous_versions: int = 1
    state_dir: str = "/var/lib/jvlei-updater"
    application_path: str = "/opt/gadget-msc-printer"
    release_root: str = "/opt/jvlei/releases/gateway"
    data_dir: str = "/var/lib/gadget-msc-printer"
    active_task_wait_seconds: int = 90
    driver_root: str = "/var/lib/gadget-msc-printer/drivers"
    local_api_host: str = "127.0.0.1"
    local_api_port: int = 8765
    health_url: str = "https://127.0.0.1/health"

    @classmethod
    def load(cls, path: str | Path) -> "UpdaterConfig":
        source = Path(path)
        if not source.is_file():
            raise UpdaterError(f"updater config not found: {source}")
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise UpdaterError("updater config root must be a mapping")
        values = {key: value for key, value in data.items() if key in cls.__dataclass_fields__}
        config = cls(**values)
        config.validate()
        return config

    def validate(self) -> None:
        if not self.center_url.startswith(("http://", "https://")):
            raise UpdaterError("center_url must be an HTTP or HTTPS URL")
        if self.install_policy not in INSTALL_POLICIES:
            raise UpdaterError("install_policy must be local_confirm or remote_allowed")
        if not 15 <= int(self.check_interval_seconds) <= 86400:
            raise UpdaterError("check_interval_seconds must be between 15 and 86400")
        if not int(self.check_interval_seconds) <= int(self.max_backoff_seconds) <= 86400:
            raise UpdaterError("max_backoff_seconds is invalid")
        if int(self.keep_previous_versions) != 1:
            raise UpdaterError("keep_previous_versions must be 1 in this release")
        if not 0 <= int(self.active_task_wait_seconds) <= 600:
            raise UpdaterError("active_task_wait_seconds must be between 0 and 600")
        if not 1 <= int(self.local_api_port) <= 65535:
            raise UpdaterError("local_api_port is invalid")


class StateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


class ApplicationInstaller:
    SERVICES = ("gadget-collector.service", "gadget-web.service")

    def __init__(
        self,
        config: UpdaterConfig,
        state_store: StateStore,
        command_runner: CommandRunner | None = None,
        prepare_runtime: bool = True,
    ) -> None:
        self.config = config
        self.state_store = state_store
        self.command_runner = command_runner or self._default_runner
        self.prepare_runtime = prepare_runtime

    @staticmethod
    def _default_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def _run(self, command: list[str], timeout: int = 120) -> str:
        result = self.command_runner(command, timeout)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip()
            raise UpdaterError(f"{' '.join(command)}: {detail}")
        return str(result.stdout or "").strip()

    @staticmethod
    def _atomic_symlink(target: Path, link: Path) -> None:
        temporary = link.with_name(f".{link.name}.next-{uuid.uuid4().hex}")
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)

    def _prepare_release(self, package: PackageInfo) -> Path:
        version = str(package.manifest["version"])
        release_root = Path(self.config.release_root)
        release_root.mkdir(parents=True, exist_ok=True)
        final = release_root / version
        if final.exists():
            raise UpdaterError(f"release already exists: {version}")
        required_free = max(128 * 1024 * 1024, int(package.manifest["payload_size"]) * 4)
        available_free = shutil.disk_usage(release_root).free
        if available_free < required_free:
            raise UpdaterError(
                f"insufficient disk space for update: {available_free} bytes free, {required_free} required"
            )
        staging = release_root / f".{version}.staging-{uuid.uuid4().hex}"
        try:
            safe_extract_payload(package.payload_path, staging)
            for required in ("pyproject.toml", "src", "scripts", "portal/portal/dist/index.html"):
                if not (staging / required).exists():
                    raise UpdaterError(f"application payload is missing {required}")
            for script in (staging / "scripts").rglob("*.sh"):
                if script.is_file():
                    script.chmod(script.stat().st_mode | 0o111)
            if self.prepare_runtime:
                self._run(
                    ["python3", "-m", "venv", "--system-site-packages", str(staging / ".venv")],
                    timeout=180,
                )
                self._run(
                    [str(staging / ".venv/bin/python"), "-m", "pip", "install", "--no-deps", "-e", str(staging)],
                    timeout=300,
                )
            (staging / "VERSION").write_text(f"{version}\n", encoding="ascii")
            os.replace(staging, final)
            return final
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _stop_services(self) -> None:
        self._run(["systemctl", "stop", *self.SERVICES], timeout=60)

    def _wait_for_active_reports(self) -> None:
        """Let an in-flight upload finish without blocking a pending queue forever."""

        database = Path(self.config.data_dir) / "state" / "jobs.sqlite3"
        if not database.is_file() or self.config.active_task_wait_seconds <= 0:
            return
        deadline = time.monotonic() + int(self.config.active_task_wait_seconds)
        while time.monotonic() < deadline:
            try:
                with sqlite3.connect(database, timeout=2) as connection:
                    row = connection.execute(
                        "SELECT COUNT(*) FROM report_jobs WHERE status='uploading'"
                    ).fetchone()
                if not row or int(row[0]) == 0:
                    return
            except sqlite3.Error:
                return
            time.sleep(2)
        LOGGER.warning("active report upload did not complete before update timeout")

    def _start_services(self, manifest: dict[str, Any]) -> None:
        self._run(["systemctl", "daemon-reload"], timeout=30)
        if manifest.get("requires_cups_restart"):
            self._run(["systemctl", "restart", "cups.service"], timeout=60)
        if manifest.get("requires_gadget_restart"):
            self._run(["systemctl", "restart", "gadget-mode.service"], timeout=90)
        self._run(["systemctl", "restart", *self.SERVICES], timeout=90)

    def _health_check(self, expected_version: str, timeout: int = 45) -> None:
        context = ssl._create_unverified_context()
        deadline = time.monotonic() + timeout
        last_error = "health check timed out"
        while time.monotonic() < deadline:
            try:
                for service in self.SERVICES:
                    result = self.command_runner(["systemctl", "is-active", service], 10)
                    if result.returncode != 0 or str(result.stdout).strip() != "active":
                        raise UpdaterError(f"service is not active: {service}")
                with urllib.request.urlopen(self.config.health_url, timeout=5, context=context) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if not payload.get("ok"):
                    raise UpdaterError("gateway health endpoint returned not-ok")
                if str(payload.get("version", "")) != expected_version:
                    raise UpdaterError(
                        f"gateway version mismatch: expected {expected_version}, got {payload.get('version')}"
                    )
                return
            except Exception as exc:
                last_error = str(exc)
                time.sleep(2)
        raise UpdaterError(last_error)

    def _current_target(self) -> tuple[Path, bool]:
        app = Path(self.config.application_path)
        if app.is_symlink():
            return app.resolve(), False
        if app.is_dir():
            return app, True
        raise UpdaterError(f"application path is missing: {app}")

    def install(self, package: PackageInfo) -> dict[str, Any]:
        if package.manifest["package_type"] != "application":
            raise UpdaterError("application installer only accepts application packages")
        target_arch = platform.machine().lower()
        package_arch = str(package.manifest["arch"]).lower()
        if package_arch not in {"all", target_arch, "arm64" if target_arch == "aarch64" else target_arch}:
            raise UpdaterError(f"package architecture {package_arch} does not match {target_arch}")
        new_release = self._prepare_release(package)
        app = Path(self.config.application_path)
        previous, previous_was_directory = self._current_target()
        previous_version = self.current_version(previous)
        compatible_versions = package.manifest.get("compatible_versions", [])
        if previous_version not in compatible_versions and "*" not in compatible_versions:
            shutil.rmtree(new_release, ignore_errors=True)
            raise UpdaterError(
                f"package {package.manifest['version']} is not compatible with current version {previous_version}"
            )
        imported_previous = previous
        switched = False
        try:
            self._wait_for_active_reports()
            self._stop_services()
            if previous_was_directory:
                imported_previous = Path(self.config.release_root) / previous_version
                if imported_previous.exists():
                    imported_previous = Path(self.config.release_root) / f"{previous_version}-imported-{int(time.time())}"
                os.replace(previous, imported_previous)
            self._atomic_symlink(new_release, app)
            switched = True
            migration = new_release / "scripts/migrate_config.py"
            if migration.is_file():
                self._run([str(new_release / ".venv/bin/python"), str(migration)], timeout=120)
            self._start_services(package.manifest)
            self._health_check(str(package.manifest["version"]))
        except Exception:
            if switched:
                try:
                    app.unlink(missing_ok=True)
                    if previous_was_directory:
                        os.replace(imported_previous, app)
                    else:
                        self._atomic_symlink(imported_previous, app)
                    self._start_services({"requires_cups_restart": False, "requires_gadget_restart": False})
                except Exception:
                    LOGGER.exception("automatic application rollback failed")
            shutil.rmtree(new_release, ignore_errors=True)
            raise
        state = self.state_store.read()
        state.update(
            current_version=str(package.manifest["version"]),
            current_release=str(new_release),
            previous_version=previous_version,
            previous_release=str(imported_previous),
            installed_at=int(time.time()),
        )
        self.state_store.write(state)
        self._prune_releases({new_release.resolve(), imported_previous.resolve()})
        return {
            "version": str(package.manifest["version"]),
            "previous_version": previous_version,
            "release": str(new_release),
        }

    def rollback(self) -> dict[str, Any]:
        state = self.state_store.read()
        previous_value = str(state.get("previous_release", ""))
        if not previous_value:
            raise UpdaterError("no previous release is available")
        previous = Path(previous_value)
        if not previous.is_dir():
            raise UpdaterError("previous release directory is missing")
        app = Path(self.config.application_path)
        current = app.resolve()
        self._stop_services()
        try:
            self._atomic_symlink(previous, app)
            self._start_services({"requires_cups_restart": False, "requires_gadget_restart": False})
            self._health_check(self.current_version(previous))
        except Exception:
            self._atomic_symlink(current, app)
            self._start_services({"requires_cups_restart": False, "requires_gadget_restart": False})
            raise
        old_current_version = str(state.get("current_version", self.current_version(current)))
        state.update(
            current_version=self.current_version(previous),
            current_release=str(previous),
            previous_version=old_current_version,
            previous_release=str(current),
            rolled_back_at=int(time.time()),
        )
        self.state_store.write(state)
        return {"version": state["current_version"], "previous_version": old_current_version}

    @staticmethod
    def current_version(release: Path) -> str:
        version_file = release / "VERSION"
        if version_file.is_file():
            return version_file.read_text(encoding="ascii", errors="ignore").strip() or "unknown"
        pyproject = release / "pyproject.toml"
        if pyproject.is_file():
            for line in pyproject.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("version") and "=" in line:
                    return line.split("=", 1)[1].strip().strip('"\'')
        return "unknown"

    def _prune_releases(self, keep: set[Path]) -> None:
        root = Path(self.config.release_root)
        for candidate in root.iterdir():
            if candidate.is_dir() and candidate.resolve() not in keep and not candidate.name.startswith("."):
                shutil.rmtree(candidate, ignore_errors=True)


class DriverPackageInstaller:
    """Installs a centrally published, already-signed printer driver package."""

    SOURCE_SUFFIXES = (".deb", ".ppd", ".ppd.gz", ".zip", ".tar", ".tgz", ".tar.gz")

    def __init__(self, config: UpdaterConfig) -> None:
        self.config = config

    def install(self, package: PackageInfo) -> dict[str, Any]:
        if package.manifest["package_type"] != "printer_driver":
            raise UpdaterError("driver installer only accepts printer driver packages")
        if not package.signed:
            raise UpdaterError("centrally published printer drivers must be signed")
        package_id = str(package.manifest["package_id"])
        root = Path(self.config.state_dir) / "driver-package-staging"
        staging = root / f"{package_id}-{uuid.uuid4().hex}"
        try:
            safe_extract_payload(package.payload_path, staging)
            candidates = [
                path
                for path in staging.rglob("*")
                if path.is_file() and path.name.lower().endswith(self.SOURCE_SUFFIXES)
            ]
            if len(candidates) != 1:
                raise UpdaterError("printer driver package must contain exactly one supported driver source file")
            source = candidates[0]
            manager = DriverManager(root=self.config.driver_root)
            staged = manager.stage_upload(source.name, source)
            analysis = staged.get("analysis") or {}
            if not analysis.get("supported"):
                reasons = "; ".join(str(value) for value in analysis.get("reasons", []))
                raise UpdaterError(f"signed printer driver did not pass compatibility analysis: {reasons or 'unknown reason'}")
            if analysis.get("maintainer_scripts"):
                raise UpdaterError(
                    "centrally published DEB driver contains maintainer scripts; install it from the local driver page after review"
                )
            result = manager.install(str(staged["id"]), confirm_scripts=False)
            return {
                "driver": result["driver"],
                "backup": result["backup"],
                "package_id": package_id,
            }
        except DriverError as exc:
            raise UpdaterError(f"printer driver installation failed: {exc}") from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)


class UpdaterService:
    def __init__(self, config_path: str | Path, config: UpdaterConfig) -> None:
        self.config_path = Path(config_path)
        self.config = config
        state_dir = Path(config.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.packages_dir = state_dir / "packages"
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.state_store = StateStore(state_dir / "state.json")
        self.installer = ApplicationInstaller(config, self.state_store)
        self.driver_installer = DriverPackageInstaller(config)
        self.operation_lock = asyncio.Lock()
        self.wake_event = asyncio.Event()
        self.stop_event = asyncio.Event()

    def _token(self) -> str:
        try:
            return Path(self.config.token_file).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _current_version(self) -> str:
        state = self.state_store.read()
        if state.get("current_version"):
            return str(state["current_version"])
        app = Path(self.config.application_path)
        return self.installer.current_version(app.resolve() if app.exists() else app)

    def status(self) -> dict[str, Any]:
        state = self.state_store.read()
        assignment = state.get("assignment") if isinstance(state.get("assignment"), dict) else None
        return {
            "ok": True,
            "enabled": self.config.enabled,
            "paired": bool(self.config.agent_id and self._token()),
            "agent_id": self.config.agent_id,
            "center_url": self.config.center_url,
            "install_policy": self.config.install_policy,
            "allow_unsigned_packages": self.config.allow_unsigned_packages,
            "current_version": self._current_version(),
            "assignment": assignment,
            "last_check_at": state.get("last_check_at"),
            "last_success_at": state.get("last_success_at"),
            "last_error": state.get("last_error", ""),
            "download": state.get("download"),
            "previous_version": state.get("previous_version", ""),
        }

    def _device_payload(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.config.state_dir)
        return {
            "agent_id": self.config.agent_id,
            "hostname": socket.gethostname(),
            "product": self.config.product,
            "version": self._current_version(),
            "arch": platform.machine().lower(),
            "install_policy": self.config.install_policy,
            "free_bytes": usage.free,
            "total_bytes": usage.total,
        }

    async def pair(self, code: str) -> dict[str, Any]:
        if not code.strip():
            raise UpdaterError("pairing code is required")
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.config.center_url.rstrip('/')}/v1/devices/pair",
                json={**self._device_payload(), "pairing_code": code.strip()},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                payload = await response.json(content_type=None)
                if response.status != 200 or not payload.get("ok"):
                    raise UpdaterError(str(payload.get("error") or f"pairing failed: HTTP {response.status}"))
        agent_id = str(payload.get("agent_id", "")).strip()
        token = str(payload.get("token", "")).strip()
        if not agent_id or not token:
            raise UpdaterError("pairing response did not contain device credentials")
        token_path = Path(self.config.token_file)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token + "\n", encoding="utf-8")
        os.chmod(token_path, 0o600)
        self.config.agent_id = agent_id
        self._save_config()
        return self.status()

    def _save_config(self) -> None:
        data = asdict(self.config)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_name(f".{self.config_path.name}.{uuid.uuid4().hex}")
        temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.chmod(temporary, 0o640)
        os.replace(temporary, self.config_path)

    async def check_once(self) -> dict[str, Any]:
        token = self._token()
        if not self.config.agent_id or not token:
            raise UpdaterError("device is not paired")
        state = self.state_store.read()
        state["last_check_at"] = int(time.time())
        self.state_store.write(state)
        headers = {"Authorization": f"Bearer {token}"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post(
                f"{self.config.center_url.rstrip('/')}/v1/devices/check-in",
                json=self._device_payload(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                payload = await response.json(content_type=None)
                if response.status != 200 or not payload.get("ok"):
                    raise UpdaterError(str(payload.get("error") or f"check-in failed: HTTP {response.status}"))
        state = self.state_store.read()
        state.update(last_success_at=int(time.time()), last_error="", assignment=payload.get("assignment"))
        self.state_store.write(state)
        assignment = payload.get("assignment")
        if isinstance(assignment, dict) and assignment.get("action") in {"download", "install"}:
            await self.download_assignment(assignment)
            if assignment.get("action") == "install" and self.config.install_policy == "remote_allowed":
                await self.install_downloaded()
        return self.status()

    async def download_assignment(self, assignment: dict[str, Any] | None = None) -> dict[str, Any]:
        async with self.operation_lock:
            state = self.state_store.read()
            selected = assignment or state.get("assignment")
            if not isinstance(selected, dict):
                raise UpdaterError("no update assignment is available")
            package = selected.get("package")
            if not isinstance(package, dict) or not package.get("id"):
                raise UpdaterError("assignment does not contain a package")
            if package.get("package_type") not in {"application", "printer_driver"}:
                raise UpdaterError("assigned package type is not supported by this updater")
            package_id = str(package["id"])
            if not package_id.isalnum() or len(package_id) > 128:
                raise UpdaterError("assignment package ID is invalid")
            if str(package.get("product", "")) != self.config.product:
                raise UpdaterError("assigned package targets a different product")
            package_arch = str(package.get("arch", "")).lower()
            board_arch = platform.machine().lower()
            if package_arch not in {"all", board_arch, "arm64" if board_arch == "aarch64" else board_arch}:
                raise UpdaterError("assigned package architecture does not match this board")
            token = self._token()
            destination = self.packages_dir / f"{package_id}.jvpkg"
            partial = destination.with_suffix(".jvpkg.part")
            previous_download = state.get("download")
            if (
                isinstance(previous_download, dict)
                and previous_download.get("ready")
                and previous_download.get("package_id") == package_id
                and destination.is_file()
            ):
                previous_manifest = previous_download.get("manifest")
                if not isinstance(previous_manifest, dict):
                    previous_manifest = {}
                await self._report_assignment(
                    "downloaded",
                    {
                        "package_id": package_id,
                        "version": previous_manifest.get("version", ""),
                        "signed": bool(previous_download.get("signed")),
                    },
                )
                return self.status()
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {"Authorization": f"Bearer {token}"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            url = f"{self.config.center_url.rstrip('/')}/v1/packages/{package_id}/download"
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=None, sock_connect=30)) as response:
                    if response.status not in {200, 206}:
                        detail = await response.text()
                        raise UpdaterError(detail or f"package download failed: HTTP {response.status}")
                    mode = "ab" if response.status == 206 and offset else "wb"
                    with partial.open(mode) as handle:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            handle.write(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
            os.replace(partial, destination)
            expected = str(package.get("sha256", ""))
            actual = sha256_file(destination)
            if expected and actual != expected:
                destination.unlink(missing_ok=True)
                raise UpdaterError("downloaded package SHA-256 mismatch")
            info = verify_package(
                destination,
                self.config.public_key_file if Path(self.config.public_key_file).is_file() else None,
                allow_unsigned=self.config.allow_unsigned_packages,
                work_root=self.config.state_dir,
            )
            manifest = dict(info.manifest)
            signed = info.signed
            info.cleanup()
            state = self.state_store.read()
            state["download"] = {
                "package_id": package_id,
                "path": str(destination),
                "manifest": manifest,
                "signed": signed,
                "ready": True,
                "downloaded_at": int(time.time()),
            }
            self.state_store.write(state)
            await self._report_assignment(
                "downloaded",
                {
                    "package_id": package_id,
                    "version": manifest.get("version", ""),
                    "signed": signed,
                },
            )
            return self.status()

    async def install_downloaded(self) -> dict[str, Any]:
        async with self.operation_lock:
            state = self.state_store.read()
            download = state.get("download")
            if not isinstance(download, dict) or not download.get("ready"):
                raise UpdaterError("no verified update is ready to install")
            package_path = Path(str(download.get("path", "")))
            info = verify_package(
                package_path,
                self.config.public_key_file if Path(self.config.public_key_file).is_file() else None,
                allow_unsigned=self.config.allow_unsigned_packages,
                work_root=self.config.state_dir,
            )
            try:
                package_type = str(info.manifest["package_type"])
                if package_type == "application":
                    result = await asyncio.to_thread(self.installer.install, info)
                elif package_type == "printer_driver":
                    result = await asyncio.to_thread(self.driver_installer.install, info)
                else:
                    raise UpdaterError("downloaded package type is not installable")
            finally:
                info.cleanup()
            state = self.state_store.read()
            state.update(last_error="", download=None, assignment=None)
            self.state_store.write(state)
            await self._report_assignment("installed", result)
            return self.status()

    async def rollback(self) -> dict[str, Any]:
        async with self.operation_lock:
            result = await asyncio.to_thread(self.installer.rollback)
            await self._report_assignment("rolled_back", result)
            return self.status()

    async def _report_assignment(self, status: str, detail: dict[str, Any]) -> None:
        state = self.state_store.read()
        assignment = state.get("assignment")
        if not isinstance(assignment, dict) or not assignment.get("id") or not self._token():
            return
        try:
            async with aiohttp.ClientSession(headers={"Authorization": f"Bearer {self._token()}"}) as session:
                async with session.post(
                    f"{self.config.center_url.rstrip('/')}/v1/jobs/{assignment['id']}/status",
                    json={"status": status, "detail": detail},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    await response.read()
        except Exception:
            LOGGER.exception("failed to report updater job status")

    def set_policy(self, policy: str) -> dict[str, Any]:
        if policy not in INSTALL_POLICIES:
            raise UpdaterError("invalid install policy")
        self.config.install_policy = policy
        self._save_config()
        return self.status()

    async def run_poll_loop(self) -> None:
        delay = self.config.check_interval_seconds
        while not self.stop_event.is_set():
            if self.config.enabled and self.config.agent_id and self._token():
                try:
                    await self.check_once()
                    delay = self.config.check_interval_seconds
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    LOGGER.warning("update center check failed: %s", exc)
                    state = self.state_store.read()
                    state["last_error"] = str(exc)
                    self.state_store.write(state)
                    delay = min(max(delay * 2, self.config.check_interval_seconds), self.config.max_backoff_seconds)
            jitter = random.uniform(0, min(10, delay * 0.1))
            try:
                await asyncio.wait_for(self.wake_event.wait(), timeout=delay + jitter)
                self.wake_event.clear()
                delay = self.config.check_interval_seconds
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
