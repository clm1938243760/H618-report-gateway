from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import AsyncMock, patch

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from gadget_msc_printer.auth import SessionStore
from gadget_msc_printer.config import AppConfig, load_config, save_config
from gadget_msc_printer.driver_manager import DriverManager
from gadget_msc_printer.maintenance import MaintenanceManager
from gadget_msc_printer.report_info import ReportInfoManager
from gadget_msc_printer.report_upload import ReportUploadWorker
from gadget_msc_printer.web import ConfigWebApp


class FakeWifiManager:
    def __init__(self) -> None:
        self.last_connect: tuple[object, ...] | None = None
        self.last_ipv4: dict[str, object] | None = None
        self.scheduled_ipv4: dict[str, object] | None = None
        self.current = {
            "available": True,
            "radio_enabled": True,
            "devices": [{"device": "wlan0", "state": "connected", "connection": "Xiaomi14"}],
            "saved_connections": [{"name": "Xiaomi14", "autoconnect": True}],
            "device": "wlan0",
            "connected": True,
            "connection": "Xiaomi14",
            "ssid": "Xiaomi14",
            "addresses": ["10.119.184.41/24"],
            "gateway": "10.119.184.80",
            "signal": 75,
            "security": "WPA2",
            "frequency": 5180,
            "channel": "36",
            "autoconnect": True,
            "ipv4_mode": "dhcp",
            "configured_address": "",
            "prefix_length": 24,
            "configured_gateway": "",
            "dns": ["10.119.184.80"],
        }
        self.hotspot = {
            "available": True,
            "configured": False,
            "active": False,
            "device": "wlan1",
            "ssid": "JVLEI-Gateway",
            "address": "192.168.0.1/24",
            "autostart": False,
            "idle_timeout_minutes": 30,
            "clients": 0,
            "idle_seconds": 0,
            "idle_remaining_seconds": None,
        }

    def status(self):
        return dict(self.current)

    def set_radio(self, enabled: bool):
        self.current["radio_enabled"] = enabled
        return self.status()

    def scan(self, device: str = "", rescan: bool = True):
        return [{"active": True, "ssid": "Xiaomi14", "signal": 75, "security": "WPA2", "frequency": 5180, "channel": "36"}]

    def connect(self, ssid: str, password: str, device: str, hidden: bool, autoconnect: bool):
        self.last_connect = (ssid, password, device, hidden, autoconnect)
        self.current.update(ssid=ssid, connection=ssid, device=device, connected=True, autoconnect=autoconnect)
        return self.status()

    def disconnect(self, device: str):
        self.current.update(connected=False, connection="", ssid="", addresses=[])
        return self.status()

    def forget(self, connection: str):
        self.current["saved_connections"] = []
        self.current.update(connected=False, connection="", ssid="", addresses=[])
        return self.status()

    def ethernet_status(self):
        return {
            "available": True,
            "connected": True,
            "device": "eth0",
            "addresses": ["192.168.20.144/24"],
            "gateway": "192.168.20.1",
            "mac": "00:11:22:33:44:55",
            "interfaces": [],
            "ipv4_mode": "dhcp",
            "configured_address": "",
            "prefix_length": 24,
            "configured_gateway": "",
            "dns": ["192.168.20.1"],
        }

    def configure_ipv4(
        self,
        interface_type,
        mode,
        address,
        prefix_length,
        gateway,
        dns,
        device,
    ):
        configuration = {
            "interface_type": interface_type,
            "backend": "networkd" if interface_type == "ethernet" else "networkmanager",
            "device": device,
            "connection": "" if interface_type == "ethernet" else self.current["connection"],
            "mode": mode,
            "address": address if mode == "manual" else "",
            "prefix_length": prefix_length,
            "gateway": gateway if mode == "manual" else "",
            "dns": list(dns),
        }
        self.last_ipv4 = configuration
        return configuration

    def schedule_ipv4_activation(self, configuration, delay_seconds=2):
        self.scheduled_ipv4 = {**configuration, "delay_seconds": delay_seconds}

    def hotspot_status(self, config):
        self.hotspot.update(
            ssid=config.ssid,
            autostart=config.autostart,
            idle_timeout_minutes=config.idle_timeout_minutes,
        )
        return dict(self.hotspot)

    def configure_hotspot(self, config):
        self.hotspot.update(configured=True)
        return self.hotspot_status(config)

    def set_hotspot(self, config, enabled: bool):
        self.hotspot.update(configured=True, active=enabled)
        return self.hotspot_status(config)

    def enforce_hotspot_idle(self, config):
        return {**self.hotspot_status(config), "auto_disabled": False}


