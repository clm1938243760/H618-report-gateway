#!/usr/bin/env bash
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="/etc/gadget-msc-printer/config.yaml"
REQUIRE_HOST=0
REQUIRE_ENABLED=0

while (( $# > 0 )); do
  case "$1" in
    --config)
      CONFIG="${2:?missing config path}"
      shift 2
      ;;
    --require-host)
      REQUIRE_HOST=1
      shift
      ;;
    --require-enabled)
      REQUIRE_ENABLED=1
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage: k2b_acceptance.sh [--config PATH] [--require-host] [--require-enabled]

The script is read-only. It validates the active K2B gateway without switching
USB modes or changing configuration.
EOF
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

failures=0
warnings=0

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

check_command() {
  local name="$1"
  if command -v "$name" >/dev/null 2>&1; then
    pass "command available: $name"
  else
    fail "required command missing: $name"
  fi
}

[[ -r "$CONFIG" ]] || { echo "configuration is not readable: $CONFIG" >&2; exit 1; }

PYTHON="$ROOT/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON=/usr/bin/python3

if ! readarray -t VALUES < <(
  PYTHONPATH="$ROOT/src" "$PYTHON" - "$CONFIG" <<'PY'
import sys
from pathlib import Path
from gadget_msc_printer.config import load_config, resolve_udc_device

config = load_config(sys.argv[1])
print(config.gadget.mode)
print(resolve_udc_device(config.gadget.udc_device))
print(config.gadget.msc_gadget_dir)
print(config.gadget.printer_gadget_dir)
print(config.device.report_info_path)
print(config.web.static_dir)
print(config.device.device_code.strip())
print(config.device.exam_doct.strip())
print(config.device.exam_doct_code.strip())
print("1" if config.physical_printer.enabled else "0")
PY
); then
  fail "configuration cannot be loaded"
  exit 1
fi

MODE="${VALUES[0]}"
UDC="${VALUES[1]}"
MSC_GADGET="${VALUES[2]}"
PRINTER_GADGET="${VALUES[3]}"
REPORT_INFO="${VALUES[4]}"
STATIC_DIR="${VALUES[5]}"
DEVICE_CODE="${VALUES[6]}"
EXAM_DOCT="${VALUES[7]}"
EXAM_DOCT_CODE="${VALUES[8]}"
PHYSICAL_PRINTER_ENABLED="${VALUES[9]}"

printf 'K2B gateway acceptance\n'
printf '  mode: %s\n' "$MODE"
printf '  UDC: %s\n' "$UDC"

for service in gadget-mode.service gadget-collector.service gadget-web.service; do
  if systemctl is-active --quiet "$service"; then
    pass "$service is active"
  else
    fail "$service is not active"
  fi

  if systemctl is-enabled --quiet "$service" 2>/dev/null; then
    pass "$service is enabled"
  elif (( REQUIRE_ENABLED == 1 )); then
    fail "$service is not enabled"
  else
    warn "$service is not enabled yet"
  fi
done

if [[ -e "/sys/class/udc/$UDC" ]]; then
  pass "UDC exists: $UDC"
else
  fail "UDC does not exist: $UDC"
fi

UDC_STATE="$(cat "/sys/class/udc/$UDC/state" 2>/dev/null || echo missing)"
if [[ "$UDC_STATE" == "configured" ]]; then
  pass "USB host configured the gadget"
elif (( REQUIRE_HOST == 1 )); then
  fail "USB host is required but UDC state is $UDC_STATE"
else
  warn "USB host is not configured; UDC state is $UDC_STATE"
fi

if [[ -r /sys/class/extcon/extcon0/state ]]; then
  EXTCON_STATE="$(cat /sys/class/extcon/extcon0/state)"
  if grep -qx 'USB=1' <<<"$EXTCON_STATE" \
    && grep -qx 'USB-HOST=0' <<<"$EXTCON_STATE"; then
    pass "USB cable is routed to the peripheral controller"
  elif grep -qx 'USB-HOST=1' <<<"$EXTCON_STATE"; then
    fail "USB0 is incorrectly routed to the Host controller"
  elif (( REQUIRE_HOST == 1 )); then
    fail "USB peripheral role is not asserted"
  else
    warn "USB peripheral role is not currently asserted"
  fi
fi

