#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jvlei_update.company_package import normalize_version, verify_company_package


PAYLOAD_PATHS = (
    "pyproject.toml",
    "requirements.txt",
    "config.example.yaml",
    "updater.example.yaml",
    "src",
    "scripts",
    "systemd",
    "overlays",
    "templates",
    "assets",
    "third_party",
    "portal/portal/dist",
)
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "node_modules", ".playwright-cli"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pem", ".key", ".crt", ".token", ".jvpkg", ".zip"}
ALLOWED_SENSITIVE_ASSETS = {PurePosixPath("assets/driver-pack-public.pem")}
INTERNAL_TEST_ONLY_PATHS = {
    PurePosixPath("scripts/build_ghostpcl.sh"),
}


def git_value(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=source, capture_output=True, text=True, check=False, timeout=30
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def include_file(path: Path) -> bool:
    portable = PurePosixPath(path.as_posix())
    if portable in ALLOWED_SENSITIVE_ASSETS:
        return True
    return (
        portable not in INTERNAL_TEST_ONLY_PATHS
        and not any(part in EXCLUDED_PARTS for part in path.parts)
        and path.suffix.lower() not in EXCLUDED_SUFFIXES
    )


def payload_files(source: Path) -> list[Path]:
    files: list[Path] = []
    for value in PAYLOAD_PATHS:
        path = source / value
        if not path.exists():
            raise SystemExit(f"required payload path is missing: {path}")
        candidates = [path] if path.is_file() else path.rglob("*")
        for candidate in candidates:
            if candidate.is_symlink():
                raise SystemExit(f"payload source must not contain symlinks: {candidate}")
            if candidate.is_file() and include_file(candidate.relative_to(source)):
                files.append(candidate)
    return sorted(set(files), key=lambda item: item.relative_to(source).as_posix())


def create_payload(source: Path, output: Path, files: list[Path], epoch: int) -> None:
    with output.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for path in files:
                    relative = PurePosixPath(path.relative_to(source).as_posix())
                    info = archive.gettarinfo(str(path), arcname=str(relative))
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = epoch
                    if relative.parts[0] == "scripts" and path.suffix == ".sh":
                        info.mode = 0o755
                    else:
                        info.mode = 0o644
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a company-compatible H618 update ZIP")
    parser.add_argument("--source", default=str(PROJECT_ROOT))
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--compatible-from", action="append", default=[])
    parser.add_argument("--app-code", default="linux")
    parser.add_argument("--platform", default="linux-arm64")
    parser.add_argument("--requires-gadget-restart", action="store_true")
    parser.add_argument("--requires-cups-restart", action="store_true")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    version = normalize_version(args.version)
    compatible = ["*" if item == "*" else "v" + normalize_version(item) for item in args.compatible_from]
    if not compatible:
        raise SystemExit("at least one --compatible-from version is required")
    files = payload_files(source)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))

    with tempfile.TemporaryDirectory(prefix="jvlei-company-update-") as temp_name:
        payload = Path(temp_name) / "payload.tar.gz"
        create_payload(source, payload, files, epoch)
        payload_bytes = payload.read_bytes()
        manifest = {
            "schemaVersion": 1,
            "packageType": "application",
            "appCode": args.app_code,
            "product": "h618-report-gateway",
            "version": f"v{version}",
            "platform": args.platform,
            "architecture": "arm64",
            "compatibleFrom": compatible,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "gitCommit": git_value(source, "rev-parse", "HEAD"),
            "releaseNote": args.notes,
            "payload": {
                "path": "payload.tar.gz",
                "format": "tar.gz",
                "size": len(payload_bytes),
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "fileCount": len(files),
            },
            "install": {
                "mode": "atomic_release",
                "requiresGadgetRestart": args.requires_gadget_restart,
                "requiresCupsRestart": args.requires_cups_restart,
                "healthUrl": "https://127.0.0.1:8443/health",
            },
        }
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        with zipfile.ZipFile(output, mode="w") as archive:
            archive.writestr(zip_info("manifest.json"), manifest_bytes)
            archive.writestr(zip_info("payload.tar.gz"), payload_bytes)

    info = verify_company_package(
        output,
        expected_size=output.stat().st_size,
        expected_app_code=args.app_code,
        expected_platform=args.platform,
        expected_version=f"v{version}",
    )
    info.cleanup()
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_name(output.name + ".sha256")
    checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii")
    print(output)
    print(checksum)
    print(f"files={len(files)} bytes={output.stat().st_size} sha256={digest}")


if __name__ == "__main__":
    main()
