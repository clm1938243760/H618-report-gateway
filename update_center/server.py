from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import shutil
import sqlite3
import ssl
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from aiohttp import web

from jvlei_update.package import PackageError, sha256_file, verify_package


COOKIE_NAME = "jvlei_center_session"
SESSION_HOURS = 8


class CenterError(RuntimeError):
    pass


@dataclass
class CenterConfig:
    data_dir: str = "./update_center_data"
    admin_host: str = "0.0.0.0"
    admin_port: int = 9443
    device_host: str = "127.0.0.1"
    device_port: int = 9444
    username: str = "admin"
    password: str = "change-this-password"
    tls_cert: str = "./update_center_data/tls.crt"
    tls_key: str = "./update_center_data/tls.key"
    public_key_file: str = ""
    allow_unsigned_packages: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "CenterConfig":
        source = Path(path)
        if not source.is_file():
            raise CenterError(f"update center config not found: {source}")
        values = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(values, dict):
            raise CenterError("update center config root must be a mapping")
        config = cls(**{key: value for key, value in values.items() if key in cls.__dataclass_fields__})
        config.validate()
        return config

    def validate(self) -> None:
        if len(self.username.strip()) < 1 or len(self.username) > 128:
            raise CenterError("invalid update center username")
        if len(self.password) < 12:
            raise CenterError("update center password must contain at least 12 characters")
        for value in (self.admin_port, self.device_port):
            if not 1 <= int(value) <= 65535:
                raise CenterError("invalid update center port")


