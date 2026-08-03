#!/usr/bin/env bash
set -euo pipefail

CONFIG=/etc/gadget-msc-printer/config.yaml
if [[ "${1:-}" == "--config" ]]; then
  CONFIG="${2:?missing config path}"
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib/udc.sh"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON=/usr/bin/python3

readarray -t VALUES < <(
  PYTHONPATH="$ROOT/src" "$PYTHON" - "$CONFIG" <<'PY'
import sys
from gadget_msc_printer.config import load_config
c = load_config(sys.argv[1])
print(c.gadget.mode)
print(c.gadget.udc_device)
print(c.gadget.msc_gadget_dir)
print(c.gadget.printer_gadget_dir)
print(c.msc.image_path)
print(c.msc.image_size_mb)
print(c.msc.label)
print(c.printer.usb_vendor_id)
print(c.printer.usb_product_id)
print(c.printer.usb_manufacturer)
print(c.printer.usb_product)
print(c.printer.usb_serial)
print(c.printer.usb_pnp_string)
PY
)

MODE="${VALUES[0]}"
UDC="${VALUES[1]}"
UDC="$(resolve_udc_name "$UDC")"
MSC_GADGET="${VALUES[2]}"
PRINTER_GADGET="${VALUES[3]}"
MSC_IMAGE="${VALUES[4]}"
MSC_SIZE_MB="${VALUES[5]}"
MSC_LABEL="${VALUES[6]}"
PRINTER_VENDOR_ID="${VALUES[7]}"
PRINTER_PRODUCT_ID="${VALUES[8]}"
PRINTER_MANUFACTURER="${VALUES[9]}"
PRINTER_PRODUCT="${VALUES[10]}"
PRINTER_SERIAL="${VALUES[11]}"
PRINTER_PNP_STRING="${VALUES[12]}"

mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config
[[ -e "/sys/class/udc/$UDC" ]] || { echo "UDC not found: $UDC"; exit 1; }

# A single K2B UDC can have only one owner. Unbind any vendor/test gadget
# before rebuilding the selected product gadget.
for attr in /sys/kernel/config/usb_gadget/*/UDC; do
  [[ -e "$attr" ]] || continue
  if [[ "$(cat "$attr" 2>/dev/null || true)" == "$UDC" ]]; then
    echo "" > "$attr"
  fi
done

remove_gadget() {
  local gadget="$1"
  [[ -d "$gadget" ]] || return 0
  echo "" > "$gadget/UDC" 2>/dev/null || true
  find "$gadget/configs" -type l -delete 2>/dev/null || true
  if [[ -d "$gadget/functions" ]]; then
    for function in "$gadget"/functions/*; do
      [[ -e "$function" ]] || continue
      rmdir "$function" 2>/dev/null || true
    done
  fi
  find "$gadget/configs" "$gadget/strings" -depth -type d -exec rmdir {} \; 2>/dev/null || true
  rmdir "$gadget/functions" 2>/dev/null || true
  rmdir "$gadget" 2>/dev/null || true
  [[ ! -d "$gadget" ]] || { echo "failed to remove stale gadget: $gadget"; exit 1; }
}

remove_gadget "$MSC_GADGET"
remove_gadget "$PRINTER_GADGET"

case "$MODE" in
  msc|msc_hid)
    ENABLE_HID=0
    [[ "$MODE" == "msc_hid" ]] && ENABLE_HID=1
    MSC_GADGET_DIR="$MSC_GADGET" MSC_UDC="$UDC" MSC_IMAGE="$MSC_IMAGE" \
      MSC_SIZE_MB="$MSC_SIZE_MB" MSC_LABEL="$MSC_LABEL" MSC_ENABLE_HID="$ENABLE_HID" \
      "$ROOT/scripts/setup_msc_gadget.sh"
    ;;
  printer|printer_hid)
    ENABLE_HID=0
    [[ "$MODE" == "printer_hid" ]] && ENABLE_HID=1
    PRINTER_GADGET_DIR="$PRINTER_GADGET" PRINTER_UDC="$UDC" \
      PRINTER_VENDOR_ID="$PRINTER_VENDOR_ID" PRINTER_PRODUCT_ID="$PRINTER_PRODUCT_ID" \
      PRINTER_MANUFACTURER="$PRINTER_MANUFACTURER" PRINTER_PRODUCT="$PRINTER_PRODUCT" \
      PRINTER_SERIAL="$PRINTER_SERIAL" PRINTER_PNP_STRING="$PRINTER_PNP_STRING" \
      PRINTER_ENABLE_HID="$ENABLE_HID" \
      "$ROOT/scripts/setup_hp_printer_gadget.sh"
    ;;
  *)
    echo "unsupported gadget mode: $MODE"
    exit 2
    ;;
esac

echo "active gadget mode: $MODE"
