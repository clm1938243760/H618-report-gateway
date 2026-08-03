from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .config import MscConfig, resolve_udc_device
from .pdf_converter import PdfConverter

LOGGER = logging.getLogger(__name__)


class MscMonitor:
    def __init__(self, config: MscConfig, converter: PdfConverter | None = None) -> None:
        self.config = config
        self.converter = converter
        self.image_path = Path(config.image_path)
        self.mount_dir = Path(config.mount_dir)
        self.output_dir = Path(config.output_dir)
        self.state_dir = Path(config.state_dir)
        self.records_file = self.state_dir / "files.jsonl"
        self.last_mtime_file = self.state_dir / "last_mtime"
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if not self.config.enabled:
            LOGGER.info("msc monitor disabled")
            return
        self.mount_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.records_file.touch(exist_ok=True)
        LOGGER.info("watching msc image: %s", self.image_path)
        while not self._stop.is_set():
            if not self.image_path.exists():
                LOGGER.warning("waiting for msc image: %s", self.image_path)
                await asyncio.sleep(2)
                continue
            current = self._image_mtime()
            previous = self._read_last_mtime()
            if current and current != previous:
                stable = await self._wait_quiet(current)
                if stable:
                    try:
                        await asyncio.to_thread(self._extract_cycle)
                    except Exception:
                        LOGGER.exception("msc extract failed; will retry")
                    else:
                        self._write_last_mtime(self._image_mtime() or stable)
            await asyncio.sleep(2)

    def _image_mtime(self) -> str:
        try:
            return str(self.image_path.stat().st_mtime_ns)
        except FileNotFoundError:
            return ""

    def _read_last_mtime(self) -> str:
        try:
            return self.last_mtime_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return ""

    def _write_last_mtime(self, value: str) -> None:
        self.last_mtime_file.write_text(value, encoding="utf-8")

    async def _wait_quiet(self, first_mtime: str) -> str:
        last = first_mtime
        quiet_started = time.monotonic()
        while not self._stop.is_set():
            await asyncio.sleep(self.config.stable_seconds)
            current = self._image_mtime()
            if not current:
                return ""
            if current != last:
                LOGGER.info("msc image still changing old=%s new=%s", last, current)
                last = current
                quiet_started = time.monotonic()
                continue
            if time.monotonic() - quiet_started >= self.config.quiet_seconds:
                return current
        return ""

    def _extract_cycle(self) -> None:
        udc = self._unbind_gadget()
        self._detach_backing_file()
        loop = ""
        try:
            loop = self._losetup()
            self._mount_loop_ro(loop)
            copied = self._copy_new_files()
            LOGGER.info("msc extract complete copied=%d", copied)
        finally:
            self._umount()
            if loop:
                subprocess.run(["losetup", "-d", loop], check=False)
            self._attach_backing_file()
            self._bind_gadget(udc)

    def _copy_new_files(self) -> int:
        records = self._load_records()
        count = 0
        for source in self._iter_files():
            info = self._file_info(source)
            signature = info["signature"]
            if signature in records:
                continue
            target = self._copy_file(source)
            self._append_record(info, target)
            records.add(signature)
            count += 1
            LOGGER.info("msc copied: %s -> %s", info["rel"], target)
            if self.converter and target.suffix.lower() in {".pdf", ".bmp", ".jpg", ".jpeg", ".png", ".txt"}:
                self.converter.convert(target, "msc")
        return count

    def _iter_files(self) -> list[Path]:
        iterator = self.mount_dir.rglob("*") if self.config.copy_recursive else self.mount_dir.glob("*")
        ignore = set(self.config.ignore_names)
        allowed = {ext.lower() for ext in self.config.report_extensions}
        files: list[Path] = []
        for path in iterator:
            if not path.is_file():
                continue
            rel_parts = path.relative_to(self.mount_dir).parts
            if any(part in ignore for part in rel_parts):
                continue
            if path.name.startswith("~$"):
                continue
            if allowed and path.suffix.lower() not in allowed:
                continue
            files.append(path)
        return files

    def _copy_file(self, source: Path) -> Path:
        rel = source.relative_to(self.mount_dir)
        target = self.output_dir / rel
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = target.with_name(f"{target.stem}_{stamp}{target.suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def _file_info(self, path: Path) -> dict[str, str | int]:
        rel = path.relative_to(self.mount_dir).as_posix()
        stat = path.stat()
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        sha = digest.hexdigest()
        return {"rel": rel, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha, "signature": f"{rel}|{stat.st_size}|{sha}"}

    def _load_records(self) -> set[str]:
        records: set[str] = set()
        for line in self.records_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            signature = str(item.get("signature", ""))
            if signature:
                records.add(signature)
        return records

    def _append_record(self, info: dict[str, str | int], target: Path) -> None:
        record = {**info, "copied_to": str(target), "copied_at": datetime.now().isoformat(timespec="seconds")}
        with self.records_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _losetup(self) -> str:
        result = subprocess.run(["losetup", "--show", "-fP", "-r", str(self.image_path)], check=True, stdout=subprocess.PIPE, text=True)
        return result.stdout.strip()

    def _mount_loop_ro(self, loop: str) -> None:
        part = f"{loop}p1"
        device = part if Path(part).exists() else loop
        subprocess.run(["mount", "-o", "ro", device, str(self.mount_dir)], check=True)

    def _umount(self) -> None:
        if self._is_mounted():
            subprocess.run(["umount", str(self.mount_dir)], check=False)

    def _is_mounted(self) -> bool:
        try:
            with Path("/proc/mounts").open("r", encoding="utf-8") as handle:
                return any(line.split()[1] == str(self.mount_dir) for line in handle if line.split())
        except FileNotFoundError:
            return False

    def _udc_attr(self) -> Path:
        return Path(self.config.gadget_dir) / "UDC"

    def _mass_storage_file_attr(self) -> Path:
        functions = Path(self.config.gadget_dir) / "functions"
        for name in ("mass_storage.0", "mass_storage.usb0"):
            attr = functions / name / "lun.0" / "file"
            if attr.exists():
                return attr
        return functions / "mass_storage.0" / "lun.0" / "file"

    def _unbind_gadget(self) -> str:
        attr = self._udc_attr()
        current = ""
        if attr.exists():
            current = attr.read_text(encoding="utf-8").strip()
            if current:
                # A zero-byte write does not invoke configfs' store callback.
                attr.write_text("\n", encoding="utf-8")
                time.sleep(1)
        return current or resolve_udc_device(self.config.udc_device)

    def _bind_gadget(self, udc: str) -> None:
        if not udc:
            return
        attr = self._udc_attr()
        if not attr.exists():
            return
        if attr.read_text(encoding="utf-8").strip() == udc:
            return
        self._write_attr_with_retry(attr, udc)

    def _detach_backing_file(self) -> None:
        attr = self._mass_storage_file_attr()
        if attr.exists():
            if attr.read_text(encoding="utf-8").strip():
                attr.write_text("\n", encoding="utf-8")
                time.sleep(0.3)

    def _attach_backing_file(self) -> None:
        attr = self._mass_storage_file_attr()
        if attr.exists():
            image = str(self.image_path)
            if attr.read_text(encoding="utf-8").strip() == image:
                return
            self._write_attr_with_retry(attr, image)

    def _write_attr_with_retry(self, attr: Path, value: str) -> None:
        for attempt in range(1, 11):
            try:
                attr.write_text(f"{value}\n", encoding="utf-8")
                return
            except OSError as exc:
                if exc.errno != errno.EBUSY or attempt == 10:
                    raise
                LOGGER.warning(
                    "configfs busy path=%s attempt=%d/10",
                    attr,
                    attempt,
                )
                time.sleep(0.5)
