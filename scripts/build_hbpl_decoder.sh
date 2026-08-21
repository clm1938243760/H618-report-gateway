#!/usr/bin/env bash
set -euo pipefail

SOURCE_COMMIT=b917a495f7b8adb1793e1b689379fdc4044b0ced
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/third_party/foo2zjs-hbpl/hbpldecode.c"
LICENSE="$ROOT/third_party/foo2zjs-hbpl/COPYING"
TARGET_DIR="${TARGET_DIR:-/usr/local/libexec/jvlei-prn-decoders}"
BUILD_ROOT="${BUILD_ROOT:-/var/tmp/jvlei-hbpldecode-build}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi
if [[ ! -s "$SOURCE" || ! -s "$LICENSE" ]]; then
  echo "Vendored HBPL decoder source or GPL license is missing." >&2
  exit 1
fi
if ! command -v cc >/dev/null 2>&1; then
  echo "A C compiler is required to build the audited HBPL decoder." >&2
  exit 1
fi
if ! printf '#include <jbig.h>\n' | cc -E - >/dev/null 2>&1; then
  echo "libjbig development headers are required to build the HBPL decoder." >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT" "$TARGET_DIR"
cc -O2 -Wall -Wextra -Wformat=2 -fstack-protector-strong \
  -D_FORTIFY_SOURCE=2 -fPIE -pie -Wl,-z,relro,-z,now \
  "$SOURCE" -ljbig -o "$BUILD_ROOT/hbpldecode"

if command -v foo2hbpl2 >/dev/null 2>&1; then
  {
    printf 'P4\n16 16\n'
    head -c 32 /dev/zero
  } >"$BUILD_ROOT/probe.pbm"
  foo2hbpl2 -g16x16 -r600x600 \
    <"$BUILD_ROOT/probe.pbm" >"$BUILD_ROOT/probe.hbpl"
  (
    cd "$BUILD_ROOT"
    ./hbpldecode -d decoded <probe.hbpl >/dev/null
  )
  if [[ ! -s "$BUILD_ROOT/decoded-01-0.pbm" ]]; then
    echo "HBPL decoder smoke test did not produce a page." >&2
    exit 1
  fi
fi

install -m 0755 "$BUILD_ROOT/hbpldecode" "$TARGET_DIR/hbpldecode"
echo "Installed audited HBPL decoder: $TARGET_DIR/hbpldecode"
echo "Source: OpenPrinting/foo2zjs commit $SOURCE_COMMIT"
