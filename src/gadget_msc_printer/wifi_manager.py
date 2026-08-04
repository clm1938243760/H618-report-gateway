from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

from .config import HotspotConfig


class WifiError(RuntimeError):
    pass


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def split_nmcli_line(line: str) -> list[str]:
    values: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line.rstrip("\r\n"):
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            values.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    values.append("".join(current))
    return values


def parse_nmcli_integer(value: str) -> int:
    token = value.strip().split(maxsplit=1)[0] if value.strip() else "0"
    return int(float(token))


class WifiManager:
    DEFAULT_HOTSPOT_CONNECTION = "gmp-hotspot"

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self._using_default_runner = command_runner is None
        self.command_runner = command_runner or self._default_runner
        self._hotspot_started_at: float | None = None
        self._hotspot_last_client_at: float | None = None

    @staticmethod
    def _default_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    def _run_command(
        self,
        command: list[str],
        timeout: int = 20,
        secrets: tuple[str, ...] = (),
    ) -> str:
        result = self.command_runner(command, timeout)
        if result.returncode == 0:
            return str(result.stdout or "").strip()
        message = str(result.stderr or result.stdout or f"{command[0]} command failed").strip()
        for secret in secrets:
            if secret:
                message = message.replace(secret, "********")
        raise WifiError(message or f"{command[0]} command failed")

    def _run(
        self,
        arguments: list[str],
        timeout: int = 20,
        secrets: tuple[str, ...] = (),
    ) -> str:
        return self._run_command(["nmcli", *arguments], timeout, secrets)

    @staticmethod
    def _validate_device(device: str) -> str:
        value = device.strip()
        if not value or len(value) > 32 or not all(char.isalnum() or char in "_.-" for char in value):
            raise ValueError("invalid Wi-Fi device")
        return value

    @staticmethod
    def _validate_ssid(ssid: str) -> str:
        value = ssid.strip()
        if not value or len(value.encode("utf-8")) > 32 or "\n" in value or "\r" in value:
            raise ValueError("SSID must contain 1 to 32 bytes")
        return value

    @staticmethod
    def _validate_password(password: str) -> str:
        if not 8 <= len(password) <= 63 or "\n" in password or "\r" in password:
            raise ValueError("Wi-Fi password must contain 8 to 63 characters")
        return password

    def _wifi_devices(self) -> list[dict[str, str]]:
        output = self._run(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
        devices: list[dict[str, str]] = []
        for line in output.splitlines():
            parts = split_nmcli_line(line)
            if len(parts) < 4 or parts[1] != "wifi":
                continue
            devices.append({"device": parts[0], "state": parts[2], "connection": parts[3]})
        return devices

    def _resolve_device(self, requested: str = "") -> str:
        devices = self._wifi_devices()
        if requested:
            value = self._validate_device(requested)
            if any(item["device"] == value for item in devices):
                return value
            raise ValueError("Wi-Fi device not found")
        connected = next(
            (
                item
                for item in devices
                if item["state"] == "connected" and item["connection"] != self.DEFAULT_HOTSPOT_CONNECTION
            ),
            None,
        )
        if connected:
            return connected["device"]
        available = next(
            (item for item in devices if item["connection"] != self.DEFAULT_HOTSPOT_CONNECTION),
            None,
        )
        if available:
            return available["device"]
        raise WifiError("Wi-Fi device not found")

    def _connection_profiles(self) -> list[dict[str, Any]]:
        output = self._run(["-t", "-f", "NAME,TYPE,AUTOCONNECT", "connection", "show"])
        profiles: list[dict[str, Any]] = []
        for line in output.splitlines():
            parts = split_nmcli_line(line)
            if len(parts) < 3 or parts[1] not in {"wifi", "802-11-wireless"}:
                continue
            profiles.append({"name": parts[0], "autoconnect": parts[2].lower() == "yes"})
        return profiles

    def _active_connections(self) -> list[dict[str, str]]:
        output = self._run(["-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
        active: list[dict[str, str]] = []
        for line in output.splitlines():
            parts = split_nmcli_line(line)
            if len(parts) >= 3:
                active.append({"name": parts[0], "type": parts[1], "device": parts[2]})
        return active

    def status(self) -> dict[str, Any]:
        if shutil.which("nmcli") is None and self._using_default_runner:
            return {
                "available": False,
                "error": "NetworkManager nmcli is not installed",
                "radio_enabled": False,
                "devices": [],
                "saved_connections": [],
                "connected": False,
            }
        devices = self._wifi_devices()
        radio_output = self._run(["-t", "-f", "WIFI", "general"])
        radio_enabled = radio_output.strip().lower() == "enabled"
        selected = next(
            (
                item
                for item in devices
                if item["state"] == "connected" and item["connection"] != self.DEFAULT_HOTSPOT_CONNECTION
            ),
            None,
        )
        if selected is None:
            selected = next(
                (item for item in devices if item["connection"] != self.DEFAULT_HOTSPOT_CONNECTION),
                None,
            )
        profiles = [
            item for item in self._connection_profiles() if item["name"] != self.DEFAULT_HOTSPOT_CONNECTION
        ]
        result: dict[str, Any] = {
            "available": bool(devices),
            "radio_enabled": radio_enabled,
            "devices": devices,
            "saved_connections": profiles,
            "device": selected["device"] if selected else "",
            "connected": bool(selected and selected["state"] == "connected"),
            "connection": selected["connection"] if selected and selected["state"] == "connected" else "",
            "ssid": "",
            "addresses": [],
            "gateway": "",
            "signal": 0,
            "security": "",
            "frequency": 0,
            "channel": "",
            "autoconnect": False,
        }
        if not result["connected"]:
            return result

        detail = self._run(
            ["-t", "-f", "GENERAL.STATE,GENERAL.CONNECTION,IP4.ADDRESS,IP4.GATEWAY", "device", "show", result["device"]]
        )
        for line in detail.splitlines():
            parts = split_nmcli_line(line)
            if len(parts) < 2:
                continue
            key, value = parts[0], parts[1]
            if key.startswith("IP4.ADDRESS") and value:
                result["addresses"].append(value)
            elif key == "IP4.GATEWAY":
                result["gateway"] = value

        connection_name = str(result["connection"])
        try:
            profile = self._run(
                ["-g", "802-11-wireless.ssid,connection.autoconnect", "connection", "show", connection_name]
            ).splitlines()
            result["ssid"] = profile[0] if profile else connection_name
            result["autoconnect"] = len(profile) > 1 and profile[1].strip().lower() == "yes"
        except WifiError:
            result["ssid"] = connection_name

        for network in self.scan(str(result["device"]), rescan=False):
            if network["active"] or network["ssid"] == result["ssid"]:
                result.update(
                    signal=network["signal"],
                    security=network["security"],
                    frequency=network["frequency"],
                    channel=network["channel"],
                )
                if network["active"]:
                    break
        return result

    def ethernet_status(self) -> dict[str, Any]:
        try:
            links = json.loads(self._run_command(["ip", "-j", "address", "show"]))
            routes = json.loads(self._run_command(["ip", "-j", "route", "show", "default"]))
        except (WifiError, json.JSONDecodeError) as exc:
            return {"available": False, "connected": False, "interfaces": [], "error": str(exc)}

        gateways = {str(item.get("dev", "")): str(item.get("gateway", "")) for item in routes}
        interfaces: list[dict[str, Any]] = []
        for item in links:
            name = str(item.get("ifname", ""))
            if item.get("link_type") != "ether" or not name.startswith(("eth", "end", "enp", "eno")):
                continue
            addresses = [
                f"{address.get('local')}/{address.get('prefixlen')}"
                for address in item.get("addr_info", [])
                if address.get("family") == "inet" and address.get("local")
            ]
            flags = set(item.get("flags", []))
            connected = "LOWER_UP" in flags and bool(addresses)
            interfaces.append(
                {
                    "device": name,
                    "connected": connected,
                    "state": str(item.get("operstate", "UNKNOWN")).lower(),
                    "addresses": addresses,
                    "gateway": gateways.get(name, ""),
                    "mac": str(item.get("address", "")),
                }
            )
        primary = next((item for item in interfaces if item["gateway"]), None)
        if primary is None:
            primary = next((item for item in interfaces if item["connected"]), None)
        return {
            "available": bool(interfaces),
            "connected": bool(primary and primary["connected"]),
            "device": primary["device"] if primary else (interfaces[0]["device"] if interfaces else ""),
            "addresses": primary["addresses"] if primary else [],
            "gateway": primary["gateway"] if primary else "",
            "mac": primary["mac"] if primary else (interfaces[0]["mac"] if interfaces else ""),
            "interfaces": interfaces,
        }

    def set_radio(self, enabled: bool) -> dict[str, Any]:
        self._run(["radio", "wifi", "on" if enabled else "off"])
        return self.status()

    def scan(self, device: str = "", rescan: bool = True) -> list[dict[str, Any]]:
        selected = self._resolve_device(device)
        if rescan:
            try:
                self._run(["device", "wifi", "rescan", "ifname", selected], timeout=20)
            except WifiError:
                pass
        output = self._run(
            ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ,CHAN", "device", "wifi", "list", "ifname", selected],
            timeout=30,
        )
        networks: dict[str, dict[str, Any]] = {}
        for line in output.splitlines():
            parts = split_nmcli_line(line)
            if len(parts) < 6 or not parts[1]:
                continue
            try:
                signal = parse_nmcli_integer(parts[2])
                frequency = parse_nmcli_integer(parts[4])
            except ValueError:
                continue
            item = {
                "active": parts[0] == "*",
                "ssid": parts[1],
                "signal": signal,
                "security": parts[3] or "开放网络",
                "frequency": frequency,
                "channel": parts[5],
            }
            existing = networks.get(item["ssid"])
            if existing is None or item["active"] or signal > existing["signal"]:
                networks[item["ssid"]] = item
        return sorted(networks.values(), key=lambda item: (not item["active"], -item["signal"], item["ssid"]))

    def connect(
        self,
        ssid: str,
        password: str = "",
        device: str = "",
        hidden: bool = False,
        autoconnect: bool = True,
    ) -> dict[str, Any]:
        selected = self._resolve_device(device)
        value = self._validate_ssid(ssid)
        if len(password) > 64 or "\n" in password or "\r" in password:
            raise ValueError("invalid Wi-Fi password")
        arguments = ["device", "wifi", "connect", value]
        if password:
            arguments.extend(["password", password])
        arguments.extend(["ifname", selected])
        if hidden:
            arguments.extend(["hidden", "yes"])
        self._run(arguments, timeout=60, secrets=(password,))
        state = self.status()
        connection = str(state.get("connection", ""))
        if not state.get("connected") or not connection:
            raise WifiError("Wi-Fi connection was not activated")
        self._run(
            [
                "connection",
                "modify",
                connection,
                "connection.autoconnect",
                "yes" if autoconnect else "no",
                "connection.autoconnect-priority",
                "10",
                "ipv4.route-metric",
                "600",
                "ipv6.route-metric",
                "600",
            ]
        )
        return self.status()

    def disconnect(self, device: str = "") -> dict[str, Any]:
        selected = self._resolve_device(device)
        self._run(["device", "disconnect", selected])
        return self.status()

    def forget(self, connection: str) -> dict[str, Any]:
        value = connection.strip()
        profiles = self._connection_profiles()
        if not value or value == self.DEFAULT_HOTSPOT_CONNECTION or not any(
            item["name"] == value for item in profiles
        ):
            raise ValueError("saved Wi-Fi connection not found")
        self._run(["connection", "delete", value])
        return self.status()

    def configure_hotspot(self, config: HotspotConfig) -> dict[str, Any]:
        device = self._validate_device(config.device)
        ssid = self._validate_ssid(config.ssid)
        password = self._validate_password(config.password)
        if not any(item["device"] == device for item in self._wifi_devices()):
            raise ValueError("hotspot Wi-Fi device not found")

        profiles = self._connection_profiles()
        exists = any(item["name"] == config.connection_name for item in profiles)
        active = any(item["name"] == config.connection_name for item in self._active_connections())
        if not exists:
            self._run(
                [
                    "connection",
                    "add",
                    "type",
                    "wifi",
                    "ifname",
                    device,
                    "con-name",
                    config.connection_name,
                    "ssid",
                    ssid,
                ]
            )
        self._run(
            [
                "connection",
                "modify",
                config.connection_name,
                "connection.interface-name",
                device,
                "connection.autoconnect",
                "yes" if config.autostart else "no",
                "connection.autoconnect-priority",
                "-10",
                "802-11-wireless.mode",
                "ap",
                "802-11-wireless.ssid",
                ssid,
                "802-11-wireless.powersave",
                "2",
                "802-11-wireless-security.key-mgmt",
                "wpa-psk",
                "802-11-wireless-security.psk",
                password,
                "ipv4.method",
                "shared",
                "ipv4.addresses",
                config.address,
                "ipv4.never-default",
                "yes",
                "ipv6.method",
                "disabled",
            ],
            secrets=(password,),
        )
        if active:
            self._run(["connection", "down", config.connection_name], timeout=30)
            self._run(["connection", "up", config.connection_name, "ifname", device], timeout=60)
            self._hotspot_started_at = time.monotonic()
            self._hotspot_last_client_at = None
        return self.hotspot_status(config)

    def _hotspot_clients(self, device: str) -> int:
        try:
            output = self._run_command(["iw", "dev", device, "station", "dump"], timeout=10)
        except WifiError:
            return 0
        return sum(1 for line in output.splitlines() if line.lstrip().startswith("Station "))

    def hotspot_status(self, config: HotspotConfig) -> dict[str, Any]:
        devices = self._wifi_devices()
        profiles = self._connection_profiles()
        active_item = next(
            (item for item in self._active_connections() if item["name"] == config.connection_name),
            None,
        )
        active = active_item is not None
        now = time.monotonic()
        if active and self._hotspot_started_at is None:
            self._hotspot_started_at = now
        if not active:
            self._hotspot_started_at = None
            self._hotspot_last_client_at = None
        clients = self._hotspot_clients(config.device) if active else 0
        if clients:
            self._hotspot_last_client_at = now
        idle_base = self._hotspot_last_client_at or self._hotspot_started_at or now
        idle_seconds = max(0, int(now - idle_base)) if active and not clients else 0
        timeout_seconds = config.idle_timeout_minutes * 60
        remaining = max(0, timeout_seconds - idle_seconds) if active and timeout_seconds else None
        return {
            "available": any(item["device"] == config.device for item in devices),
            "configured": any(item["name"] == config.connection_name for item in profiles),
            "active": active,
            "device": config.device,
            "ssid": config.ssid,
            "address": config.address,
            "autostart": config.autostart,
            "idle_timeout_minutes": config.idle_timeout_minutes,
            "clients": clients,
            "idle_seconds": idle_seconds,
            "idle_remaining_seconds": remaining,
        }

    def set_hotspot(self, config: HotspotConfig, enabled: bool) -> dict[str, Any]:
        profiles = self._connection_profiles()
        exists = any(item["name"] == config.connection_name for item in profiles)
        if enabled:
            if not exists:
                self.configure_hotspot(config)
            self._run(["radio", "wifi", "on"])
            self._run(["connection", "up", config.connection_name, "ifname", config.device], timeout=60)
            self._hotspot_started_at = time.monotonic()
            self._hotspot_last_client_at = None
        elif exists and any(item["name"] == config.connection_name for item in self._active_connections()):
            self._run(["connection", "down", config.connection_name], timeout=30)
            self._hotspot_started_at = None
            self._hotspot_last_client_at = None
        return self.hotspot_status(config)

    def enforce_hotspot_idle(self, config: HotspotConfig) -> dict[str, Any]:
        status = self.hotspot_status(config)
        remaining = status.get("idle_remaining_seconds")
        if status["active"] and config.idle_timeout_minutes > 0 and remaining == 0:
            status = self.set_hotspot(config, False)
            status["auto_disabled"] = True
        else:
            status["auto_disabled"] = False
        return status