if [[ "$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)" == *"KICKPI K2B"* ]]; then
  EHCI0_STATUS="$(tr -d '\0' </sys/firmware/devicetree/base/soc/usb@5101000/status 2>/dev/null || echo missing)"
  OHCI0_STATUS="$(tr -d '\0' </sys/firmware/devicetree/base/soc/usb@5101400/status 2>/dev/null || echo missing)"
  if [[ "$EHCI0_STATUS" == "disabled" && "$OHCI0_STATUS" == "disabled" ]]; then
    pass "K2B USB0 Host branches are disabled"
  elif (( REQUIRE_HOST == 1 )); then
    fail "K2B USB0 Host branches are not disabled"
  else
    warn "K2B USB0 peripheral overlay is not active"
  fi
fi

case "$MODE" in
  msc|msc_hid)
    GADGET="$MSC_GADGET"
    EXPECTED_FUNCTION="mass_storage.0"
    ;;
  printer|printer_hid)
    GADGET="$PRINTER_GADGET"
    EXPECTED_FUNCTION="printer.usb0"
    ;;
  *)
    fail "unsupported mode: $MODE"
    GADGET=""
    EXPECTED_FUNCTION=""
    ;;
esac

if [[ -n "$GADGET" && -d "$GADGET" ]]; then
  pass "active gadget directory exists: $GADGET"
  BOUND_UDC="$(cat "$GADGET/UDC" 2>/dev/null || true)"
  [[ "$BOUND_UDC" == "$UDC" ]] \
    && pass "gadget is bound to $UDC" \
    || fail "gadget is not bound to $UDC"
else
  fail "active gadget directory is missing: $GADGET"
fi

if [[ -n "$EXPECTED_FUNCTION" && -d "$GADGET/functions/$EXPECTED_FUNCTION" ]]; then
  pass "USB function exists: $EXPECTED_FUNCTION"
else
  fail "USB function is missing: $EXPECTED_FUNCTION"
fi

if [[ "$MODE" == printer || "$MODE" == printer_hid ]]; then
  [[ -c /dev/g_printer0 ]] \
    && pass "/dev/g_printer0 is available" \
    || fail "/dev/g_printer0 is unavailable"
fi

if [[ "$MODE" == *_hid ]]; then
  [[ -d "$GADGET/functions/hid.keyboard" ]] \
    && pass "HID keyboard function exists" \
    || fail "HID keyboard function is missing"
  [[ -d "$GADGET/functions/hid.mouse" ]] \
    && pass "HID mouse function exists" \
    || fail "HID mouse function is missing"
  [[ -c /dev/hidg0 && -c /dev/hidg1 ]] \
    && pass "two HID character devices are available" \
    || fail "two HID character devices are not available"
fi

if command -v curl >/dev/null 2>&1 \
  && curl -ksSf --max-time 5 https://127.0.0.1/health 2>/dev/null \
    | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true'; then
  pass "HTTPS health endpoint is healthy"
else
  fail "HTTPS health endpoint is unavailable"
fi

[[ -s "$STATIC_DIR/index.html" ]] \
  && pass "Vue production bundle is installed" \
  || fail "Vue production bundle is missing"

if [[ -n "$DEVICE_CODE" && -n "$EXAM_DOCT" && -n "$EXAM_DOCT_CODE" ]]; then
  pass "device and doctor fields are configured"
  [[ -s "$REPORT_INFO" ]] \
    && pass "ReportInfo.xml exists" \
    || fail "ReportInfo.xml is missing"
else
  warn "DeviceCode, ExamDoct or ExamDoctCode is not configured yet"
fi

check_command ps2pdf
if command -v gpcl6 >/dev/null 2>&1 || command -v pcl6 >/dev/null 2>&1; then
  pass "GhostPCL is available"
else
  warn "GhostPCL is missing; PCL/PCL XL conversion is not ready"
fi
if command -v zjsdecode >/dev/null 2>&1; then
  pass "ZjStream decoder is available"
else
  warn "zjsdecode is missing; ZjStream conversion is not ready"
fi

if command -v lpstat >/dev/null 2>&1 && systemctl is-active --quiet cups.service; then
  pass "CUPS physical printer service is available"
elif [[ "$PHYSICAL_PRINTER_ENABLED" == "1" ]]; then
  fail "physical printing is enabled but CUPS is unavailable"
else
  warn "CUPS is unavailable; physical printer output is not ready"
fi

AVAILABLE_KB="$(df -Pk /var/lib/gadget-msc-printer 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ "$AVAILABLE_KB" =~ ^[0-9]+$ ]] && (( AVAILABLE_KB >= 1048576 )); then
  pass "at least 1 GiB is free in the data filesystem"
else
  fail "less than 1 GiB is free in the data filesystem"
fi

printf 'RESULT failures=%d warnings=%d\n' "$failures" "$warnings"
(( failures == 0 ))
