from __future__ import annotations

import asyncio
import copy
import hmac
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import web

from .auth import Session, SessionStore
from .config import (
    GADGET_MODES,
    PRINTER_DRIVER_COMMANDS,
    AppConfig,
    build_printer_pnp_string,
    is_msc_mode,
    load_config,
    resolve_udc_device,
    save_config,
    validate_config,
)
from .cups_manager import CupsError, CupsManager
from .driver_manager import DriverError, DriverManager, MAX_DRIVER_BYTES
from .maintenance import MaintenanceManager
from .physical_print import PhysicalPrintWorker
from .prn_analyzer import analyze_recent_prn
from .report_info import ReportInfoManager
from .report_upload import ReportUploadWorker
from .updater_client import UpdaterClient, UpdaterClientError
from .wifi_manager import WifiError, WifiManager

LOGGER = logging.getLogger(__name__)
COOKIE_NAME = "gmp_session"
SESSION_KEY = (
    web.RequestKey("session", Session)
    if hasattr(web, "RequestKey")
    else "gmp_session_context"
)

class ConfigWebApp:
    def __init__(
        self,
        config_path: str | Path,
        config: AppConfig,
        sessions: SessionStore,
        report_info: ReportInfoManager,
        uploader: ReportUploadWorker,
        maintenance: MaintenanceManager,
        wifi: WifiManager | None = None,
        cups: CupsManager | None = None,
        physical_printer: PhysicalPrintWorker | None = None,
        driver_manager: DriverManager | None = None,
        updater_client: UpdaterClient | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.config = config
        self.sessions = sessions
        self.report_info = report_info
        self.uploader = uploader
        self.maintenance = maintenance
        self.wifi = wifi or WifiManager()
        self.driver_manager = driver_manager or DriverManager()
        self.cups = cups or CupsManager(custom_profile_provider=self.driver_manager.profiles)
        self.updater = updater_client or UpdaterClient()
        self.physical_printer = physical_printer or PhysicalPrintWorker(
            config.physical_printer, config.pdf, self.cups
        )
        self.hotspot_lock = asyncio.Lock()
        self.login_failures: dict[str, list[float]] = {}
        self.app = web.Application(
            middlewares=[self.security_middleware],
            client_max_size=MAX_DRIVER_BYTES + 8 * 1024 * 1024,
        )
        self.app.add_routes(
            [
                web.get("/health", self.health),
                web.get("/login", self.login_page),
                web.post("/api/login", self.login),
                web.get("/api/session", self.session_status),
                web.post("/api/logout", self.logout),
                web.get("/", self.dashboard),
                web.get("/favicon.ico", self.favicon),
                web.get(r"/static-resource/{path:.*}", self.static_resource),
                web.get("/api/status", self.status),
                web.get("/api/config", self.get_config),
                web.put("/api/config", self.put_config),
                web.get("/api/printer/config", self.get_printer_config),
                web.put("/api/printer/config", self.put_printer_config),
                web.get("/api/printer/analysis", self.printer_analysis),
                web.get(r"/api/printer/files/{name:.+}/download", self.download_printer_file),
                web.get("/api/physical-printer", self.get_physical_printer),
                web.post("/api/physical-printer/scan", self.scan_physical_printers),
                web.put("/api/physical-printer/config", self.put_physical_printer),
                web.post("/api/physical-printer/test", self.test_physical_printer),
                web.post("/api/physical-printer/control", self.control_physical_printer),
                web.delete("/api/physical-printer/queue", self.delete_physical_printer),
                web.get("/api/drivers", self.get_drivers),
                web.post("/api/drivers/analyze", self.analyze_driver),
                web.post("/api/drivers/install", self.install_driver),
                web.post("/api/drivers/rollback", self.rollback_driver),
                web.get("/api/msc/config", self.get_msc_config),
                web.put("/api/msc/config", self.put_msc_config),
                web.post("/api/msc/rebuild", self.rebuild_msc),
                web.post("/api/gadget/switch", self.switch_gadget),
                web.get("/api/reports", self.reports),
                web.get(r"/api/reports/{job_id:\d+}/download", self.download_report),
                web.post(r"/api/reports/{job_id:\d+}/retry", self.retry_report),
                web.get("/api/maintenance", self.maintenance_status),
                web.post("/api/maintenance/cleanup", self.cleanup_now),
                web.post("/api/upload/test", self.test_upload),
                web.get("/api/wifi", self.wifi_status),
                web.post("/api/wifi/radio", self.wifi_radio),
                web.post("/api/wifi/scan", self.wifi_scan),
                web.post("/api/wifi/connect", self.wifi_connect),
                web.post("/api/wifi/disconnect", self.wifi_disconnect),
                web.post("/api/wifi/forget", self.wifi_forget),
                web.get("/api/network", self.network_status),
                web.put("/api/network/ipv4", self.put_network_ipv4),
                web.put("/api/hotspot/config", self.put_hotspot_config),
                web.post("/api/hotspot/switch", self.switch_hotspot),
                web.get("/api/update/status", self.update_status),
                web.post("/api/update/pair", self.update_pair),
                web.post("/api/update/check", self.update_check),
                web.post("/api/update/download", self.update_download),
                web.post("/api/update/install", self.update_install),
                web.post("/api/update/rollback", self.update_rollback),
                web.put("/api/update/policy", self.update_policy),
            ]
        )

    @web.middleware
    async def security_middleware(self, request: web.Request, handler):
        if request.path in {"/health", "/login", "/api/login", "/favicon.ico"} or request.path.startswith(
            "/static-resource/"
        ):
            return await handler(request)
        token = request.cookies.get(COOKIE_NAME, "")
        session = self.sessions.get(token)
        if session is None:
            if request.path.startswith("/api/"):
                return web.json_response({"ok": False, "error": "authentication required"}, status=401)
            raise web.HTTPFound("/login")
        request[SESSION_KEY] = session
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token", "")
            if not supplied or supplied != session.csrf:
                return web.json_response({"ok": False, "error": "invalid CSRF token"}, status=403)
        return await handler(request)

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "gadget-web", "version": "0.21.0"})

    async def login_page(self, request: web.Request) -> web.Response:
        return self._frontend_index()

    async def login(self, request: web.Request) -> web.Response:
        remote = request.remote or "unknown"
        now = time.time()
        failures = [value for value in self.login_failures.get(remote, []) if now - value < 300]
        self.login_failures[remote] = failures
        if len(failures) >= 5:
            return web.json_response({"ok": False, "error": "too many failed attempts"}, status=429)
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            return web.json_response({"ok": False, "error": "invalid request body"}, status=400)
        config = load_config(self.config_path)
        username = str(payload.get("username", ""))
        password = str(payload.get("password", ""))
        username_ok = hmac.compare_digest(username, config.web.username)
        password_ok = hmac.compare_digest(
            password,
            config.web.password,
        )
        ok = username_ok & password_ok
        if not ok:
            failures.append(now)
            return web.json_response({"ok": False, "error": "invalid username or password"}, status=401)
        self.login_failures.pop(remote, None)
        session = self.sessions.create(config.web.username)
        response = web.json_response(
            {"ok": True, "csrf": session.csrf, "username": session.username}
        )
        response.set_cookie(
            COOKIE_NAME,
            session.token,
            max_age=self.sessions.lifetime,
            httponly=True,
            secure=request.secure,
            samesite="Strict",
        )
        return response

    async def session_status(self, request: web.Request) -> web.Response:
        session = request[SESSION_KEY]
        return web.json_response(
            {"ok": True, "csrf": session.csrf, "username": session.username}
        )

    async def logout(self, request: web.Request) -> web.Response:
        token = request.cookies.get(COOKIE_NAME, "")
        self.sessions.remove(token)
        response = web.json_response({"ok": True})
        response.del_cookie(COOKIE_NAME)
        return response

    async def dashboard(self, request: web.Request) -> web.Response:
        return self._frontend_index()

    async def favicon(self, request: web.Request) -> web.StreamResponse:
        return self._frontend_file("favicon.ico")

    async def static_resource(self, request: web.Request) -> web.StreamResponse:
        relative_path = str(request.match_info.get("path", "")).strip("/")
        return self._frontend_file(f"static-resource/{relative_path}")

    def _frontend_index(self) -> web.StreamResponse:
        return self._frontend_file("index.html", missing_status=503)

    def _frontend_file(self, relative_path: str, missing_status: int = 404) -> web.StreamResponse:
        static_root = Path(self.config.web.static_dir).resolve()
        target = (static_root / relative_path).resolve()
        try:
            target.relative_to(static_root)
        except ValueError:
            raise web.HTTPNotFound()
        if not target.is_file():
            if missing_status == 503:
                return web.Response(
                    text="Vue frontend bundle is not installed",
                    status=503,
                    content_type="text/plain",
                )
            raise web.HTTPNotFound()
        return web.FileResponse(target)

    async def status(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        xml_valid = False
        xml_error = ""
        try:
            self.report_info.config = config.device
            self.report_info.snapshot()
            xml_valid = True
        except ValueError as exc:
            xml_error = str(exc)
        try:
            resolved_udc = resolve_udc_device(config.gadget.udc_device)
            udc_state_path = Path("/sys/class/udc") / resolved_udc / "state"
            udc_state = udc_state_path.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, RuntimeError):
            resolved_udc = config.gadget.udc_device
            udc_state = "missing"
        bound = ""
        for gadget_dir in (config.gadget.msc_gadget_dir, config.gadget.printer_gadget_dir):
            attr = Path(gadget_dir) / "UDC"
            if attr.exists() and attr.read_text(encoding="utf-8").strip():
                bound = Path(gadget_dir).name
                break
        disk = shutil.disk_usage(config.runtime.data_dir)
        return web.json_response(
            {
                "ok": True,
                "mode": config.gadget.mode,
                "udc": resolved_udc,
                "udc_state": udc_state,
                "bound_gadget": bound,
                "xml_valid": xml_valid,
                "xml_error": xml_error,
                "report_counts": self.uploader.store.counts(),
                "maintenance": self.maintenance.status(),
                "disk_free": disk.free,
                "disk_total": disk.total,
            }
        )

    async def get_config(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        return web.json_response(
            {
                "mode": config.gadget.mode,
                "device_code": config.device.device_code,
                "exam_doct": config.device.exam_doct,
                "exam_doct_code": config.device.exam_doct_code,
                "upload_enabled": config.upload.enabled,
                "deduplicate": config.upload.deduplicate and config.msc.deduplicate,
                "endpoint": config.upload.endpoint,
                "timeout_seconds": config.upload.timeout_seconds,
                "retry_interval_seconds": config.upload.retry_interval_seconds,
                "max_attempts": config.upload.max_attempts,
                "cleanup_enabled": config.cleanup.enabled,
                "cleanup_interval_hours": config.cleanup.interval_hours,
                "report_retention_days": config.cleanup.report_retention_days,
                "log_retention_days": config.cleanup.log_retention_days,
            }
        )

    async def put_config(self, request: web.Request) -> web.Response:
        payload = await request.json()
        config = load_config(self.config_path)
        previous_msc_deduplicate = config.msc.deduplicate
        config.device.device_code = str(payload.get("device_code", config.device.device_code)).strip()
        config.device.exam_doct = str(payload.get("exam_doct", config.device.exam_doct)).strip()
        config.device.exam_doct_code = str(payload.get("exam_doct_code", config.device.exam_doct_code)).strip()
        config.upload.enabled = bool(payload.get("upload_enabled", config.upload.enabled))
        if "deduplicate" in payload:
            if not isinstance(payload["deduplicate"], bool):
                return web.json_response(
                    {"ok": False, "error": "deduplicate must be a boolean"},
                    status=400,
                )
            deduplicate = payload["deduplicate"]
            config.upload.deduplicate = deduplicate
            config.msc.deduplicate = deduplicate
        config.upload.endpoint = str(payload.get("endpoint", config.upload.endpoint)).strip()
        config.upload.timeout_seconds = int(payload.get("timeout_seconds", config.upload.timeout_seconds))
        config.upload.retry_interval_seconds = int(
            payload.get("retry_interval_seconds", config.upload.retry_interval_seconds)
        )
        config.upload.max_attempts = int(payload.get("max_attempts", config.upload.max_attempts))
        config.cleanup.enabled = bool(payload.get("cleanup_enabled", config.cleanup.enabled))
        config.cleanup.interval_hours = int(
            payload.get("cleanup_interval_hours", config.cleanup.interval_hours)
        )
        config.cleanup.report_retention_days = int(
            payload.get("report_retention_days", config.cleanup.report_retention_days)
        )
        config.cleanup.log_retention_days = int(
            payload.get("log_retention_days", config.cleanup.log_retention_days)
        )
        try:
            validate_config(config)
            manager = ReportInfoManager(config.device)
            snapshot = await asyncio.to_thread(
                manager.write,
                config.device.device_code,
                config.device.exam_doct,
                config.device.exam_doct_code,
            )
            await asyncio.to_thread(save_config, self.config_path, config)
        except (ValueError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        self.config = config
        self.report_info = manager
        self.uploader.report_info = manager
        self.uploader.update_config(config.upload)
        self.uploader.wake()
        self.maintenance.update_config(
            config.cleanup,
            config.runtime,
            config.pdf,
            config.printer,
            config.msc,
        )
        collector_restarted = False
        warning = ""
        if previous_msc_deduplicate != config.msc.deduplicate and is_msc_mode(config.gadget.mode):
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    ["systemctl", "restart", "gadget-collector.service"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=20,
                )
                collector_restarted = True
            except (OSError, subprocess.SubprocessError) as exc:
                warning = f"configuration saved, but collector restart failed: {exc}"
                LOGGER.warning(warning)
        return web.json_response(
            {
                "ok": True,
                "xml_sha256": snapshot.sha256,
                "collector_restarted": collector_restarted,
                "warning": warning,
            }
        )

    async def get_printer_config(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        labels = {
            "universal": "通用 PCL/PCL XL/PostScript",
            "pcl": "PCL/PCL XL",
            "postscript": "PostScript",
            "raw": "原始数据采集",
        }
        return web.json_response(
            {
                "driver_profile": config.printer.driver_profile,
                "driver_profiles": [
                    {
                        "value": value,
                        "label": labels[value],
                        "commands": commands,
                    }
                    for value, commands in PRINTER_DRIVER_COMMANDS.items()
                ],
                "usb_product": config.printer.usb_product,
                "usb_serial": config.printer.usb_serial,
                "idle_complete_seconds": config.printer.idle_complete_seconds,
                "min_job_bytes": config.printer.min_job_bytes,
                "active": config.gadget.mode in {"printer", "printer_hid"},
            }
        )

    async def put_printer_config(self, request: web.Request) -> web.Response:
        payload = await request.json()
        previous = load_config(self.config_path)
        config = copy.deepcopy(previous)
        config.printer.driver_profile = str(
            payload.get("driver_profile", config.printer.driver_profile)
        ).strip()
        config.printer.usb_product = str(
            payload.get("usb_product", config.printer.usb_product)
        ).strip()
        config.printer.usb_serial = str(
            payload.get("usb_serial", config.printer.usb_serial)
        ).strip()
        try:
            config.printer.idle_complete_seconds = float(
                payload.get("idle_complete_seconds", config.printer.idle_complete_seconds)
            )
            config.printer.min_job_bytes = int(
                payload.get("min_job_bytes", config.printer.min_job_bytes)
            )
            config.printer.usb_pnp_string = build_printer_pnp_string(config.printer)
            validate_config(config)
            await asyncio.to_thread(save_config, self.config_path, config)
        except (KeyError, TypeError, ValueError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

        applied = False
        if config.gadget.mode in {"printer", "printer_hid"}:
            try:
                await self._reapply_gadget(config)
                applied = True
            except Exception as exc:
                LOGGER.exception("printer gadget reconfiguration failed")
                await asyncio.to_thread(save_config, self.config_path, previous)
                try:
                    await self._reapply_gadget(previous)
                except Exception:
                    LOGGER.exception("failed to restore previous printer gadget configuration")
                return web.json_response(
                    {"ok": False, "error": f"printer gadget apply failed: {exc}"},
                    status=500,
                )
        self.config = config
        return web.json_response(
            {
                "ok": True,
                "applied": applied,
            }
        )

    async def printer_analysis(self, request: web.Request) -> web.Response:
        try:
            limit = int(request.query.get("limit", "20"))
        except ValueError:
            return web.json_response({"ok": False, "error": "limit must be an integer"}, status=400)
        config = load_config(self.config_path)
        jobs = await asyncio.to_thread(analyze_recent_prn, config.printer.output_dir, limit)
        return web.json_response({"ok": True, "jobs": jobs})

    async def download_printer_file(self, request: web.Request) -> web.StreamResponse:
        name = request.match_info["name"]
        if Path(name).name != name or Path(name).suffix.lower() != ".prn":
            raise web.HTTPNotFound(text="print job not found")
        config = load_config(self.config_path)
        root = Path(config.printer.output_dir).resolve()
        path = (root / name).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            LOGGER.warning("blocked print job download outside output directory: %s", path)
            raise web.HTTPNotFound(text="print job not found") from None
        if not path.is_file():
            raise web.HTTPNotFound(text="print job not found")
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(path.name)}",
            "Cache-Control": "private, no-store",
        }
        return web.FileResponse(path, headers=headers)

    async def get_physical_printer(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        cups_status = await asyncio.to_thread(self.cups.status, config.physical_printer)
        print_status = await asyncio.to_thread(self.physical_printer.status)
        return web.json_response(
            {
                "ok": True,
                "config": self._physical_printer_payload(config),
                "cups": cups_status,
                "auto_print": print_status,
            }
        )

    async def scan_physical_printers(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        status = await asyncio.to_thread(self.cups.status, config.physical_printer)
        return web.json_response({"ok": True, "cups": status})

    async def put_physical_printer(self, request: web.Request) -> web.Response:
        payload = await request.json()
        config = load_config(self.config_path)
        physical = config.physical_printer
        for key in ("enabled", "auto_print", "set_default"):
            if key in payload:
                if not isinstance(payload[key], bool):
                    return web.json_response(
                        {"ok": False, "error": f"{key} must be a boolean"}, status=400
                    )
                setattr(physical, key, payload[key])
        physical.queue_name = str(payload.get("queue_name", physical.queue_name)).strip()
        physical.device_uri = str(payload.get("device_uri", physical.device_uri)).strip()
        physical.driver_profile = str(
            payload.get("driver_profile", physical.driver_profile)
        ).strip()
        physical.page_size = str(payload.get("page_size", physical.page_size)).strip()
        physical.resolution = str(payload.get("resolution", physical.resolution)).strip()
        try:
            physical.copies = int(payload.get("copies", physical.copies))
            validate_config(config)
            applied = False
            if physical.enabled:
                await asyncio.to_thread(self.cups.configure, physical)
                applied = True
            await asyncio.to_thread(save_config, self.config_path, config)
        except (CupsError, OSError, TypeError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        self.config = config
        self.physical_printer.update_config(physical)
        self.physical_printer.wake()
        status = await asyncio.to_thread(self.cups.status, physical)
        return web.json_response(
            {
                "ok": True,
                "applied": applied,
                "config": self._physical_printer_payload(config),
                "cups": status,
            }
        )

    async def test_physical_printer(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        if not config.physical_printer.enabled:
            return web.json_response(
                {"ok": False, "error": "physical printer is not enabled"}, status=400
            )
        try:
            job_id = await asyncio.to_thread(self.cups.test_print, config.physical_printer)
        except (CupsError, OSError, subprocess.SubprocessError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "job_id": job_id})

    async def control_physical_printer(self, request: web.Request) -> web.Response:
        payload = await request.json()
        action = str(payload.get("action", "")).strip()
        if action not in {"pause", "resume"}:
            return web.json_response({"ok": False, "error": "unsupported queue action"}, status=400)
        config = load_config(self.config_path)
        try:
            await asyncio.to_thread(
                self.cups.set_queue_enabled,
                config.physical_printer.queue_name,
                action == "resume",
            )
        except CupsError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        status = await asyncio.to_thread(self.cups.status, config.physical_printer)
        return web.json_response({"ok": True, "cups": status})

    async def delete_physical_printer(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        try:
            await asyncio.to_thread(
                self.cups.delete_queue, config.physical_printer.queue_name
            )
            config.physical_printer.enabled = False
            config.physical_printer.auto_print = False
            await asyncio.to_thread(save_config, self.config_path, config)
        except (CupsError, OSError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        self.config = config
        self.physical_printer.update_config(config.physical_printer)
        self.physical_printer.wake()
        return web.json_response({"ok": True})

    async def get_drivers(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "drivers": await asyncio.to_thread(self.driver_manager.drivers),
                "profiles": await asyncio.to_thread(self.driver_manager.profiles),
            }
        )

    async def analyze_driver(self, request: web.Request) -> web.Response:
        """Stage and inspect a local Linux printer driver without installing it."""

        try:
            reader = await request.multipart()
            field = await reader.next()
            if field is None or field.name != "driver" or not field.filename:
                raise DriverError("请选择一个驱动文件")
            self.driver_manager.staging_dir.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".driver-upload-",
                dir=str(self.driver_manager.staging_dir),
            )
            temporary_path = Path(temporary_name)
            total = 0
            try:
                with open(descriptor, "wb", closefd=True) as handle:
                    while True:
                        chunk = await field.read_chunk(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_DRIVER_BYTES:
                            raise DriverError("驱动文件超过 512 MB 限制")
                        handle.write(chunk)
                    handle.flush()
                    os.fsync(handle.fileno())
                staged = await asyncio.to_thread(
                    self.driver_manager.stage_upload,
                    str(field.filename),
                    temporary_path,
                )
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
        except (DriverError, OSError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "upload": staged})

    async def install_driver(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            upload_id = str(payload.get("upload_id", ""))
            confirm_scripts = payload.get("confirm_scripts") is True
            result = await asyncio.to_thread(
                self.driver_manager.install,
                upload_id,
                confirm_scripts,
            )
        except (DriverError, OSError, ValueError, subprocess.SubprocessError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **result})

    async def rollback_driver(self, request: web.Request) -> web.Response:
        try:
            payload = await request.json()
            backup_id = str(payload.get("backup_id", ""))
            result = await asyncio.to_thread(self.driver_manager.rollback, backup_id)
        except (DriverError, OSError, ValueError, subprocess.SubprocessError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **result})

    async def update_status(self, request: web.Request) -> web.Response:
        return web.json_response(await self.updater.status())

    async def update_pair(self, request: web.Request) -> web.Response:
        payload = await request.json()
        code = str(payload.get("pairing_code", "")).strip()
        if not 1 <= len(code) <= 128:
            return web.json_response({"ok": False, "error": "配对码格式无效"}, status=400)
        try:
            return web.json_response(await self.updater.pair(code))
        except UpdaterClientError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)

    async def update_check(self, request: web.Request) -> web.Response:
        try:
            return web.json_response(await self.updater.check())
        except UpdaterClientError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)

    async def update_download(self, request: web.Request) -> web.Response:
        try:
            return web.json_response(await self.updater.download())
        except UpdaterClientError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)

    async def update_install(self, request: web.Request) -> web.Response:
        try:
            return web.json_response(await self.updater.install())
        except UpdaterClientError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)

    async def update_rollback(self, request: web.Request) -> web.Response:
        try:
            return web.json_response(await self.updater.rollback())
        except UpdaterClientError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)

    async def update_policy(self, request: web.Request) -> web.Response:
        payload = await request.json()
        policy = str(payload.get("install_policy", "")).strip()
        try:
            return web.json_response(await self.updater.set_policy(policy))
        except UpdaterClientError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)

    @staticmethod
    def _physical_printer_payload(config: AppConfig) -> dict[str, Any]:
        physical = config.physical_printer
        return {
            "enabled": physical.enabled,
            "auto_print": physical.auto_print,
            "queue_name": physical.queue_name,
            "device_uri": physical.device_uri,
            "driver_profile": physical.driver_profile,
            "page_size": physical.page_size,
            "resolution": physical.resolution,
            "copies": physical.copies,
            "set_default": physical.set_default,
        }

    async def get_msc_config(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        image = Path(config.msc.image_path)
        actual_size = image.stat().st_size if image.is_file() else 0
        configured_size = config.msc.image_size_mb * 1024 * 1024
        protected = []
        seed_root = Path(config.msc.protected_seed_dir)
        for value in config.msc.protected_files:
            protected.append(
                {
                    "path": value,
                    "seeded": seed_root.joinpath(*Path(value).parts).is_file(),
                }
            )
        return web.json_response(
            {
                "image_size_mb": config.msc.image_size_mb,
                "actual_size_bytes": actual_size,
                "label": config.msc.label,
                "auto_delete": config.msc.auto_delete,
                "deduplicate": config.msc.deduplicate and config.upload.deduplicate,
                "restore_protected_files": config.msc.restore_protected_files,
                "protected_files": list(config.msc.protected_files),
                "protected_status": protected,
                "rebuild_required": actual_size != configured_size,
                "active": is_msc_mode(config.gadget.mode),
            }
        )

    async def put_msc_config(self, request: web.Request) -> web.Response:
        payload = await request.json()
        config = load_config(self.config_path)
        previous_runtime = (
            config.msc.auto_delete,
            config.msc.deduplicate,
            config.msc.restore_protected_files,
            tuple(config.msc.protected_files),
        )
        try:
            config.msc.image_size_mb = int(payload.get("image_size_mb", config.msc.image_size_mb))
            config.msc.label = str(payload.get("label", config.msc.label)).strip().upper()
            for name in ("auto_delete", "deduplicate", "restore_protected_files"):
                if name in payload and not isinstance(payload[name], bool):
                    raise ValueError(f"{name} must be a boolean")
            config.msc.auto_delete = payload.get("auto_delete", config.msc.auto_delete)
            config.msc.restore_protected_files = payload.get(
                "restore_protected_files", config.msc.restore_protected_files
            )
            if "deduplicate" in payload:
                config.msc.deduplicate = payload["deduplicate"]
                config.upload.deduplicate = payload["deduplicate"]
            if "protected_files" in payload:
                if not isinstance(payload["protected_files"], list):
                    raise ValueError("protected_files must be a list")
                values: list[str] = []
                for raw in payload["protected_files"]:
                    value = str(raw).strip().replace("\\", "/")
                    if value and value not in values:
                        values.append(value)
                if len(values) > 50 or any(len(value) > 255 for value in values):
                    raise ValueError("protected_files contains too many or overly long paths")
                config.msc.protected_files = values
            validate_config(config)
            await asyncio.to_thread(save_config, self.config_path, config)
        except (TypeError, ValueError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

        current_runtime = (
            config.msc.auto_delete,
            config.msc.deduplicate,
            config.msc.restore_protected_files,
            tuple(config.msc.protected_files),
        )
        collector_restarted = False
        if previous_runtime != current_runtime and is_msc_mode(config.gadget.mode):
            try:
                await self._restart_collector()
                collector_restarted = True
            except Exception as exc:
                LOGGER.exception("msc collector restart failed")
                return web.json_response(
                    {"ok": False, "error": f"configuration saved, but collector restart failed: {exc}"},
                    status=500,
                )
        self.config = config
        self.uploader.update_config(config.upload)
        self.maintenance.update_config(
            config.cleanup,
            config.runtime,
            config.pdf,
            config.printer,
            config.msc,
        )
        image = Path(config.msc.image_path)
        actual_size = image.stat().st_size if image.is_file() else 0
        return web.json_response(
            {
                "ok": True,
                "collector_restarted": collector_restarted,
                "rebuild_required": actual_size != config.msc.image_size_mb * 1024 * 1024,
            }
        )

    async def rebuild_msc(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if payload.get("confirm") is not True:
            return web.json_response(
                {"ok": False, "error": "explicit rebuild confirmation is required"},
                status=400,
            )
        config = load_config(self.config_path)
        command = str(Path(config.gadget.apply_command).with_name("rebuild_msc_image.sh"))
        active = is_msc_mode(config.gadget.mode)
        if active:
            await self._run_command(["systemctl", "stop", "gadget-collector.service"], 20)
        try:
            result = await self._run_command([command, "--config", str(self.config_path)], 180)
        except Exception as exc:
            LOGGER.exception("msc image rebuild failed")
            return web.json_response({"ok": False, "error": f"MSC rebuild failed: {exc}"}, status=500)
        finally:
            if active:
                try:
                    await self._run_command(["systemctl", "start", "gadget-collector.service"], 20)
                except Exception:
                    LOGGER.exception("failed to restart collector after MSC rebuild")
        return web.json_response({"ok": True, "output": result.stdout[-2000:]})

    async def _run_command(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return await asyncio.to_thread(
            subprocess.run,
            command,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )

    async def _restart_collector(self) -> None:
        await self._run_command(["systemctl", "restart", "gadget-collector.service"], 20)

    async def _reapply_gadget(self, config: AppConfig) -> None:
        await self._run_command(["systemctl", "stop", "gadget-collector.service"], 20)
        try:
            await self._run_command(
                [config.gadget.apply_command, "--config", str(self.config_path)],
                60,
            )
        finally:
            await self._run_command(["systemctl", "start", "gadget-collector.service"], 20)

    async def switch_gadget(self, request: web.Request) -> web.Response:
        payload = await request.json()
        mode = str(payload.get("mode", ""))
        if mode not in GADGET_MODES:
            return web.json_response(
                {"ok": False, "error": "mode must be msc, printer, msc_hid, or printer_hid"},
                status=400,
            )
        config = load_config(self.config_path)
        previous = config.gadget.mode
        config.gadget.mode = mode
        await asyncio.to_thread(save_config, self.config_path, config)
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["systemctl", "stop", "gadget-collector.service"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
            )
            result = await asyncio.to_thread(
                subprocess.run,
                [config.gadget.apply_command, "--config", str(self.config_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=40,
            )
            await asyncio.to_thread(
                subprocess.run,
                ["systemctl", "start", "gadget-collector.service"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=20,
            )
        except Exception as exc:
            config.gadget.mode = previous
            await asyncio.to_thread(save_config, self.config_path, config)
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [config.gadget.apply_command, "--config", str(self.config_path)],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=40,
                )
                await asyncio.to_thread(
                    subprocess.run,
                    ["systemctl", "start", "gadget-collector.service"],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=20,
                )
            except Exception:
                LOGGER.exception("failed to restore previous gadget mode: %s", previous)
            return web.json_response({"ok": False, "error": f"gadget switch failed: {exc}"}, status=500)
        self.config = config
        return web.json_response({"ok": True, "mode": mode, "output": result.stdout[-2000:]})

    async def reports(self, request: web.Request) -> web.Response:
        try:
            page = int(request.query.get("page", "1"))
            page_size = int(request.query.get("page_size", request.query.get("limit", "20")))
            status = str(request.query.get("status", "")).strip().lower()
            start_at = _optional_float(request.query.get("start"))
            end_at = _optional_float(request.query.get("end"))
            if start_at is not None and end_at is not None and start_at > end_at:
                raise ValueError("start must not be after end")
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        result = await asyncio.to_thread(
            self.uploader.store.list_page,
            page,
            page_size,
            status,
            start_at,
            end_at,
        )
        return web.json_response(result)

    async def download_report(self, request: web.Request) -> web.StreamResponse:
        job_id = int(request.match_info["job_id"])
        job = await asyncio.to_thread(self.uploader.store.get, job_id)
        if job is None:
            raise web.HTTPNotFound(text="report job not found")
        config = load_config(self.config_path)
        root = Path(config.pdf.output_dir).resolve()
        path = Path(str(job["pdf_path"])).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            LOGGER.warning("blocked report download outside output directory: %s", path)
            raise web.HTTPNotFound(text="report file not found") from None
        if not path.is_file():
            raise web.HTTPNotFound(text="report file not found")
        filename = Path(str(job.get("pdf_name") or path.name)).name
        headers = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "private, no-store",
        }
        return web.FileResponse(path, headers=headers)

    async def retry_report(self, request: web.Request) -> web.Response:
        job_id = int(request.match_info["job_id"])
        changed = await asyncio.to_thread(self.uploader.store.retry, job_id)
        if changed:
            self.uploader.wake()
        return web.json_response({"ok": changed})

    async def maintenance_status(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, **self.maintenance.status()})

    async def cleanup_now(self, request: web.Request) -> web.Response:
        payload = await request.json()
        kind = str(payload.get("kind", "")).strip().lower()
        try:
            if kind == "reports":
                result = await asyncio.to_thread(self.maintenance.cleanup_reports)
            elif kind == "logs":
                result = await asyncio.to_thread(self.maintenance.cleanup_logs)
            else:
                return web.json_response(
                    {"ok": False, "error": "kind must be reports or logs"},
                    status=400,
                )
        except Exception as exc:
            LOGGER.exception("manual cleanup failed: %s", kind)
            return web.json_response({"ok": False, "error": str(exc)}, status=500)
        return web.json_response({"ok": True, "kind": kind, "result": result})

    async def test_upload(self, request: web.Request) -> web.Response:
        try:
            queued = await asyncio.to_thread(self.uploader.scan_once)
            processed = await asyncio.to_thread(self.uploader.process_ready, True)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": processed > 0, "queued": queued, "processed": processed})

    async def wifi_status(self, request: web.Request) -> web.Response:
        try:
            status = await asyncio.to_thread(self.wifi.status)
        except (WifiError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **status})

    async def wifi_radio(self, request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            status = await asyncio.to_thread(self.wifi.set_radio, bool(payload.get("enabled")))
        except (WifiError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **status})

    async def wifi_scan(self, request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            networks = await asyncio.to_thread(self.wifi.scan, str(payload.get("device", "")), True)
        except (WifiError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "networks": networks})

    async def wifi_connect(self, request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            status = await asyncio.to_thread(
                self.wifi.connect,
                str(payload.get("ssid", "")),
                str(payload.get("password", "")),
                str(payload.get("device", "")),
                bool(payload.get("hidden", False)),
                bool(payload.get("autoconnect", True)),
            )
        except (WifiError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **status})

    async def wifi_disconnect(self, request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            status = await asyncio.to_thread(self.wifi.disconnect, str(payload.get("device", "")))
        except (WifiError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **status})

    async def wifi_forget(self, request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            status = await asyncio.to_thread(self.wifi.forget, str(payload.get("connection", "")))
        except (WifiError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **status})

    async def network_status(self, request: web.Request) -> web.Response:
        config = load_config(self.config_path)
        try:
            ethernet = await asyncio.to_thread(self.wifi.ethernet_status)
            wifi = await asyncio.to_thread(self.wifi.status)
            async with self.hotspot_lock:
                hotspot = await asyncio.to_thread(self.wifi.hotspot_status, config.hotspot)
        except (WifiError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(
            {
                "ok": True,
                "ethernet": ethernet,
                "wifi": wifi,
                "hotspot": hotspot,
            }
        )

    async def put_network_ipv4(self, request: web.Request) -> web.Response:
        payload = await request.json()
        dns = payload.get("dns", [])
        if not isinstance(dns, (list, tuple, str)):
            return web.json_response({"ok": False, "error": "dns must be a list or string"}, status=400)
        try:
            prefix_length = int(payload.get("prefix_length", 24))
            configuration = await asyncio.to_thread(
                self.wifi.configure_ipv4,
                str(payload.get("interface_type", "")),
                str(payload.get("mode", "")),
                str(payload.get("address", "")),
                prefix_length,
                str(payload.get("gateway", "")),
                dns,
                str(payload.get("device", "")),
            )
            await asyncio.to_thread(self.wifi.schedule_ipv4_activation, configuration, 2)
        except (WifiError, ValueError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response(
            {
                "ok": True,
                **configuration,
                "activation_delay_seconds": 2,
            }
        )

    async def put_hotspot_config(self, request: web.Request) -> web.Response:
        payload = await request.json()
        config = load_config(self.config_path)
        if "autostart" in payload and not isinstance(payload["autostart"], bool):
            return web.json_response({"ok": False, "error": "autostart must be a boolean"}, status=400)
        config.hotspot.ssid = str(payload.get("ssid", config.hotspot.ssid)).strip()
        password = str(payload.get("password", ""))
        if password:
            config.hotspot.password = password
        config.hotspot.autostart = bool(payload.get("autostart", config.hotspot.autostart))
        try:
            config.hotspot.idle_timeout_minutes = int(
                payload.get("idle_timeout_minutes", config.hotspot.idle_timeout_minutes)
            )
            validate_config(config)
            async with self.hotspot_lock:
                status = await asyncio.to_thread(self.wifi.configure_hotspot, config.hotspot)
            await asyncio.to_thread(save_config, self.config_path, config)
        except (WifiError, ValueError, OSError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        self.config = config
        return web.json_response({"ok": True, **status})

    async def switch_hotspot(self, request: web.Request) -> web.Response:
        payload = await request.json()
        if not isinstance(payload.get("enabled"), bool):
            return web.json_response({"ok": False, "error": "enabled must be a boolean"}, status=400)
        config = load_config(self.config_path)
        try:
            async with self.hotspot_lock:
                status = await asyncio.to_thread(
                    self.wifi.set_hotspot,
                    config.hotspot,
                    payload["enabled"],
                )
        except (WifiError, ValueError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, **status})

    async def monitor_hotspot(self) -> None:
        startup_complete = False
        while True:
            try:
                startup_complete = await self._monitor_hotspot_once(startup_complete)
            except asyncio.CancelledError:
                raise
            except (OSError, ValueError, WifiError):
                LOGGER.exception("hotspot idle monitor failed")
            await asyncio.sleep(15)

    async def _monitor_hotspot_once(self, startup_complete: bool) -> bool:
        config = load_config(self.config_path)
        async with self.hotspot_lock:
            if not startup_complete:
                status = await asyncio.to_thread(self.wifi.hotspot_status, config.hotspot)
                if config.hotspot.autostart and not status["active"]:
                    status = await asyncio.to_thread(self.wifi.set_hotspot, config.hotspot, True)
                    LOGGER.info("hotspot %s restored by autostart", config.hotspot.ssid)
                return True
            status = await asyncio.to_thread(self.wifi.enforce_hotspot_idle, config.hotspot)
        if status.get("auto_disabled"):
            LOGGER.info(
                "hotspot %s disabled after %d idle minute(s)",
                config.hotspot.ssid,
                config.hotspot.idle_timeout_minutes,
            )
        return True


def _optional_float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)
