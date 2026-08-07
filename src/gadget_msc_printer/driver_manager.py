from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


class DriverError(RuntimeError):
    pass


MAX_DRIVER_BYTES = 512 * 1024 * 1024
SUPPORTED_SUFFIXES = {".deb", ".ppd", ".ppd.gz", ".zip", ".tar", ".tgz", ".tar.gz"}
MAINTAINER_SCRIPTS = ("preinst", "postinst", "prerm", "postrm")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(value: str, maximum: int = 64) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.lower()).strip(".-")
    return normalized[:maximum] or "driver"


def _read_ppd(path: Path) -> dict[str, Any]:
    try:
        raw = gzip.open(path, "rb").read() if path.suffix.lower() == ".gz" else path.read_bytes()
    except OSError as exc:
        raise DriverError(f"cannot read PPD: {exc}") from exc
    text = raw.decode("latin-1", errors="replace")
    fields: dict[str, str] = {}
    for key in ("Manufacturer", "ModelName", "NickName", "Product", "PCFileName"):
        match = re.search(rf'^\*{key}:\s*"?([^"\r\n]+)', text, re.MULTILINE)
        if match:
            fields[key] = match.group(1).strip()
    filters = re.findall(r'^\*cupsFilter2?\s*:\s*"?([^"\r\n]+)', text, re.MULTILINE)
    return {
        "manufacturer": fields.get("Manufacturer", ""),
        "model_name": fields.get("ModelName", ""),
        "nick_name": fields.get("NickName", ""),
        "product": fields.get("Product", ""),
        "pc_file_name": fields.get("PCFileName", ""),
        "filters": filters,
    }


def _elf_arch(data: bytes) -> str:
    if data[:4] != b"\x7fELF" or len(data) < 20:
        return ""
    machine = int.from_bytes(data[18:20], "little" if data[5:6] == b"\x01" else "big")
    return {183: "arm64", 40: "arm", 62: "amd64", 3: "i386"}.get(machine, f"elf-{machine}")


