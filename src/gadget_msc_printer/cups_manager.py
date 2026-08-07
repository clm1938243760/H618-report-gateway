from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .config import PhysicalPrinterConfig


class CupsError(RuntimeError):
    pass


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


DRIVER_PROFILES: tuple[dict[str, Any], ...] = (
    {
        "value": "ipp_everywhere",
        "label": "IPP Everywhere（免驱）",
        "description": "适用于支持 IPP Everywhere/AirPrint 的现代网络打印机",
        "patterns": (),
        "model": "everywhere",
    },
    {
        "value": "hp_laserjet_m401_pcl6",
        "label": "HP LaserJet Pro 400 M401\uff08PCL 6 / PCL XL\uff09",
        "description": "\u9002\u7528\u4e8e HP LaserJet Pro 400 M401 \u7cfb\u5217\uff0c\u8f93\u51fa\u9ed1\u767d PCL XL \u6253\u5370\u6d41",
        "patterns": (r"Generic-PCL_6_PCL_XL_Printer-pxlmono\.ppd", r"Generic PCL 6/PCL XL Printer Foomatic/pxlmono"),
    },
    {
        "value": "brother_hl1200",
        "label": "Brother HL-1200 系列（brlaser）",
        "description": "适用于 HL-1200/HL-1210/HL-1218W 系列黑白激光打印机",
        "patterns": (r"br1200\.ppd", r"Brother HL-1200 series"),
    },
    {
        "value": "generic_postscript",
        "label": "通用 PostScript",
        "description": "适用于原生支持 PostScript 的打印机",
        "patterns": (r"Generic PostScript", r"sample\.drv/generic\.ppd"),
    },
    {
        "value": "generic_pcl",
        "label": "通用 PCL 5/5e",
        "description": "适用于原生支持 PCL 5 或 PCL 5e 的打印机",
        "patterns": (r"sample\.drv/generpcl\.ppd", r"Generic PCL Laser Printer$"),
    },
    {
        "value": "generic_pcl6",
        "label": "通用 PCL 6/PCL XL",
        "description": "适用于原生支持 PCL 6 或 PCL XL 的打印机",
        "patterns": (r"Generic-PCL_6_PCL_XL_Printer-pxlmono\.ppd", r"Generic PCL 6/PCL XL Printer Foomatic/pxlmono"),
    },
)


