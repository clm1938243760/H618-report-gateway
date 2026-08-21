#!/usr/bin/env bash
set -euo pipefail

SOURCE_COMMIT=2a49e3287c70c254e7e3ac9dabe9d6a07218c3fa
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/third_party/brlaser-brdecode/brdecode.cc"
LICENSE="$ROOT/third_party/foo2zjs-hbpl/COPYING"
TARGET_DIR="${TARGET_DIR:-/usr/local/libexec/jvlei-prn-decoders}"
BUILD_ROOT="${BUILD_ROOT:-/var/tmp/jvlei-brdecode-build}"

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi
if [[ ! -s "$SOURCE" || ! -s "$LICENSE" ]]; then
  echo "Vendored brdecode source or GPL license is missing." >&2
  exit 1
fi
if ! command -v c++ >/dev/null 2>&1; then
  echo "A C++ compiler is required to build the Brother decoder." >&2
  exit 1
fi

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT" "$TARGET_DIR"
c++ -O2 -Wall -Wextra -Wformat=2 -fstack-protector-strong \
  -D_FORTIFY_SOURCE=2 -fPIE -pie -Wl,-z,relro,-z,now \
  "$SOURCE" -o "$BUILD_ROOT/brdecode"

printf '\033w\000\001\001\000\200\014' >"$BUILD_ROOT/probe.hbp"
"$BUILD_ROOT/brdecode" "$BUILD_ROOT/probe.hbp" "$BUILD_ROOT/page" >/dev/null
if [[ ! -s "$BUILD_ROOT/page-1.pbm" ]]; then
  echo "Brother decoder smoke test did not produce a page." >&2
  exit 1
fi

install -m 0755 "$BUILD_ROOT/brdecode" "$TARGET_DIR/brdecode"
echo "Installed audited Brother decoder: $TARGET_DIR/brdecode"
echo "Source: pdewacht/brlaser commit $SOURCE_COMMIT"
