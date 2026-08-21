#!/usr/bin/env bash
set -euo pipefail

SOURCE_VERSION=20200505dfsg0-3
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT/third_party/foo2zjs-ddst"
SOURCE="$SOURCE_DIR/ddstdecode.c"
HEADER="$SOURCE_DIR/ddst.h"
LICENSE="$SOURCE_DIR/COPYING"
TARGET_DIR="${TARGET_DIR:-/usr/local/libexec/jvlei-prn-decoders}"
BUILD_ROOT="${BUILD_ROOT:-/var/tmp/jvlei-ddstdecode-build}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi
if [[ ! -s "$SOURCE" || ! -s "$HEADER" || ! -s "$LICENSE" ]]; then
  echo "Vendored DDST decoder source, header, or GPL license is missing." >&2
  exit 1
fi
if ! command -v cc >/dev/null 2>&1; then
  echo "A C compiler is required to build the audited DDST decoder." >&2
  exit 1
fi
if ! printf '#include <jbig.h>\n' | cc -E - >/dev/null 2>&1; then
  echo "libjbig development headers are required to build the DDST decoder." >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT" "$TARGET_DIR"
cc -O2 -Wall -Wextra -Wformat=2 -fstack-protector-strong \
  -D_FORTIFY_SOURCE=2 -fPIE -pie -Wl,-z,relro,-z,now \
  "$SOURCE" -ljbig -o "$BUILD_ROOT/ddstdecode"

if command -v foo2ddst >/dev/null 2>&1; then
  {
    printf 'P4\n16 16\n'
    head -c 32 /dev/zero
  } >"$BUILD_ROOT/probe.pbm"
  foo2ddst -g16x16 -r600x600 -p5 \
    <"$BUILD_ROOT/probe.pbm" >"$BUILD_ROOT/probe.ddst"
  (
    cd "$BUILD_ROOT"
    ./ddstdecode -d decoded <probe.ddst >/dev/null
  )
  if [[ ! -s "$BUILD_ROOT/decoded-01-4.pbm" ]]; then
    echo "DDST decoder smoke test did not produce a page." >&2
    exit 1
  fi
fi

install -m 0755 "$BUILD_ROOT/ddstdecode" "$TARGET_DIR/ddstdecode"
echo "Installed audited DDST decoder: $TARGET_DIR/ddstdecode"
echo "Source: Debian foo2zjs $SOURCE_VERSION"
