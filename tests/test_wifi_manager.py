from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gadget_msc_printer.config import AppConfig
from gadget_msc_printer.wifi_manager import WifiError, WifiManager, parse_nmcli_integer, split_nmcli_line


class StubRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        key = tuple(command[1:])
        outputs = {
            ("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"):
                "wlan0:wifi:connected:Xiaomi14\neth0:ethernet:connected:Wired\n",
            ("-t", "-f", "WIFI", "general"): "enabled\n",
            ("-t", "-f", "NAME,TYPE,AUTOCONNECT", "connection", "show"):
                "Xiaomi14:802-11-wireless:yes\nWired:802-3-ethernet:yes\n",
            ("-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY", "device", "show", "wlan0"):
                "GENERAL.STATE:100 (connected)\nGENERAL.CONNECTION:Xiaomi14\nIP4.ADDRESS[1]:10.119.184.41/24\nIP4.GATEWAY:10.119.184.80\n",
            ("-g", "802-11-wireless.ssid,connection.autoconnect", "connection", "show", "Xiaomi14"):
                "Xiaomi14\nyes\n",
            (
                "-t",
                "-f",
                "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns",
                "connection",
                "show",
                "Xiaomi14",
            ): "ipv4.method:auto\nipv4.addresses:\nipv4.gateway:\nipv4.dns:223.5.5.5\n",
            ("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ,CHAN", "device", "wifi", "list", "ifname", "wlan0"):
                "*:Xiaomi14:78:WPA2:5180 MHz:36\n:Guest\\:Lab:52:--:2412 MHz:1\n",
        }
        if key[:2] == ("connection", "modify"):
            return subprocess.CompletedProcess(command, 0, "modified", "")
        if key not in outputs:
            return subprocess.CompletedProcess(command, 10, "", "unexpected command")
        return subprocess.CompletedProcess(command, 0, outputs[key], "")


