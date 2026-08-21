#!/usr/bin/env bash
set -euo pipefail

SOURCE_VERSION=20200505dfsg0-3
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT/third_party/foo2zjs-slx"
SOURCE="$SOURCE_DIR/slxdecode.c"
HEADER="$SOURCE_DIR/slx.h"
LICENSE="$SOURCE_DIR/COPYING"
TARGET_DIR="${TARGET_DIR:-/usr/local/libexec/jvlei-prn-decoders}"
BUILD_ROOT="${BUILD_ROOT:-/var/tmp/jvlei-slxdecode-build}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi
if [[ ! -s "$SOURCE" || ! -s "$HEADER" || ! -s "$LICENSE" ]]; then
  echo "Vendored SLX decoder source, header, or GPL license is missing." >&2
  exit 1
fi
if ! command -v cc >/dev/null 2>&1; then
  echo "A C compiler is required to build the audited SLX decoder." >&2
  exit 1
fi
if ! printf '#include <jbig.h>\n' | cc -E - >/dev/null 2>&1; then
  echo "libjbig development headers are required to build the SLX decoder." >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT" "$TARGET_DIR"
cc -O2 -Wall -Wextra -Wformat=2 -fstack-protector-strong \
  -D_FORTIFY_SOURCE=2 -fPIE -pie -Wl,-z,relro,-z,now \
  "$SOURCE" -ljbig -o "$BUILD_ROOT/slxdecode"

if command -v foo2slx >/dev/null 2>&1; then
  {
    printf 'P4\n16 16\n'
    head -c 32 /dev/zero
  } >"$BUILD_ROOT/probe.pbm"
  foo2slx -g16x16 -r600x600 \
    <"$BUILD_ROOT/probe.pbm" >"$BUILD_ROOT/probe.slx"
  (
    cd "$BUILD_ROOT"
    ./slxdecode -d decoded <probe.slx >/dev/null
  )
  if [[ ! -s "$BUILD_ROOT/decoded-01-1.pbm" ]]; then
    echo "SLX decoder smoke test did not produce a page." >&2
    exit 1
  fi
fi

install -m 0755 "$BUILD_ROOT/slxdecode" "$TARGET_DIR/slxdecode"
echo "Installed audited SLX decoder: $TARGET_DIR/slxdecode"
echo "Source: Debian foo2zjs $SOURCE_VERSION"
