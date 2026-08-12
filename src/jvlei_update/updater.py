from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import socket
import sqlite3
import ssl
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import aiohttp
import yaml

from .company_package import server_version, verify_company_package
from .package import MAX_MANIFEST_BYTES, MAX_PAYLOAD_BYTES, PackageInfo, safe_extract_payload, sha256_file


LOGGER = logging.getLogger(__name__)
MAX_COMPANY_PACKAGE_BYTES = MAX_PAYLOAD_BYTES + MAX_MANIFEST_BYTES + 16 * 1024 * 1024


class UpdaterError(RuntimeError):
    pass


@dataclass
class UpdaterConfig:
    enabled: bool = True
    center_url: str = "http://192.168.112.229:28080"
    app_code: str = "linux"
    platform: str = "linux-arm64"
    product: str = "h618-report-gateway"
    business_config_file: str = "/etc/gadget-msc-printer/config.yaml"
    config_dir: str = "/etc/gadget-msc-printer"
    boot_check: bool = True
    allow_unsigned_packages: bool = True
    keep_previous_versions: int = 1
    state_dir: str = "/var/lib/jvlei-updater"
    application_path: str = "/opt/gadget-msc-printer"
    release_root: str = "/opt/jvlei/releases/gateway"
    updater_release_root: str = "/usr/local/libexec/jvlei-updater/releases"
    updater_current_path: str = "/usr/local/libexec/jvlei-updater/current"
    data_dir: str = "/var/lib/gadget-msc-printer"
    active_task_wait_seconds: int = 90
    driver_root: str = "/var/lib/gadget-msc-printer/drivers"
    local_api_host: str = "127.0.0.1"
    local_api_port: int = 8765
    health_url: str = "https://127.0.0.1:8443/health"

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
        parsed = urlparse(self.center_url)
        if (
            not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise UpdaterError("center_url must be an HTTP(S) origin without credentials, query, or fragment")
        for field_name in ("app_code", "platform", "product"):
            value = str(getattr(self, field_name)).strip()
            if not value or len(value) > 128:
                raise UpdaterError(f"{field_name} is invalid")
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
        self.last_rollback_attempted = False
        self.last_rollback_succeeded = False

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
        try:
            result = self.command_runner(command, timeout)
        except subprocess.TimeoutExpired as exc:
            raise UpdaterError(f"{' '.join(command)} timed out after {timeout} seconds") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip()
            raise UpdaterError(f"{' '.join(command)}: {detail}")
        return str(result.stdout or "").strip()

    @staticmethod
    def _atomic_symlink(target: Path, link: Path) -> None:
        temporary = link.with_name(f".{link.name}.next-{uuid.uuid4().hex}")
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)

    def _prepare_python_runtime(self, release: Path) -> None:
        venv = release / ".venv"
        self._run(["python3", "-m", "venv", "--system-site-packages", str(venv)], timeout=180)
        site_output = self._run(
            [str(venv / "bin/python"), "-c", "import site; print(site.getsitepackages()[0])"],
            timeout=30,
        )
        site_packages = Path(site_output.splitlines()[-1].strip())
        if not site_packages.is_dir():
            raise UpdaterError(f"virtualenv site-packages is missing: {site_packages}")
        relative_source = os.path.relpath(release / "src", site_packages)
        (site_packages / "jvlei_gateway.pth").write_text(f"{relative_source}\n", encoding="utf-8")

    def _prepare_updater_release(self, application_release: Path, version: str) -> Path:
        source = application_release / "src" / "jvlei_update"
        if not source.is_dir():
            raise UpdaterError("application payload is missing the update agent")
        root = Path(self.config.updater_release_root)
        root.mkdir(parents=True, exist_ok=True)
        final = root / version
        if final.exists():
            raise UpdaterError(f"updater release already exists: {version}")
        staging = root / f".{version}.staging-{uuid.uuid4().hex}"
        try:
            staging.mkdir()
            shutil.copytree(source, staging / "jvlei_update")
            (staging / "VERSION").write_text(f"{version}\n", encoding="ascii")
            os.replace(staging, final)
            return final
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

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
            extracted = safe_extract_payload(package.payload_path, staging)
            expected_files = package.manifest.get("payload_file_count")
            if expected_files is not None and len(extracted) != int(expected_files):
                raise UpdaterError(
                    f"payload file count mismatch: expected {expected_files}, extracted {len(extracted)}"
                )
            for required in ("pyproject.toml", "src", "scripts", "portal/portal/dist/index.html"):
                if not (staging / required).exists():
                    raise UpdaterError(f"application payload is missing {required}")
            for script in (staging / "scripts").rglob("*.sh"):
                if script.is_file():
                    script.chmod(script.stat().st_mode | 0o111)
            if self.prepare_runtime:
                self._prepare_python_runtime(staging)
            (staging / "VERSION").write_text(f"{version}\n", encoding="ascii")
            os.replace(staging, final)
            return final
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def _stop_services(self) -> None:
        self._run(["systemctl", "stop", *self.SERVICES], timeout=120)

    def _restart_services_after_failure(self) -> None:
        try:
            self._start_services({"requires_cups_restart": False, "requires_gadget_restart": False})
        except Exception:
            LOGGER.exception("failed to restart gateway services after update error")

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

    def _backup_configuration(self, version: str) -> Path:
        source = Path(self.config.config_dir)
        if not source.is_dir():
            raise UpdaterError(f"configuration directory is missing: {source}")
        backup_root = Path(self.config.state_dir) / "backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        destination = backup_root / f"config-before-{version}-{int(time.time())}.tar.gz"
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            with tarfile.open(temporary, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
                archive.add(source, arcname=source.name, recursive=True)
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise UpdaterError(f"cannot back up configuration: {exc}") from exc
        return destination

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
        self.last_rollback_attempted = False
        self.last_rollback_succeeded = False
        if package.manifest["package_type"] != "application":
            raise UpdaterError("application installer only accepts application packages")
        manifest_health_url = str(package.manifest.get("health_url", "")).strip()
        if manifest_health_url and manifest_health_url != self.config.health_url:
            raise UpdaterError("package health URL does not match the fixed device health endpoint")
        target_arch = platform.machine().lower()
        package_arch = str(package.manifest["arch"]).lower()
        if package_arch not in {"all", target_arch, "arm64" if target_arch == "aarch64" else target_arch}:
            raise UpdaterError(f"package architecture {package_arch} does not match {target_arch}")
        app = Path(self.config.application_path)
        previous, previous_was_directory = self._current_target()
        previous_version = self.current_version(previous)
        version = str(package.manifest["version"])
        if version == previous_version:
            raise UpdaterError(f"version {version} is already installed")
        compatible_versions = package.manifest.get("compatible_versions", [])
        if previous_version not in compatible_versions and "*" not in compatible_versions:
            raise UpdaterError(
                f"package {package.manifest['version']} is not compatible with current version {previous_version}"
            )
        updater_current = Path(self.config.updater_current_path)
        previous_updater_release = updater_current.resolve() if updater_current.is_symlink() else None
        release_path = Path(self.config.release_root) / version
        updater_release_path = Path(self.config.updater_release_root) / version
        replaced_release: Path | None = None
        replaced_updater_release: Path | None = None

        def park_existing(path: Path) -> Path | None:
            if not path.exists():
                return None
            parked = path.with_name(f".{path.name}.replaced-{uuid.uuid4().hex}")
            os.replace(path, parked)
            return parked

        def restore_parked(path: Path, parked: Path | None) -> None:
            if parked is None or not parked.exists():
                return
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            os.replace(parked, path)

        try:
            replaced_release = park_existing(release_path)
            replaced_updater_release = park_existing(updater_release_path)
            new_release = self._prepare_release(package)
            new_updater_release = self._prepare_updater_release(new_release, version)
        except Exception:
            shutil.rmtree(release_path, ignore_errors=True)
            shutil.rmtree(updater_release_path, ignore_errors=True)
            restore_parked(release_path, replaced_release)
            restore_parked(updater_release_path, replaced_updater_release)
            raise
        imported_previous = previous
        switched = False
        updater_switched = False
        try:
            self._wait_for_active_reports()
            configuration_backup = self._backup_configuration(version)
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
            self._health_check(version)
            self._atomic_symlink(new_updater_release, updater_current)
            updater_switched = True
        except Exception:
            if updater_switched:
                try:
                    if previous_updater_release is None:
                        updater_current.unlink(missing_ok=True)
                    else:
                        self._atomic_symlink(previous_updater_release, updater_current)
                except Exception:
                    LOGGER.exception("automatic updater-agent rollback failed")
            if switched:
                self.last_rollback_attempted = True
                try:
                    app.unlink(missing_ok=True)
                    if previous_was_directory:
                        os.replace(imported_previous, app)
                    else:
                        self._atomic_symlink(imported_previous, app)
                    self.last_rollback_succeeded = True
                except Exception:
                    LOGGER.exception("automatic application rollback failed")
            self._restart_services_after_failure()
            shutil.rmtree(new_release, ignore_errors=True)
            shutil.rmtree(new_updater_release, ignore_errors=True)
            restore_parked(release_path, replaced_release)
            restore_parked(updater_release_path, replaced_updater_release)
            raise
        if replaced_release is not None:
            shutil.rmtree(replaced_release, ignore_errors=True)
        if replaced_updater_release is not None:
            shutil.rmtree(replaced_updater_release, ignore_errors=True)
        state = self.state_store.read()
        state.update(
            current_version=version,
            current_release=str(new_release),
            previous_version=previous_version,
            previous_release=str(imported_previous),
            current_updater_release=str(new_updater_release),
            previous_updater_release=str(previous_updater_release or ""),
            installed_at=int(time.time()),
            configuration_backup=str(configuration_backup),
        )
        self.state_store.write(state)
        self._prune_releases({new_release.resolve(), imported_previous.resolve()})
        updater_keep = {new_updater_release.resolve()}
        if previous_updater_release is not None:
            updater_keep.add(previous_updater_release.resolve())
        self._prune_directory(Path(self.config.updater_release_root), updater_keep)
        return {
            "version": version,
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
        updater_current = Path(self.config.updater_current_path)
        current_updater = updater_current.resolve() if updater_current.is_symlink() else None
        previous_updater_value = str(state.get("previous_updater_release", ""))
        previous_updater = Path(previous_updater_value) if previous_updater_value else None
        switched = False
        updater_switched = False
        try:
            self._stop_services()
            self._atomic_symlink(previous, app)
            switched = True
            self._start_services({"requires_cups_restart": False, "requires_gadget_restart": False})
            self._health_check(self.current_version(previous))
            if previous_updater is not None and previous_updater.is_dir():
                self._atomic_symlink(previous_updater, updater_current)
                updater_switched = True
        except Exception:
            if switched:
                try:
                    self._atomic_symlink(current, app)
                except Exception:
                    LOGGER.exception("manual rollback recovery could not restore the application link")
            if updater_switched and current_updater is not None:
                try:
                    self._atomic_symlink(current_updater, updater_current)
                except Exception:
                    LOGGER.exception("manual rollback recovery could not restore the updater link")
            self._restart_services_after_failure()
            raise
        old_current_version = str(state.get("current_version", self.current_version(current)))
        state.update(
            current_version=self.current_version(previous),
            current_release=str(previous),
            previous_version=old_current_version,
            previous_release=str(current),
            current_updater_release=str(previous_updater or current_updater or ""),
            previous_updater_release=str(current_updater or ""),
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
        self._prune_directory(Path(self.config.release_root), keep)

    @staticmethod
    def _prune_directory(root: Path, keep: set[Path]) -> None:
        for candidate in root.iterdir():
            if candidate.is_dir() and candidate.resolve() not in keep and not candidate.name.startswith("."):
                shutil.rmtree(candidate, ignore_errors=True)


class UpdaterService:
    ORGANIZATION_FIELDS = (
        "hospital_code",
        "hospital_id",
        "hospital_area_code",
        "hospital_area_id",
        "dept_code",
        "dept_id",
    )

    def __init__(self, config_path: str | Path, config: UpdaterConfig) -> None:
        self.config_path = Path(config_path)
        self.config = config
        state_dir = Path(config.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        self.packages_dir = state_dir / "packages"
        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.state_store = StateStore(state_dir / "state.json")
        state = self.state_store.read()
        if state.get("installing"):
            state.update(
                installing=False,
                operation="",
                last_error=str(state.get("last_error") or "previous update operation was interrupted"),
            )
        self.installer = ApplicationInstaller(config, self.state_store)
        self._reconcile_release_state(state)
        self.operation_lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.background_operation: asyncio.Task[None] | None = None

    def _reconcile_release_state(self, state: dict[str, Any]) -> None:
        application = Path(self.config.application_path)
        if not application.exists():
            self.state_store.write(state)
            return
        active_release = application.resolve()
        active_version = self.installer.current_version(active_release)
        recorded_release = Path(str(state.get("current_release", "")))
        recorded_version = str(state.get("current_version", ""))
        release_changed = recorded_release != active_release or recorded_version != active_version
        if release_changed and recorded_release.is_dir() and recorded_release.resolve() != active_release:
            state.update(
                previous_release=str(recorded_release.resolve()),
                previous_version=self.installer.current_version(recorded_release.resolve()),
            )
        state.update(current_release=str(active_release), current_version=active_version)

        updater_link = Path(self.config.updater_current_path)
        if updater_link.is_symlink():
            active_updater = updater_link.resolve()
            recorded_updater = Path(str(state.get("current_updater_release", "")))
            if recorded_updater != active_updater:
                if recorded_updater.is_dir():
                    state["previous_updater_release"] = str(recorded_updater.resolve())
            state["current_updater_release"] = str(active_updater)
        self.state_store.write(state)

    def _current_version(self) -> str:
        app = Path(self.config.application_path)
        return self.installer.current_version(app.resolve() if app.exists() else app)

    @staticmethod
    def _integer(value: object, field: str, *, optional: bool = False) -> int | None:
        if optional and value in (None, ""):
            return None
        try:
            result = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise UpdaterError(f"company response field {field} must be an integer") from exc
        if result < 0:
            raise UpdaterError(f"company response field {field} must not be negative")
        return result

    def _network_identity(self) -> dict[str, str]:
        parsed = urlparse(self.config.center_url)
        host = parsed.hostname or ""
        try:
            destination = socket.gethostbyname(host)
            result = subprocess.run(
                ["ip", "-j", "route", "get", destination],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            routes = json.loads(result.stdout) if result.returncode == 0 else []
            route = routes[0] if isinstance(routes, list) and routes else {}
            device = str(route.get("dev", "")).strip()
            address = str(route.get("prefsrc", route.get("src", ""))).strip()
            mac_path = Path("/sys/class/net") / device / "address"
            mac = mac_path.read_text(encoding="ascii").strip().upper() if mac_path.is_file() else ""
            if address:
                return {"interface": device, "ip": address, "mac": mac}
        except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
                connection.connect((host, port))
                address = str(connection.getsockname()[0])
            return {"interface": "", "ip": address, "mac": ""}
        except OSError as exc:
            raise UpdaterError(f"cannot determine network identity for update center: {exc}") from exc

    def _business_identity(self) -> dict[str, str]:
        try:
            data = yaml.safe_load(Path(self.config.business_config_file).read_text(encoding="utf-8")) or {}
            if not isinstance(data, dict):
                return {}
            upload = data.get("upload")
            company = data.get("company_update")
            upload = upload if isinstance(upload, dict) else {}
            company = company if isinstance(company, dict) else {}
            values = {
                "hospital_code": str(upload.get("hospital_code", "")).strip(),
                "hospital_id": str(company.get("hospital_id", "")).strip(),
                "hospital_area_code": str(company.get("hospital_area_code", "")).strip(),
                "hospital_area_id": str(company.get("hospital_area_id", "")).strip(),
                "dept_code": str(company.get("dept_code", "")).strip(),
                "dept_id": str(company.get("dept_id", "")).strip(),
            }
            return values
        except (OSError, yaml.YAMLError):
            return {}

    def _base_terminal_payload(self) -> dict[str, Any]:
        identity = self._network_identity()
        payload: dict[str, Any] = {
            "appCode": self.config.app_code,
            "terminalIp": identity["ip"],
            "terminalName": socket.gethostname(),
        }
        if identity["mac"]:
            payload["terminalMac"] = identity["mac"]
        return payload

    def _terminal_payload(self) -> dict[str, Any]:
        payload = self._base_terminal_payload()
        organization = self._business_identity()
        for source, target in (
            ("hospital_code", "hospitalCode"),
            ("hospital_id", "hospitalId"),
            ("hospital_area_code", "campusCode"),
            ("hospital_area_id", "campusId"),
            ("dept_code", "deptCode"),
            ("dept_id", "deptId"),
        ):
            if organization.get(source):
                payload[target] = organization[source]
        return payload

    def _check_payload(self) -> dict[str, Any]:
        payload = self._base_terminal_payload()
        payload.update(
            currentVersion=server_version(self._current_version()),
            platform=self.config.platform,
            osVersion=f"{platform.system()} {platform.release()} {platform.machine()}",
        )
        organization = self._business_identity()
        for source, target in (
            ("hospital_code", "hospitalCode"),
            ("hospital_id", "hospitalId"),
            ("hospital_area_code", "hospitalAreaCode"),
            ("dept_code", "deptCode"),
        ):
            if organization.get(source):
                payload[target] = organization[source]
        version_id = self.state_store.read().get("current_version_id")
        if version_id not in (None, "", 0, "0"):
            payload["currentVersionId"] = int(version_id)
        return payload

    async def _request_json(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.config.center_url.rstrip('/')}{path}"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30, sock_connect=10)) as session:
                async with session.request(method, url, json=body) as response:
                    try:
                        payload = await response.json(content_type=None)
                    except (ValueError, aiohttp.ClientError) as exc:
                        detail = await response.text()
                        raise UpdaterError(detail or f"company API returned invalid JSON: {exc}") from exc
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise UpdaterError(f"company API unavailable: {exc}") from exc
        if response.status not in {200, 201}:
            raise UpdaterError(str(payload.get("msg") or f"company API failed: HTTP {response.status}"))
        code = self._integer(payload.get("code"), "code")
        if payload.get("success") is not True or code not in {0, 200}:
            raise UpdaterError(str(payload.get("msg") or f"company API rejected request: code={code}"))
        return payload

    def status(self) -> dict[str, Any]:
        state = self.state_store.read()
        try:
            identity = self._network_identity()
        except UpdaterError:
            identity = {"interface": "", "ip": "", "mac": ""}
        update = state.get("update")
        if isinstance(update, dict):
            update = dict(update)
            for field in ("record_id", "strategy_id", "version_id", "package_id"):
                if update.get(field) is not None:
                    update[field] = str(update[field])
        current_version_id = state.get("current_version_id")
        return {
            "ok": True,
            "enabled": self.config.enabled,
            "center_url": self.config.center_url,
            "app_code": self.config.app_code,
            "platform": self.config.platform,
            "allow_unsigned_packages": self.config.allow_unsigned_packages,
            "current_version": server_version(self._current_version()),
            # Company IDs are int64 and exceed JavaScript's safe integer range.
            "current_version_id": str(current_version_id) if current_version_id is not None else None,
            "update": update,
            "download": state.get("download"),
            "network": identity,
            "organization": self._business_identity(),
            "last_check_at": state.get("last_check_at"),
            "last_success_at": state.get("last_success_at"),
            "last_terminal_report_at": state.get("last_terminal_report_at"),
            "last_terminal_report_error": state.get("last_terminal_report_error", ""),
            "last_error": state.get("last_error", ""),
            "previous_version": state.get("previous_version", ""),
            "pending_reports": len(state.get("pending_reports", [])),
            "installing": bool(state.get("installing")),
            "operation": str(state.get("operation", "")),
        }

    def _save_config(self) -> None:
        data = asdict(self.config)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_name(f".{self.config_path.name}.{uuid.uuid4().hex}")
        temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.chmod(temporary, 0o640)
        os.replace(temporary, self.config_path)

    def set_center_url(self, center_url: str) -> dict[str, Any]:
        previous = self.config.center_url
        self.config.center_url = center_url.strip().rstrip("/")
        try:
            self.config.validate()
            self._save_config()
        except Exception:
            self.config.center_url = previous
            raise
        return self.status()

    def _save_business_identity(self, values: dict[str, Any]) -> None:
        source = Path(self.config.business_config_file)
        data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise UpdaterError("business config root must be a mapping")
        normalized: dict[str, str] = {}
        for field in self.ORGANIZATION_FIELDS:
            value = str(values.get(field, "")).strip()
            if len(value) > 128 or any(char in value for char in "\r\n"):
                raise UpdaterError(f"organization field {field} is invalid")
            normalized[field] = value
        if not normalized["hospital_code"]:
            raise UpdaterError("hospital_code must not be empty")
        upload = data.setdefault("upload", {})
        company = data.setdefault("company_update", {})
        if not isinstance(upload, dict) or not isinstance(company, dict):
            raise UpdaterError("business upload/company_update config must be a mapping")
        upload["hospital_code"] = normalized.pop("hospital_code")
        company.update(normalized)
        temporary = source.with_name(f".{source.name}.{uuid.uuid4().hex}")
        try:
            temporary.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            os.chmod(temporary, 0o640)
            os.replace(temporary, source)
        finally:
            temporary.unlink(missing_ok=True)

    async def report_terminal_info(self) -> dict[str, Any]:
        try:
            await self._request_json("POST", "/api/auto-update/report-terminal-info", self._terminal_payload())
        except Exception as exc:
            state = self.state_store.read()
            state["last_terminal_report_error"] = str(exc)
            self.state_store.write(state)
            raise
        state = self.state_store.read()
        state.update(last_terminal_report_at=int(time.time()), last_terminal_report_error="")
        self.state_store.write(state)
        return self.status()

    async def configure_company(self, center_url: str, organization: dict[str, Any]) -> dict[str, Any]:
        previous_url = self.config.center_url
        business_path = Path(self.config.business_config_file)
        previous_business = business_path.read_bytes()
        try:
            self.set_center_url(center_url)
            self._save_business_identity(organization)
        except Exception:
            self.config.center_url = previous_url
            self._save_config()
            business_path.write_bytes(previous_business)
            os.chmod(business_path, 0o640)
            raise
        try:
            return await self.report_terminal_info()
        except Exception:
            return self.status()

    async def _flush_reports(self) -> None:
        state = self.state_store.read()
        pending = state.get("pending_reports")
        if not isinstance(pending, list) or not pending:
            return
        remaining: list[dict[str, Any]] = []
        for index, item in enumerate(pending):
            if not isinstance(item, dict):
                continue
            try:
                await self._request_json("POST", str(item["path"]), dict(item["body"]))
            except Exception:
                remaining.extend(value for value in pending[index:] if isinstance(value, dict))
                break
        state = self.state_store.read()
        state["pending_reports"] = remaining
        self.state_store.write(state)

    async def _queue_report(self, path: str, body: dict[str, Any]) -> None:
        state = self.state_store.read()
        pending = state.get("pending_reports")
        if not isinstance(pending, list):
            pending = []
        pending.append({"path": path, "body": body, "queued_at": int(time.time())})
        state["pending_reports"] = pending[-100:]
        self.state_store.write(state)
        try:
            await self._flush_reports()
        except Exception:
            LOGGER.exception("failed to flush company update reports")

    async def _report_upgrade(
        self,
        status: int,
        result: str,
        *,
        error: str = "",
        current_version: str = "",
        current_version_id: int | None = None,
    ) -> None:
        update = self.state_store.read().get("update")
        if not isinstance(update, dict) or not update.get("record_id"):
            return
        body: dict[str, Any] = {
            "recordId": int(update["record_id"]),
            "upgradeStatus": status,
            "upgradeResult": result[:2000],
        }
        if error:
            body["errorMessage"] = error[:2000]
        if current_version:
            body["currentVersion"] = server_version(current_version)
        if current_version_id is not None:
            body["currentVersionId"] = int(current_version_id)
        await self._queue_report("/api/auto-update/report", body)

    async def _report_rollback(
        self,
        status: int,
        result: str,
        *,
        error: str = "",
        current_version: str = "",
        current_version_id: int | None = None,
    ) -> None:
        update = self.state_store.read().get("update")
        if not isinstance(update, dict) or not update.get("record_id"):
            return
        body: dict[str, Any] = {
            "recordId": int(update["record_id"]),
            "rollbackStatus": status,
            "rollbackResult": result[:2000],
        }
        if error:
            body["errorMessage"] = error[:2000]
        if current_version:
            body["currentVersion"] = server_version(current_version)
        if current_version_id is not None:
            body["currentVersionId"] = int(current_version_id)
        await self._queue_report("/api/auto-update/rollback-report", body)

    async def _check_company(self, *, report_terminal: bool = True) -> dict[str, Any] | None:
        if report_terminal:
            await self.report_terminal_info()
        response = await self._request_json("POST", "/api/auto-update/check", self._check_payload())
        data = response.get("data")
        if not isinstance(data, dict) or data.get("hasUpdate") is not True:
            return None
        required = ("recordId", "newVersion", "newVersionId", "packageFileId", "packageFileName", "packageSize")
        missing = [field for field in required if data.get(field) in (None, "")]
        if missing:
            raise UpdaterError("company update response missing: " + ", ".join(missing))
        filename = Path(str(data["packageFileName"])).name
        if filename != str(data["packageFileName"]) or not filename.lower().endswith(".zip"):
            raise UpdaterError("company update package filename is invalid")
        package_size = self._integer(data["packageSize"], "packageSize")
        if package_size is None or not 1 <= package_size <= MAX_COMPANY_PACKAGE_BYTES:
            raise UpdaterError("company update package size is outside the allowed range")
        download_url = str(data.get("downloadUrl", "")).strip()
        if download_url:
            parsed_url = urlparse(download_url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
                raise UpdaterError("company update download URL must use HTTP or HTTPS")
            if parsed_url.username or parsed_url.password:
                raise UpdaterError("company update download URL must not contain credentials")
        return {
            "record_id": self._integer(data["recordId"], "recordId"),
            "strategy_id": self._integer(data.get("strategyId"), "strategyId", optional=True),
            "version": server_version(data["newVersion"]),
            "version_id": self._integer(data["newVersionId"], "newVersionId"),
            "package_id": self._integer(data["packageFileId"], "packageFileId"),
            "package_name": filename,
            "package_size": package_size,
            "download_url": download_url,
            "auto_upgrade": data.get("autoUpgrade") is True,
            "release_note": str(data.get("releaseNote", "")),
            "release_time": str(data.get("releaseTime", "")),
        }

    async def check_once(self, *, auto_execute: bool = True) -> dict[str, Any]:
        await self._flush_reports()
        state = self.state_store.read()
        state["last_check_at"] = int(time.time())
        self.state_store.write(state)
        try:
            update = await self._check_company()
        except Exception as exc:
            state = self.state_store.read()
            state["last_error"] = str(exc)
            self.state_store.write(state)
            raise
        state = self.state_store.read()
        previous_update = state.get("update")
        previous_version = previous_update.get("version") if isinstance(previous_update, dict) else None
        state.update(last_success_at=int(time.time()), last_error="", update=update)
        if update is None or update.get("version") != previous_version:
            state["download"] = None
        self.state_store.write(state)
        if auto_execute and update and update["auto_upgrade"]:
            await self.download_update()
            await self.install_downloaded()
        return self.status()

    async def _download_to(self, url: str, partial: Path, expected_size: int) -> None:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None, sock_connect=30)) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        detail = await response.text()
                        raise UpdaterError(detail or f"package download failed: HTTP {response.status}")
                    content_length = response.content_length
                    if content_length is not None and content_length != expected_size:
                        raise UpdaterError("package Content-Length does not match the update response")
                    downloaded = 0
                    with partial.open("wb") as handle:
                        async for chunk in response.content.iter_chunked(1024 * 1024):
                            downloaded += len(chunk)
                            if downloaded > expected_size:
                                raise UpdaterError("package download exceeded the declared size")
                            handle.write(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise UpdaterError(f"package download failed: {exc}") from exc

    async def download_update(self) -> dict[str, Any]:
        async with self.operation_lock:
            state = self.state_store.read()
            update = state.get("update")
            if not isinstance(update, dict):
                raise UpdaterError("no company update is available")
            destination = self.packages_dir / str(update["package_name"])
            partial = destination.with_suffix(destination.suffix + ".part")
            await self._report_upgrade(1, "Package download started.")
            try:
                if not self.config.allow_unsigned_packages:
                    raise UpdaterError("unsigned company ZIP packages are disabled on this device")
                url = str(update.get("download_url", ""))
                if not url:
                    refreshed = await self._check_company(report_terminal=False)
                    if not refreshed or refreshed["version"] != update["version"]:
                        raise UpdaterError("company update no longer provides the selected package")
                    update = refreshed
                    url = str(update.get("download_url", ""))
                    state = self.state_store.read()
                    state["update"] = update
                    self.state_store.write(state)
                if not url:
                    raise UpdaterError("company update did not provide a temporary download URL")
                try:
                    await self._download_to(url, partial, int(update["package_size"]))
                except UpdaterError:
                    refreshed = await self._check_company(report_terminal=False)
                    if (
                        not refreshed
                        or refreshed["version"] != update["version"]
                        or not refreshed["download_url"]
                    ):
                        raise
                    update = refreshed
                    state = self.state_store.read()
                    state["update"] = update
                    self.state_store.write(state)
                    await self._download_to(
                        str(refreshed["download_url"]), partial, int(refreshed["package_size"])
                    )
                if partial.stat().st_size != int(update["package_size"]):
                    raise UpdaterError("downloaded package size does not match the update response")
                os.replace(partial, destination)
                info = verify_company_package(
                    destination,
                    expected_size=int(update["package_size"]),
                    expected_app_code=self.config.app_code,
                    expected_platform=self.config.platform,
                    expected_version=str(update["version"]),
                    work_root=self.config.state_dir,
                )
                try:
                    manifest = dict(info.manifest)
                finally:
                    info.cleanup()
            except Exception as exc:
                partial.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                value = self.state_store.read()
                value.update(download=None, last_error=str(exc))
                self.state_store.write(value)
                await self._report_upgrade(
                    5,
                    "Package download or verification failed.",
                    error=str(exc),
                    current_version=self._current_version(),
                    current_version_id=self._integer(
                        value.get("current_version_id"), "currentVersionId", optional=True
                    ),
                )
                raise
            state = self.state_store.read()
            state["download"] = {
                "ready": True,
                "path": str(destination),
                "manifest": manifest,
                "downloaded_at": int(time.time()),
                "package_sha256": sha256_file(destination),
            }
            state["last_error"] = ""
            self.state_store.write(state)
            await self._report_upgrade(2, "Package downloaded; size, ZIP CRC, and payload SHA-256 verified.")
            return self.status()

    async def install_downloaded(self) -> dict[str, Any]:
        async with self.operation_lock:
            state = self.state_store.read()
            download = state.get("download")
            update = state.get("update")
            if not isinstance(download, dict) or not download.get("ready") or not isinstance(update, dict):
                raise UpdaterError("no verified company update is ready to install")
            package_path = Path(str(download.get("path", "")))
            old_version = self._current_version()
            old_version_id = self._integer(state.get("current_version_id"), "currentVersionId", optional=True)
            state["installing"] = True
            self.state_store.write(state)
            await self._report_upgrade(3, "Installation started; preparing atomic application release.")
            try:
                info = verify_company_package(
                    package_path,
                    expected_size=int(update["package_size"]),
                    expected_app_code=self.config.app_code,
                    expected_platform=self.config.platform,
                    expected_version=str(update["version"]),
                    work_root=self.config.state_dir,
                )
                try:
                    result = await asyncio.to_thread(self.installer.install, info)
                finally:
                    info.cleanup()
            except Exception as exc:
                state = self.state_store.read()
                state.update(last_error=str(exc), installing=False)
                self.state_store.write(state)
                await self._report_upgrade(
                    5,
                    "Upgrade failed; the application installer restored the previous release.",
                    error=str(exc),
                    current_version=old_version,
                    current_version_id=old_version_id,
                )
                if self.installer.last_rollback_attempted and self.installer.last_rollback_succeeded:
                    await self._report_rollback(0, "Automatic rollback started after installation failure.")
                    await self._report_rollback(
                        1,
                        "Automatic rollback completed; previous release is active.",
                        current_version=old_version,
                        current_version_id=old_version_id,
                    )
                elif self.installer.last_rollback_attempted:
                    await self._report_rollback(2, "Automatic rollback failed.", error=str(exc))
                raise
            new_version_id = int(update["version_id"])
            await self._report_upgrade(
                4,
                "Upgrade completed and health check passed.",
                current_version=str(result["version"]),
                current_version_id=new_version_id,
            )
            state = self.state_store.read()
            completed_record_id = update.get("record_id")
            state.update(
                current_version_id=new_version_id,
                previous_version_id=old_version_id,
                previous_version=server_version(old_version),
                last_record_id=completed_record_id,
                last_error="",
                installing=False,
                operation="",
                download=None,
                update=None,
            )
            self.state_store.write(state)
            self._schedule_agent_restart()
            return self.status()

    def _start_background(self, operation: str, callback: Callable[[], Any]) -> dict[str, Any]:
        if self.background_operation is not None and not self.background_operation.done():
            raise UpdaterError("another update operation is already running")
        state = self.state_store.read()
        state.update(installing=True, operation=operation, last_error="")
        self.state_store.write(state)

        async def run() -> None:
            await asyncio.sleep(2)
            try:
                await callback()
            except Exception as exc:
                LOGGER.exception("background update operation failed: %s", operation)
                value = self.state_store.read()
                value.update(installing=False, operation="", last_error=str(exc))
                self.state_store.write(value)

        self.background_operation = asyncio.create_task(run(), name=f"jvlei-update-{operation}")
        return self.status()

    def start_install(self) -> dict[str, Any]:
        state = self.state_store.read()
        download = state.get("download")
        if not isinstance(download, dict) or not download.get("ready"):
            raise UpdaterError("no verified company update is ready to install")
        return self._start_background("install", self.install_downloaded)

    def start_auto_update(self) -> dict[str, Any]:
        state = self.state_store.read()
        update = state.get("update")
        if not isinstance(update, dict) or update.get("auto_upgrade") is not True:
            raise UpdaterError("no automatic company update is available")

        async def execute() -> None:
            await self.download_update()
            await self.install_downloaded()

        return self._start_background("auto_upgrade", execute)

    def start_rollback(self) -> dict[str, Any]:
        if not self.state_store.read().get("previous_release"):
            raise UpdaterError("no previous release is available")
        return self._start_background("rollback", self.rollback)

    def _schedule_agent_restart(self) -> None:
        try:
            subprocess.Popen(
                [
                    "systemd-run",
                    "--quiet",
                    "--collect",
                    "--unit=jvlei-updater-self-restart",
                    "--on-active=3s",
                    "systemctl",
                    "restart",
                    "jvlei-updater.service",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            LOGGER.exception("failed to schedule updater service restart")

    async def rollback(self) -> dict[str, Any]:
        async with self.operation_lock:
            state = self.state_store.read()
            update = state.get("update")
            if not isinstance(update, dict):
                record_id = state.get("last_record_id")
                if record_id:
                    state["update"] = {"record_id": record_id}
                    self.state_store.write(state)
            await self._report_rollback(0, "Manual rollback started from the device management page.")
            try:
                result = await asyncio.to_thread(self.installer.rollback)
            except Exception as exc:
                await self._report_rollback(2, "Manual rollback failed.", error=str(exc))
                raise
            previous_id = self._integer(state.get("previous_version_id"), "previousVersionId", optional=True)
            await self._report_rollback(
                1,
                "Manual rollback completed and health check passed.",
                current_version=str(result["version"]),
                current_version_id=previous_id,
            )
            state = self.state_store.read()
            current_id = state.get("current_version_id")
            state.update(
                current_version_id=previous_id,
                previous_version_id=current_id,
                last_record_id=None,
                update=None,
                download=None,
                last_error="",
                installing=False,
                operation="",
            )
            self.state_store.write(state)
            self._schedule_agent_restart()
            return self.status()

    async def run_boot_check(self) -> None:
        if not self.config.enabled or not self.config.boot_check:
            return
        try:
            status = await self.check_once(auto_execute=False)
            update = status.get("update")
            if isinstance(update, dict) and update.get("auto_upgrade") is True:
                self.start_auto_update()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("company update boot check failed: %s", exc)

    def stop(self) -> None:
        self.stop_event.set()