class FakeCupsManager:
    def __init__(self) -> None:
        self.configured = None
        self.queue_enabled = True
        self.deleted = False

    def status(self, config):
        configured = None
        if self.configured is not None and not self.deleted:
            configured = {
                "name": config.queue_name,
                "device_uri": config.device_uri,
                "enabled": self.queue_enabled,
                "state": "空闲" if self.queue_enabled else "暂停",
                "detail": "idle",
            }
        return {
            "available": True,
            "running": True,
            "error": "",
            "devices": [
                {
                    "uri": "usb://Brother/HL-1218W?serial=TEST",
                    "backend": "direct",
                    "scheme": "usb",
                    "label": "Brother/HL-1218W",
                    "connection": "USB",
                    "recommended_profile": "brother_hl1200",
                }
            ],
            "profiles": [
                {
                    "value": "brother_hl1200",
                    "label": "Brother HL-1200 系列（brlaser）",
                    "available": True,
                    "model": "drv:///brlaser.drv/br1200.ppd",
                }
            ],
            "queues": [configured] if configured else [],
            "configured_queue": configured,
            "default_queue": config.queue_name if configured else "",
        }

    def configure(self, config):
        self.configured = config
        self.deleted = False
        return {"queue_name": config.queue_name}

    def test_print(self, config):
        return f"{config.queue_name}-1"

    def set_queue_enabled(self, queue_name: str, enabled: bool):
        self.queue_enabled = enabled

    def delete_queue(self, queue_name: str):
        self.deleted = True


