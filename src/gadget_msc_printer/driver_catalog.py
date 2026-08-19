from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from jvlei_update.package import PackageError, safe_extract_payload, verify_package


LOGGER = logging.getLogger(__name__)


class DriverCatalogError(RuntimeError):
    pass


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess[str]]
ModelProvider = Callable[[], list[dict[str, str]]]
CacheInvalidator = Callable[[], None]

MAX_OFFLINE_PACK_BYTES = 512 * 1024 * 1024
CATALOG_SCHEMA = 1
DRIVER_PACK_PRODUCT = "jvlei-printer-drivers-noble-arm64"
APT_LOCK_OPTIONS = ["-o", "DPkg::Lock::Timeout=120"]


# Package names are never accepted from an HTTP request. Only entries from this
# table can reach apt-get.
PACKAGE_CATALOG: dict[str, dict[str, Any]] = {
    "printer-driver-brlaser": {"label": "Brother 黑白激光（brlaser）", "vendors": ["Brother"], "protocols": ["Brother raster"]},
    "printer-driver-c2050": {"label": "Lexmark 2050 系列", "vendors": ["Lexmark"], "protocols": ["C2050"]},
    "printer-driver-c2esp": {"label": "Kodak ESP", "vendors": ["Kodak"], "protocols": ["C2ESP"]},
    "printer-driver-cjet": {"label": "Canon LBP（cjet）", "vendors": ["Canon"], "protocols": ["CAPSL"]},
    "printer-driver-dymo": {"label": "DYMO 标签打印机", "vendors": ["DYMO"], "protocols": ["DYMO raster"]},
    "printer-driver-escpr": {"label": "Epson ESC/P-R", "vendors": ["Epson"], "protocols": ["ESC/P-R"]},
    "printer-driver-foo2zjs": {"label": "foo2zjs 主机型打印机", "vendors": ["HP", "Minolta", "Samsung", "Xerox"], "protocols": ["ZjStream", "QPDL", "XQX", "HIPERC"]},
    "printer-driver-fujixerox": {"label": "Fuji Xerox", "vendors": ["Fuji Xerox", "Fujifilm"], "protocols": ["Fuji Xerox raster"]},
    "printer-driver-gutenprint": {"label": "Gutenprint 喷墨与旧型号", "vendors": ["Epson", "Canon", "HP"], "protocols": ["Gutenprint raster"]},
    "printer-driver-hpcups": {"label": "HP HPLIP/HPCUPS", "vendors": ["HP"], "protocols": ["HPCUPS raster"]},
    "printer-driver-hpijs": {"label": "HP HPIJS 旧型号", "vendors": ["HP"], "protocols": ["HPIJS raster"]},
    "printer-driver-indexbraille": {"label": "Index Braille", "vendors": ["Index Braille"], "protocols": ["Braille"]},
    "printer-driver-m2300w": {"label": "Minolta magicolor 2300W/2400W", "vendors": ["Minolta", "Konica Minolta"], "protocols": ["m2300w"]},
    "printer-driver-min12xxw": {"label": "Minolta PagePro 12xxW", "vendors": ["Minolta", "Konica Minolta"], "protocols": ["min12xxw"]},
    "printer-driver-oki": {"label": "OKI 打印机", "vendors": ["OKI"], "protocols": ["OKI raster"]},
    "printer-driver-pnm2ppa": {"label": "HP PPA/GDI 旧型号", "vendors": ["HP"], "protocols": ["PPA"]},
    "printer-driver-postscript-hp": {"label": "HP PostScript PPD", "vendors": ["HP"], "protocols": ["PostScript"]},
    "printer-driver-ptouch": {"label": "Brother PT/QL 标签打印机", "vendors": ["Brother"], "protocols": ["Brother label raster"]},
    "printer-driver-pxljr": {"label": "HP Color LaserJet PCL XL", "vendors": ["HP"], "protocols": ["PCL XL"]},
    "printer-driver-sag-gdi": {"label": "Ricoh/Sagem GDI", "vendors": ["Ricoh", "Sagem"], "protocols": ["SAG-GDI"]},
    "printer-driver-splix": {"label": "Samsung/Xerox SPL", "vendors": ["Samsung", "Xerox"], "protocols": ["SPL2", "SPLc", "QPDL"]},
}

BASE_PACKAGES = frozenset(
    {
        "printer-driver-brlaser",
        "printer-driver-foo2zjs",
        "printer-driver-hpcups",
        "printer-driver-pxljr",
        "openprinting-ppds",
        "foomatic-db-compressed-ppds",
    }
)

GENERIC_MODELS: tuple[dict[str, Any], ...] = (
    {
        "model_id": "generic-ipp-everywhere",
        "manufacturer": "通用",
        "model": "IPP Everywhere（免驱）",
        "cups_model": "everywhere",
        "package_name": "",
        "protocols": ["IPP Everywhere"],
        "source": "generic",
        "verification": "generic",
    },
    {
        "model_id": "generic-postscript",
        "manufacturer": "通用",
        "model": "通用 PostScript",
        "cups_model": "drv:///sample.drv/generic.ppd",
        "package_name": "",
        "protocols": ["PostScript"],
        "source": "generic",
        "verification": "generic",
    },
    {
        "model_id": "generic-pcl5",
        "manufacturer": "通用",
        "model": "通用 PCL 5/5e",
        "cups_model": "drv:///sample.drv/generpcl.ppd",
        "package_name": "",
        "protocols": ["PCL 5", "PCL 5e"],
        "source": "generic",
        "verification": "generic",
    },
    {
        "model_id": "generic-pcl6",
        "manufacturer": "通用",
        "model": "通用 PCL 6/PCL XL",
        "cups_model": "foomatic-db-compressed-ppds:0/ppd/foomatic-ppd/Generic-PCL_6_PCL_XL_Printer-pxlmono.ppd",
        "package_name": "printer-driver-pxljr",
        "protocols": ["PCL 6", "PCL XL"],
        "source": "generic",
        "verification": "generic",
    },
)

