#!/usr/bin/env bash
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${DEST:-/opt/gadget-msc-printer}"
CONFIG_DIR=/etc/gadget-msc-printer
DATA_DIR=/var/lib/gadget-msc-printer
ENABLE_SERVICES="${ENABLE_SERVICES:-1}"
START_SERVICES="${START_SERVICES:-1}"
INSTALL_K2B_USB0_OVERLAY="${INSTALL_K2B_USB0_OVERLAY:-auto}"

for value_name in ENABLE_SERVICES START_SERVICES; do
  value="${!value_name}"
  if [[ "$value" != "0" && "$value" != "1" ]]; then
    echo "ERROR: $value_name must be 0 or 1" >&2
    exit 2
  fi
done

if [[ "$INSTALL_K2B_USB0_OVERLAY" != "auto" \
  && "$INSTALL_K2B_USB0_OVERLAY" != "0" \
  && "$INSTALL_K2B_USB0_OVERLAY" != "1" ]]; then
  echo "ERROR: INSTALL_K2B_USB0_OVERLAY must be auto, 0 or 1" >&2
  exit 2
fi

if [[ ! -s "$SRC/portal/portal/dist/index.html" ]]; then
  echo "ERROR: Vue production bundle is missing: $SRC/portal/portal/dist/index.html" >&2
  echo "Build it on the development PC before installing." >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-yaml python3-pil python3-aiohttp \
    dosfstools util-linux ghostscript openssl device-tree-compiler
fi

if ! command -v gpcl6 >/dev/null 2>&1 && ! command -v pcl6 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
WARNING: GhostPCL is not installed. MSC, PDF, PostScript, image and text handling
will work, but raw PCL/PCL XL print jobs cannot be converted to PDF yet.
Use scripts/build_ghostpcl.sh after reviewing the AGPL/commercial license terms.
EOF
fi

mkdir -p "$DEST" "$CONFIG_DIR" "$DATA_DIR"
cp -a "$SRC"/. "$DEST"/
rm -rf "$DEST/portal/portal/node_modules"
find "$DEST/scripts" -type f -name '*.sh' -exec chmod 755 {} +

K2B_OVERLAY_SELECTED=0
BOARD_MODEL="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
if [[ "$INSTALL_K2B_USB0_OVERLAY" == "1" \
  || ( "$INSTALL_K2B_USB0_OVERLAY" == "auto" && "$BOARD_MODEL" == *"KICKPI K2B"* ) ]]; then
  K2B_OVERLAY_SELECTED=1
  if [[ -f /boot/armbianEnv.txt ]]; then
    "$DEST/scripts/k2b_usb0_peripheral_overlay.sh" install
  elif [[ "$INSTALL_K2B_USB0_OVERLAY" == "1" ]]; then
    echo "ERROR: forced K2B USB0 overlay installation requires /boot/armbianEnv.txt" >&2
    exit 1
  else
    echo "WARNING: K2B detected but /boot/armbianEnv.txt is missing; USB0 overlay was not installed." >&2
  fi
fi

if [[ ! -s "$CONFIG_DIR/config.yaml" ]]; then
  install -m 0640 "$DEST/config.example.yaml" "$CONFIG_DIR/config.yaml"
fi

python3 - "$CONFIG_DIR/config.yaml" <<'PY'
from pathlib import Path
import os
import sys
import tempfile
import yaml

path = Path(sys.argv[1])
data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
web = data.setdefault("web", {})
web.setdefault("username", "tejian01")
web.setdefault("password", "julei123#")
web.setdefault("session_hours", 8)
web.setdefault("static_dir", "/opt/gadget-msc-printer/portal/portal/dist")
upload = data.setdefault("upload", {})
upload.setdefault("hospital_code", "tejian01")
text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp_name, 0o640)
    os.replace(temp_name, path)
except Exception:
    try:
        os.unlink(temp_name)
    except FileNotFoundError:
        pass
    raise
PY

python3 -m venv --system-site-packages "$DEST/.venv"
"$DEST/.venv/bin/python" -m pip install --no-deps -e "$DEST"
"$DEST/scripts/generate_tls_cert.sh" "$CONFIG_DIR/tls.crt" "$CONFIG_DIR/tls.key"

install -m 0644 "$DEST/systemd/gadget-mode.service" /etc/systemd/system/gadget-mode.service
install -m 0644 "$DEST/systemd/gadget-collector.service" /etc/systemd/system/gadget-collector.service
install -m 0644 "$DEST/systemd/gadget-web.service" /etc/systemd/system/gadget-web.service
systemctl daemon-reload

if [[ "$ENABLE_SERVICES" == "1" || "$START_SERVICES" == "1" ]]; then
  systemctl disable --now usb-gadget.service 2>/dev/null || true
  systemctl mask usb-gadget.service 2>/dev/null || true
  systemctl disable --now gadget-msc.service gadget-hp-printer.service 2>/dev/null || true
  rm -f /etc/systemd/system/gadget-msc.service /etc/systemd/system/gadget-hp-printer.service
fi

if [[ "$ENABLE_SERVICES" == "1" ]]; then
  systemctl enable gadget-mode.service gadget-collector.service gadget-web.service
fi

if [[ "$START_SERVICES" == "1" ]]; then
  systemctl restart gadget-mode.service
  systemctl restart gadget-collector.service
  systemctl restart gadget-web.service
fi

echo "Installed to $DEST"
echo "Configuration: https://$(hostname -I | awk '{print $1}'):8443"
echo "Web account is configured in $CONFIG_DIR/config.yaml"
echo "Service enable requested: $ENABLE_SERVICES"
echo "Service start requested: $START_SERVICES"
echo "K2B USB0 overlay selection: $INSTALL_K2B_USB0_OVERLAY"
if [[ "$K2B_OVERLAY_SELECTED" == "1" \
  && -r /sys/firmware/devicetree/base/soc/usb@5101000/status \
  && "$(tr -d '\0' </sys/firmware/devicetree/base/soc/usb@5101000/status)" != "disabled" ]]; then
  echo "Reboot required before the K2B USB-C port enumerates as a gadget."
fi
