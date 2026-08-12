from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_config.py"
SPEC = importlib.util.spec_from_file_location("migrate_config", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MigrateConfigTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
