from __future__ import annotations

import asyncio
import hmac
import logging
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from aiohttp import web

from .auth import Session, SessionStore
from .config import GADGET_MODES, AppConfig, load_config, resolve_udc_device, save_config, validate_config
from .maintenance import MaintenanceManager
from .report_info import ReportInfoManager
from .report_upload import ReportUploadWorker

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
    ) -> None:
        self.config_path = Path(config_path)
        self.config = config
        self.sessions = sessions
        self.report_info = report_info
        self.uploader = uploader
        self.maintenance = maintenance
        self.login_failures: dict[str, list[float]] = {}
        self.app = web.Application(middlewares=[self.security_middleware])
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
                web.post("/api/gadget/switch", self.switch_gadget),
                web.get("/api/reports", self.reports),
                web.post(r"/api/reports/{job_id:\d+}/retry", self.retry_report),
                web.get("/api/maintenance", self.maintenance_status),
                web.post("/api/maintenance/cleanup", self.cleanup_now),
                web.post("/api/upload/test", self.test_upload),
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
        return web.json_response({"ok": True, "service": "gadget-web", "version": "0.4.0"})

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
        config.device.device_code = str(payload.get("device_code", config.device.device_code)).strip()
        config.device.exam_doct = str(payload.get("exam_doct", config.device.exam_doct)).strip()
        config.device.exam_doct_code = str(payload.get("exam_doct_code", config.device.exam_doct_code)).strip()
        config.upload.enabled = bool(payload.get("upload_enabled", config.upload.enabled))
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
        return web.json_response({"ok": True, "xml_sha256": snapshot.sha256})

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


def _optional_float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)
