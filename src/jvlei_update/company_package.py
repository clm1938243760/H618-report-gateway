from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

from .package import (
    MAX_MANIFEST_BYTES,
    MAX_PAYLOAD_BYTES,
    PackageError,
    PackageInfo,
    inspect_payload,
    sha256_file,
)


COMPANY_PACKAGE_MEMBERS = frozenset({"manifest.json", "payload.tar.gz"})
VERSION_PATTERN = re.compile(r"v?[0-9]+(?:\.[0-9]+){1,3}(?:[-+][A-Za-z0-9._-]+)?$")


def normalize_version(value: object) -> str:
    version = str(value or "").strip()
    if VERSION_PATTERN.fullmatch(version) is None:
        raise PackageError(f"invalid package version: {version or '<empty>'}")
    return version.removeprefix("v")


def server_version(value: object) -> str:
    return "v" + normalize_version(value)


def _copy_member(source: BinaryIO, destination: Path, maximum: int) -> int:
    total = 0
    with destination.open("wb") as output:
        while True:
            chunk = source.read(min(1024 * 1024, maximum - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise PackageError(f"package member is larger than {maximum} bytes")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    return total


def _as_nonempty_string(manifest: dict[str, Any], field: str, maximum: int = 128) -> str:
    value = str(manifest.get(field, "")).strip()
    if not value or len(value) > maximum:
        raise PackageError(f"invalid manifest field: {field}")
    return value


def _normalize_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("schemaVersion") != 1:
        raise PackageError(f"unsupported company package schema: {raw.get('schemaVersion')}")
    if raw.get("packageType") != "application":
        raise PackageError("company package type must be application")
    app_code = _as_nonempty_string(raw, "appCode")
    product = _as_nonempty_string(raw, "product")
    platform_name = _as_nonempty_string(raw, "platform")
    architecture = _as_nonempty_string(raw, "architecture").lower()
    if architecture not in {"arm64", "aarch64", "all"}:
        raise PackageError("package architecture must be arm64, aarch64, or all")
    version = normalize_version(raw.get("version"))
    compatible = raw.get("compatibleFrom")
    if not isinstance(compatible, list) or not 1 <= len(compatible) <= 64:
        raise PackageError("compatibleFrom must contain 1 to 64 versions")
    compatible_versions = ["*" if value == "*" else normalize_version(value) for value in compatible]

    payload = raw.get("payload")
    if not isinstance(payload, dict):
        raise PackageError("manifest payload must be an object")
    if payload.get("path") != "payload.tar.gz" or payload.get("format") != "tar.gz":
        raise PackageError("manifest payload layout is unsupported")
    try:
        payload_size = int(payload.get("size"))
        file_count = int(payload.get("fileCount"))
    except (TypeError, ValueError) as exc:
        raise PackageError("payload size and file count must be integers") from exc
    payload_sha256 = str(payload.get("sha256", "")).lower()
    if not 1 <= payload_size <= MAX_PAYLOAD_BYTES:
        raise PackageError("payload size is outside the allowed range")
    if re.fullmatch(r"[0-9a-f]{64}", payload_sha256) is None:
        raise PackageError("invalid payload SHA-256")
    if not 1 <= file_count <= 100000:
        raise PackageError("payload file count is outside the allowed range")

    install = raw.get("install")
    if not isinstance(install, dict) or install.get("mode") != "atomic_release":
        raise PackageError("manifest install mode must be atomic_release")
    for field in ("requiresGadgetRestart", "requiresCupsRestart"):
        if field in install and not isinstance(install[field], bool):
            raise PackageError(f"manifest install field {field} must be a boolean")
    requires_gadget_restart = install.get("requiresGadgetRestart", False)
    requires_cups_restart = install.get("requiresCupsRestart", False)
    release_note = str(raw.get("releaseNote", ""))
    if len(release_note) > 32768:
        raise PackageError("release note is too long")

    return {
        "schema": 1,
        "package_id": f"{product}-{version}",
        "package_type": "application",
        "app_code": app_code,
        "product": product,
        "version": version,
        "server_version": "v" + version,
        "platform": platform_name,
        "arch": architecture,
        "compatible_versions": compatible_versions,
        "created_at": str(raw.get("createdAt", raw.get("releaseTime", ""))),
        "payload_sha256": payload_sha256,
        "payload_size": payload_size,
        "payload_file_count": file_count,
        "release_notes": release_note,
        "git_commit": str(raw.get("gitCommit", "")),
        "migration_level": int(raw.get("migrationLevel", 0)),
        "requires_gadget_restart": requires_gadget_restart,
        "requires_cups_restart": requires_cups_restart,
        "health_url": str(install.get("healthUrl", "")),
        "unsigned_test_package": True,
        "raw_company_manifest": raw,
    }


def verify_company_package(
    package_path: str | Path,
    *,
    expected_size: int | None = None,
    expected_app_code: str = "linux",
    expected_platform: str = "linux-arm64",
    expected_version: str | None = None,
    work_root: str | Path | None = None,
) -> PackageInfo:
    source = Path(package_path).resolve()
    if not source.is_file():
        raise PackageError(f"package not found: {source}")
    if expected_size is not None and source.stat().st_size != int(expected_size):
        raise PackageError("downloaded package size does not match the update response")
    work_dir = Path(tempfile.mkdtemp(prefix="company-update-", dir=str(work_root) if work_root else None))
    try:
        try:
            archive = zipfile.ZipFile(source, mode="r")
        except (zipfile.BadZipFile, OSError) as exc:
            raise PackageError(f"invalid company update ZIP: {exc}") from exc
        with archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or set(names) != COMPANY_PACKAGE_MEMBERS:
                raise PackageError("company ZIP must contain exactly manifest.json and payload.tar.gz")
            bad_entry = archive.testzip()
            if bad_entry:
                raise PackageError(f"ZIP CRC failed: {bad_entry}")
            limits = {"manifest.json": MAX_MANIFEST_BYTES, "payload.tar.gz": MAX_PAYLOAD_BYTES}
            for entry in entries:
                if entry.is_dir() or entry.filename not in COMPANY_PACKAGE_MEMBERS:
                    raise PackageError("company ZIP contains an unsupported member")
                if entry.file_size > limits[entry.filename]:
                    raise PackageError(f"package member is larger than {limits[entry.filename]} bytes")
                with archive.open(entry, "r") as member:
                    _copy_member(member, work_dir / entry.filename, limits[entry.filename])

        manifest_path = work_dir / "manifest.json"
        payload_path = work_dir / "payload.tar.gz"
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"invalid manifest JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise PackageError("manifest root must be an object")
        manifest = _normalize_manifest(raw)
        if manifest["app_code"] != expected_app_code:
            raise PackageError("package appCode does not match this device")
        if manifest["platform"] != expected_platform:
            raise PackageError("package platform does not match this device")
        if expected_version and manifest["server_version"] != server_version(expected_version):
            raise PackageError("package version does not match the update response")
        if payload_path.stat().st_size != manifest["payload_size"]:
            raise PackageError("payload size does not match manifest")
        if sha256_file(payload_path) != manifest["payload_sha256"]:
            raise PackageError("payload SHA-256 does not match manifest")
        payload_files = inspect_payload(payload_path)
        if len(payload_files) != manifest["payload_file_count"]:
            raise PackageError(
                "payload file count does not match manifest: "
                f"expected {manifest['payload_file_count']}, got {len(payload_files)}"
            )
        signature_path = work_dir / "signature.bin"
        signature_path.write_bytes(b"")
        return PackageInfo(
            path=source,
            work_dir=work_dir,
            manifest=manifest,
            manifest_path=manifest_path,
            payload_path=payload_path,
            signature_path=signature_path,
            signed=False,
        )
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
