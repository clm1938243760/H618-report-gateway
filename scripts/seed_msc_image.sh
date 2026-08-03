#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:-/var/lib/gadget-msc-printer/msc/ums_shared.img}"
TEMPLATE_DIR="${2:-templates/wince}"
MNT="${MNT:-/mnt/gmp_seed_msc}"

if [[ ! -f "$IMAGE" ]]; then
  echo "image not found: $IMAGE"
  exit 1
fi
if [[ ! -d "$TEMPLATE_DIR" ]]; then
  echo "template dir not found: $TEMPLATE_DIR"
  exit 1
fi

LOOP="$(losetup --show -fP "$IMAGE")"
trap 'umount "$MNT" 2>/dev/null || true; losetup -d "$LOOP" 2>/dev/null || true' EXIT

mkdir -p "$MNT"
if [[ -b "${LOOP}p1" ]]; then
  mount -o rw,sync "${LOOP}p1" "$MNT"
else
  mount -o rw,sync "$LOOP" "$MNT"
fi

cp -a "$TEMPLATE_DIR"/. "$MNT"/
sync
find "$MNT" -maxdepth 3 -print

umount "$MNT"
losetup -d "$LOOP"
trap - EXIT
echo "seed complete: $IMAGE <= $TEMPLATE_DIR"
