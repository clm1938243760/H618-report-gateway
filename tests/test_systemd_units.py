from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SystemdUnitTests(unittest.TestCase):
    def test_web_ui_does_not_wait_for_network_or_updater(self) -> None:
        unit = (ROOT / "systemd" / "gadget-web.service").read_text(encoding="utf-8")

        self.assertNotIn("network-online.target", unit)
        self.assertIn("After=local-fs.target network.target", unit)
        self.assertIn("Wants=jvlei-updater.service", unit)
        self.assertNotRegex(unit, r"After=.*jvlei-updater\.service")


if __name__ == "__main__":
    unittest.main()
