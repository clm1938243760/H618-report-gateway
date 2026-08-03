from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


PBKDF2_ITERATIONS = 260_000


class AuthStore:
    def __init__(self, data_dir: str | Path) -> None:
        self.auth_dir = Path(data_dir) / "auth"
        self.auth_file = self.auth_dir / "admin.json"
        self.initial_password_file = self.auth_dir / "initial_password.txt"

    def ensure_admin(self) -> str | None:
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.auth_dir, 0o700)
        if self.auth_file.exists():
            return None
        password = secrets.token_urlsafe(12)
        self.set_password(password, must_change=True)
        self.initial_password_file.write_text(password + "\n", encoding="utf-8")
        os.chmod(self.initial_password_file, 0o600)
        return password

    def verify(self, username: str, password: str) -> tuple[bool, bool]:
        if username != "admin" or not self.auth_file.exists():
            return False, False
        record = json.loads(self.auth_file.read_text(encoding="utf-8"))
        salt = base64.b64decode(record["salt"])
        expected = base64.b64decode(record["hash"])
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(record.get("iterations", PBKDF2_ITERATIONS)),
        )
        return hmac.compare_digest(actual, expected), bool(record.get("must_change", False))

    def set_password(self, password: str, must_change: bool = False) -> None:
        if len(password) < 8:
            raise ValueError("password must contain at least 8 characters")
        if len(password) > 256:
            raise ValueError("password is too long")
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
        record = {
            "username": "admin",
            "algorithm": "pbkdf2_hmac_sha256",
            "iterations": PBKDF2_ITERATIONS,
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": base64.b64encode(digest).decode("ascii"),
            "must_change": must_change,
            "updated_at": int(time.time()),
        }
        _atomic_json(self.auth_file, record, mode=0o600)
        if not must_change:
            self.initial_password_file.unlink(missing_ok=True)


@dataclass
class Session:
    token: str
    csrf: str
    expires_at: float
    username: str


class SessionStore:
    def __init__(self, session_hours: int) -> None:
        self.lifetime = max(1, session_hours) * 3600
        self.sessions: dict[str, Session] = {}

    def create(self, username: str) -> Session:
        self._purge()
        session = Session(
            token=secrets.token_urlsafe(32),
            csrf=secrets.token_urlsafe(24),
            expires_at=time.time() + self.lifetime,
            username=username,
        )
        self.sessions[session.token] = session
        return session

    def get(self, token: str) -> Session | None:
        self._purge()
        session = self.sessions.get(token)
        if session:
            session.expires_at = time.time() + self.lifetime
        return session

    def remove(self, token: str) -> None:
        self.sessions.pop(token, None)

    def _purge(self) -> None:
        now = time.time()
        for token in [key for key, value in self.sessions.items() if value.expires_at <= now]:
            self.sessions.pop(token, None)


def _atomic_json(path: Path, payload: dict[str, object], mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