class WifiManagerTests(unittest.TestCase):
    def test_nmcli_escaped_fields_are_parsed(self) -> None:
        self.assertEqual(split_nmcli_line(r"wifi\:lab:WPA2\\WPA3"), ["wifi:lab", "WPA2\\WPA3"])
        self.assertEqual(parse_nmcli_integer("2412 MHz"), 2412)

    def test_status_and_scan_do_not_expose_secrets(self) -> None:
        runner = StubRunner()
        manager = WifiManager(runner)
        status = manager.status()

        self.assertTrue(status["available"])
        self.assertTrue(status["connected"])
        self.assertEqual(status["ssid"], "Xiaomi14")
        self.assertEqual(status["addresses"], ["10.119.184.41/24"])
        self.assertEqual(status["signal"], 78)
        self.assertEqual(status["ipv4_mode"], "dhcp")
        self.assertEqual(status["dns"], ["223.5.5.5"])
        networks = manager.scan("wlan0", rescan=False)
        self.assertEqual(networks[1]["ssid"], "Guest:Lab")
        self.assertNotIn("password", status)

    def test_secret_is_removed_from_nmcli_error(self) -> None:
        secret = "secret-password"

        def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 10, "", f"invalid password {secret}")

        manager = WifiManager(runner)
        with self.assertRaises(WifiError) as caught:
            manager._run(["device", "wifi", "connect", "test", "password", secret], secrets=(secret,))
        self.assertNotIn(secret, str(caught.exception))

    def test_invalid_device_and_ssid_are_rejected(self) -> None:
        manager = WifiManager(StubRunner())
        with self.assertRaises(ValueError):
            manager.scan("wlan0;reboot", rescan=False)
        with self.assertRaises(ValueError):
            manager.connect("bad\nssid", device="wlan0")

    def test_ethernet_status_reads_iproute_json(self) -> None:
        def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            outputs = {
                ("ip", "-j", "address", "show"):
                    '[{"ifname":"eth0","link_type":"ether","operstate":"UP",'
                    '"flags":["UP","LOWER_UP"],"address":"00:11:22:33:44:55",'
                    '"addr_info":[{"family":"inet","local":"192.168.20.144","prefixlen":24,"dynamic":true}]}]',
                ("ip", "-j", "route", "show", "default"):
                    '[{"dst":"default","gateway":"192.168.20.1","dev":"eth0"}]',
                ("resolvectl", "dns", "eth0"): "Link 2 (eth0): 192.168.20.1 223.5.5.5\n",
            }
            output = outputs.get(tuple(command))
            if output is None:
                return subprocess.CompletedProcess(command, 1, "", "unexpected command")
            return subprocess.CompletedProcess(command, 0, output, "")

        status = WifiManager(runner).ethernet_status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["device"], "eth0")
        self.assertEqual(status["addresses"], ["192.168.20.144/24"])
        self.assertEqual(status["mac"], "00:11:22:33:44:55")
        self.assertEqual(status["ipv4_mode"], "dhcp")
        self.assertEqual(status["dns"], ["192.168.20.1", "223.5.5.5"])

    def test_ethernet_static_ipv4_writes_isolated_networkd_profile(self) -> None:
        def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            outputs = {
                ("ip", "-j", "address", "show"):
                    '[{"ifname":"eth0","link_type":"ether","operstate":"UP",'
                    '"flags":["UP","LOWER_UP"],"address":"00:11:22:33:44:55",'
                    '"addr_info":[{"family":"inet","local":"192.168.20.144","prefixlen":24,"dynamic":true}]}]',
                ("ip", "-j", "route", "show", "default"):
                    '[{"dst":"default","gateway":"192.168.20.1","dev":"eth0"}]',
                ("resolvectl", "dns", "eth0"): "Link 2 (eth0): 192.168.20.1\n",
            }
            output = outputs.get(tuple(command))
            if output is None:
                return subprocess.CompletedProcess(command, 1, "", "unexpected command")
            return subprocess.CompletedProcess(command, 0, output, "")

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "05-gateway-ethernet.network"
            manager = WifiManager(runner, path)
            configuration = manager.configure_ipv4(
                "ethernet",
                "manual",
                "192.168.20.88",
                24,
                "192.168.20.1",
                ["192.168.20.1", "223.5.5.5"],
                "eth0",
            )
            profile = path.read_text(encoding="utf-8")

        self.assertEqual(configuration["backend"], "networkd")
        self.assertIn("Address=192.168.20.88/24", profile)
        self.assertIn("DNS=192.168.20.1 223.5.5.5", profile)
        self.assertIn("Gateway=192.168.20.1", profile)

    def test_wifi_static_ipv4_modifies_current_profile(self) -> None:
        runner = StubRunner()
        manager = WifiManager(runner)
        configuration = manager.configure_ipv4(
            "wifi",
            "manual",
            "10.119.184.50",
            24,
            "10.119.184.80",
            ["223.5.5.5"],
            "wlan0",
        )

        self.assertEqual(configuration["backend"], "networkmanager")
        command = next(item for item in runner.commands if item[1:3] == ["connection", "modify"])
        self.assertIn("10.119.184.50/24", command)
        self.assertIn("223.5.5.5", command)

    def test_static_ipv4_rejects_gateway_outside_subnet(self) -> None:
        with self.assertRaisesRegex(ValueError, "same subnet"):
            WifiManager._validate_ipv4_settings(
                "manual",
                "192.168.20.88",
                24,
                "192.168.21.1",
                ["223.5.5.5"],
            )

    def test_hotspot_status_reports_clients_without_password(self) -> None:
        def runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
            outputs = {
                ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"):
                    "wlan0:wifi:connected:Xiaomi14\nwlan1:wifi:connected:gmp-hotspot\n",
                ("nmcli", "-t", "-f", "NAME,TYPE,AUTOCONNECT", "connection", "show"):
                    "Xiaomi14:802-11-wireless:yes\ngmp-hotspot:802-11-wireless:no\n",
                ("nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"):
                    "Xiaomi14:802-11-wireless:wlan0\ngmp-hotspot:802-11-wireless:wlan1\n",
                ("iw", "dev", "wlan1", "station", "dump"):
                    "Station aa:bb:cc:dd:ee:ff (on wlan1)\n\tsignal: -42 dBm\n",
            }
            output = outputs.get(tuple(command))
            if output is None:
                return subprocess.CompletedProcess(command, 1, "", "unexpected command")
            return subprocess.CompletedProcess(command, 0, output, "")

        status = WifiManager(runner).hotspot_status(AppConfig().hotspot)
        self.assertTrue(status["active"])
        self.assertEqual(status["clients"], 1)
        self.assertNotIn("password", status)

    def test_idle_hotspot_is_automatically_disabled(self) -> None:
        class HotspotRunner:
            def __init__(self) -> None:
                self.active = True

            def __call__(self, command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
                key = tuple(command)
                if key == ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"):
                    output = "wlan0:wifi:disconnected:\nwlan1:wifi:connected:gmp-hotspot\n"
                elif key == ("nmcli", "-t", "-f", "NAME,TYPE,AUTOCONNECT", "connection", "show"):
                    output = "gmp-hotspot:802-11-wireless:no\n"
                elif key == ("nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"):
                    output = "gmp-hotspot:802-11-wireless:wlan1\n" if self.active else ""
                elif key == ("iw", "dev", "wlan1", "station", "dump"):
                    output = ""
                elif key == ("nmcli", "connection", "down", "gmp-hotspot"):
                    self.active = False
                    output = "deactivated"
                else:
                    return subprocess.CompletedProcess(command, 1, "", "unexpected command")
                return subprocess.CompletedProcess(command, 0, output, "")

        config = AppConfig().hotspot
        config.idle_timeout_minutes = 1
        runner = HotspotRunner()
        manager = WifiManager(runner)
        manager._hotspot_started_at = 1.0
        with patch("gadget_msc_printer.wifi_manager.time.monotonic", return_value=62.0):
            status = manager.enforce_hotspot_idle(config)
        self.assertTrue(status["auto_disabled"])
        self.assertFalse(status["active"])
        self.assertFalse(runner.active)


if __name__ == "__main__":
    unittest.main()
