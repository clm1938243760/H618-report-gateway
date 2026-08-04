#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/udc.sh"
source "$SCRIPT_DIR/lib/hid.sh"

CONFIGFS="${CONFIGFS:-/sys/kernel/config}"
GADGET="${PRINTER_GADGET_DIR:-/sys/kernel/config/usb_gadget/gmp_printer}"
UDC="${PRINTER_UDC:-auto}"
UDC="$(resolve_udc_name "$UDC")"
VENDOR_ID="${PRINTER_VENDOR_ID:-0x0525}"
PRODUCT_ID="${PRINTER_PRODUCT_ID:-0xa4a8}"
MANUFACTURER="${PRINTER_MANUFACTURER:-JVLEI}"
PRODUCT="${PRINTER_PRODUCT:-K2B USB Printer}"
SERIAL="${PRINTER_SERIAL:-K2B-H618-PRINTER-001}"
PNP_STRING="${PRINTER_PNP_STRING:-MFG:JVLEI;MDL:K2B USB Printer;DES:K2B USB Printer;CMD:PJL,PCL,PCLXL,POSTSCRIPT,RAW;CLS:PRINTER;}"
ENABLE_HID="${PRINTER_ENABLE_HID:-0}"

modprobe libcomposite 2>/dev/null || true
modprobe usb_f_printer 2>/dev/null || true
mountpoint -q "$CONFIGFS" || mount -t configfs none "$CONFIGFS"

[[ -e "/sys/class/udc/$UDC" ]] || {
  echo "UDC not found: $UDC"
  ls /sys/class/udc || true
  exit 1
}

[[ -f "$GADGET/UDC" ]] && echo "" > "$GADGET/UDC" 2>/dev/null || true
[[ -d "$GADGET/configs" ]] && find "$GADGET/configs" -type l -exec rm -f {} \; 2>/dev/null || true

mkdir -p "$GADGET"
echo "$VENDOR_ID" > "$GADGET/idVendor"
echo "$PRODUCT_ID" > "$GADGET/idProduct"
echo 0x0200 > "$GADGET/bcdUSB"
echo 0x0100 > "$GADGET/bcdDevice"
echo 0x00 > "$GADGET/bDeviceClass"
echo 0x00 > "$GADGET/bDeviceSubClass"
echo 0x00 > "$GADGET/bDeviceProtocol"

mkdir -p "$GADGET/strings/0x409"
echo "$MANUFACTURER" > "$GADGET/strings/0x409/manufacturer"
echo "$PRODUCT" > "$GADGET/strings/0x409/product"
echo "$SERIAL" > "$GADGET/strings/0x409/serialnumber"

mkdir -p "$GADGET/configs/c.1/strings/0x409"
echo "$PRODUCT" > "$GADGET/configs/c.1/strings/0x409/configuration"
echo 250 > "$GADGET/configs/c.1/MaxPower"

PRN="$GADGET/functions/printer.usb0"
mkdir -p "$PRN"
echo 16 > "$PRN/q_len"
echo "$PNP_STRING" > "$PRN/pnp_string"

ln -s "$PRN" "$GADGET/configs/c.1/f1" 2>/dev/null || true
if [[ "$ENABLE_HID" == "1" ]]; then
  add_hid_functions "$GADGET" "$GADGET/configs/c.1"
fi
echo "$UDC" > "$GADGET/UDC"

echo "Printer gadget attached: $GADGET -> $UDC"
ls -l /dev/g_printer* 2>/dev/null || true
cat "/sys/class/udc/$UDC/state" 2>/dev/null || true
