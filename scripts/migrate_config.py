#!/usr/bin/env python3
from __future__ import annotations

import os
import hashlib
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HBPL_DECODER_SHA256 = "25c2f178941f1f88bf5cfc87cdec36f05372ecbf7b8fd240ed00d2ce093251e5"
HBPL_DECODER_RELATIVE = Path("third_party/foo2zjs-hbpl/bin/linux-arm64/hbpldecode")
HBPL_DECODER_TARGET = Path("/usr/local/libexec/jvlei-prn-decoders/hbpldecode")
DDST_DECODER_SHA256 = "63f8154d45a1debd8c7ed68a1c23abaed1c18178cb3575ec490f0d5851646cd0"
DDST_DECODER_RELATIVE = Path("third_party/foo2zjs-ddst/bin/linux-arm64/ddstdecode")
DDST_DECODER_TARGET = Path("/usr/local/libexec/jvlei-prn-decoders/ddstdecode")
OPL_DECODER_SHA256 = "86061fb03f723d9f465bb2c777213455a4cdcbfdf2141d56526dca68a56030c0"
OPL_DECODER_RELATIVE = Path("third_party/foo2zjs-opl/bin/linux-arm64/opldecode")
OPL_DECODER_TARGET = Path("/usr/local/libexec/jvlei-prn-decoders/opldecode")
SLX_DECODER_SHA256 = "03eaa5afb30e78220f941aa7ee0b02224e2b4813d8504f2bc73167c1aa3b7665"
SLX_DECODER_RELATIVE = Path("third_party/foo2zjs-slx/bin/linux-arm64/slxdecode")
SLX_DECODER_TARGET = Path("/usr/local/libexec/jvlei-prn-decoders/slxdecode")
BRLASER_DECODER_SHA256 = "48fc35456f4be5eb61014e6b584a336637ed28bdfbd66a25a6926a5a1ecf8d27"
BRLASER_DECODER_RELATIVE = Path("third_party/brlaser-brdecode/bin/linux-arm64/brdecode")
BRLASER_DECODER_TARGET = Path("/usr/local/libexec/jvlei-prn-decoders/brdecode")


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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_hbpl_decoder(
    source_root: Path = PROJECT_ROOT,
    target: Path = HBPL_DECODER_TARGET,
    *,
    machine: str | None = None,
    expected_sha256: str = HBPL_DECODER_SHA256,
    smoke_test: bool = True,
) -> bool:
    return _install_verified_decoder(
        source_root,
        target,
        relative=HBPL_DECODER_RELATIVE,
        machine=machine,
        expected_sha256=expected_sha256,
        label="HBPL",
        smoke_test=smoke_test,
    )


def install_ddst_decoder(
    source_root: Path = PROJECT_ROOT,
    target: Path = DDST_DECODER_TARGET,
    *,
    machine: str | None = None,
    expected_sha256: str = DDST_DECODER_SHA256,
    smoke_test: bool = True,
) -> bool:
    return _install_verified_decoder(
        source_root,
        target,
        relative=DDST_DECODER_RELATIVE,
        machine=machine,
        expected_sha256=expected_sha256,
        label="DDST",
        smoke_test=smoke_test,
    )


def install_opl_decoder(
    source_root: Path = PROJECT_ROOT,
    target: Path = OPL_DECODER_TARGET,
    *,
    machine: str | None = None,
    expected_sha256: str = OPL_DECODER_SHA256,
    smoke_test: bool = True,
) -> bool:
    return _install_verified_decoder(
        source_root,
        target,
        relative=OPL_DECODER_RELATIVE,
        machine=machine,
        expected_sha256=expected_sha256,
        label="OPL",
        smoke_test=smoke_test,
    )


def install_slx_decoder(
    source_root: Path = PROJECT_ROOT,
    target: Path = SLX_DECODER_TARGET,
    *,
    machine: str | None = None,
    expected_sha256: str = SLX_DECODER_SHA256,
    smoke_test: bool = True,
) -> bool:
    return _install_verified_decoder(
        source_root,
        target,
        relative=SLX_DECODER_RELATIVE,
        machine=machine,
        expected_sha256=expected_sha256,
        label="SLX",
        smoke_test=smoke_test,
    )


def install_brlaser_decoder(
    source_root: Path = PROJECT_ROOT,
    target: Path = BRLASER_DECODER_TARGET,
    *,
    machine: str | None = None,
    expected_sha256: str = BRLASER_DECODER_SHA256,
    smoke_test: bool = True,
) -> bool:
    return _install_verified_decoder(
        source_root,
        target,
        relative=BRLASER_DECODER_RELATIVE,
        machine=machine,
        expected_sha256=expected_sha256,
        label="Brother",
        smoke_test=smoke_test,
    )


def _install_verified_decoder(
    source_root: Path,
    target: Path,
    *,
    relative: Path,
    machine: str | None,
    expected_sha256: str,
    label: str,
    smoke_test: bool,
) -> bool:
    architecture = (machine or platform.machine()).lower()
    if architecture not in {"aarch64", "arm64"}:
        return False
    source = source_root / relative
    if not source.is_file():
        raise RuntimeError(f"audited {label} decoder is missing: {source}")
    if _sha256(source) != expected_sha256:
        raise RuntimeError(f"audited {label} decoder SHA-256 mismatch")
    if target.is_file() and _sha256(target) == expected_sha256:
        os.chmod(target, 0o755)
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with source.open("rb") as source_handle, os.fdopen(fd, "wb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        os.chmod(temporary, 0o755)
        if smoke_test:
            result = subprocess.run(
                [temporary], input=b"", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False, timeout=5,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"audited {label} decoder smoke test failed: "
                    + result.stderr.decode("utf-8", errors="replace")[-500:]
                )
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return True


def main() -> None:
    service_changed = sync_service_unit()
    hbpl_changed = install_hbpl_decoder()
    ddst_changed = install_ddst_decoder()
    opl_changed = install_opl_decoder()
    slx_changed = install_slx_decoder()
    brlaser_changed = install_brlaser_decoder()
    print(f"gadget-web.service synchronized={str(service_changed).lower()}")
    print(f"audited hbpldecode installed={str(hbpl_changed).lower()}")
    print(f"audited ddstdecode installed={str(ddst_changed).lower()}")
    print(f"audited opldecode installed={str(opl_changed).lower()}")
    print(f"audited slxdecode installed={str(slx_changed).lower()}")
    print(f"audited brdecode installed={str(brlaser_changed).lower()}")


if __name__ == "__main__":
    main()
