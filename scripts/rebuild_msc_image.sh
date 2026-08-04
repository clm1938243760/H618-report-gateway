#!/usr/bin/env bash
set -euo pipefail

CONFIG=/etc/gadget-msc-printer/config.yaml
if [[ "${1:-}" == "--config" ]]; then
  CONFIG="${2:?missing config path}"
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON=/usr/bin/python3

readarray -t VALUES < <(
  PYTHONPATH="$ROOT/src" "$PYTHON" - "$CONFIG" <<'PY'
import sys
from gadget_msc_printer.config import is_msc_mode, load_config
c = load_config(sys.argv[1])
print("1" if is_msc_mode(c.gadget.mode) else "0")
print(c.msc.gadget_dir)
print(c.msc.image_path)
print(c.msc.image_size_mb)
print(c.msc.label)
print(c.msc.protected_seed_dir)
print(c.gadget.apply_command)
PY
)

ACTIVE_MSC="${VALUES[0]}"
GADGET="${VALUES[1]}"
IMAGE="${VALUES[2]}"
SIZE_MB="${VALUES[3]}"
LABEL="${VALUES[4]}"
SEED_DIR="${VALUES[5]}"
APPLY_COMMAND="${VALUES[6]}"

if (( SIZE_MB < 32 || SIZE_MB > 4096 )); then
  echo "invalid MSC size: $SIZE_MB MB" >&2
  exit 2
fi

if [[ "$ACTIVE_MSC" == "1" && -f "$GADGET/UDC" ]]; then
  echo "" > "$GADGET/UDC" 2>/dev/null || true
  for attr in "$GADGET"/functions/mass_storage.*/lun.0/file; do
    [[ -e "$attr" ]] || continue
    echo "" > "$attr" 2>/dev/null || true
  done
  sleep 1
fi

mkdir -p "$(dirname "$IMAGE")"
rm -f -- "$IMAGE"
truncate -s "${SIZE_MB}M" "$IMAGE"
printf 'label: dos\nunit: sectors\n\nstart=32, type=c\n' | sfdisk "$IMAGE"

LOOP="$(losetup --show -fP "$IMAGE")"
MOUNT_DIR="$(mktemp -d /tmp/gmp-msc-rebuild.XXXXXX)"
cleanup() {
  umount "$MOUNT_DIR" 2>/dev/null || true
  rmdir "$MOUNT_DIR" 2>/dev/null || true
  losetup -d "$LOOP" 2>/dev/null || true
}
trap cleanup EXIT

PART="${LOOP}p1"
for _ in $(seq 1 20); do
  [[ -b "$PART" ]] && break
  sleep 0.1
done
[[ -b "$PART" ]] || { echo "MSC partition device was not created: $PART" >&2; exit 1; }

if command -v mkfs.vfat >/dev/null 2>&1; then
  mkfs.vfat -F 32 -n "$LABEL" "$PART"
else
  mkfs.fat -F 32 -n "$LABEL" "$PART"
fi

if [[ -d "$SEED_DIR" ]] && find "$SEED_DIR" -mindepth 1 -print -quit | grep -q .; then
  mount -o rw,sync "$PART" "$MOUNT_DIR"
  cp -a "$SEED_DIR"/. "$MOUNT_DIR"/
  sync
  umount "$MOUNT_DIR"
fi

losetup -d "$LOOP"
rmdir "$MOUNT_DIR"
trap - EXIT

if [[ "$ACTIVE_MSC" == "1" ]]; then
  "$APPLY_COMMAND" --config "$CONFIG"
fi

echo "MSC image rebuilt: $IMAGE size=${SIZE_MB}MB label=$LABEL"
