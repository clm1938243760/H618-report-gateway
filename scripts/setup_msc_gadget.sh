#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/udc.sh"
source "$SCRIPT_DIR/lib/hid.sh"

CONFIGFS="${CONFIGFS:-/sys/kernel/config}"
GADGET="${MSC_GADGET_DIR:-/sys/kernel/config/usb_gadget/gmp_msc}"
UDC="${MSC_UDC:-auto}"
UDC="$(resolve_udc_name "$UDC")"
IMAGE="${MSC_IMAGE:-/var/lib/gadget-msc-printer/msc/ums_shared.img}"
SIZE_MB="${MSC_SIZE_MB:-512}"
LABEL="${MSC_LABEL:-USB DISK}"
ENABLE_HID="${MSC_ENABLE_HID:-0}"

modprobe libcomposite 2>/dev/null || true
modprobe usb_f_mass_storage 2>/dev/null || true
mountpoint -q "$CONFIGFS" || mount -t configfs none "$CONFIGFS"

[[ -e "/sys/class/udc/$UDC" ]] || {
  echo "UDC not found: $UDC"
  ls /sys/class/udc || true
  exit 1
}

unbind() {
  [[ -f "$GADGET/UDC" ]] && echo "" > "$GADGET/UDC" 2>/dev/null || true
}

clear_links() {
  [[ -d "$GADGET/configs" ]] && find "$GADGET/configs" -type l -exec rm -f {} \; 2>/dev/null || true
}

make_image() {
  mkdir -p "$(dirname "$IMAGE")"
  if [[ ! -s "$IMAGE" ]]; then
    truncate -s "${SIZE_MB}M" "$IMAGE"
    # Hospital WinCE test passed with an MBR + FAT32 removable disk. Keep the
    # first partition at sector 32 to resemble the sampled SanDisk disk layout.
    printf 'label: dos\nunit: sectors\n\nstart=32, type=c\n' | sfdisk "$IMAGE"
    LOOP="$(losetup --show -fP "$IMAGE")"
    trap 'losetup -d "$LOOP" 2>/dev/null || true' RETURN
    if command -v mkfs.vfat >/dev/null 2>&1; then
      mkfs.vfat -F 32 -n "$LABEL" "${LOOP}p1"
    else
      mkfs.fat -F 32 -n "$LABEL" "${LOOP}p1"
    fi
    sync
    losetup -d "$LOOP"
    trap - RETURN
  fi
}

make_image
mkdir -p "$GADGET"
unbind
clear_links

echo 0x0781 > "$GADGET/idVendor"
echo 0x558a > "$GADGET/idProduct"
echo 0x0200 > "$GADGET/bcdUSB"
echo 0x0100 > "$GADGET/bcdDevice"
echo 0x00 > "$GADGET/bDeviceClass"
echo 0x00 > "$GADGET/bDeviceSubClass"
echo 0x00 > "$GADGET/bDeviceProtocol"

mkdir -p "$GADGET/strings/0x409"
echo "SanDisk" > "$GADGET/strings/0x409/manufacturer"
echo "Ultra" > "$GADGET/strings/0x409/product"
echo "GMP-SANDISK-FAT32" > "$GADGET/strings/0x409/serialnumber"

mkdir -p "$GADGET/configs/c.1/strings/0x409"
echo "mass storage" > "$GADGET/configs/c.1/strings/0x409/configuration"
echo 224 > "$GADGET/configs/c.1/MaxPower"

MSC="$GADGET/functions/mass_storage.0"
mkdir -p "$MSC"
echo "" > "$MSC/lun.0/file" 2>/dev/null || true
echo 1 > "$MSC/lun.0/removable"
echo 0 > "$MSC/lun.0/ro"
echo 0 > "$MSC/lun.0/cdrom"
echo 1 > "$MSC/lun.0/nofua" 2>/dev/null || true
echo "$IMAGE" > "$MSC/lun.0/file"

ln -s "$MSC" "$GADGET/configs/c.1/f1" 2>/dev/null || true
if [[ "$ENABLE_HID" == "1" ]]; then
  add_hid_functions "$GADGET" "$GADGET/configs/c.1"
fi
echo "$UDC" > "$GADGET/UDC"

echo "MSC gadget attached: $GADGET -> $UDC"
echo "image: $IMAGE"
cat "/sys/class/udc/$UDC/state" 2>/dev/null || true
