from __future__ import annotations

import importlib.util
import hashlib
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_config.py"
SPEC = importlib.util.spec_from_file_location("migrate_config", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MigrateConfigTests(unittest.TestCase):
    def test_vendored_decoder_hashes_match_install_constants(self) -> None:
        self.assertEqual(
            MODULE._sha256(MODULE.PROJECT_ROOT / MODULE.HBPL_DECODER_RELATIVE),
            MODULE.HBPL_DECODER_SHA256,
        )
        self.assertEqual(
            MODULE._sha256(MODULE.PROJECT_ROOT / MODULE.DDST_DECODER_RELATIVE),
            MODULE.DDST_DECODER_SHA256,
        )
        self.assertEqual(
            MODULE._sha256(MODULE.PROJECT_ROOT / MODULE.OPL_DECODER_RELATIVE),
            MODULE.OPL_DECODER_SHA256,
        )
        self.assertEqual(
            MODULE._sha256(MODULE.PROJECT_ROOT / MODULE.SLX_DECODER_RELATIVE),
            MODULE.SLX_DECODER_SHA256,
        )
        self.assertEqual(
            MODULE._sha256(MODULE.PROJECT_ROOT / MODULE.BRLASER_DECODER_RELATIVE),
            MODULE.BRLASER_DECODER_SHA256,
        )

    def test_service_unit_sync_is_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source_root = root / "release"
            systemd_dir = root / "etc-systemd"
            source = source_root / "systemd" / "gadget-web.service"
            source.parent.mkdir(parents=True)
            source.write_text("[Unit]\nAfter=jvlei-updater.service\n", encoding="utf-8")

            self.assertTrue(MODULE.sync_service_unit(source_root, systemd_dir))
            destination = systemd_dir / "gadget-web.service"
            self.assertEqual(destination.read_bytes(), source.read_bytes())
            self.assertFalse(MODULE.sync_service_unit(source_root, systemd_dir))

    def test_hbpl_decoder_install_is_verified_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source_root = root / "release"
            source = source_root / MODULE.HBPL_DECODER_RELATIVE
            source.parent.mkdir(parents=True)
            source.write_bytes(b"audited-arm64-hbpl-decoder")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = root / "usr-local" / "hbpldecode"

            self.assertTrue(
                MODULE.install_hbpl_decoder(
                    source_root,
                    target,
                    machine="aarch64",
                    expected_sha256=digest,
                    smoke_test=False,
                )
            )
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertFalse(
                MODULE.install_hbpl_decoder(
                    source_root,
                    target,
                    machine="arm64",
                    expected_sha256=digest,
                    smoke_test=False,
                )
            )

    def test_hbpl_decoder_install_rejects_tampering_and_other_architectures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source_root = root / "release"
            source = source_root / MODULE.HBPL_DECODER_RELATIVE
            source.parent.mkdir(parents=True)
            source.write_bytes(b"tampered")
            target = root / "hbpldecode"

            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                MODULE.install_hbpl_decoder(
                    source_root,
                    target,
                    machine="aarch64",
                    expected_sha256="0" * 64,
                    smoke_test=False,
                )
            self.assertFalse(target.exists())
            self.assertFalse(
                MODULE.install_hbpl_decoder(
                    source_root,
                    target,
                    machine="x86_64",
                    expected_sha256="0" * 64,
                    smoke_test=False,
                )
            )

    def test_brlaser_decoder_install_is_verified_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source_root = root / "release"
            source = source_root / MODULE.BRLASER_DECODER_RELATIVE
            source.parent.mkdir(parents=True)
            source.write_bytes(b"audited-arm64-brother-decoder")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = root / "usr-local" / "brdecode"

            self.assertTrue(
                MODULE.install_brlaser_decoder(
                    source_root,
                    target,
                    machine="aarch64",
                    expected_sha256=digest,
                    smoke_test=False,
                )
            )
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertFalse(
                MODULE.install_brlaser_decoder(
                    source_root,
                    target,
                    machine="arm64",
                    expected_sha256=digest,
                    smoke_test=False,
                )
            )

    def test_ddst_decoder_install_is_verified_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source_root = root / "release"
            source = source_root / MODULE.DDST_DECODER_RELATIVE
            source.parent.mkdir(parents=True)
            source.write_bytes(b"audited-arm64-ddst-decoder")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            target = root / "usr-local" / "ddstdecode"

            self.assertTrue(
                MODULE.install_ddst_decoder(
                    source_root,
                    target,
                    machine="aarch64",
                    expected_sha256=digest,
                    smoke_test=False,
                )
            )
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertFalse(
                MODULE.install_ddst_decoder(
                    source_root,
                    target,
                    machine="arm64",
                    expected_sha256=digest,
                    smoke_test=False,
                )
            )

    def test_opl_and_slx_decoders_install_verified_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            source_root = root / "release"
            cases = (
                (MODULE.OPL_DECODER_RELATIVE, MODULE.install_opl_decoder, "opldecode"),
                (MODULE.SLX_DECODER_RELATIVE, MODULE.install_slx_decoder, "slxdecode"),
            )
            for relative, installer, name in cases:
                with self.subTest(decoder=name):
                    source = source_root / relative
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(f"audited-{name}".encode())
                    digest = hashlib.sha256(source.read_bytes()).hexdigest()
                    target = root / "usr-local" / name
                    self.assertTrue(
                        installer(
                            source_root,
                            target,
                            machine="aarch64",
                            expected_sha256=digest,
                            smoke_test=False,
                        )
                    )
                    self.assertEqual(target.read_bytes(), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
