from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


SCHEMA_VERSION = 1
PACKAGE_TYPES = frozenset({"application", "printer_driver", "updater"})
PACKAGE_MEMBERS = frozenset({"manifest.json", "payload.tar.gz", "signature.bin"})
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SIGNATURE_BYTES = 16 * 1024
MAX_PAYLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_EXTRACTED_BYTES = 4 * 1024 * 1024 * 1024


class PackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class PackageInfo:
    path: Path
    work_dir: Path
    manifest: dict[str, Any]
    manifest_path: Path
    payload_path: Path
    signature_path: Path
    signed: bool

    def cleanup(self) -> None:
        shutil.rmtree(self.work_dir, ignore_errors=True)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_manifest(manifest: dict[str, Any]) -> bytes:
    return (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def validate_manifest(manifest: dict[str, Any]) -> None:
    required = {
        "schema",
        "package_id",
        "package_type",
        "product",
        "version",
        "arch",
        "compatible_versions",
        "created_at",
        "payload_sha256",
        "payload_size",
        "release_notes",
        "git_commit",
        "migration_level",
        "requires_gadget_restart",
        "requires_cups_restart",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise PackageError("manifest missing field(s): " + ", ".join(missing))
    if manifest["schema"] != SCHEMA_VERSION:
        raise PackageError(f"unsupported package schema: {manifest['schema']}")
    if manifest["package_type"] not in PACKAGE_TYPES:
        raise PackageError("unsupported package type")
    for field in ("package_id", "product", "version", "arch"):
        value = str(manifest[field])
        if not value or len(value) > 128 or re.fullmatch(r"[A-Za-z0-9._+-]+", value) is None:
            raise PackageError(f"invalid manifest field: {field}")
    if manifest["arch"] not in {"arm64", "aarch64", "all"}:
        raise PackageError("package architecture must be arm64, aarch64, or all")
    compatible_versions = manifest["compatible_versions"]
    if not isinstance(compatible_versions, list) or not 1 <= len(compatible_versions) <= 64:
        raise PackageError("compatible_versions must contain 1 to 64 versions")
    for version in compatible_versions:
        value = str(version)
        if value != "*" and (
            not value or len(value) > 128 or re.fullmatch(r"[A-Za-z0-9._+-]+", value) is None
        ):
            raise PackageError("invalid compatible version")
    if re.fullmatch(r"[0-9a-f]{64}", str(manifest["payload_sha256"])) is None:
        raise PackageError("invalid payload SHA-256")
    try:
        payload_size = int(manifest["payload_size"])
        migration_level = int(manifest["migration_level"])
    except (TypeError, ValueError) as exc:
        raise PackageError("manifest size and migration level must be integers") from exc
    if not 1 <= payload_size <= MAX_PAYLOAD_BYTES:
        raise PackageError("payload size is outside the allowed range")
    if migration_level < 0:
        raise PackageError("migration level must not be negative")
    for field in ("requires_gadget_restart", "requires_cups_restart"):
        if not isinstance(manifest[field], bool):
            raise PackageError(f"manifest field {field} must be boolean")
    if len(str(manifest["release_notes"])) > 32768:
        raise PackageError("release notes are too long")


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


def _extract_outer(package_path: Path, work_dir: Path) -> tuple[Path, Path, Path]:
    try:
        archive = tarfile.open(package_path, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise PackageError(f"invalid jvpkg archive: {exc}") from exc
    with archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or set(names) != PACKAGE_MEMBERS:
            raise PackageError("jvpkg must contain exactly manifest.json, payload.tar.gz, and signature.bin")
        limits = {
            "manifest.json": MAX_MANIFEST_BYTES,
            "payload.tar.gz": MAX_PAYLOAD_BYTES,
            "signature.bin": MAX_SIGNATURE_BYTES,
        }
        for member in members:
            if not member.isfile() or member.name not in PACKAGE_MEMBERS:
                raise PackageError("jvpkg contains an unsupported member")
            source = archive.extractfile(member)
            if source is None:
                raise PackageError(f"cannot read package member: {member.name}")
            _copy_member(source, work_dir / member.name, limits[member.name])
    return work_dir / "manifest.json", work_dir / "payload.tar.gz", work_dir / "signature.bin"


def _verify_ed25519(manifest_path: Path, signature_path: Path, public_key: Path) -> None:
    if not public_key.is_file():
        raise PackageError(f"update public key not found: {public_key}")
    try:
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(public_key),
                "-sigfile",
                str(signature_path),
                "-rawin",
                "-in",
                str(manifest_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PackageError(f"cannot verify package signature: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "signature verification failed").strip()
        raise PackageError(detail)


def verify_package(
    package_path: str | Path,
    public_key: str | Path | None,
    allow_unsigned: bool = False,
    work_root: str | Path | None = None,
) -> PackageInfo:
    source = Path(package_path).resolve()
    if not source.is_file():
        raise PackageError(f"package not found: {source}")
    work_dir = Path(tempfile.mkdtemp(prefix="jvpkg-", dir=str(work_root) if work_root else None))
    try:
        manifest_path, payload_path, signature_path = _extract_outer(source, work_dir)
        manifest_bytes = manifest_path.read_bytes()
        try:
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"invalid manifest JSON: {exc}") from exc
        if not isinstance(manifest, dict):
            raise PackageError("manifest root must be an object")
        validate_manifest(manifest)
        if canonical_manifest(manifest) != manifest_bytes:
            raise PackageError("manifest is not canonical JSON")
        if payload_path.stat().st_size != int(manifest["payload_size"]):
            raise PackageError("payload size does not match manifest")
        if sha256_file(payload_path) != manifest["payload_sha256"]:
            raise PackageError("payload SHA-256 does not match manifest")
        signed = signature_path.stat().st_size > 0
        if signed:
            if public_key is None:
                raise PackageError("signed package cannot be verified without a public key")
            _verify_ed25519(manifest_path, signature_path, Path(public_key))
        elif not allow_unsigned:
            raise PackageError("unsigned update package is not allowed")
        return PackageInfo(
            path=source,
            work_dir=work_dir,
            manifest=manifest,
            manifest_path=manifest_path,
            payload_path=payload_path,
            signature_path=signature_path,
            signed=signed,
        )
    except Exception:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise


def safe_extract_payload(
    payload_path: str | Path,
    destination: str | Path,
    maximum_bytes: int = MAX_EXTRACTED_BYTES,
) -> list[str]:
    target = Path(destination).resolve()
    target.mkdir(parents=True, exist_ok=True)
    try:
        archive = tarfile.open(payload_path, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise PackageError(f"invalid payload archive: {exc}") from exc
    extracted: list[str] = []
    total = 0
    with archive:
        members = archive.getmembers()
        if len(members) > 100000:
            raise PackageError("payload contains too many files")
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise PackageError("payload contains duplicate paths")
        for member in members:
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or not pure.parts or ".." in pure.parts:
                raise PackageError(f"unsafe payload path: {member.name}")
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise PackageError(f"unsupported payload member: {member.name}")
            resolved = (target / Path(*pure.parts)).resolve()
            try:
                resolved.relative_to(target)
            except ValueError as exc:
                raise PackageError(f"payload path escapes destination: {member.name}") from exc
            if member.isdir():
                resolved.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise PackageError(f"unsupported payload member: {member.name}")
            total += member.size
            if total > maximum_bytes:
                raise PackageError("extracted payload is too large")
            resolved.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise PackageError(f"cannot read payload member: {member.name}")
            _copy_member(source, resolved, member.size)
            os.chmod(resolved, member.mode & 0o777)
            extracted.append(member.name)
    return extracted


def inspect_payload(
    payload_path: str | Path,
    maximum_bytes: int = MAX_EXTRACTED_BYTES,
) -> list[str]:
    """Validate payload members without writing the expanded archive to disk."""

    try:
        archive = tarfile.open(payload_path, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise PackageError(f"invalid payload archive: {exc}") from exc
    files: list[str] = []
    total = 0
    with archive:
        members = archive.getmembers()
        if len(members) > 100000:
            raise PackageError("payload contains too many files")
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise PackageError("payload contains duplicate paths")
        for member in members:
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or not pure.parts or ".." in pure.parts:
                raise PackageError(f"unsafe payload path: {member.name}")
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise PackageError(f"unsupported payload member: {member.name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise PackageError(f"unsupported payload member: {member.name}")
            total += member.size
            if total > maximum_bytes:
                raise PackageError("extracted payload is too large")
            files.append(member.name)
    return files


def _sign_manifest(manifest_path: Path, signature_path: Path, private_key: Path) -> None:
    result = subprocess.run(
        [
            "openssl",
            "pkeyutl",
            "-sign",
            "-inkey",
            str(private_key),
            "-rawin",
            "-in",
            str(manifest_path),
            "-out",
            str(signature_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise PackageError((result.stderr or result.stdout or "package signing failed").strip())


def build_package(
    payload_path: str | Path,
    manifest: dict[str, Any],
    output_path: str | Path,
    private_key: str | Path | None = None,
    allow_unsigned: bool = False,
) -> Path:
    payload = Path(payload_path).resolve()
    if not payload.is_file():
        raise PackageError(f"payload not found: {payload}")
    data = dict(manifest)
    data["schema"] = SCHEMA_VERSION
    data["payload_size"] = payload.stat().st_size
    data["payload_sha256"] = sha256_file(payload)
    validate_manifest(data)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jvpkg-build-") as temp_name:
        temp = Path(temp_name)
        manifest_path = temp / "manifest.json"
        signature_path = temp / "signature.bin"
        manifest_path.write_bytes(canonical_manifest(data))
        if private_key:
            _sign_manifest(manifest_path, signature_path, Path(private_key).resolve())
        elif allow_unsigned:
            signature_path.write_bytes(b"")
        else:
            raise PackageError("a private key is required unless --allow-unsigned is explicit")
        with tarfile.open(destination, mode="w:gz", format=tarfile.PAX_FORMAT) as archive:
            archive.add(manifest_path, arcname="manifest.json", recursive=False)
            archive.add(payload, arcname="payload.tar.gz", recursive=False)
            archive.add(signature_path, arcname="signature.bin", recursive=False)
    return destination