class CupsManager:
    def __init__(
        self,
        command_runner: CommandRunner | None = None,
        custom_profile_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._using_default_runner = command_runner is None
        self.command_runner = command_runner or self._default_runner
        self.custom_profile_provider = custom_profile_provider

    @staticmethod
    def _default_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["LC_ALL"] = "C"
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )

    def _run(self, command: list[str], timeout: int = 30) -> str:
        result = self.command_runner(command, timeout)
        if result.returncode == 0:
            return str(result.stdout or "").strip()
        message = str(result.stderr or result.stdout or f"{command[0]} command failed").strip()
        raise CupsError(message or f"{command[0]} command failed")

    def _run_optional(self, command: list[str], timeout: int = 30) -> str:
        result = self.command_runner(command, timeout)
        return str(result.stdout or "").strip()

    def available(self) -> bool:
        if not self._using_default_runner:
            return True
        return all(shutil.which(command) for command in ("lpstat", "lpinfo", "lpadmin", "lp"))

    def discover_devices(self) -> list[dict[str, str]]:
        output = self._run(["lpinfo", "-v"], timeout=30)
        devices: list[dict[str, str]] = []
        seen: set[str] = set()
        for line in output.splitlines():
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2:
                continue
            backend, uri = parts
            parsed = urlparse(uri)
            if parsed.scheme not in {"usb", "ipp", "ipps", "socket", "lpd"} or uri in seen:
                continue
            seen.add(uri)
            label_source = f"{parsed.netloc}{parsed.path}" if parsed.netloc or parsed.path else uri
            label = unquote(label_source).strip("/") or uri
            devices.append(
                {
                    "uri": uri,
                    "backend": backend,
                    "scheme": parsed.scheme,
                    "label": label,
                    "connection": "USB" if parsed.scheme == "usb" else "网络",
                    "recommended_profile": self.recommend_profile(uri),
                }
            )
        return devices

    @staticmethod
    def recommend_profile(uri: str) -> str:
        lowered = unquote(uri).lower()
        if "hp" in lowered and ("m401" in lowered or "laserjet pro 400" in lowered):
            return "hp_laserjet_m401_pcl6"
        if "brother" in lowered and any(value in lowered for value in ("hl-120", "hl-121")):
            return "brother_hl1200"
        if lowered.startswith(("ipp://", "ipps://")):
            return "ipp_everywhere"
        return ""

    def installed_models(self) -> list[dict[str, str]]:
        output = self._run(["lpinfo", "-m"], timeout=60)
        models: list[dict[str, str]] = []
        for line in output.splitlines():
            parts = line.strip().split(maxsplit=1)
            if not parts:
                continue
            models.append({"model": parts[0], "label": parts[1] if len(parts) > 1 else parts[0]})
        return models

    def driver_profiles(self) -> list[dict[str, Any]]:
        models = self.installed_models()
        profiles: list[dict[str, Any]] = []
        for definition in DRIVER_PROFILES:
            profile = {key: value for key, value in definition.items() if key != "patterns"}
            if definition["value"] == "ipp_everywhere":
                profile.update(available=True, model="everywhere")
            else:
                match = next(
                    (
                        model
                        for model in models
                        if any(
                            re.search(pattern, f"{model['model']} {model['label']}", re.IGNORECASE)
                            for pattern in definition["patterns"]
                        )
                    ),
                    None,
                )
                profile.update(
                    available=match is not None,
                    model=match["model"] if match else "",
                    installed_label=match["label"] if match else "",
                )
            profiles.append(profile)
        if self.custom_profile_provider is not None:
            try:
                supplied_profiles = self.custom_profile_provider()
            except Exception:
                supplied_profiles = []
            for supplied in supplied_profiles:
                if not isinstance(supplied, dict):
                    continue
                value = str(supplied.get("value", ""))
                model = str(supplied.get("model", ""))
                if not value.startswith("custom:") or not model:
                    continue
                model_path = Path(model)
                profiles.append(
                    {
                        "value": value,
                        "label": str(supplied.get("label", value)),
                        "description": str(supplied.get("description", "现场导入驱动")),
                        "available": model_path.is_file(),
                        "model": str(model_path),
                        "installed_label": str(supplied.get("installed_label", "")),
                        "source_type": str(supplied.get("source_type", "")),
                    }
                )
        return profiles

    def _model_for_profile(self, profile: str) -> tuple[str, bool]:
        selected = next((item for item in self.driver_profiles() if item["value"] == profile), None)
        if selected is None:
            raise CupsError("unsupported physical printer driver profile")
        if not selected["available"] or not selected["model"]:
            raise CupsError(f"selected printer driver is not installed: {selected['label']}")
        model = str(selected["model"])
        return model, profile.startswith("custom:") and Path(model).is_file()

    def queues(self) -> list[dict[str, Any]]:
        # lpstat exits with status 1 when CUPS is healthy but no queue exists.
        printers = self._run_optional(["lpstat", "-p"], timeout=20)
        devices = self._run_optional(["lpstat", "-v"], timeout=20)
        uri_by_name: dict[str, str] = {}
        for line in devices.splitlines():
            match = re.match(r"device for ([^:]+):\s*(.+)$", line.strip())
            if match:
                uri_by_name[match.group(1)] = match.group(2)
        queues: list[dict[str, Any]] = []
        for line in printers.splitlines():
            match = re.match(r"printer\s+(\S+)\s+(.+)$", line.strip())
            if not match:
                continue
            detail = match.group(2)
            queues.append(
                {
                    "name": match.group(1),
                    "device_uri": uri_by_name.get(match.group(1), ""),
                    "enabled": "disabled" not in detail.lower(),
                    "state": "空闲" if "idle" in detail.lower() else "暂停" if "disabled" in detail.lower() else "处理中",
                    "detail": detail,
                }
            )
        return queues

    def status(self, config: PhysicalPrinterConfig) -> dict[str, Any]:
        if not self.available():
            return {
                "available": False,
                "running": False,
                "error": "CUPS is not installed",
                "devices": [],
                "profiles": [],
                "queues": [],
                "default_queue": "",
            }
        try:
            scheduler = self._run(["lpstat", "-r"], timeout=20)
            running = "running" in scheduler.lower()
            default_output = self._run_optional(["lpstat", "-d"], timeout=20)
            default_queue = default_output.split(":", 1)[1].strip() if ":" in default_output else ""
            queues = self.queues()
            devices = self.discover_devices()
            profiles = self.driver_profiles()
            configured = next((item for item in queues if item["name"] == config.queue_name), None)
            return {
                "available": True,
                "running": running,
                "error": "",
                "devices": devices,
                "profiles": profiles,
                "queues": queues,
                "default_queue": default_queue,
                "configured_queue": configured,
            }
        except CupsError as exc:
            return {
                "available": True,
                "running": False,
                "error": str(exc),
                "devices": [],
                "profiles": [],
                "queues": [],
                "default_queue": "",
            }

    def configure(self, config: PhysicalPrinterConfig) -> dict[str, Any]:
        if not config.device_uri:
            raise CupsError("physical printer device URI is required")
        model, local_ppd = self._model_for_profile(config.driver_profile)
        driver_option = ["-P", model] if local_ppd else ["-m", model]
        command = [
            "lpadmin", "-p", config.queue_name, "-E", "-v", config.device_uri,
            *driver_option, "-o", f"PageSize={config.page_size}",
            "-o", f"Resolution={config.resolution}", "-o", "printer-is-shared=false",
        ]
        self._run(command, timeout=60)
        self._run(["cupsenable", config.queue_name], timeout=20)
        self._run(["cupsaccept", config.queue_name], timeout=20)
        if config.set_default:
            self._run(["lpadmin", "-d", config.queue_name], timeout=20)
        return {"queue_name": config.queue_name, "model": model, "device_uri": config.device_uri}

    def print_file(self, path: str | Path, config: PhysicalPrinterConfig) -> str:
        source = Path(path)
        if not source.is_file():
            raise CupsError("print file does not exist")
        output = self._run(
            [
                "lp", "-d", config.queue_name, "-n", str(config.copies),
                "-o", f"media={config.page_size}", "-o", f"Resolution={config.resolution}", str(source),
            ],
            timeout=60,
        )
        match = re.search(r"request id is\s+(\S+)", output, re.IGNORECASE)
        return match.group(1) if match else output

    def test_print(self, config: PhysicalPrinterConfig) -> str:
        test_page = Path("/usr/share/cups/data/testprint")
        if not test_page.is_file():
            raise CupsError("CUPS test page is missing")
        return self.print_file(test_page, config)

    def set_queue_enabled(self, queue_name: str, enabled: bool) -> None:
        if enabled:
            self._run(["cupsenable", queue_name], timeout=20)
            self._run(["cupsaccept", queue_name], timeout=20)
        else:
            self._run(["cupsdisable", queue_name], timeout=20)

    def delete_queue(self, queue_name: str) -> None:
        self._run(["lpadmin", "-x", queue_name], timeout=20)
