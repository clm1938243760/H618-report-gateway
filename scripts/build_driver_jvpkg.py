#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from jvlei_update.package import build_package


SUPPORTED_SUFFIXES = (".deb", ".ppd", ".ppd.gz", ".zip", ".tar", ".tgz", ".tar.gz")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a signed JVLEI printer-driver package")
    parser.add_argument("--source", required=True, help="reviewed ARM64 driver file")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--private-key")
    parser.add_argument("--allow-unsigned", action="store_true")
    parser.add_argument("--notes", default="")
    parser.add_argument("--compatible-from", action="append", default=[])
    args = parser.parse_args()

    source = Path(args.source).resolve()
    if not source.is_file() or not source.name.lower().endswith(SUPPORTED_SUFFIXES):
        raise SystemExit("source must be a DEB, PPD, PPD.GZ, ZIP, TAR, TGZ, or TAR.GZ driver file")
    safe_name = re.sub(r"[^a-z0-9._+-]+", "-", source.stem.lower()).strip(".-") or "driver"
    with tempfile.TemporaryDirectory(prefix="jvlei-driver-payload-") as temp_name:
        payload = Path(temp_name) / "payload.tar.gz"
        epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
        with tarfile.open(payload, "w:gz", format=tarfile.PAX_FORMAT) as archive:
            info = archive.gettarinfo(str(source), arcname=f"driver/{source.name}")
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = epoch
            with source.open("rb") as handle:
                archive.addfile(info, handle)
        manifest = {
            "package_id": f"h618-driver-{safe_name}-{args.version}",
            "package_type": "printer_driver",
            "product": "h618-report-gateway",
            "version": args.version,
            "arch": "arm64",
            "compatible_versions": list(dict.fromkeys(args.compatible_from or ["*"])),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "release_notes": args.notes,
            "git_commit": "driver-package",
            "migration_level": 0,
            "requires_gadget_restart": False,
            "requires_cups_restart": True,
        }
        output = build_package(
            payload,
            manifest,
            Path(args.output).resolve(),
            private_key=args.private_key,
            allow_unsigned=args.allow_unsigned,
        )
    print(output)


if __name__ == "__main__":
    main()