def _now() -> int:
    return int(time.time())


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CenterStore:
    def __init__(self, database: str | Path) -> None:
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self):
        """Commit or roll back and always close SQLite handles.

        ``sqlite3.Connection`` commits when used as a context manager but does
        not close itself.  Explicit close matters on Windows, where a pending
        handle also prevents update-center data directories from being moved or
        removed during maintenance.
        """

        conn = self._connect()
        try:
            yield conn
        except Exception:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS devices (
                    agent_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL,
                    hostname TEXT NOT NULL DEFAULT '',
                    product TEXT NOT NULL DEFAULT '',
                    version TEXT NOT NULL DEFAULT '',
                    arch TEXT NOT NULL DEFAULT '',
                    install_policy TEXT NOT NULL DEFAULT 'local_confirm',
                    free_bytes INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    group_name TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    last_seen_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code_hash TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER,
                    created_at INTEGER NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS packages (
                    id TEXT PRIMARY KEY,
                    package_id TEXT NOT NULL UNIQUE,
                    package_type TEXT NOT NULL,
                    version TEXT NOT NULL,
                    product TEXT NOT NULL,
                    arch TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    signed INTEGER NOT NULL,
                    manifest_json TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assignments (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    package_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    FOREIGN KEY(agent_id) REFERENCES devices(agent_id),
                    FOREIGN KEY(package_id) REFERENCES packages(id)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at INTEGER NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_assignments_device ON assignments(agent_id, created_at DESC);
                """
            )
            columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(devices)")}
            if "group_name" not in columns:
                conn.execute("ALTER TABLE devices ADD COLUMN group_name TEXT NOT NULL DEFAULT ''")

    def audit(self, actor: str, action: str, target: str, detail: dict[str, Any] | None = None) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO audit_log(created_at, actor, action, target, detail_json) VALUES(?,?,?,?,?)",
                (_now(), actor, action, target, json.dumps(detail or {}, ensure_ascii=False)),
            )

    def create_pair_code(self, ttl_minutes: int, note: str) -> str:
        code = "-".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(12))
        now = _now()
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO pairing_codes(code_hash, expires_at, created_at, note) VALUES(?,?,?,?)",
                (_sha256(code), now + ttl_minutes * 60, now, note),
            )
        self.audit("admin", "pair_code_created", "pairing", {"ttl_minutes": ttl_minutes, "note": note})
        return code

    def consume_pair_code(self, code: str) -> bool:
        now = _now()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE pairing_codes SET used_at=? WHERE code_hash=? AND used_at IS NULL AND expires_at>=?",
                (now, _sha256(code), now),
            )
            return cursor.rowcount == 1

    def pair_device(self, payload: dict[str, Any]) -> tuple[str, str]:
        agent_id = str(payload.get("agent_id") or "").strip() or f"h618-{uuid.uuid4().hex[:16]}"
        if not all(char.isalnum() or char in "._-" for char in agent_id) or len(agent_id) > 128:
            raise CenterError("invalid agent ID")
        token = secrets.token_urlsafe(36)
        now = _now()
        values = (
            _sha256(token),
            str(payload.get("hostname", ""))[:128],
            str(payload.get("product", ""))[:128],
            str(payload.get("version", ""))[:128],
            str(payload.get("arch", ""))[:64],
            str(payload.get("install_policy", "local_confirm"))[:32],
            int(payload.get("free_bytes", 0) or 0),
            int(payload.get("total_bytes", 0) or 0),
            now,
            now,
            agent_id,
        )
        with self._connection() as conn:
            existing = conn.execute("SELECT agent_id FROM devices WHERE agent_id=?", (agent_id,)).fetchone()
            if existing:
                raise CenterError("agent ID is already paired")
            conn.execute(
                """
                INSERT INTO devices(token_hash,hostname,product,version,arch,install_policy,free_bytes,total_bytes,created_at,last_seen_at,agent_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                values,
            )
        self.audit("device", "paired", agent_id, {"product": payload.get("product", "")})
        return agent_id, token

    def authenticate_device(self, token: str) -> sqlite3.Row | None:
        if not token:
            return None
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM devices WHERE token_hash=? AND enabled=1", (_sha256(token),)).fetchone()
            return row

    def update_device(self, agent_id: str, payload: dict[str, Any]) -> None:
        now = _now()
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE devices SET hostname=?,product=?,version=?,arch=?,install_policy=?,free_bytes=?,total_bytes=?,last_seen_at=?
                WHERE agent_id=?
                """,
                (
                    str(payload.get("hostname", ""))[:128],
                    str(payload.get("product", ""))[:128],
                    str(payload.get("version", ""))[:128],
                    str(payload.get("arch", ""))[:64],
                    str(payload.get("install_policy", "local_confirm"))[:32],
                    int(payload.get("free_bytes", 0) or 0),
                    int(payload.get("total_bytes", 0) or 0),
                    now,
                    agent_id,
                ),
            )

    def devices(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM devices ORDER BY last_seen_at DESC").fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _validate_group_name(group_name: str) -> str:
        value = group_name.strip()
        if len(value) > 64 or any(ord(char) < 32 for char in value):
            raise CenterError("invalid device group name")
        return value

    def groups(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT group_name,COUNT(*) AS device_count FROM devices "
                "WHERE group_name <> '' GROUP BY group_name ORDER BY group_name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def set_device_group(self, agent_id: str, group_name: str) -> None:
        group = self._validate_group_name(group_name)
        with self._connection() as conn:
            cursor = conn.execute("UPDATE devices SET group_name=? WHERE agent_id=?", (group, agent_id))
            if cursor.rowcount != 1:
                raise CenterError("device not found")
        self.audit("admin", "device_group_changed", agent_id, {"group_name": group})

    def add_package(self, metadata: dict[str, Any], source: Path, signed: bool, packages_dir: Path) -> dict[str, Any]:
        packages_dir.mkdir(parents=True, exist_ok=True)
        package_id = str(metadata["package_id"])
        identifier = uuid.uuid4().hex
        destination = packages_dir / f"{identifier}.jvpkg"
        shutil.copy2(source, destination)
        record = {
            "id": identifier,
            "package_id": package_id,
            "package_type": str(metadata["package_type"]),
            "version": str(metadata["version"]),
            "product": str(metadata["product"]),
            "arch": str(metadata["arch"]),
            "sha256": sha256_file(destination),
            "size_bytes": destination.stat().st_size,
            "signed": 1 if signed else 0,
            "manifest_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            "file_path": str(destination),
            "created_at": _now(),
        }
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO packages(id,package_id,package_type,version,product,arch,sha256,size_bytes,signed,manifest_json,file_path,created_at)
                VALUES(:id,:package_id,:package_type,:version,:product,:arch,:sha256,:size_bytes,:signed,:manifest_json,:file_path,:created_at)
                """,
                record,
            )
        self.audit("admin", "package_uploaded", identifier, {"package_id": package_id, "version": record["version"]})
        return self.package(identifier) or record

    def package(self, package_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM packages WHERE id=?", (package_id,)).fetchone()
        return self._package_row(row) if row else None

    @staticmethod
    def _package_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["manifest"] = json.loads(value.pop("manifest_json"))
        return value

    def packages(self) -> list[dict[str, Any]]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM packages WHERE enabled=1 ORDER BY created_at DESC").fetchall()
        return [self._package_row(row) for row in rows]

    def assign(self, agent_id: str, package_id: str, action: str) -> dict[str, Any]:
        if action not in {"download", "install"}:
            raise CenterError("assignment action must be download or install")
        if not self.package(package_id):
            raise CenterError("update package not found")
        with self._connection() as conn:
            if not conn.execute("SELECT agent_id FROM devices WHERE agent_id=? AND enabled=1", (agent_id,)).fetchone():
                raise CenterError("device not found")
            now = _now()
            assignment_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO assignments(id,agent_id,package_id,action,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (assignment_id, agent_id, package_id, action, "queued", now, now),
            )
        self.audit("admin", "assignment_created", assignment_id, {"agent_id": agent_id, "package_id": package_id, "action": action})
        return self.assignment(assignment_id) or {}

    def assign_group(self, group_name: str, package_id: str, action: str) -> list[dict[str, Any]]:
        group = self._validate_group_name(group_name)
        if not group:
            raise CenterError("device group is required")
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT agent_id FROM devices WHERE group_name=? AND enabled=1 ORDER BY agent_id",
                (group,),
            ).fetchall()
        if not rows:
            raise CenterError("device group has no enabled devices")
        assignments = [self.assign(str(row["agent_id"]), package_id, action) for row in rows]
        self.audit(
            "admin",
            "group_assignment_created",
            group,
            {"package_id": package_id, "action": action, "device_count": len(assignments)},
        )
        return assignments

    def assignment(self, assignment_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT a.*, p.package_id AS manifest_package_id,p.package_type,p.version,p.product,p.arch,p.sha256,p.size_bytes,p.signed
                FROM assignments a JOIN packages p ON p.id=a.package_id WHERE a.id=?
                """,
                (assignment_id,),
            ).fetchone()
        return dict(row) if row else None

    def pending_assignment(self, agent_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT a.*, p.package_id AS manifest_package_id,p.package_type,p.version,p.product,p.arch,p.sha256,p.size_bytes,p.signed
                FROM assignments a JOIN packages p ON p.id=a.package_id
                WHERE a.agent_id=? AND a.status='queued'
                ORDER BY a.created_at ASC LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
        if not row:
            return None
        value = dict(row)
        return {
            "id": value["id"],
            "action": value["action"],
            "status": value["status"],
            "package": {
                "id": value["package_id"],
                "package_id": value["manifest_package_id"],
                "package_type": value["package_type"],
                "version": value["version"],
                "product": value["product"],
                "arch": value["arch"],
                "sha256": value["sha256"],
                "size_bytes": value["size_bytes"],
                "signed": bool(value["signed"]),
            },
        }

    def update_assignment(self, assignment_id: str, status: str, detail: dict[str, Any]) -> None:
        if status not in {"downloaded", "installed", "rolled_back", "failed", "cancelled"}:
            raise CenterError("invalid assignment status")
        with self._connection() as conn:
            conn.execute(
                "UPDATE assignments SET status=?,detail_json=?,updated_at=? WHERE id=?",
                (status, json.dumps(detail, ensure_ascii=False), _now(), assignment_id),
            )
        self.audit("device", f"assignment_{status}", assignment_id, detail)

    def cancel_assignment(self, assignment_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE assignments SET status='cancelled',updated_at=? WHERE id=? AND status IN ('queued','downloaded')",
                (_now(), assignment_id),
            )
            changed = cursor.rowcount == 1
        if changed:
            self.audit("admin", "assignment_cancelled", assignment_id)
        return changed


class CenterApp:
    def __init__(self, config: CenterConfig) -> None:
        self.config = config
        self.data_dir = Path(config.data_dir).resolve()
        self.packages_dir = self.data_dir / "packages"
        self.upload_dir = self.data_dir / "uploads"
        self.store = CenterStore(self.data_dir / "center.sqlite3")
        self.sessions: dict[str, dict[str, Any]] = {}
        self.admin_app = web.Application(middlewares=[self.admin_security])
        self.device_app = web.Application(client_max_size=2 * 1024 * 1024 * 1024)
        self._add_admin_routes()
        self._add_device_routes()

    def _add_admin_routes(self) -> None:
        self.admin_app.add_routes(
            [
                web.get("/health", self.health),
                web.get("/login", self.login_page),
                web.post("/api/login", self.login),
                web.post("/api/logout", self.logout),
                web.get("/api/session", self.session),
                web.get("/api/devices", self.admin_devices),
                web.get("/api/groups", self.admin_groups),
                web.put(r"/api/devices/{agent_id}/group", self.admin_set_device_group),
                web.get("/api/packages", self.admin_packages),
                web.post("/api/packages", self.admin_upload_package),
                web.post("/api/pair-codes", self.admin_create_pair_code),
                web.post("/api/assignments", self.admin_assign),
                web.post(r"/api/assignments/{assignment_id}/cancel", self.admin_cancel_assignment),
                web.get("/", self.dashboard),
            ]
        )

    def _add_device_routes(self) -> None:
        self.device_app.add_routes(
            [
                web.post("/v1/devices/pair", self.device_pair),
                web.post("/v1/devices/check-in", self.device_check_in),
                web.get(r"/v1/packages/{package_id}/download", self.device_download),
                web.post(r"/v1/jobs/{assignment_id}/status", self.device_job_status),
            ]
        )

    @web.middleware
    async def admin_security(self, request: web.Request, handler):
        if request.path in {"/health", "/login", "/api/login"}:
            return await handler(request)
        session = self._admin_session(request)
        if session is None:
            if request.path.startswith("/api/"):
                return web.json_response({"ok": False, "error": "authentication required"}, status=401)
            raise web.HTTPFound("/login")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("X-CSRF-Token", "") != session["csrf"]:
                return web.json_response({"ok": False, "error": "invalid CSRF token"}, status=403)
        request["admin_session"] = session
        return await handler(request)

    def _admin_session(self, request: web.Request) -> dict[str, Any] | None:
        token = request.cookies.get(COOKIE_NAME, "")
        value = self.sessions.get(token)
        if not value or int(value["expires_at"]) < _now():
            self.sessions.pop(token, None)
            return None
        return value

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "jvlei-update-center"})

    async def login_page(self, request: web.Request) -> web.Response:
        return web.Response(text=LOGIN_HTML, content_type="text/html")

    async def login(self, request: web.Request) -> web.Response:
        payload = await request.json()
        username = str(payload.get("username", ""))
        password = str(payload.get("password", ""))
        if not (
            hmac.compare_digest(username, self.config.username)
            and hmac.compare_digest(password, self.config.password)
        ):
            return web.json_response({"ok": False, "error": "用户名或密码错误"}, status=401)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        self.sessions[token] = {"username": username, "csrf": csrf, "expires_at": _now() + SESSION_HOURS * 3600}
        response = web.json_response({"ok": True, "username": username, "csrf": csrf})
        response.set_cookie(COOKIE_NAME, token, httponly=True, secure=True, samesite="Strict", max_age=SESSION_HOURS * 3600)
        return response

    async def logout(self, request: web.Request) -> web.Response:
        self.sessions.pop(request.cookies.get(COOKIE_NAME, ""), None)
        response = web.json_response({"ok": True})
        response.del_cookie(COOKIE_NAME)
        return response

    async def session(self, request: web.Request) -> web.Response:
        value = request["admin_session"]
        return web.json_response({"ok": True, "username": value["username"], "csrf": value["csrf"]})

    async def dashboard(self, request: web.Request) -> web.Response:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    async def admin_devices(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "devices": self.store.devices()})

    async def admin_groups(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "groups": self.store.groups()})

    async def admin_set_device_group(self, request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            self.store.set_device_group(request.match_info["agent_id"], str(payload.get("group_name", "")))
        except CenterError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True})

    async def admin_packages(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "packages": self.store.packages()})

    async def admin_create_pair_code(self, request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            ttl = int(payload.get("ttl_minutes", 30))
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "有效期必须是整数"}, status=400)
        if not 1 <= ttl <= 1440:
            return web.json_response({"ok": False, "error": "有效期必须在 1 到 1440 分钟"}, status=400)
        code = self.store.create_pair_code(ttl, str(payload.get("note", ""))[:200])
        return web.json_response({"ok": True, "pairing_code": code, "ttl_minutes": ttl})

    async def admin_upload_package(self, request: web.Request) -> web.Response:
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "package" or not field.filename:
            return web.json_response({"ok": False, "error": "请选择 .jvpkg 文件"}, status=400)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.upload_dir / f"{uuid.uuid4().hex}.jvpkg"
        total = 0
        try:
            with temporary.open("wb") as handle:
                while True:
                    chunk = await field.read_chunk(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 2 * 1024 * 1024 * 1024:
                        raise CenterError("升级包超过 2 GB 限制")
                    handle.write(chunk)
            info = verify_package(
                temporary,
                self.config.public_key_file or None,
                allow_unsigned=self.config.allow_unsigned_packages,
                work_root=self.upload_dir,
            )
            try:
                record = self.store.add_package(info.manifest, temporary, info.signed, self.packages_dir)
            finally:
                info.cleanup()
        except (CenterError, PackageError, OSError) as exc:
            temporary.unlink(missing_ok=True)
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        temporary.unlink(missing_ok=True)
        return web.json_response({"ok": True, "package": record})

    async def admin_assign(self, request: web.Request) -> web.Response:
        payload = await request.json()
        try:
            action = str(payload.get("action", "download"))
            package_id = str(payload.get("package_id", ""))
            group_name = str(payload.get("group_name", "")).strip()
            if group_name:
                assignments = self.store.assign_group(group_name, package_id, action)
                return web.json_response({"ok": True, "assignments": assignments})
            assignment = self.store.assign(str(payload.get("agent_id", "")), package_id, action)
        except CenterError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "assignment": assignment})

    async def admin_cancel_assignment(self, request: web.Request) -> web.Response:
        changed = self.store.cancel_assignment(request.match_info["assignment_id"])
        return web.json_response({"ok": changed})

    @staticmethod
    def _device_token(request: web.Request) -> str:
        value = request.headers.get("Authorization", "")
        return value[7:].strip() if value.startswith("Bearer ") else ""

    def _authenticated_device(self, request: web.Request) -> sqlite3.Row:
        device = self.store.authenticate_device(self._device_token(request))
        if device is None:
            raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": "device authentication failed"}), content_type="application/json")
        return device

    async def device_pair(self, request: web.Request) -> web.Response:
        payload = await request.json()
        code = str(payload.get("pairing_code", ""))
        if not self.store.consume_pair_code(code):
            return web.json_response({"ok": False, "error": "配对码无效或已过期"}, status=400)
        try:
            agent_id, token = self.store.pair_device(payload)
        except CenterError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "agent_id": agent_id, "token": token})

    async def device_check_in(self, request: web.Request) -> web.Response:
        device = self._authenticated_device(request)
        payload = await request.json()
        if str(payload.get("agent_id", "")) != device["agent_id"]:
            return web.json_response({"ok": False, "error": "agent ID does not match token"}, status=403)
        self.store.update_device(device["agent_id"], payload)
        return web.json_response({"ok": True, "assignment": self.store.pending_assignment(device["agent_id"])})

    async def device_download(self, request: web.Request) -> web.StreamResponse:
        device = self._authenticated_device(request)
        package_id = request.match_info["package_id"]
        assignment = self.store.pending_assignment(device["agent_id"])
        if not assignment or assignment["package"]["id"] != package_id:
            raise web.HTTPNotFound(text="package is not assigned to this device")
        package = self.store.package(package_id)
        if not package or not Path(package["file_path"]).is_file():
            raise web.HTTPNotFound(text="package file is missing")
        return web.FileResponse(Path(package["file_path"]), headers={"Cache-Control": "no-store"})

    async def device_job_status(self, request: web.Request) -> web.Response:
        device = self._authenticated_device(request)
        assignment = self.store.assignment(request.match_info["assignment_id"])
        if not assignment or assignment["agent_id"] != device["agent_id"]:
            return web.json_response({"ok": False, "error": "assignment not found"}, status=404)
        payload = await request.json()
        try:
            self.store.update_assignment(assignment["id"], str(payload.get("status", "")), payload.get("detail") or {})
        except CenterError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True})


def create_ssl_context(config: CenterConfig) -> ssl.SSLContext:
    cert = Path(config.tls_cert)
    key = Path(config.tls_key)
    if not cert.is_file() or not key.is_file():
        raise CenterError(
            "缺少升级中心 TLS 证书。请使用 scripts/generate_center_tls.py 生成后，再启动升级中心。"
        )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context


LOGIN_HTML = """<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>JVLEI 更新中心登录</title>
<style>body{margin:0;font-family:Arial,'Microsoft YaHei';background:#eef5f9;display:grid;place-items:center;min-height:100vh}.box{width:330px;background:white;padding:32px;border-radius:8px;box-shadow:0 12px 40px #16466a22}h1{font-size:22px;color:#12304a}input,button{box-sizing:border-box;width:100%;padding:11px;margin:8px 0;border:1px solid #cdd9e3;border-radius:4px}button{background:#1296db;color:white;border:0;cursor:pointer}.error{color:#d64646;min-height:20px}</style>
<main class='box'><h1>JVLEI 设备升级中心</h1><input id='u' placeholder='账号'><input id='p' type='password' placeholder='密码'><div class='error' id='e'></div><button onclick='login()'>登录</button></main>
<script>async function login(){let r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u.value,password:p.value})});let d=await r.json();if(d.ok){sessionStorage.csrf=d.csrf;location='/'}else e.textContent=d.error||'登录失败'}</script></html>"""


DASHBOARD_HTML = """<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>JVLEI 更新中心</title>
<style>body{margin:0;background:#f2f6f9;color:#213547;font:14px Arial,'Microsoft YaHei'}header{height:64px;background:#0796d7;color:white;display:flex;align-items:center;padding:0 28px;justify-content:space-between}main{padding:22px;max-width:1450px;margin:auto}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.card{background:white;border-radius:6px;padding:18px;box-shadow:0 1px 4px #1a456611}h2{margin:0 0 14px;font-size:18px}input,select,button{padding:9px;border:1px solid #ccd8e1;border-radius:4px;margin:4px}button{background:#0796d7;color:white;border:0;cursor:pointer}button.alt{background:#eef4f7;color:#17415f}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:9px;border-bottom:1px solid #e6eef3;word-break:break-all}.muted{color:#668}.ok{color:#17884d}.bad{color:#d64444}#notice{min-height:20px}@media(max-width:800px){.grid{grid-template-columns:1fr}main{padding:10px}}</style>
<header><strong>聚垒科技 | 设备升级中心</strong><span id='who'></span></header><main><div id='notice'></div><div class='grid'><section class='card'><h2>设备配对</h2><input id='note' placeholder='备注，例如：K2B 测试板'><input id='ttl' type='number' value='30' min='1' max='1440'><button onclick='pair()'>生成一次性配对码</button><p id='paircode' class='ok'></p></section><section class='card'><h2>发布包</h2><input id='file' type='file' accept='.jvpkg'><button onclick='upload()'>上传并校验</button><p class='muted'>生产环境只接受已签名 .jvpkg 包。</p></section></div><section class='card'><h2>设备</h2><table><thead><tr><th>设备</th><th>版本</th><th>架构</th><th>安装策略</th><th>最后在线</th><th>下发</th></tr></thead><tbody id='devices'></tbody></table></section><section class='card'><h2>可用发布包</h2><table><thead><tr><th>版本</th><th>类型</th><th>架构</th><th>签名</th><th>大小</th></tr></thead><tbody id='packages'></tbody></table></section></main>
<script>let csrf='';const q=s=>document.querySelector(s);function fmt(t){return t?new Date(t*1000).toLocaleString():'-'}function size(n){return n?(n/1024/1024).toFixed(1)+' MB':'-'}async function api(p,o={}){o.headers={...(o.headers||{}),'X-CSRF-Token':csrf};let r=await fetch(p,o);let d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d}function msg(v,bad=false){q('#notice').innerHTML='<p class="'+(bad?'bad':'ok')+'">'+v+'</p>'}async function init(){try{let s=await api('/api/session');csrf=s.csrf;q('#who').textContent=s.username;await load()}catch(e){location='/login'}}async function load(){let [d,p]=await Promise.all([api('/api/devices'),api('/api/packages')]);q('#devices').innerHTML=d.devices.map(x=>'<tr><td>'+x.agent_id+'<br><small>'+x.hostname+'</small></td><td>'+x.version+'</td><td>'+x.arch+'</td><td>'+x.install_policy+'</td><td>'+fmt(x.last_seen_at)+'</td><td><select id="pkg-'+x.agent_id+'"><option value="">选择包</option>'+p.packages.map(y=>'<option value="'+y.id+'">'+y.version+' '+y.package_type+'</option>').join('')+'</select><button data-agent="'+x.agent_id+'" data-action="download" onclick="assign(this.dataset.agent,this.dataset.action)">下载</button><button data-agent="'+x.agent_id+'" data-action="install" onclick="assign(this.dataset.agent,this.dataset.action)">安装</button></td></tr>').join('')||'<tr><td colspan="6">暂无已配对设备</td></tr>';q('#packages').innerHTML=p.packages.map(x=>'<tr><td>'+x.version+'</td><td>'+x.package_type+'</td><td>'+x.arch+'</td><td>'+ (x.signed?'已签名':'未签名')+'</td><td>'+size(x.size_bytes)+'</td></tr>').join('')||'<tr><td colspan="5">暂无发布包</td></tr>'}async function pair(){try{let d=await api('/api/pair-codes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({note:q('#note').value,ttl_minutes:+q('#ttl').value})});q('#paircode').textContent='配对码：'+d.pairing_code+'，有效 '+d.ttl_minutes+' 分钟'}catch(e){msg(e.message,true)}}async function upload(){try{let f=q('#file').files[0];if(!f)throw Error('请选择发布包');let fd=new FormData();fd.append('package',f);let d=await api('/api/packages',{method:'POST',body:fd});msg('已接收 '+d.package.version);await load()}catch(e){msg(e.message,true)}}async function assign(id,action){try{let pid=q('#pkg-'+id).value;if(!pid)throw Error('请先选择发布包');await api('/api/assignments',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent_id:id,package_id:pid,action})});msg('任务已下发，设备下次签到时接收');await load()}catch(e){msg(e.message,true)}}init()</script></html>"""
