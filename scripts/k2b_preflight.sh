#!/usr/bin/env bash
set -uo pipefail

failures=0
warnings=0

section() {
  printf '\n=== %s ===\n' "$1"
}

pass() {
  printf '[PASS] %s\n' "$1"
}

warn() {
  warnings=$((warnings + 1))
  printf '[WARN] %s\n' "$1"
}

fail() {
  failures=$((failures + 1))
  printf '[FAIL] %s\n' "$1"
}

command_status() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    pass "$name: $(command -v "$name")"
  else
    warn "$name is not installed"
  fi
}

kernel_config=""
read_kernel_config() {
  if [[ -r /proc/config.gz ]] && command -v zcat >/dev/null 2>&1; then
    zcat /proc/config.gz
    return
  fi
  if [[ -r "/boot/config-$(uname -r)" ]]; then
    cat "/boot/config-$(uname -r)"
    return
  fi
  return 1
}

check_kernel_option() {
  local option="$1"
  local required="${2:-yes}"
  local line
  line="$(printf '%s\n' "$kernel_config" | grep -E "^${option}=(y|m)$" | head -n 1 || true)"
  if [[ -n "$line" ]]; then
    pass "$line"
  elif [[ "$required" == "yes" ]]; then
    fail "$option is not enabled"
  else
    warn "$option is not enabled"
  fi
}

section "Board and operating system"
printf 'date: %s\n' "$(date -Is 2>/dev/null || date)"
printf 'hostname: %s\n' "$(hostname)"
printf 'architecture: %s\n' "$(uname -m)"
printf 'kernel: %s\n' "$(uname -r)"
if [[ "$(uname -m)" == "aarch64" ]]; then
  pass "64-bit ARM userspace"
else
  warn "expected aarch64, found $(uname -m)"
fi
if [[ -r /etc/os-release ]]; then
  grep -E '^(PRETTY_NAME|ID|VERSION_ID)=' /etc/os-release || true
fi

section "CPU, memory and storage"
command -v nproc >/dev/null 2>&1 && printf 'cpus: %s\n' "$(nproc)"
command -v free >/dev/null 2>&1 && free -h || true
command -v lsblk >/dev/null 2>&1 && lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL || true
df -hT / /var 2>/dev/null || df -hT / || true

section "Network"
ip -br link 2>/dev/null || true
ip -br address 2>/dev/null || true

section "USB device controller"
udcs=()
for path in /sys/class/udc/*; do
  [[ -e "$path" ]] || continue
  udcs+=("${path##*/}")
done
if (( ${#udcs[@]} == 0 )); then
  fail "no UDC is exposed in /sys/class/udc"
else
  printf 'UDC candidates: %s\n' "${udcs[*]}"
  for udc in "${udcs[@]}"; do
    state="unknown"
    [[ -r "/sys/class/udc/$udc/state" ]] && state="$(cat "/sys/class/udc/$udc/state")"
    printf '  %s state=%s\n' "$udc" "$state"
  done
  if (( ${#udcs[@]} == 1 )); then
    pass "single UDC can be selected automatically"
  else
    warn "multiple UDCs require an explicit gadget.udc_device setting"
  fi
fi

if [[ -r /sys/class/extcon/extcon0/state ]]; then
  extcon_state="$(cat /sys/class/extcon/extcon0/state)"
  printf '%s\n' "$extcon_state" | sed 's/^/  extcon: /'
  if grep -qx 'USB=1' <<<"$extcon_state" \
    && grep -qx 'USB-HOST=1' <<<"$extcon_state"; then
    warn "USB cable is detected but USB0 is also routed as Host; install the K2B USB0 peripheral overlay"
  elif grep -qx 'USB-HOST=0' <<<"$extcon_state"; then
    pass "USB0 is not routed to the Host controller"
  fi
fi

for node in usb@5100000 usb@5101000 usb@5101400; do
  status_path="/sys/firmware/devicetree/base/soc/${node}/status"
  [[ -r "$status_path" ]] || continue
  printf '  %s status=%s\n' "$node" "$(tr -d '\0' <"$status_path")"
done

section "Kernel USB Gadget capabilities"
if grep -qw configfs /proc/filesystems 2>/dev/null; then
  pass "configfs filesystem is available"
else
  fail "configfs filesystem is unavailable"
fi
if mountpoint -q /sys/kernel/config 2>/dev/null; then
  pass "/sys/kernel/config is mounted"
else
  warn "/sys/kernel/config is not mounted yet"
fi
if kernel_config="$(read_kernel_config 2>/dev/null)"; then
  check_kernel_option CONFIG_USB_GADGET
  check_kernel_option CONFIG_USB_LIBCOMPOSITE
  check_kernel_option CONFIG_USB_CONFIGFS
  check_kernel_option CONFIG_USB_CONFIGFS_MASS_STORAGE
  check_kernel_option CONFIG_USB_CONFIGFS_F_PRINTER
  check_kernel_option CONFIG_USB_CONFIGFS_F_HID no
  check_kernel_option CONFIG_USB_PRINTER no
else
  warn "kernel configuration is not exposed via /proc/config.gz or /boot/config-*"
fi

for module in libcomposite usb_f_mass_storage usb_f_printer usb_f_hid; do
  if modinfo "$module" >/dev/null 2>&1; then
    pass "module available: $module"
  else
    printf '[INFO] module not listed (it may be built into the kernel): %s\n' "$module"
  fi
done

section "Existing gadget ownership"
if [[ -d /sys/kernel/config/usb_gadget ]]; then
  found=0
  for attr in /sys/kernel/config/usb_gadget/*/UDC; do
    [[ -e "$attr" ]] || continue
    found=1
    printf '%s -> %s\n' "$attr" "$(cat "$attr" 2>/dev/null || true)"
  done
  (( found == 1 )) || printf 'no configured gadget found\n'
else
  warn "/sys/kernel/config/usb_gadget does not exist"
fi
ls -l /dev/g_printer* /dev/hidg* 2>/dev/null || true

section "Required userspace commands"
for command_name in python3 openssl losetup mount umount sfdisk mkfs.vfat systemctl; do
  command_status "$command_name"
done
for command_name in gs ps2pdf gpcl6 pcl6 xpstopdf gxps escapy; do
  command_status "$command_name"
done
for decoder_path in \
  /usr/lib/cups/filter/pwgtopdf \
  /usr/local/libexec/jvlei-prn-decoders/hbpldecode \
  /usr/local/libexec/jvlei-prn-decoders/ddstdecode \
  /usr/local/libexec/jvlei-prn-decoders/opldecode \
  /usr/local/libexec/jvlei-prn-decoders/slxdecode \
  /usr/local/libexec/jvlei-prn-decoders/brdecode; do
  if [[ -x "$decoder_path" ]]; then
    pass "isolated decoder available: $decoder_path"
  else
    printf '[INFO] isolated decoder not installed: %s\n' "$decoder_path"
  fi
done
if command -v python3 >/dev/null 2>&1; then
  python3 --version
fi

section "Potential service conflicts"
if command -v systemctl >/dev/null 2>&1; then
  systemctl list-unit-files --no-legend 2>/dev/null \
    | grep -E '(^|[-_])(usb.*gadget|gadget|adb|ums|printer)' \
    || printf 'no matching unit files found\n'
fi

section "Result"
printf 'failures=%d warnings=%d\n' "$failures" "$warnings"
if (( failures > 0 )); then
  echo "K2B is not ready for gateway deployment. Resolve FAIL items first."
  exit 1
fi
echo "No blocking capability issue was detected. Continue with controlled gadget tests."