class FakeUpdaterClient:
    def __init__(self) -> None:
        self.center_url = "http://192.168.112.229:28080"
        self.calls: list[str] = []

    def _status(self):
        return {
            "ok": True,
            "available": True,
            "enabled": True,
            "boot_check": True,
            "center_url": self.center_url,
            "app_code": "linux",
            "platform": "linux-arm64",
            "terminal_name": "K2B-TEST",
            "os_version": "Linux 6.1.0 aarch64",
            "allow_unsigned_packages": True,
            "current_version": "v0.21.3",
            "current_version_id": "21",
            "previous_version": "v0.21.2",
            "update": None,
            "download": None,
            "network": {
                "interface": "eth0",
                "ip": "192.168.20.144",
                "mac": "02:00:89:BD:16:D6",
            },
            "last_check_at": "",
            "last_terminal_report_at": "",
            "last_error": "",
            "pending_reports": 0,
            "installing": False,
        }

    async def status(self):
        return self._status()

    async def check(self):
        self.calls.append("check")
        value = self._status()
        value["update"] = {
            "record_id": "1001",
            "version": "v0.22.0",
            "version_id": "22",
            "package_size": 4096,
            "auto_upgrade": False,
            "release_note": "company update",
        }
        return value

    async def download(self):
        self.calls.append("download")
        value = self._status()
        value["download"] = {
            "ready": True,
            "path": "/var/lib/jvlei-updater/downloads/v0.22.0.zip",
            "manifest": {"server_version": "v0.22.0"},
        }
        return value

    async def install(self):
        self.calls.append("install")
        value = self._status()
        value["current_version"] = "v0.22.0"
        return value

    async def rollback(self):
        self.calls.append("rollback")
        value = self._status()
        value["current_version"] = "v0.21.2"
        return value

    async def configure(self, settings: dict[str, object], organization: dict[str, str]):
        self.calls.append(
            f"config:{settings.get('center_url')}:{settings.get('app_code')}:{organization.get('hospital_code', '')}"
        )
        self.center_url = str(settings["center_url"])
        value = self._status()
        value.update(settings)
        value["organization"] = dict(organization)
        value["last_terminal_report_at"] = 1786521474
        return value


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config_path = root / "config.yaml"
        config = AppConfig()
        config.runtime.data_dir = str(root / "data")
        config.web.username = "tejian01"
        config.web.password = "test-password-123"
        config.web.static_dir = str(root / "frontend")
        config.device.device_code = "D-OLD"
        config.device.exam_doct = "旧医生"
        config.device.exam_doct_code = "DOC-OLD"
        config.device.report_info_path = str(root / "data" / "device" / "ReportInfo.xml")
        config.upload.state_db = str(root / "data" / "state" / "jobs.sqlite3")
        config.pdf.output_dir = str(root / "data" / "reports_pdf")
        config.printer.output_dir = str(root / "data" / "print_jobs")
        config.physical_printer.state_db = str(root / "data" / "state" / "physical.sqlite3")
        config.msc.output_dir = str(root / "data" / "msc_files")
        frontend = Path(config.web.static_dir)
        (frontend / "static-resource" / "js").mkdir(parents=True)
        (frontend / "index.html").write_text(
            "<!doctype html><html><body><div id=\"app\">Vue gateway</div></body></html>",
            encoding="utf-8",
        )
        (frontend / "favicon.ico").write_bytes(b"ico")
        (frontend / "static-resource" / "js" / "app.js").write_text(
            "console.log('gateway')",
            encoding="utf-8",
        )
        save_config(self.config_path, config)
        report_info = ReportInfoManager(config.device)
        report_info.write(config.device.device_code, config.device.exam_doct, config.device.exam_doct_code)
        uploader = ReportUploadWorker(config.upload, config.pdf, report_info)
        self.uploader = uploader
        self.maintenance = MaintenanceManager(
            config.cleanup,
            config.runtime,
            config.pdf,
            config.printer,
            config.msc,
            uploader.store,
            command_runner=lambda *args, **kwargs: CompletedProcess(args[0], 0, "vacuumed", ""),
        )
        self.wifi = FakeWifiManager()
        self.cups = FakeCupsManager()
        self.updater = FakeUpdaterClient()
        self.driver_manager = DriverManager(root=root / "drivers")
        self.web = ConfigWebApp(
            self.config_path,
            config,
            SessionStore(8),
            report_info,
            uploader,
            self.maintenance,
            self.wifi,
            self.cups,
            driver_manager=self.driver_manager,
            updater_client=self.updater,
        )
        self.client = TestClient(TestServer(self.web.app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.temp.cleanup()

    async def _login(self) -> tuple[str, str]:
        response = await self.client.post(
            "/api/login",
            json={"username": "tejian01", "password": "test-password-123"},
        )
        payload = await response.json()
        self.assertEqual(response.status, 200)
        token = response.cookies["gmp_session"].value
        return token, str(payload["csrf"])

    async def test_api_requires_login(self) -> None:
        response = await self.client.get("/api/config")
        self.assertEqual(response.status, 401)

    async def test_update_proxy_requires_session_and_forwards_board_actions(self) -> None:
        response = await self.client.get("/api/update/status")
        self.assertEqual(response.status, 401)
        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}", "X-CSRF-Token": csrf}

        response = await self.client.get("/api/update/status", headers=headers)
        payload = await response.json()
        self.assertTrue(payload["available"])
        self.assertEqual(payload["app_code"], "linux")

        response = await self.client.post("/api/update/check", headers=headers, json={})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["update"]["version"], "v0.22.0")

        response = await self.client.post("/api/update/download", headers=headers, json={})
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["download"]["ready"])

        response = await self.client.put(
            "/api/update/config",
            headers=headers,
            json={
                "settings": {
                    "enabled": True,
                    "boot_check": False,
                    "center_url": "http://192.168.112.230:28080",
                    "app_code": "linux-box",
                    "platform": "linux-arm64",
                },
                "organization": {
                    "hospital_code": "tejian01",
                    "hospital_id": "H-021",
                    "hospital_area_code": "AREA-01",
                    "hospital_area_id": "CAMPUS-01",
                    "dept_code": "DEPT-01",
                    "dept_id": "D-01",
                },
            },
        )
        self.assertEqual(response.status, 200)
        saved_update = await response.json()
        self.assertEqual(saved_update["center_url"], "http://192.168.112.230:28080")
        self.assertEqual(saved_update["app_code"], "linux-box")
        self.assertFalse(saved_update["boot_check"])
        self.assertIn("download", self.updater.calls)
        self.assertIn("config:http://192.168.112.230:28080:linux-box:tejian01", self.updater.calls)

    async def test_driver_upload_is_analyzed_before_installation(self) -> None:
        token, csrf = await self._login()
        form = FormData()
        form.add_field(
            "driver",
            b'*PPD-Adobe: "4.3"\n*Manufacturer: "JVLEI"\n*ModelName: "Test Printer"\n',
            filename="test-printer.ppd",
            content_type="application/vnd.cups-ppd",
        )
        response = await self.client.post(
            "/api/drivers/analyze",
            headers={"Cookie": f"gmp_session={token}", "X-CSRF-Token": csrf},
            data=form,
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertTrue(payload["upload"]["analysis"]["supported"])
        self.assertEqual(payload["upload"]["analysis"]["source_type"], "ppd")

    async def test_wifi_status_scan_connect_disconnect_and_forget(self) -> None:
        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}", "X-CSRF-Token": csrf}

        response = await self.client.get("/api/wifi", headers=headers)
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["ssid"], "Xiaomi14")
        self.assertNotIn("password", payload)

        response = await self.client.post("/api/wifi/scan", json={"device": "wlan0"}, headers=headers)
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["networks"][0]["ssid"], "Xiaomi14")

        response = await self.client.post(
            "/api/wifi/connect",
            json={"device": "wlan0", "ssid": "HospitalWiFi", "password": "test-password", "autoconnect": True},
            headers=headers,
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(self.wifi.last_connect, ("HospitalWiFi", "test-password", "wlan0", False, True))
        self.assertNotIn("test-password", str(payload))

        response = await self.client.post("/api/wifi/disconnect", json={"device": "wlan0"}, headers=headers)
        self.assertEqual(response.status, 200)
        response = await self.client.post("/api/wifi/forget", json={"connection": "HospitalWiFi"}, headers=headers)
        self.assertEqual(response.status, 200)
        response = await self.client.post("/api/wifi/radio", json={"enabled": False}, headers=headers)
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertFalse(payload["radio_enabled"])

    async def test_network_and_hotspot_configuration_do_not_expose_password(self) -> None:
        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}", "X-CSRF-Token": csrf}

        response = await self.client.get("/api/network", headers=headers)
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["ethernet"]["addresses"], ["192.168.20.144/24"])
        self.assertEqual(payload["ethernet"]["mac"], "00:11:22:33:44:55")
        self.assertEqual(payload["hotspot"]["ssid"], "JVLEI-Gateway")
        self.assertNotIn("password", str(payload))

        response = await self.client.put(
            "/api/network/ipv4",
            headers=headers,
            json={
                "interface_type": "ethernet",
                "device": "eth0",
                "mode": "manual",
                "address": "192.168.20.88",
                "prefix_length": 24,
                "gateway": "192.168.20.1",
                "dns": ["192.168.20.1", "223.5.5.5"],
            },
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["address"], "192.168.20.88")
        self.assertEqual(payload["activation_delay_seconds"], 2)
        self.assertEqual(self.wifi.last_ipv4["device"], "eth0")
        self.assertEqual(self.wifi.scheduled_ipv4["delay_seconds"], 2)

        response = await self.client.put(
            "/api/hotspot/config",
            headers=headers,
            json={
                "ssid": "JVLEI-Maintenance",
                "password": "new-hotspot-password",
                "autostart": True,
                "idle_timeout_minutes": 45,
            },
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertTrue(payload["configured"])
        self.assertNotIn("new-hotspot-password", str(payload))
        saved = load_config(self.config_path)
        self.assertEqual(saved.hotspot.ssid, "JVLEI-Maintenance")
        self.assertEqual(saved.hotspot.password, "new-hotspot-password")
        self.assertTrue(saved.hotspot.autostart)
        self.assertEqual(saved.hotspot.idle_timeout_minutes, 45)

        response = await self.client.post(
            "/api/hotspot/switch",
            headers=headers,
            json={"enabled": True},
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertTrue(payload["active"])

    async def test_hotspot_monitor_restores_autostart_only_during_startup(self) -> None:
        config = load_config(self.config_path)
        config.hotspot.autostart = True
        save_config(self.config_path, config)
        self.wifi.hotspot["active"] = False

        startup_complete = await self.web._monitor_hotspot_once(False)
        self.assertTrue(startup_complete)
        self.assertTrue(self.wifi.hotspot["active"])

        self.wifi.hotspot["active"] = False
        startup_complete = await self.web._monitor_hotspot_once(startup_complete)
        self.assertTrue(startup_complete)
        self.assertFalse(self.wifi.hotspot["active"])

    async def test_login_session_restore_and_static_frontend(self) -> None:
        response = await self.client.post(
            "/api/login",
            json={"username": "tejian01", "password": "wrong-password"},
        )
        self.assertEqual(response.status, 401)

        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}
        response = await self.client.get("/api/session", headers=headers)
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["username"], "tejian01")
        self.assertEqual(payload["csrf"], csrf)

        response = await self.client.get("/login")
        self.assertEqual(response.status, 200)
        self.assertIn("Vue gateway", await response.text())
        response = await self.client.get("/static-resource/js/app.js")
        self.assertEqual(response.status, 200)
        self.assertIn("gateway", await response.text())

        response = await self.client.post(
            "/api/logout",
            headers={
                "Cookie": f"gmp_session={token}",
                "X-CSRF-Token": csrf,
            },
        )
        self.assertEqual(response.status, 200)
        response = await self.client.get(
            "/api/session",
            headers={"Cookie": f"gmp_session={token}"},
        )
        self.assertEqual(response.status, 401)

    async def test_login_failure_rate_limit(self) -> None:
        for _ in range(5):
            response = await self.client.post(
                "/api/login",
                json={"username": "tejian01", "password": "wrong-password"},
            )
            self.assertEqual(response.status, 401)
        response = await self.client.post(
            "/api/login",
            json={"username": "tejian01", "password": "test-password-123"},
        )
        self.assertEqual(response.status, 429)

    async def test_login_csrf_and_xml_configuration(self) -> None:
        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}
        response = await self.client.put(
            "/api/config",
            headers=headers,
            json={"device_code": "D-NEW", "exam_doct": "新医生", "exam_doct_code": "DOC-NEW"},
        )
        self.assertEqual(response.status, 403)
        headers["X-CSRF-Token"] = csrf
        response = await self.client.put(
            "/api/config",
            headers=headers,
            json={
                "device_code": "D-NEW",
                "exam_doct": "新医生",
                "exam_doct_code": "DOC-NEW",
                "upload_enabled": True,
                "endpoint": "http://127.0.0.1:9999/upload",
                "timeout_seconds": 12,
                "retry_interval_seconds": 15,
                "max_attempts": 4,
                "cleanup_enabled": True,
                "cleanup_interval_hours": 12,
                "report_retention_days": 45,
                "log_retention_days": 21,
            },
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        xml = (Path(self.temp.name) / "data" / "device" / "ReportInfo.xml").read_text(encoding="utf-8")
        self.assertIn("<DeviceCode>D-NEW</DeviceCode>", xml)
        self.assertIn("<ExamDoct>新医生</ExamDoct>", xml)
        self.assertIn("<ExamDoctCode>DOC-NEW</ExamDoctCode>", xml)
        self.assertLess(xml.index("<ExamDoct>"), xml.index("<ExamDoctCode>"))
        self.assertNotIn("xmlns", xml)
        response = await self.client.get("/api/config", headers=headers)
        saved = await response.json()
        self.assertNotIn("username", saved)
        self.assertNotIn("password", saved)
        self.assertEqual(saved["cleanup_interval_hours"], 12)
        self.assertEqual(saved["report_retention_days"], 45)
        self.assertEqual(saved["log_retention_days"], 21)

    async def test_invalid_cleanup_config_does_not_modify_report_info(self) -> None:
        token, csrf = await self._login()
        headers = {
            "Cookie": f"gmp_session={token}",
            "X-CSRF-Token": csrf,
        }
        report_info_path = Path(self.temp.name) / "data" / "device" / "ReportInfo.xml"
        original_xml = report_info_path.read_bytes()

        response = await self.client.put(
            "/api/config",
            headers=headers,
            json={
                "device_code": "D-BAD",
                "exam_doct": "Doctor Bad",
                "exam_doct_code": "DOC-BAD",
                "cleanup_interval_hours": 0,
            },
        )

        self.assertEqual(response.status, 400)
        self.assertEqual(report_info_path.read_bytes(), original_xml)

    async def test_deduplication_option_updates_upload_and_msc(self) -> None:
        token, csrf = await self._login()
        headers = {
            "Cookie": f"gmp_session={token}",
            "X-CSRF-Token": csrf,
        }

        with patch(
            "gadget_msc_printer.web.subprocess.run",
            return_value=CompletedProcess(["systemctl"], 0, "", ""),
        ) as run:
            response = await self.client.put(
                "/api/config",
                headers=headers,
                json={"deduplicate": False},
            )

        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertTrue(payload["collector_restarted"])
        self.assertEqual(payload["warning"], "")
        run.assert_called_once()
        saved_config = load_config(self.config_path)
        self.assertFalse(saved_config.upload.deduplicate)
        self.assertFalse(saved_config.msc.deduplicate)

        response = await self.client.get("/api/config", headers=headers)
        saved = await response.json()
        self.assertFalse(saved["deduplicate"])

        response = await self.client.put(
            "/api/config",
            headers=headers,
            json={"deduplicate": "false"},
        )
        self.assertEqual(response.status, 400)

    async def test_authenticated_dashboard_uses_vue_bundle(self) -> None:
        token, _ = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}

        response = await self.client.get("/", headers=headers)
        self.assertEqual(response.status, 200)
        dashboard = await response.text()
        self.assertIn("Vue gateway", dashboard)

    async def test_printer_configuration_and_protocol_analysis(self) -> None:
        token, csrf = await self._login()
        headers = {
            "Cookie": f"gmp_session={token}",
            "X-CSRF-Token": csrf,
        }
        config = load_config(self.config_path)
        print_dir = Path(config.printer.output_dir)
        print_dir.mkdir(parents=True, exist_ok=True)
        (print_dir / "sample.prn").write_bytes(
            b"\x1b%-12345X@PJL ENTER LANGUAGE=PCLXL\r\n) HP-PCL XL;2;0;"
        )

        response = await self.client.put(
            "/api/printer/config",
            headers=headers,
            json={
                "driver_profile": "pcl",
                "usb_vendor_id": "0xffff",
                "usb_product_id": "0xffff",
                "usb_manufacturer": "UNTRUSTED",
                "usb_product": "K2B PCL Printer",
                "usb_serial": "K2B-TEST-001",
                "idle_complete_seconds": 5,
                "min_job_bytes": 64,
            },
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertFalse(payload["applied"])
        self.assertNotIn("usb_pnp_string", payload)
        saved = load_config(self.config_path)
        self.assertEqual(saved.printer.usb_vendor_id, "0x0525")
        self.assertEqual(saved.printer.usb_product_id, "0xa4a8")
        self.assertEqual(saved.printer.usb_manufacturer, "JVLEI")
        self.assertIn("MFG:JVLEI", saved.printer.usb_pnp_string)
        self.assertIn("CMD:PJL,PCL,PCLXL,RAW", saved.printer.usb_pnp_string)

        response = await self.client.get("/api/printer/config", headers=headers)
        public_config = await response.json()
        self.assertEqual(response.status, 200, public_config)
        self.assertTrue(public_config["boundary_detection"]["enabled"])
        self.assertEqual(public_config["boundary_detection"]["mode"], "protocol_first")
        self.assertIn("PCL", public_config["boundary_detection"]["supported_protocols"])
        for hidden in ("usb_vendor_id", "usb_product_id", "usb_manufacturer", "usb_pnp_string"):
            self.assertNotIn(hidden, public_config)

        response = await self.client.get("/api/printer/analysis", headers=headers)
        analysis = await response.json()
        self.assertEqual(response.status, 200, analysis)
        self.assertEqual(analysis["jobs"][0]["protocol"], "pclxl")
        self.assertTrue(analysis["jobs"][0]["sha256"])
        self.assertEqual(analysis["jobs"][0]["declared_language"], "PCLXL")

        response = await self.client.get(
            "/api/printer/files/sample.prn/download",
            headers=headers,
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), (print_dir / "sample.prn").read_bytes())
        self.assertIn("attachment", response.headers["Content-Disposition"])

    async def test_physical_printer_configuration_and_queue_controls(self) -> None:
        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}", "X-CSRF-Token": csrf}

        response = await self.client.get("/api/physical-printer", headers=headers)
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertTrue(payload["cups"]["running"])
        self.assertEqual(payload["cups"]["devices"][0]["recommended_profile"], "brother_hl1200")

        response = await self.client.put(
            "/api/physical-printer/config",
            headers=headers,
            json={
                "enabled": True,
                "auto_print": True,
                "queue_name": "Brother_HL1218W",
                "device_uri": "usb://Brother/HL-1218W?serial=TEST",
                "driver_profile": "brother_hl1200",
                "page_size": "A4",
                "resolution": "600dpi",
                "copies": 1,
                "set_default": True,
            },
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertTrue(payload["applied"])
        self.assertEqual(load_config(self.config_path).physical_printer.queue_name, "Brother_HL1218W")

        response = await self.client.post("/api/physical-printer/test", headers=headers, json={})
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["job_id"], "Brother_HL1218W-1")

        response = await self.client.post(
            "/api/physical-printer/control", headers=headers, json={"action": "pause"}
        )
        self.assertEqual(response.status, 200)
        self.assertFalse(self.cups.queue_enabled)

        response = await self.client.delete("/api/physical-printer/queue", headers=headers)
        self.assertEqual(response.status, 200)
        saved = load_config(self.config_path)
        self.assertFalse(saved.physical_printer.enabled)
        self.assertFalse(saved.physical_printer.auto_print)

    async def test_msc_configuration_and_explicit_rebuild(self) -> None:
        token, csrf = await self._login()
        headers = {
            "Cookie": f"gmp_session={token}",
            "X-CSRF-Token": csrf,
        }
        restart = AsyncMock()
        with patch.object(self.web, "_restart_collector", new=restart):
            response = await self.client.put(
                "/api/msc/config",
                headers=headers,
                json={
                    "image_size_mb": 256,
                    "label": "TEST DISK",
                    "auto_delete": True,
                    "deduplicate": False,
                    "restore_protected_files": True,
                    "protected_files": ["DEVICE.INI", "Config/marker.dat"],
                },
            )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertTrue(payload["collector_restarted"])
        self.assertTrue(payload["rebuild_required"])
        restart.assert_awaited_once()
        saved = load_config(self.config_path)
        self.assertTrue(saved.msc.auto_delete)
        self.assertFalse(saved.msc.deduplicate)
        self.assertFalse(saved.upload.deduplicate)
        self.assertEqual(saved.msc.protected_files, ["DEVICE.INI", "Config/marker.dat"])

        response = await self.client.post(
            "/api/msc/rebuild",
            headers=headers,
            json={"confirm": False},
        )
        self.assertEqual(response.status, 400)

        command = AsyncMock(return_value=CompletedProcess(["mock"], 0, "rebuilt", ""))
        with patch.object(self.web, "_run_command", new=command):
            response = await self.client.post(
                "/api/msc/rebuild",
                headers=headers,
                json={"confirm": True},
            )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(command.await_count, 3)

    async def test_report_download_is_authenticated_and_confined_to_report_directory(self) -> None:
        token, _ = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}
        root = Path(self.temp.name) / "data" / "reports_pdf"
        root.mkdir(parents=True, exist_ok=True)
        report = root / "download-test.pdf"
        report.write_bytes(b"%PDF-1.4\ndownload\n%%EOF\n")
        snapshot = self.web.report_info.snapshot()
        job_id = self.uploader.store.enqueue(report, snapshot, "printer", deduplicate=False)
        self.assertIsNotNone(job_id)

        response = await self.client.get(f"/api/reports/{job_id}/download", headers=headers)
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), report.read_bytes())
        self.assertIn("attachment", response.headers["Content-Disposition"])

        outside = Path(self.temp.name) / "outside.pdf"
        outside.write_bytes(b"outside")
        outside_id = self.uploader.store.enqueue(outside, snapshot, "printer", deduplicate=False)
        response = await self.client.get(f"/api/reports/{outside_id}/download", headers=headers)
        self.assertEqual(response.status, 404)

    async def test_reports_api_supports_pagination_and_status_filters(self) -> None:
        token, _ = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}
        root = Path(self.temp.name) / "data" / "reports_pdf"
        root.mkdir(parents=True, exist_ok=True)
        snapshot = self.web.report_info.snapshot()

        uploaded = root / "uploaded.pdf"
        uploaded.write_bytes(b"uploaded")
        uploaded_id = self.uploader.store.enqueue(uploaded, snapshot, "msc")
        self.assertIsNotNone(uploaded_id)
        self.uploader.store.finish(int(uploaded_id), True, 1, 3, 60, 200, "", "ok")

        failed = root / "failed.pdf"
        failed.write_bytes(b"failed")
        failed_id = self.uploader.store.enqueue(failed, snapshot, "printer")
        self.assertIsNotNone(failed_id)
        self.uploader.store.finish(int(failed_id), False, 1, 1, 60, 500, "failed", "")

        pending = root / "pending.pdf"
        pending.write_bytes(b"pending")
        self.assertIsNotNone(self.uploader.store.enqueue(pending, snapshot, "msc"))

        response = await self.client.get(
            "/api/reports?page=1&page_size=1&status=failed",
            headers=headers,
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["jobs"][0]["status"], "exhausted")

        response = await self.client.get("/api/reports?start=20&end=10", headers=headers)
        self.assertEqual(response.status, 400)

    async def test_manual_cleanup_requires_csrf_and_exposes_status(self) -> None:
        token, csrf = await self._login()
        headers = {"Cookie": f"gmp_session={token}"}

        response = await self.client.get("/api/maintenance", headers=headers)
        status = await response.json()
        self.assertEqual(response.status, 200, status)
        self.assertIn("next_run_at", status)

        response = await self.client.post(
            "/api/maintenance/cleanup",
            headers=headers,
            json={"kind": "logs"},
        )
        self.assertEqual(response.status, 403)

        response = await self.client.post(
            "/api/maintenance/cleanup",
            headers={**headers, "X-CSRF-Token": csrf},
            json={"kind": "logs"},
        )
        payload = await response.json()
        self.assertEqual(response.status, 200, payload)
        self.assertEqual(payload["kind"], "logs")
        self.assertEqual(payload["result"]["journal_output"], "vacuumed")


if __name__ == "__main__":
    unittest.main()
