#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gadget_msc_printer.driver_catalog import DriverCatalogManager, PACKAGE_CATALOG  # noqa: E402


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout or f"{command[0]} failed").strip())
    return result.stdout.strip()


def models() -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for line in run(["lpinfo", "-m"]).splitlines():
        parts = line.strip().split(maxsplit=1)
        if parts:
            values.append({"model": parts[0], "label": parts[1] if len(parts) > 1 else parts[0]})
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Noble ARM64 CUPS model catalog")
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-missing-packages", action="store_true")
    args = parser.parse_args()
    if platform.machine().lower() not in {"aarch64", "arm64"}:
        raise SystemExit("catalog must be generated in a Noble ARM64 environment")
    os_release = platform.freedesktop_os_release()
    if os_release.get("ID") != "ubuntu" or os_release.get("VERSION_ID") != "24.04":
        raise SystemExit("catalog must be generated on Ubuntu Noble 24.04")
    missing: list[str] = []
    for package in PACKAGE_CATALOG:
        result = subprocess.run(
            ["dpkg-query", "-W", "-f=${db:Status-Status}", package],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or result.stdout.strip() != "installed":
            missing.append(package)
    if missing and not args.allow_missing_packages:
        raise SystemExit(
            "install the complete driver whitelist before building the catalog:\n  apt-get install -y --no-install-recommends "
            + " ".join(missing)
        )
    with tempfile.TemporaryDirectory(prefix="jvlei-driver-catalog-") as temp_name:
        manager = DriverCatalogManager(Path(temp_name), model_provider=models)
        summary = manager.refresh(False)
        output = manager.export_catalog(args.output)
    metadata_path = Path(args.output).with_suffix(".build.json")
    metadata_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "os": "ubuntu",
                "version": "24.04",
                "arch": "arm64",
                "models": summary["total"],
                "missing_packages": missing,
                "source_date_epoch": os.environ.get("SOURCE_DATE_EPOCH", ""),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
