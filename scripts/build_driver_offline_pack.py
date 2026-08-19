#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gadget_msc_printer.driver_catalog import DRIVER_PACK_PRODUCT, PACKAGE_CATALOG  # noqa: E402
from jvlei_update.package import build_package  # noqa: E402


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout or f"{command[0]} failed").strip())
    return result.stdout.strip()


def run_in(command: list[str], cwd: Path) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout or f"{command[0]} failed").strip())
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dependency_closure(packages: list[str]) -> list[str]:
    output = run(
        [
            "apt-cache",
            "depends",
            "--recurse",
            "--no-recommends",
            "--no-suggests",
            "--no-conflicts",
            "--no-breaks",
            "--no-replaces",
            "--no-enhances",
            *packages,
        ]
    )
    values = set(packages)
    for line in output.splitlines():
        if line != line.lstrip():
            continue
        name = line.strip().split(":", 1)[0]
        if re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", name):
            values.add(name)
    return sorted(values)


def control_fields(deb: Path) -> tuple[str, str, str]:
    fields = run(["dpkg-deb", "-f", str(deb), "Package", "Version", "Architecture"]).splitlines()
    if len(fields) < 3:
        raise SystemExit(f"cannot read DEB metadata: {deb}")
    return fields[0], fields[1], fields[2]


def package_index(pool: Path) -> tuple[str, list[str]]:
    paragraphs: list[str] = []
    names: list[str] = []
    for deb in sorted(pool.glob("*.deb")):
        control = run(["dpkg-deb", "-f", str(deb)])
        package, _version, architecture = control_fields(deb)
        if architecture not in {"arm64", "all"}:
            raise SystemExit(f"unsupported architecture in {deb.name}: {architecture}")
        names.append(package)
        digest = sha256_file(deb)
        paragraphs.append(
            control.rstrip()
            + f"\nFilename: pool/{deb.name}\nSize: {deb.stat().st_size}\nSHA256: {digest}\n"
        )
    return "\n".join(paragraphs), sorted(set(names))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the signed Noble ARM64 offline printer-driver repository")
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if platform.machine().lower() not in {"aarch64", "arm64"}:
        raise SystemExit("offline pack must be built in a Noble ARM64 environment")
    os_release = platform.freedesktop_os_release()
    if os_release.get("ID") != "ubuntu" or os_release.get("VERSION_ID") != "24.04":
        raise SystemExit("offline pack must be built on Ubuntu Noble 24.04")
    catalog = Path(args.catalog).resolve()
    private_key = Path(args.private_key).resolve()
    if not catalog.is_file() or not private_key.is_file():
        raise SystemExit("catalog or private key does not exist")
    catalog_data = json.loads(catalog.read_text(encoding="utf-8"))
    packages = sorted(PACKAGE_CATALOG)
    with tempfile.TemporaryDirectory(prefix="jvlei-driver-pack-") as temp_name:
        temp = Path(temp_name)
        payload_root = temp / "payload"
        repo = payload_root / "repo"
        pool = repo / "pool"
        pool.mkdir(parents=True)
        for package in dependency_closure(packages):
            before = set(pool.glob("*.deb"))
            run_in(["apt-get", "download", package], pool)
            created = set(pool.glob("*.deb")) - before
            if len(created) != 1:
                raise SystemExit(f"cannot locate downloaded package: {package}")
        index, package_names = package_index(pool)
        (repo / "Packages").write_text(index, encoding="utf-8", newline="\n")
        with (repo / "Packages.gz").open("wb") as raw_output:
            with gzip.GzipFile(fileobj=raw_output, mode="wb", mtime=0) as output:
                output.write(index.encode("utf-8"))
        shutil.copy2(catalog, payload_root / "catalog.json")
        payload = temp / "payload.tar.gz"
        with tarfile.open(payload, "w:gz") as archive:
            archive.add(payload_root / "catalog.json", arcname="catalog.json", recursive=False)
            archive.add(repo, arcname="repo")
        dependencies = sorted(set(package_names) - set(packages))
        git_commit = run(["git", "rev-parse", "--short=12", "HEAD"]) if (ROOT / ".git").exists() else "unknown"
        output = build_package(
            payload,
            {
                "package_id": f"noble-arm64-drivers-{args.version}",
                "package_type": "printer_driver",
                "product": DRIVER_PACK_PRODUCT,
                "version": args.version,
                "arch": "arm64",
                "compatible_versions": ["*"],
                "created_at": datetime.now(timezone.utc).isoformat(),
                "release_notes": "Ubuntu Noble ARM64 offline printer-driver repository",
                "git_commit": git_commit,
                "migration_level": 0,
                "requires_gadget_restart": False,
                "requires_cups_restart": True,
                "catalog_version": str(catalog_data.get("updated_at", args.version)),
                "os_id": "ubuntu",
                "os_version": "24.04",
                "dependencies": dependencies,
                "package_names": package_names,
            },
            args.output,
            private_key=private_key,
        )
    print(output)


if __name__ == "__main__":
    main()
