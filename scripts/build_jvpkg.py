#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jvlei_update.package import build_package


EXCLUDED_PARTS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist-packages",
    "update_center_data",
    "update_center",
    "output",
    "tmp",
    ".playwright-cli",
    "tests",
    "docs",
}

SENSITIVE_SUFFIXES = {".pem", ".key", ".token", ".crt"}
SENSITIVE_PATHS = {
    Path("update_center/config.yaml"),
    Path("updater.yaml"),
}


def include_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if relative in SENSITIVE_PATHS or path.suffix.lower() in SENSITIVE_SUFFIXES:
        return False
    if path.suffix.lower() in {".jvpkg", ".pyc", ".pyo"}:
        return False
    return True


def create_payload(source: Path, output: Path) -> None:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))

    def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        original = source / info.name
        if not include_path(original, source):
            return None
        relative = original.relative_to(source)
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        info.mtime = epoch
        if len(relative.parts) > 1 and relative.parts[0] == "scripts" and original.suffix == ".sh":
            info.mode = 0o755
        return info

    with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for child in sorted(source.iterdir(), key=lambda item: item.name):
            if include_path(child, source):
                archive.add(child, arcname=child.name, recursive=True, filter=normalize)


def git_value(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=source, capture_output=True, text=True, check=False, timeout=30
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a signed JVLEI application update package")
    parser.add_argument("--source", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--private-key")
    parser.add_argument("--allow-unsigned", action="store_true")
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--compatible-from",
        action="append",
        default=[],
        help="current gateway version accepted by this package; repeat for more versions",
    )
    parser.add_argument("--requires-gadget-restart", action="store_true")
    parser.add_argument("--requires-cups-restart", action="store_true")
    args = parser.parse_args()
    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    commit = git_value(source, "rev-parse", "HEAD")
    with tempfile.TemporaryDirectory(prefix="jvlei-payload-") as temp_name:
        payload = Path(temp_name) / "payload.tar.gz"
        create_payload(source, payload)
        manifest = {
            "package_id": f"h618-report-gateway-{args.version}-{commit[:12]}",
            "package_type": "application",
            "product": "h618-report-gateway",
            "version": args.version,
            "arch": "arm64",
            "compatible_versions": args.compatible_from or ["0.20.0"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "release_notes": args.notes,
            "git_commit": commit,
            "migration_level": 0,
            "requires_gadget_restart": args.requires_gadget_restart,
            "requires_cups_restart": args.requires_cups_restart,
        }
        build_package(
            payload,
            manifest,
            output,
            private_key=args.private_key,
            allow_unsigned=args.allow_unsigned,
        )
    print(output)


if __name__ == "__main__":
    main()
