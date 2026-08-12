from __future__ import annotations

import io
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from jvlei_update.company_package import verify_company_package
from jvlei_update.package import PackageError, build_package, safe_extract_payload, verify_package


def make_payload(path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        content = b"gateway application payload\n"
        member = tarfile.TarInfo("README.txt")
        member.size = len(content)
        archive.addfile(member, io.BytesIO(content))


def manifest() -> dict[str, object]:
    return {
        "package_id": "h618-report-gateway-0.21.0-test",
        "package_type": "application",
        "product": "h618-report-gateway",
        "version": "0.21.0",
        "arch": "arm64",
        "compatible_versions": ["0.20.0"],
        "created_at": "2026-08-06T00:00:00+00:00",
        "release_notes": "test package",
        "git_commit": "0123456789abcdef",
        "migration_level": 0,
        "requires_gadget_restart": False,
        "requires_cups_restart": False,
    }


class UpdatePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = self.root / "payload.tar.gz"
        make_payload(self.payload)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_unsigned_package_requires_explicit_local_allowance(self) -> None:
        package = self.root / "test.jvpkg"
        build_package(self.payload, manifest(), package, allow_unsigned=True)
        with self.assertRaisesRegex(PackageError, "unsigned"):
            verify_package(package, None, allow_unsigned=False)
        info = verify_package(package, None, allow_unsigned=True)
        try:
            self.assertFalse(info.signed)
            self.assertEqual(info.manifest["version"], "0.21.0")
        finally:
            info.cleanup()

    def test_payload_tampering_is_detected_before_installation(self) -> None:
        source = self.root / "source.jvpkg"
        damaged = self.root / "damaged.jvpkg"
        build_package(self.payload, manifest(), source, allow_unsigned=True)
        with tarfile.open(source, "r:gz") as archive:
            manifest_bytes = archive.extractfile("manifest.json").read()  # type: ignore[union-attr]
            payload_bytes = archive.extractfile("payload.tar.gz").read()  # type: ignore[union-attr]
            signature_bytes = archive.extractfile("signature.bin").read()  # type: ignore[union-attr]
        with tarfile.open(damaged, "w:gz") as archive:
            for name, content in (
                ("manifest.json", manifest_bytes),
                (
                    "payload.tar.gz",
                    payload_bytes[:-1] + (b"\x00" if payload_bytes[-1:] != b"\x00" else b"\x01"),
                ),
                ("signature.bin", signature_bytes),
            ):
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        with self.assertRaisesRegex(PackageError, "SHA-256"):
            verify_package(damaged, None, allow_unsigned=True)

    def test_payload_extraction_rejects_path_traversal(self) -> None:
        unsafe = self.root / "unsafe.tar.gz"
        with tarfile.open(unsafe, "w:gz") as archive:
            content = b"unsafe"
            member = tarfile.TarInfo("../outside.txt")
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        with self.assertRaisesRegex(PackageError, "unsafe payload path"):
            safe_extract_payload(unsafe, self.root / "target")

    def test_payload_extraction_rejects_duplicate_paths(self) -> None:
        unsafe = self.root / "duplicate.tar.gz"
        with tarfile.open(unsafe, "w:gz") as archive:
            for content in (b"first", b"second"):
                member = tarfile.TarInfo("duplicate.txt")
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        with self.assertRaisesRegex(PackageError, "duplicate paths"):
            safe_extract_payload(unsafe, self.root / "target")

    def test_ed25519_signature_is_verified_when_openssl_is_available(self) -> None:
        openssl = shutil.which("openssl")
        if not openssl:
            self.skipTest("OpenSSL is not installed")
        private_key = self.root / "private.pem"
        public_key = self.root / "public.pem"
        subprocess.run(
            [openssl, "genpkey", "-algorithm", "ED25519", "-out", str(private_key)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [openssl, "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)],
            check=True,
            capture_output=True,
        )
        package = self.root / "signed.jvpkg"
        build_package(self.payload, manifest(), package, private_key=private_key)
        info = verify_package(package, public_key, allow_unsigned=False)
        try:
            self.assertTrue(info.signed)
        finally:
            info.cleanup()


class CompanyUpdatePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def build_package(
        self,
        output: Path,
        *,
        member_name: str = "README.txt",
        declared_file_count: int = 1,
        platform: str = "linux-arm64",
    ) -> None:
        payload = self.root / f"{output.stem}.tar.gz"
        with tarfile.open(payload, "w:gz") as archive:
            content = b"company update payload\n"
            member = tarfile.TarInfo(member_name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        payload_bytes = payload.read_bytes()
        manifest = {
            "schemaVersion": 1,
            "packageType": "application",
            "appCode": "linux",
            "product": "h618-report-gateway",
            "version": "v0.22.0",
            "platform": platform,
            "architecture": "arm64",
            "compatibleFrom": ["v0.21.3"],
            "releaseNote": "company update test",
            "payload": {
                "path": "payload.tar.gz",
                "format": "tar.gz",
                "size": len(payload_bytes),
                "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "fileCount": declared_file_count,
            },
            "install": {"mode": "atomic_release"},
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
            archive.writestr("payload.tar.gz", payload_bytes)

    def test_company_zip_checks_manifest_crc_hash_and_payload_members(self) -> None:
        package = self.root / "valid.zip"
        self.build_package(package)
        info = verify_company_package(
            package,
            expected_size=package.stat().st_size,
            expected_version="v0.22.0",
        )
        try:
            self.assertEqual(info.manifest["version"], "0.22.0")
            self.assertFalse(info.signed)
        finally:
            info.cleanup()

    def test_company_zip_rejects_payload_path_traversal_before_installation(self) -> None:
        package = self.root / "unsafe.zip"
        self.build_package(package, member_name="../outside.txt")
        with self.assertRaisesRegex(PackageError, "unsafe payload path"):
            verify_company_package(package)

    def test_company_zip_rejects_wrong_file_count_and_platform(self) -> None:
        wrong_count = self.root / "wrong-count.zip"
        self.build_package(wrong_count, declared_file_count=2)
        with self.assertRaisesRegex(PackageError, "file count"):
            verify_company_package(wrong_count)

        wrong_platform = self.root / "wrong-platform.zip"
        self.build_package(wrong_platform, platform="win-x64")
        with self.assertRaisesRegex(PackageError, "platform"):
            verify_company_package(wrong_platform)

    def test_company_zip_rejects_string_restart_flags(self) -> None:
        package = self.root / "invalid-boolean.zip"
        self.build_package(package)
        with zipfile.ZipFile(package, "r") as archive:
            manifest = json.loads(archive.read("manifest.json"))
            payload = archive.read("payload.tar.gz")
        manifest["install"]["requiresGadgetRestart"] = "false"
        with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest).encode("utf-8"))
            archive.writestr("payload.tar.gz", payload)
        with self.assertRaisesRegex(PackageError, "must be a boolean"):
            verify_company_package(package)