KNOWN_MODEL_ALIASES: tuple[dict[str, Any], ...] = (
    {
        "model_id": "alias-brother-hl1218w",
        "manufacturer": "Brother",
        "model": "Brother HL-1218W",
        "aliases": ["HL-1218W", "HL-1200 series"],
        "cups_model": "drv:///brlaser.drv/br1200.ppd",
        "package_name": "printer-driver-brlaser",
        "protocols": ["Brother raster"],
        "source": "alias",
        "verification": "repository",
    },
    {
        "model_id": "alias-hp-laserjet-pro-400-m401",
        "manufacturer": "HP",
        "model": "HP LaserJet Pro 400 M401",
        "aliases": ["LaserJet Pro 400 M401", "M401", "PCL 6", "PCL XL"],
        "cups_model": "foomatic-db-compressed-ppds:0/ppd/foomatic-ppd/Generic-PCL_6_PCL_XL_Printer-pxlmono.ppd",
        "package_name": "printer-driver-pxljr",
        "protocols": ["PCL 6", "PCL XL"],
        "source": "alias",
        "verification": "repository",
    },
)

KNOWN_VENDORS = (
    "Konica Minolta",
    "Fuji Xerox",
    "Index Braille",
    "Hewlett-Packard",
    "Texas Instruments",
    "Brother",
    "Canon",
    "Epson",
    "Fujifilm",
    "Kyocera",
    "Panasonic",
    "Lexmark",
    "Samsung",
    "Toshiba",
    "Gestetner",
    "Imagistics",
    "InfoPrint",
    "Intellitech",
    "Mitsubishi",
    "Tektronix",
    "Heidelberg",
    "Fujitsu",
    "Genicom",
    "Hitachi",
    "Infotec",
    "Lanier",
    "Olivetti",
    "Minolta",
    "Ricoh",
    "Sagem",
    "Savin",
    "Seiko",
    "Sharp",
    "Citizen",
    "Compaq",
    "Apollo",
    "Apple",
    "Dell",
    "DYMO",
    "HP",
    "IBM",
    "Kodak",
    "NEC",
    "NRG",
    "OKI",
    "Oce",
    "QMS",
    "SiPix",
    "Star",
    "Tally",
    "UTAX",
    "Xante",
    "Xerox",
    "Zebra",
    "Generic",
    "IPP",
    "Raw",
)


def _stable_id(*values: str) -> str:
    digest = hashlib.sha256("\0".join(values).encode("utf-8", errors="replace")).hexdigest()
    return f"model-{digest[:24]}"


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def _manufacturer(label: str) -> str:
    lowered = label.lower()
    for vendor in KNOWN_VENDORS:
        if vendor.lower() in lowered:
            if vendor in {"Generic", "IPP", "Raw"}:
                return "通用"
            return "HP" if vendor == "Hewlett-Packard" else vendor
    first = re.split(r"[\s,/]+", label.strip(), maxsplit=1)[0]
    if not first or re.search(r"\d", first) or first.lower().endswith((".ppd", ".drv")):
        return "其他"
    return first[:64]


def _protocols(model: str, label: str) -> list[str]:
    text = f"{model} {label}".lower()
    found: list[str] = []
    for marker, protocol in (
        ("postscript", "PostScript"),
        ("pcl xl", "PCL XL"),
        ("pcl 6", "PCL 6"),
        ("pcl6", "PCL 6"),
        ("pcl 5", "PCL 5"),
        ("pcl5", "PCL 5"),
        ("zjs", "ZjStream"),
        ("foo2zjs", "ZjStream"),
        ("spl", "SPL/QPDL"),
        ("escpr", "ESC/P-R"),
        ("gutenprint", "Gutenprint raster"),
        ("brlaser", "Brother raster"),
    ):
        if marker in text and protocol not in found:
            found.append(protocol)
    return found or ["型号驱动"]


def _package_for_model(model: str, label: str) -> str:
    text = f"{model} {label}".lower()
    rules = (
        (("brlaser", "br1200"), "printer-driver-brlaser"),
        (("escpr", "epson-escpr"), "printer-driver-escpr"),
        (("gutenprint",), "printer-driver-gutenprint"),
        (("hpcups",), "printer-driver-hpcups"),
        (("hpijs",), "printer-driver-hpijs"),
        (("foo2zjs", "foo2xqx", "foo2qpdl", "foo2hiperc", "foo2lava", "foo2oak", "foo2slx"), "printer-driver-foo2zjs"),
        (("splix",), "printer-driver-splix"),
        (("ptouch",), "printer-driver-ptouch"),
        (("pxljr", "pxlmono", "pxlcolor"), "printer-driver-pxljr"),
        (("c2esp",), "printer-driver-c2esp"),
        (("cjet",), "printer-driver-cjet"),
        (("dymo",), "printer-driver-dymo"),
        (("fujixerox",), "printer-driver-fujixerox"),
        (("m2300w",), "printer-driver-m2300w"),
        (("min12xxw",), "printer-driver-min12xxw"),
        (("pnm2ppa",), "printer-driver-pnm2ppa"),
        (("sag-gdi",), "printer-driver-sag-gdi"),
        (("indexbraille",), "printer-driver-indexbraille"),
    )
    for markers, package in rules:
        if any(marker in text for marker in markers):
            return package
    return ""


