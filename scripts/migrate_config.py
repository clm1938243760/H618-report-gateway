#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sync_service_unit(
    source_root: Path = PROJECT_ROOT,
    systemd_dir: Path = Path("/etc/systemd/system"),
) -> bool:
    source = source_root / "systemd" / "gadget-web.service"
    destination = systemd_dir / "gadget-web.service"
    content = source.read_bytes()
    if destination.is_file() and destination.read_bytes() == content:
        return False

    systemd_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".gadget-web.service.", dir=str(systemd_dir))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return True


def main() -> None:
    changed = sync_service_unit()
    print(f"gadget-web.service synchronized={str(changed).lower()}")


if __name__ == "__main__":
    main()
