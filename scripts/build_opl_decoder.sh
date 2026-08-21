#!/usr/bin/env bash
set -euo pipefail

SOURCE_VERSION=20200505dfsg0-3
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT/third_party/foo2zjs-opl"
SOURCE="$SOURCE_DIR/opldecode.c"
LICENSE="$SOURCE_DIR/COPYING"
TARGET_DIR="${TARGET_DIR:-/usr/local/libexec/jvlei-prn-decoders}"
BUILD_ROOT="${BUILD_ROOT:-/var/tmp/jvlei-opldecode-build}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi
if [[ ! -s "$SOURCE" || ! -s "$LICENSE" ]]; then
  echo "Vendored OPL decoder source or GPL license is missing." >&2
  exit 1
fi
if ! command -v cc >/dev/null 2>&1; then
  echo "A C compiler is required to build the audited OPL decoder." >&2
  exit 1
fi
if ! printf '#include <jbig.h>\n' | cc -E - >/dev/null 2>&1; then
  echo "libjbig development headers are required to build the OPL decoder." >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT" "$TARGET_DIR"
cc -O2 -Wall -Wextra -Wformat=2 -fstack-protector-strong \
  -D_FORTIFY_SOURCE=2 -fPIE -pie -Wl,-z,relro,-z,now \
  "$SOURCE" -ljbig -o "$BUILD_ROOT/opldecode"

if command -v foo2lava >/dev/null 2>&1; then
  {
    printf 'P4\n16 16\n'
    head -c 32 /dev/zero
  } >"$BUILD_ROOT/probe.pbm"
  foo2lava -z1 -g16x16 -r600x600 \
    <"$BUILD_ROOT/probe.pbm" >"$BUILD_ROOT/probe.opl"
  (
    cd "$BUILD_ROOT"
    ./opldecode -d decoded <probe.opl >/dev/null
  )
  if [[ ! -s "$BUILD_ROOT/decoded-01-1.pbm" ]]; then
    echo "OPL decoder smoke test did not produce a page." >&2
    exit 1
  fi
fi

install -m 0755 "$BUILD_ROOT/opldecode" "$TARGET_DIR/opldecode"
echo "Installed audited OPL decoder: $TARGET_DIR/opldecode"
echo "Source: Debian foo2zjs $SOURCE_VERSION with the documented local fix"