def _human_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / 1024 / 1024:.1f} MB"


class DriverCatalogManager:
    def __init__(
        self,
        root: str | Path = "/var/lib/gadget-msc-printer/driver-catalog",
        model_provider: ModelProvider | None = None,
        command_runner: CommandRunner | None = None,
        public_key: str | Path = "/etc/gadget-msc-printer/driver-pack-public.pem",
        bundled_catalog: str | Path = "/opt/gadget-msc-printer/assets/driver-catalog-noble-arm64.json",
        model_cache_invalidator: CacheInvalidator | None = None,
    ) -> None:
        self.root = Path(root)
        self.db_path = self.root / "catalog.sqlite3"
        self.staging_dir = self.root / "staging"
        self.offline_dir = self.root / "offline"
        self.model_provider = model_provider or (lambda: [])
        self.command_runner = command_runner or self._default_runner
        self.public_key = Path(public_key)
        self.bundled_catalog = Path(bundled_catalog)
        self.model_cache_invalidator = model_cache_invalidator
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._seed_if_empty()

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

    def _run(self, command: list[str], timeout: int = 60) -> str:
        try:
            result = self.command_runner(command, timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            raise DriverCatalogError(f"{command[0]} 执行失败：{exc}") from exc
        if result.returncode != 0:
            detail = str(result.stderr or result.stdout or f"{command[0]} failed").strip()
            raise DriverCatalogError(detail[-8000:])
        return str(result.stdout or "").strip()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS models (
                    model_id TEXT PRIMARY KEY,
                    manufacturer TEXT NOT NULL,
                    model TEXT NOT NULL,
                    aliases TEXT NOT NULL,
                    cups_model TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    protocols TEXT NOT NULL,
                    source TEXT NOT NULL,
                    architecture TEXT NOT NULL,
                    verification TEXT NOT NULL,
                    installed INTEGER NOT NULL,
                    available INTEGER NOT NULL,
                    candidate_version TEXT NOT NULL,
                    match_text TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS models_search_idx ON models(manufacturer, model);
                CREATE INDEX IF NOT EXISTS models_package_idx ON models(package_name);
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    package_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS validations (
                    model_id TEXT PRIMARY KEY,
                    result TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    tested_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS offline_packs (
                    pack_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    path TEXT NOT NULL,
                    packages TEXT NOT NULL,
                    installed_at INTEGER NOT NULL
                );
                """
            )
            connection.execute(
                "UPDATE jobs SET state='failed', summary='服务重启，安装状态需要人工确认', updated_at=? "
                "WHERE state NOT IN ('completed', 'failed')",
                (int(time.time()),),
            )

    def _seed_if_empty(self) -> None:
        with self._connect() as connection:
            count = int(connection.execute("SELECT COUNT(*) FROM models").fetchone()[0])
            if count:
                return
            now = int(time.time())
            for item in GENERIC_MODELS:
                self._insert_model(connection, item, installed=True, available=True, candidate_version="")
            for package, metadata in PACKAGE_CATALOG.items():
                item = {
                    "model_id": f"package-{package}",
                    "manufacturer": metadata["vendors"][0],
                    "model": metadata["label"] + "（安装后展开型号）",
                    "aliases": f"{metadata['label']} {' '.join(metadata['vendors'])}",
                    "cups_model": "",
                    "package_name": package,
                    "protocols": metadata["protocols"],
                    "source": "package",
                    "architecture": "arm64/all",
                    "verification": "repository",
                }
                self._insert_model(connection, item, installed=False, available=False, candidate_version="")
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema', ?)",
                (str(CATALOG_SCHEMA),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('seeded_at', ?)",
                (str(now),),
            )

    @staticmethod
    def _insert_model(
        connection: sqlite3.Connection,
        item: dict[str, Any],
        installed: bool,
        available: bool,
        candidate_version: str,
    ) -> None:
        aliases = item.get("aliases") or ""
        if isinstance(aliases, list):
            aliases = " ".join(str(value) for value in aliases)
        protocols = item.get("protocols") or []
        if not isinstance(protocols, list):
            protocols = [str(protocols)]
        manufacturer = str(item.get("manufacturer", "其他"))[:128]
        model = str(item.get("model", "未知型号"))[:512]
        match_text = _normalize(f"{manufacturer} {model} {aliases} {' '.join(protocols)}")
        connection.execute(
            """
            INSERT OR REPLACE INTO models(
                model_id, manufacturer, model, aliases, cups_model,
                package_name, protocols, source, architecture, verification,
                installed, available, candidate_version, match_text, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(item["model_id"]), manufacturer, model, str(aliases),
                str(item.get("cups_model", "")), str(item.get("package_name", "")),
                json.dumps(protocols, ensure_ascii=False), str(item.get("source", "cups")),
                str(item.get("architecture", "arm64/all")), str(item.get("verification", "repository")),
                1 if installed else 0, 1 if available else 0, candidate_version,
                match_text, int(time.time()),
            ),
        )

    def _package_state(self, package: str) -> dict[str, Any]:
        if package not in PACKAGE_CATALOG and package not in BASE_PACKAGES:
            return {"installed": False, "version": "", "candidate": "", "available": False}
        installed = ""
        result = self.command_runner(
            ["dpkg-query", "-W", "-f=${db:Status-Status}\t${Version}", package], 15
        )
        if result.returncode == 0:
            fields = str(result.stdout or "").strip().split("\t", 1)
            if fields and fields[0] == "installed":
                installed = fields[1] if len(fields) > 1 else "installed"
        candidate = ""
        result = self.command_runner(["apt-cache", "policy", package], 20)
        if result.returncode == 0:
            match = re.search(r"^\s*Candidate:\s*(\S+)", str(result.stdout or ""), re.MULTILINE)
            if match and match.group(1) != "(none)":
                candidate = match.group(1)
        return {
            "installed": bool(installed),
            "version": installed,
            "candidate": candidate,
            "available": bool(installed or candidate),
        }

    def _maybe_update_sources(self, force: bool) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key='apt_updated_at'").fetchone()
        previous = int(row[0]) if row and str(row[0]).isdigit() else 0
        if not force and time.time() - previous < 24 * 3600:
            return False
        self._run(["apt-get", *APT_LOCK_OPTIONS, "update"], 600)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('apt_updated_at', ?)",
                (str(int(time.time())),),
            )
        return True

    @staticmethod
    def _catalog_models(path: Path, source: str) -> list[dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        supplied = data.get("models", []) if isinstance(data, dict) else []
        if not isinstance(supplied, list) or len(supplied) > 100000:
            return []
        models: list[dict[str, Any]] = []
        for item in supplied:
            if not isinstance(item, dict):
                continue
            package = str(item.get("package_name", ""))
            cups_model = str(item.get("cups_model", ""))
            if package not in PACKAGE_CATALOG or not cups_model:
                continue
            models.append(
                {
                    "model_id": str(item.get("model_id") or _stable_id(package, cups_model, str(item.get("model", "")))),
                    "manufacturer": str(item.get("manufacturer", "其他")),
                    "model": str(item.get("model", "未知型号")),
                    "aliases": item.get("aliases", ""),
                    "cups_model": cups_model,
                    "package_name": package,
                    "protocols": item.get("protocols", ["型号驱动"]),
                    "source": source,
                    "architecture": "arm64/all",
                    "verification": str(item.get("verification", "repository")),
                }
            )
        return models

    def _offline_catalog_models(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            paths = [Path(row[0]) / "catalog.json" for row in connection.execute(
                "SELECT path FROM offline_packs ORDER BY installed_at"
            )]
        models: list[dict[str, Any]] = []
        for path in paths:
            models.extend(self._catalog_models(path, "offline"))
        return models

    def refresh(self, update_sources: bool = False) -> dict[str, Any]:
        if update_sources:
            self._maybe_update_sources(True)
        package_states = {package: self._package_state(package) for package in PACKAGE_CATALOG}
        try:
            supplied = self.model_provider()
        except Exception as exc:
            raise DriverCatalogError(f"读取CUPS型号失败：{exc}") from exc
        rows: dict[str, tuple[dict[str, Any], bool, bool, str]] = {}
        for generic in GENERIC_MODELS:
            package = str(generic.get("package_name", ""))
            state = package_states.get(package, {"installed": True, "available": True, "candidate": ""})
            rows[str(generic["model_id"])] = (
                generic,
                bool(state["installed"] or not package),
                bool(state["available"] or not package),
                str(state["candidate"]),
            )
        for item in KNOWN_MODEL_ALIASES:
            package = str(item["package_name"])
            state = package_states[package]
            rows[str(item["model_id"])] = (
                item,
                bool(state["installed"]),
                bool(state["available"]),
                str(state["candidate"]),
            )
        for item in self._catalog_models(self.bundled_catalog, "bundled"):
            package = str(item["package_name"])
            state = package_states[package]
            rows[str(item["model_id"])] = (
                item,
                bool(state["installed"]),
                bool(state["available"]),
                str(state["candidate"]),
            )
        for raw in supplied:
            cups_model = str(raw.get("model", "")).strip()
            label = str(raw.get("label", cups_model)).strip()
            if not cups_model or not label:
                continue
            package = _package_for_model(cups_model, label)
            state = package_states.get(package, {"installed": True, "available": True, "candidate": ""})
            item = {
                "model_id": _stable_id(package, cups_model, label),
                "manufacturer": _manufacturer(f"{label} {cups_model}"),
                "model": re.split(r"\s+(?:Foomatic/|using\s)", label, maxsplit=1, flags=re.IGNORECASE)[0].strip(),
                "aliases": label,
                "cups_model": cups_model,
                "package_name": package,
                "protocols": _protocols(cups_model, label),
                "source": "cups",
                "architecture": "arm64/all",
                "verification": "repository",
            }
            rows[item["model_id"]] = (
                item,
                bool(state["installed"] if package else True),
                bool(state["available"] if package else True),
                str(state["candidate"]),
            )
        offline_packages: set[str] = set()
        with self._connect() as connection:
            for row in connection.execute("SELECT packages FROM offline_packs"):
                offline_packages.update(json.loads(row[0]))
        for item in self._offline_catalog_models():
            package = str(item["package_name"])
            state = package_states[package]
            rows[str(item["model_id"])] = (
                item,
                bool(state["installed"]),
                bool(state["available"] or package in offline_packages),
                str(state["candidate"]),
            )
        for package, metadata in PACKAGE_CATALOG.items():
            if any(value[0].get("package_name") == package for value in rows.values()):
                continue
            state = package_states[package]
            item = {
                "model_id": f"package-{package}",
                "manufacturer": metadata["vendors"][0],
                "model": metadata["label"] + "（安装后展开型号）",
                "aliases": f"{metadata['label']} {' '.join(metadata['vendors'])}",
                "cups_model": "",
                "package_name": package,
                "protocols": metadata["protocols"],
                "source": "package",
                "architecture": "arm64/all",
                "verification": "repository",
            }
            rows[item["model_id"]] = (
                item, bool(state["installed"]), bool(state["available"]), str(state["candidate"])
            )
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM models")
            for item, installed, available, candidate in rows.values():
                self._insert_model(connection, item, installed, available, candidate)
            connection.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('catalog_updated_at', ?)",
                (str(int(time.time())),),
            )
        return self.summary()

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            counts = connection.execute(
                "SELECT COUNT(*) total, SUM(installed) installed, SUM(available) available FROM models"
            ).fetchone()
            vendors = [row[0] for row in connection.execute(
                "SELECT DISTINCT manufacturer FROM models WHERE manufacturer <> '' ORDER BY manufacturer"
            )]
            packages = [
                {
                    "package_name": row["package_name"],
                    "installed": bool(row["installed"]),
                    "available": bool(row["available"]),
                    "candidate_version": row["candidate_version"],
                    "model_count": int(row["model_count"]),
                    "label": str(PACKAGE_CATALOG.get(row["package_name"], {}).get("label", row["package_name"])),
                }
                for row in connection.execute(
                    """
                    SELECT package_name, MAX(installed) installed, MAX(available) available,
                           MAX(candidate_version) candidate_version, COUNT(*) model_count
                    FROM models WHERE package_name <> '' GROUP BY package_name ORDER BY package_name
                    """
                )
            ]
            meta = {row[0]: row[1] for row in connection.execute("SELECT key, value FROM meta")}
            offline = connection.execute(
                "SELECT pack_id, version, installed_at FROM offline_packs ORDER BY installed_at DESC LIMIT 1"
            ).fetchone()
        return {
            "schema": CATALOG_SCHEMA,
            "total": int(counts["total"] or 0),
            "installed": int(counts["installed"] or 0),
            "available": int(counts["available"] or 0),
            "vendors": vendors,
            "packages": packages,
            "updated_at": int(meta.get("catalog_updated_at", meta.get("seeded_at", "0")) or 0),
            "apt_updated_at": int(meta.get("apt_updated_at", "0") or 0),
            "offline_pack": dict(offline) if offline else None,
            "platform": {"os": "ubuntu", "version": "24.04", "arch": "arm64"},
        }

    @staticmethod
    def _public_row(row: sqlite3.Row, validation: sqlite3.Row | None = None) -> dict[str, Any]:
        verification = str(row["verification"])
        validation_result = str(validation["result"]) if validation else ""
        if validation_result == "passed":
            verification = "verified"
        return {
            "model_id": row["model_id"],
            "manufacturer": row["manufacturer"],
            "model": row["model"],
            "cups_model": row["cups_model"],
            "package_name": row["package_name"],
            "protocols": json.loads(row["protocols"]),
            "source": row["source"],
            "architecture": row["architecture"],
            "verification": verification,
            "installed": bool(row["installed"]),
            "available": bool(row["available"]),
            "candidate_version": row["candidate_version"],
            "validation": {
                "result": validation_result,
                "notes": str(validation["notes"]) if validation else "",
                "tested_at": int(validation["tested_at"]) if validation else 0,
            },
        }

    def search(
        self,
        query: str = "",
        vendor: str = "",
        status: str = "",
        page: int = 1,
        page_size: int = 30,
    ) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(100, int(page_size)))
        conditions: list[str] = []
        values: list[Any] = []
        normalized = _normalize(query)[:256]
        for token in normalized.split():
            conditions.append("m.match_text LIKE ?")
            values.append(f"%{token}%")
        if vendor:
            conditions.append("m.manufacturer = ?")
            values.append(vendor[:128])
        if status == "installed":
            conditions.append("m.installed = 1")
        elif status == "available":
            conditions.append("m.available = 1")
        elif status == "unavailable":
            conditions.append("m.available = 0")
        elif status == "verified":
            conditions.append("v.result = 'passed'")
        elif status == "generic":
            conditions.append("m.verification = 'generic'")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        join = " LEFT JOIN validations v ON v.model_id = m.model_id"
        with self._connect() as connection:
            total = int(connection.execute(f"SELECT COUNT(*) FROM models m{join}{where}", values).fetchone()[0])
            rows = connection.execute(
                f"""
                SELECT m.*, v.result validation_result, v.notes validation_notes, v.tested_at validation_tested_at
                FROM models m{join}{where}
                ORDER BY
                    CASE WHEN v.result='passed' THEN 0 WHEN m.verification='generic' THEN 1
                         WHEN m.installed=1 THEN 2 WHEN m.available=1 THEN 3 ELSE 4 END,
                    m.manufacturer, m.model
                LIMIT ? OFFSET ?
                """,
                [*values, page_size, (page - 1) * page_size],
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            validation = None
            if row["validation_result"] is not None:
                validation = {
                    "result": row["validation_result"],
                    "notes": row["validation_notes"],
                    "tested_at": row["validation_tested_at"],
                }
            item = self._public_row(row)
            if validation:
                item["verification"] = "verified" if validation["result"] == "passed" else item["verification"]
                item["validation"] = validation
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size, "summary": self.summary()}

    def get_model(self, model_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,127}", model_id):
            raise DriverCatalogError("型号编号无效")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM models WHERE model_id=?", (model_id,)).fetchone()
        if row is None:
            raise DriverCatalogError("没有找到该驱动型号")
        return self._public_row(row)

    def recommendations(self, devices: list[dict[str, Any]], limit: int = 3) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for device in devices:
            uri = str(device.get("uri", ""))
            label = str(device.get("label", ""))
            if uri.startswith(("ipp://", "ipps://")):
                result[uri] = [self.get_model("generic-ipp-everywhere")]
                continue
            normalized = _normalize(label)
            tokens = [token for token in normalized.split() if len(token) >= 2 and token not in {"usb", "printer", "series"}]
            candidates = self.search(query=" ".join(tokens[:6]), page_size=50)["items"] if tokens else []
            scored: list[tuple[int, dict[str, Any]]] = []
            for candidate in candidates:
                target = _normalize(f"{candidate['manufacturer']} {candidate['model']}")
                overlap = sum(1 for token in tokens if token in target)
                score = overlap * 10
                if target and target in normalized:
                    score += 80
                elif normalized and normalized in target:
                    score += 60
                if candidate["verification"] == "verified":
                    score += 20
                if candidate["installed"]:
                    score += 5
                if score:
                    scored.append((score, candidate))
            scored.sort(key=lambda value: (-value[0], value[1]["model"]))
            result[uri] = [{**item, "match_score": score} for score, item in scored[:limit]]
        return result

    @staticmethod
    def _parse_plan_output(output: str) -> tuple[int, int, list[str]]:
        download_bytes = sum(
            int(match.group(1))
            for match in re.finditer(r"^'[^']+'\s+\S+\s+(\d+)(?:\s|$)", output, re.MULTILINE)
        )
        install_bytes = 0
        match = re.search(r"After this operation,\s+([0-9.]+)\s*([kMGT]?B)\s+of additional disk space", output)
        if match:
            factors = {"B": 1, "kB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4}
            install_bytes = int(float(match.group(1)) * factors.get(match.group(2), 1))
        packages: list[str] = []
        block = re.search(r"The following (?:NEW )?packages will be installed:\s*(.+?)(?:\n\d+ upgraded|\nSuggested packages:|\nRecommended packages:)", output, re.DOTALL)
        if block:
            packages = [value for value in re.findall(r"[a-z0-9][a-z0-9+.-]+", block.group(1))]
        return download_bytes, install_bytes, packages

    def _offline_pack_for(self, package: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM offline_packs ORDER BY installed_at DESC").fetchall()
        for row in rows:
            if package in json.loads(row["packages"]):
                return dict(row)
        return None

    @staticmethod
    def _local_apt_options(path: str) -> list[str]:
        source = str(Path(path) / "jvlei-driver-pack.list")
        return [
            "-o", f"Dir::Etc::sourcelist={source}",
            "-o", "Dir::Etc::sourceparts=-",
            "-o", "APT::Get::List-Cleanup=0",
        ]

    def plan(self, model_id: str) -> dict[str, Any]:
        model = self.get_model(model_id)
        package = str(model["package_name"])
        if model["installed"] and model["cups_model"]:
            return {
                "model": model, "required": False, "package_name": package,
                "candidate_version": model["candidate_version"], "dependencies": [],
                "download_bytes": 0, "install_bytes": 0,
                "free_bytes": shutil.disk_usage(self.root).free, "source": "installed",
            }
        if package not in PACKAGE_CATALOG:
            raise DriverCatalogError("该型号没有可按需安装的软件源驱动")
        offline = self._offline_pack_for(package)
        if offline is None:
            self._maybe_update_sources(False)
        apt_options = self._local_apt_options(str(offline["path"])) if offline else []
        output = self._run(
            ["apt-get", *APT_LOCK_OPTIONS, *apt_options, "--print-uris", "--yes", "--no-install-recommends", "install", "--", package],
            120,
        )
        download_bytes, install_bytes, dependencies = self._parse_plan_output(output)
        free_bytes = shutil.disk_usage(self.root).free
        required_free = max(128 * 1024 * 1024, download_bytes * 2 + install_bytes)
        if free_bytes < required_free:
            raise DriverCatalogError(
                f"磁盘空间不足：至少需要 {_human_bytes(required_free)}，当前可用 {_human_bytes(free_bytes)}"
            )
        state = self._package_state(package)
        return {
            "model": model,
            "required": not state["installed"],
            "package_name": package,
            "candidate_version": state["candidate"],
            "dependencies": dependencies,
            "download_bytes": download_bytes,
            "install_bytes": install_bytes,
            "free_bytes": free_bytes,
            "source": "offline" if offline else "online",
        }

    def _set_job(self, job_id: str, state: str, summary: str, detail: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET state=?, summary=?, detail=?, updated_at=? WHERE job_id=?",
                (state, summary[:512], detail[-16000:], int(time.time()), job_id),
            )

    def install_async(self, model_id: str) -> dict[str, Any]:
        model = self.get_model(model_id)
        package = str(model["package_name"])
        if package and package not in PACKAGE_CATALOG:
            raise DriverCatalogError("软件包不在驱动白名单中")
        with self._connect() as connection:
            active = connection.execute(
                "SELECT job_id FROM jobs WHERE state NOT IN ('completed','failed') ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if active:
                raise DriverCatalogError(f"已有驱动安装任务正在运行：{active['job_id']}")
            job_id = uuid.uuid4().hex
            now = int(time.time())
            connection.execute(
                "INSERT INTO jobs(job_id, model_id, package_name, state, summary, detail, created_at, updated_at) "
                "VALUES(?, ?, ?, 'queued', '等待安装', '', ?, ?)",
                (job_id, model_id, package, now, now),
            )
        thread = threading.Thread(target=self._install_worker, args=(job_id, model_id), daemon=True)
        self._threads[job_id] = thread
        thread.start()
        return self.job(job_id)

    def _install_worker(self, job_id: str, model_id: str) -> None:
        try:
            self._set_job(job_id, "resolving", "正在解析软件包和依赖")
            plan = self.plan(model_id)
            package = str(plan["package_name"])
            if plan["required"]:
                self._set_job(job_id, "downloading", "正在下载驱动软件包")
                offline = self._offline_pack_for(package)
                options = self._local_apt_options(str(offline["path"])) if offline else []
                self._set_job(job_id, "installing", "正在安装驱动")
                output = self._run(
                    ["apt-get", *APT_LOCK_OPTIONS, *options, "install", "-y", "--no-install-recommends", "--", package],
                    900,
                )
            else:
                output = "driver package is already installed"
            self._set_job(job_id, "indexing", "正在刷新CUPS型号")
            self._run(["systemctl", "restart", "cups.service"], 90)
            if self.model_cache_invalidator is not None:
                self.model_cache_invalidator()
            self.refresh(False)
            try:
                model = self.get_model(model_id)
            except DriverCatalogError:
                model = None
            if model is not None and model["cups_model"] and not model["installed"]:
                raise DriverCatalogError("驱动已安装，但CUPS没有发现目标型号")
            if model is None:
                with self._connect() as connection:
                    installed_count = int(connection.execute(
                        "SELECT COUNT(*) FROM models WHERE package_name=? AND installed=1",
                        (package,),
                    ).fetchone()[0])
                if not installed_count:
                    raise DriverCatalogError("驱动包已安装，但CUPS没有发现该驱动提供的型号")
            self._set_job(job_id, "completed", "驱动安装完成，可以创建打印队列", output)
        except Exception as exc:
            LOGGER.exception("driver install job %s failed", job_id)
            self._set_job(job_id, "failed", "驱动安装失败", str(exc))

    def job(self, job_id: str) -> dict[str, Any]:
        if re.fullmatch(r"[a-f0-9]{32}", job_id) is None:
            raise DriverCatalogError("任务编号无效")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None:
            raise DriverCatalogError("没有找到驱动安装任务")
        return dict(row)

    def recent_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(100, limit)),)
            )]

    def validate(self, model_id: str, result: str, notes: str = "") -> dict[str, Any]:
        self.get_model(model_id)
        if result not in {"passed", "failed"}:
            raise DriverCatalogError("验证结果必须是passed或failed")
        if len(notes) > 2000:
            raise DriverCatalogError("验证备注不能超过2000个字符")
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO validations(model_id, result, notes, tested_at) VALUES(?, ?, ?, ?)",
                (model_id, result, notes, now),
            )
        return {"model_id": model_id, "result": result, "notes": notes, "tested_at": now}

    def stage_offline(self, filename: str, source_path: str | Path) -> dict[str, Any]:
        source = Path(source_path)
        if not source.is_file() or source.stat().st_size < 1:
            raise DriverCatalogError("离线驱动包不存在")
        if source.stat().st_size > MAX_OFFLINE_PACK_BYTES:
            raise DriverCatalogError("离线驱动包超过512 MB限制")
        if not filename.lower().endswith(".jvdrv"):
            raise DriverCatalogError("离线驱动包扩展名必须是.jvdrv")
        upload_id = uuid.uuid4().hex
        folder = self.staging_dir / upload_id
        folder.mkdir(parents=True, exist_ok=False)
        target = folder / "source.jvdrv"
        try:
            shutil.copy2(source, target)
            analysis = self._inspect_offline(target)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        metadata = {
            "id": upload_id,
            "filename": Path(filename).name,
            "path": str(target),
            "analysis": analysis,
            "created_at": int(time.time()),
        }
        (folder / "meta.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    def _inspect_offline(self, path: Path) -> dict[str, Any]:
        try:
            info = verify_package(path, self.public_key, allow_unsigned=False, work_root=self.staging_dir)
        except PackageError as exc:
            raise DriverCatalogError(f"离线驱动包校验失败：{exc}") from exc
        try:
            manifest = dict(info.manifest)
            if manifest.get("package_type") != "printer_driver" or manifest.get("product") != DRIVER_PACK_PRODUCT:
                raise DriverCatalogError("不是JVLEI Noble ARM64实体打印驱动包")
            if str(manifest.get("arch")) not in {"arm64", "aarch64"}:
                raise DriverCatalogError("离线驱动包架构不匹配")
            if manifest.get("os_id") != "ubuntu" or str(manifest.get("os_version")) != "24.04":
                raise DriverCatalogError("离线驱动包仅适用于Ubuntu Noble 24.04")
            with tempfile.TemporaryDirectory(prefix="driver-pack-inspect-", dir=str(self.staging_dir)) as temp_name:
                extracted = Path(temp_name)
                safe_extract_payload(info.payload_path, extracted, MAX_OFFLINE_PACK_BYTES)
                catalog_path = extracted / "catalog.json"
                packages_path = extracted / "repo" / "Packages.gz"
                pool = extracted / "repo" / "pool"
                if not catalog_path.is_file() or not packages_path.is_file() or not pool.is_dir():
                    raise DriverCatalogError("离线驱动包缺少catalog.json、Packages.gz或pool目录")
                try:
                    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                    gzip.open(packages_path, "rb").read(1024)
                except (OSError, json.JSONDecodeError) as exc:
                    raise DriverCatalogError(f"离线驱动索引损坏：{exc}") from exc
                package_names: list[str] = []
                for deb in sorted(pool.glob("*.deb")):
                    fields = self._run(["dpkg-deb", "-f", str(deb), "Package", "Architecture"], 30).splitlines()
                    if len(fields) < 2 or fields[0] not in PACKAGE_CATALOG and fields[0] not in set(manifest.get("dependencies", [])):
                        raise DriverCatalogError(f"离线包包含未授权软件包：{fields[0] if fields else deb.name}")
                    if fields[1] not in {"arm64", "all"}:
                        raise DriverCatalogError(f"离线包包含不兼容架构：{fields[1]}")
                    package_names.append(fields[0])
            return {
                "version": str(manifest.get("version", "")),
                "catalog_version": str(manifest.get("catalog_version", "")),
                "package_count": len(package_names),
                "packages": sorted(set(package_names)),
                "model_count": int(catalog.get("total", len(catalog.get("models", [])))) if isinstance(catalog, dict) else 0,
                "signed": info.signed,
                "size_bytes": path.stat().st_size,
            }
        finally:
            info.cleanup()

    def _staged_offline(self, upload_id: str) -> dict[str, Any]:
        if re.fullmatch(r"[a-f0-9]{32}", upload_id) is None:
            raise DriverCatalogError("离线包编号无效")
        path = self.staging_dir / upload_id / "meta.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DriverCatalogError("没有找到待安装的离线驱动包") from exc
        return data

    def install_offline(self, upload_id: str) -> dict[str, Any]:
        staged = self._staged_offline(upload_id)
        source = Path(staged["path"])
        analysis = self._inspect_offline(source)
        info = verify_package(source, self.public_key, allow_unsigned=False, work_root=self.staging_dir)
        version = re.sub(r"[^A-Za-z0-9._-]+", "-", analysis["version"])[:64]
        target = self.offline_dir / version
        temporary = self.offline_dir / f".{version}-{uuid.uuid4().hex}"
        try:
            temporary.mkdir(parents=True, exist_ok=False)
            safe_extract_payload(info.payload_path, temporary, MAX_OFFLINE_PACK_BYTES)
            source_list = temporary / "jvlei-driver-pack.list"
            source_list.write_text(f"deb [trusted=yes] file:{temporary / 'repo'} ./\n", encoding="utf-8")
            self.offline_dir.mkdir(parents=True, exist_ok=True)
            if target.exists():
                shutil.rmtree(target)
            os.replace(temporary, target)
            final_list = target / "jvlei-driver-pack.list"
            final_list.write_text(f"deb [trusted=yes] file:{target / 'repo'} ./\n", encoding="utf-8")
            self._run(["apt-get", *APT_LOCK_OPTIONS, *self._local_apt_options(str(target)), "update"], 300)
            digest = hashlib.sha256()
            with source.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            pack_id = digest.hexdigest()[:24]
            with self._connect() as connection:
                connection.execute("DELETE FROM offline_packs WHERE path=?", (str(target),))
                connection.execute(
                    "INSERT OR REPLACE INTO offline_packs(pack_id, version, path, packages, installed_at) VALUES(?, ?, ?, ?, ?)",
                    (pack_id, analysis["version"], str(target), json.dumps(analysis["packages"]), int(time.time())),
                )
            self.refresh(False)
            return {"pack_id": pack_id, "path": str(target), **analysis}
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        finally:
            info.cleanup()

    def export_catalog(self, destination: str | Path) -> Path:
        target = Path(destination)
        data = self.search(page=1, page_size=100)["summary"]
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM models ORDER BY manufacturer, model").fetchall()
        data["models"] = [self._public_row(row) for row in rows]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return target