class DriverManager:
    def __init__(
        self,
        root: str | Path = "/var/lib/gadget-msc-printer/drivers",
        command_runner: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.staging_dir = self.root / "staging"
        self.installed_dir = self.root / "installed"
        self.backup_dir = self.root / "backups"
        self.registry_path = self.root / "registry.json"
        self.command_runner = command_runner or self._default_runner

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

    def _run(self, command: list[str], timeout: int = 60) -> str:
        result = self.command_runner(command, timeout)
        if result.returncode != 0:
            raise DriverError((result.stderr or result.stdout or "driver command failed").strip())
        return str(result.stdout or "").strip()

    def _read_registry(self) -> dict[str, Any]:
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        drivers = data.get("drivers")
        if not isinstance(drivers, list):
            drivers = []
        return {"schema": 1, "drivers": drivers}

    def _write_registry(self, registry: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".registry.", dir=str(self.root))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(registry, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o640)
            os.replace(temporary, self.registry_path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def profiles(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for item in self._read_registry()["drivers"]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model = str(item.get("model", ""))
            profiles.append(
                {
                    "value": f"custom:{item['id']}",
                    "label": str(item.get("label", item["id"])),
                    "description": str(item.get("description", "现场导入驱动")),
                    "model": model,
                    "available": bool(model and Path(model).is_file()),
                    "installed_label": str(item.get("version", "")),
                    "source_type": str(item.get("source_type", "")),
                }
            )
        return profiles

    def drivers(self) -> list[dict[str, Any]]:
        """Return reviewed driver records without exposing writable paths."""

        records: list[dict[str, Any]] = []
        for item in self._read_registry()["drivers"]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model = str(item.get("model", ""))
            records.append(
                {
                    "id": str(item["id"]),
                    "label": str(item.get("label", item["id"])),
                    "description": str(item.get("description", "")),
                    "version": str(item.get("version", "")),
                    "source_type": str(item.get("source_type", "")),
                    "available": bool(model and Path(model).is_file()),
                    "installed_at": int(item.get("installed_at", 0) or 0),
                    "backup_id": str(item.get("backup_id", "")),
                }
            )
        return sorted(records, key=lambda item: int(item["installed_at"]), reverse=True)

    def _stage_meta_path(self, upload_id: str) -> Path:
        if re.fullmatch(r"[a-f0-9]{32}", upload_id) is None:
            raise DriverError("invalid driver upload ID")
        return self.staging_dir / upload_id / "meta.json"

    def stage_upload(self, filename: str, source_path: str | Path) -> dict[str, Any]:
        source = Path(source_path)
        if not source.is_file():
            raise DriverError("driver upload does not exist")
        if source.stat().st_size > MAX_DRIVER_BYTES:
            raise DriverError("driver upload exceeds 512 MB")
        filename = Path(filename).name
        if not filename or len(filename.encode("utf-8")) > 255:
            raise DriverError("driver file name is invalid")
        lower_name = filename.lower()
        if not any(lower_name.endswith(suffix) for suffix in SUPPORTED_SUFFIXES):
            raise DriverError("supported driver files are DEB, PPD, PPD.GZ, ZIP, TAR, TGZ, and TAR.GZ")
        upload_id = uuid.uuid4().hex
        folder = self.staging_dir / upload_id
        folder.mkdir(parents=True, exist_ok=False)
        target = folder / "source" / filename
        target.parent.mkdir()
        shutil.copy2(source, target)
        analysis = self.analyze(target)
        metadata = {"id": upload_id, "filename": Path(filename).name, "path": str(target), "analysis": analysis, "created_at": int(time.time())}
        self._stage_meta_path(upload_id).write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    def staged(self, upload_id: str) -> dict[str, Any]:
        meta_path = self._stage_meta_path(upload_id)
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DriverError("driver upload was not found") from exc
        path = Path(str(data.get("path", "")))
        root = self.staging_dir.resolve()
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise DriverError("invalid staged driver path") from exc
        if not path.is_file():
            raise DriverError("staged driver file is missing")
        return data

    def analyze(self, source: str | Path) -> dict[str, Any]:
        path = Path(source)
        if not path.is_file():
            raise DriverError("driver file not found")
        size = path.stat().st_size
        if size < 1 or size > MAX_DRIVER_BYTES:
            raise DriverError("driver file size is invalid")
        suffix = path.suffix.lower()
        base = path.name.lower()
        common = {
            "filename": path.name,
            "size_bytes": size,
            "sha256": _sha256(path),
            "supported": False,
            "reasons": [],
            "warnings": [],
            "architectures": [],
            "ppds": [],
            "filters": [],
            "maintainer_scripts": [],
            "source_type": "unknown",
        }
        if base.endswith(".deb"):
            return self._analyze_deb(path, common)
        if base.endswith(".ppd") or base.endswith(".ppd.gz"):
            common.update(source_type="ppd", ppds=[{**_read_ppd(path), "name": path.name}])
            common["supported"] = True
            return common
        if base.endswith((".zip", ".tar", ".tgz", ".tar.gz")):
            return self._analyze_archive(path, common)
        if suffix in {".exe", ".inf", ".dll", ".rpm", ".run", ".sh"}:
            common["reasons"].append("Windows、RPM 或可执行安装脚本不能在 ARM64 Armbian 上直接使用")
            return common
        common["reasons"].append("无法识别的驱动格式")
        return common

    def _analyze_deb(self, path: Path, result: dict[str, Any]) -> dict[str, Any]:
        result["source_type"] = "deb"
        try:
            fields = self._run(["dpkg-deb", "-f", str(path), "Package", "Version", "Architecture", "Depends", "Description"], 30)
        except DriverError as exc:
            result["reasons"].append(f"DEB 元数据读取失败：{exc}")
            return result
        lines = fields.splitlines()
        package, version, architecture, depends, description = (lines + [""] * 5)[:5]
        result.update(package=package, version=version, architecture=architecture, depends=depends, description=description)
        result["architectures"] = [architecture]
        with tempfile.TemporaryDirectory(prefix="jvlei-deb-") as temp_name:
            control = Path(temp_name) / "control"
            try:
                self._run(["dpkg-deb", "-e", str(path), str(control)], 30)
                result["maintainer_scripts"] = [name for name in MAINTAINER_SCRIPTS if (control / name).is_file()]
                listing = self._run(["dpkg-deb", "-c", str(path)], 60)
            except DriverError as exc:
                result["reasons"].append(f"DEB 内容读取失败：{exc}")
                return result
        result["contains_ppd"] = "/ppd/" in listing.lower() or ".ppd" in listing.lower()
        if architecture not in {"all", "arm64"}:
            result["reasons"].append(f"DEB 架构 {architecture} 不能安装到 ARM64 板子")
            return result
        if result["maintainer_scripts"]:
            result["warnings"].append("此 DEB 包含 root 安装脚本，安装时需要二次确认")
        result["supported"] = True
        return result

    def _analyze_archive(self, path: Path, result: dict[str, Any]) -> dict[str, Any]:
        result["source_type"] = "archive"
        entries: list[tuple[str, bytes]] = []
        try:
            if path.name.lower().endswith(".zip"):
                with zipfile.ZipFile(path) as archive:
                    members = archive.infolist()
                    if len(members) > 10000:
                        result["reasons"].append("压缩包文件数量超过限制")
                        return result
                    total = sum(item.file_size for item in members if not item.is_dir())
                    if total > MAX_DRIVER_BYTES:
                        result["reasons"].append("压缩包解压后的总大小超过 512 MB 限制")
                        return result
                    for item in members:
                        mode = (item.external_attr >> 16) & 0o170000
                        if mode == 0o120000:
                            result["reasons"].append("压缩包包含不允许的符号链接")
                            return result
                        if item.is_dir() or item.file_size > 64 * 1024 * 1024:
                            continue
                        entries.append((item.filename, archive.read(item)))
            else:
                with tarfile.open(path, "r:*") as archive:
                    members = archive.getmembers()
                    if len(members) > 10000:
                        result["reasons"].append("压缩包文件数量超过限制")
                        return result
                    if any(item.issym() or item.islnk() or item.isdev() or item.isfifo() for item in members):
                        result["reasons"].append("压缩包包含不允许的链接或设备文件")
                        return result
                    total = sum(item.size for item in members if item.isfile())
                    if total > MAX_DRIVER_BYTES:
                        result["reasons"].append("压缩包解压后的总大小超过 512 MB 限制")
                        return result
                    for item in members:
                        if not item.isfile() or item.size > 64 * 1024 * 1024:
                            continue
                        stream = archive.extractfile(item)
                        if stream is not None:
                            entries.append((item.name, stream.read()))
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            result["reasons"].append(f"压缩包读取失败：{exc}")
            return result
        unsafe = [name for name, _ in entries if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts]
        if unsafe:
            result["reasons"].append("压缩包包含不安全路径")
            return result
        ppds: list[dict[str, Any]] = []
        architectures: set[str] = set()
        filters: list[str] = []
        for name, data in entries:
            lowered = name.lower()
            if lowered.endswith((".ppd", ".ppd.gz")):
                suffix = ".ppd.gz" if lowered.endswith(".ppd.gz") else ".ppd"
                temporary = self.root / f".analysis-{uuid.uuid4().hex}{suffix}"
                try:
                    temporary.parent.mkdir(parents=True, exist_ok=True)
                    temporary.write_bytes(data)
                    ppds.append({**_read_ppd(temporary), "name": name})
                finally:
                    temporary.unlink(missing_ok=True)
            arch = _elf_arch(data[:64])
            if arch:
                architectures.add(arch)
                filters.append(name)
        result.update(ppds=ppds, filters=filters, architectures=sorted(architectures))
        incompatible = sorted(value for value in architectures if value not in {"arm64", "arm"})
        if incompatible:
            result["reasons"].append("压缩包包含不兼容的二进制 Filter：" + ", ".join(incompatible))
            return result
        if not ppds:
            result["reasons"].append("压缩包中没有发现 PPD 文件")
            return result
        result["supported"] = True
        return result

    def _backup(self) -> dict[str, Any]:
        backup_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        target = self.backup_dir / backup_id
        target.mkdir(parents=True, exist_ok=False)
        cups = Path("/etc/cups")
        if cups.is_dir():
            shutil.copytree(cups, target / "cups", dirs_exist_ok=True)
        if self.registry_path.is_file():
            shutil.copy2(self.registry_path, target / "registry.json")
        return {"id": backup_id, "path": str(target), "created_at": int(time.time())}

    def _dependency_check(self, depends: str) -> list[str]:
        missing: list[str] = []
        for group in depends.split(","):
            alternatives = []
            for part in group.split("|"):
                package = re.split(r"\s|\(|:", part.strip(), maxsplit=1)[0]
                if package:
                    alternatives.append(package)
            if not alternatives:
                continue
            installed = False
            for package in alternatives:
                result = self.command_runner(["dpkg-query", "-W", "-f=${db:Status-Status}", package], 10)
                if result.returncode == 0 and str(result.stdout).strip() == "installed":
                    installed = True
                    break
            if not installed:
                missing.append(" | ".join(alternatives))
        return missing

    def _copy_deb_ppd(self, package: str, target: Path) -> Path | None:
        """Copy a DEB-provided PPD into the reviewed-driver directory.

        A package may put its PPD below /usr/share or another CUPS model path.
        Keep an owned copy so the selected custom profile remains explicit and
        independently auditable by the gateway registry.
        """

        listing = self._run(["dpkg-query", "-L", package], 30)
        candidates = sorted(
            (
                Path(item.strip())
                for item in listing.splitlines()
                if item.strip().lower().endswith((".ppd", ".ppd.gz"))
            ),
            key=lambda path: ("/share/ppd/" not in str(path).replace("\\", "/").lower(), str(path).lower()),
        )
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            return None
        destination = target / source.name
        shutil.copy2(source, destination)
        return destination

    def install(self, upload_id: str, confirm_scripts: bool = False) -> dict[str, Any]:
        staged = self.staged(upload_id)
        analysis = staged["analysis"]
        if not analysis.get("supported"):
            raise DriverError("此驱动不兼容，不能安装")
        scripts = analysis.get("maintainer_scripts") or []
        if scripts and not confirm_scripts:
            raise DriverError("该 DEB 包含 root 安装脚本，必须确认后才能安装")
        backup = self._backup()
        source = Path(staged["path"])
        driver_id = f"{_safe_name(Path(staged['filename']).stem)}-{analysis['sha256'][:10]}"
        target = self.installed_dir / driver_id
        target.mkdir(parents=True, exist_ok=False)
        model = ""
        source_type = str(analysis["source_type"])
        try:
            if source_type == "deb":
                missing = self._dependency_check(str(analysis.get("depends", "")))
                if missing:
                    raise DriverError("缺少 DEB 依赖：" + ", ".join(missing))
                self._run(["dpkg", "-i", str(source)], 180)
                package = str(analysis.get("package", ""))
                ppd = self._copy_deb_ppd(package, target) if package else None
                if ppd is not None:
                    model = str(ppd)
                    analysis["ppds"] = [{**_read_ppd(ppd), "name": ppd.name}]
                else:
                    analysis["warnings"] = list(analysis.get("warnings") or []) + [
                        "DEB 已安装，但没有发现可供 CUPS 选择的 PPD；请向厂商索取对应 PPD。"
                    ]
            elif source_type == "ppd":
                ppd = target / Path(staged["filename"]).name
                shutil.copy2(source, ppd)
                model = str(ppd)
            elif source_type == "archive":
                self._extract_archive(source, target)
                ppd = next(
                    (path for path in target.rglob("*") if path.is_file() and path.name.lower().endswith((".ppd", ".ppd.gz"))),
                    None,
                )
                if ppd is None:
                    raise DriverError("安装时未找到 PPD 文件")
                model = str(ppd)
                self._install_filters(target)
            else:
                raise DriverError("unsupported driver source type")
            registry = self._read_registry()
            label = self._driver_label(analysis, staged["filename"])
            record = {
                "id": driver_id,
                "label": label,
                "description": "现场导入 Linux 打印驱动",
                "version": str(analysis.get("version", "")),
                "source_type": source_type,
                "model": model,
                "source_sha256": analysis["sha256"],
                "installed_at": int(time.time()),
                "backup_id": backup["id"],
                "analysis": analysis,
            }
            registry["drivers"] = [item for item in registry["drivers"] if item.get("id") != driver_id] + [record]
            self._write_registry(registry)
            self._run(["systemctl", "restart", "cups.service"], 60)
            return {"driver": record, "backup": backup, "profiles": self.profiles()}
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    @staticmethod
    def _driver_label(analysis: dict[str, Any], filename: str) -> str:
        ppds = analysis.get("ppds") or []
        if ppds:
            ppd = ppds[0]
            return str(ppd.get("nick_name") or ppd.get("model_name") or filename)
        return str(analysis.get("package") or filename)

    def _extract_archive(self, source: Path, target: Path) -> None:
        def allow(relative: str) -> Path:
            pure = PurePosixPath(relative)
            if pure.is_absolute() or not pure.parts or ".." in pure.parts:
                raise DriverError("archive contains unsafe path")
            resolved = (target / Path(*pure.parts)).resolve()
            try:
                resolved.relative_to(target.resolve())
            except ValueError as exc:
                raise DriverError("archive path escapes installation directory") from exc
            return resolved
        if source.name.lower().endswith(".zip"):
            with zipfile.ZipFile(source) as archive:
                for item in archive.infolist():
                    if item.is_dir():
                        continue
                    destination = allow(item.filename)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as input_handle, destination.open("wb") as output_handle:
                        shutil.copyfileobj(input_handle, output_handle)
        else:
            with tarfile.open(source, "r:*") as archive:
                for item in archive.getmembers():
                    if item.isdir():
                        continue
                    if not item.isfile():
                        raise DriverError("archive contains unsupported link or device file")
                    destination = allow(item.name)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    input_handle = archive.extractfile(item)
                    if input_handle is None:
                        raise DriverError("cannot read archive file")
                    with input_handle, destination.open("wb") as output_handle:
                        shutil.copyfileobj(input_handle, output_handle)
                    os.chmod(destination, item.mode & 0o755)

    def _install_filters(self, target: Path) -> None:
        filter_dir = Path("/usr/lib/cups/filter")
        for candidate in target.rglob("*"):
            if not candidate.is_file():
                continue
            data = candidate.read_bytes()[:64]
            if _elf_arch(data) not in {"arm64", "arm"}:
                continue
            destination = filter_dir / _safe_name(candidate.name)
            filter_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, destination)
            os.chmod(destination, 0o755)

    def rollback(self, backup_id: str = "") -> dict[str, Any]:
        candidates = sorted((path for path in self.backup_dir.glob("*") if path.is_dir()), reverse=True)
        if backup_id:
            candidates = [path for path in candidates if path.name == backup_id]
        if not candidates:
            raise DriverError("没有可恢复的驱动备份")
        source = candidates[0]
        cups_source = source / "cups"
        if cups_source.is_dir():
            cups_target = Path("/etc/cups")
            temporary = cups_target.with_name(f".cups-restore-{uuid.uuid4().hex}")
            shutil.copytree(cups_source, temporary)
            if cups_target.exists():
                shutil.rmtree(cups_target)
            os.replace(temporary, cups_target)
        registry_source = source / "registry.json"
        if registry_source.is_file():
            self.root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(registry_source, self.registry_path)
        else:
            self.registry_path.unlink(missing_ok=True)
        self._run(["systemctl", "restart", "cups.service"], 60)
        return {"backup_id": source.name, "profiles": self.profiles()}
