from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

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
