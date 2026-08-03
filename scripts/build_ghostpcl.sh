#!/usr/bin/env bash
set -euo pipefail

VERSION=10.07.1
EXPECTED_SHA256=56f6a82907c3a73bba95de1319e029adf16477e34df2dea180d390e71e7c4053
DEFAULT_BUILD_ROOT=/var/tmp/ghostpdl-build-${VERSION}

usage() {
  cat <<EOF
Usage: sudo $0 --accept-agpl /path/to/ghostpdl-${VERSION}.tar.xz

This helper builds and installs gpcl6 from the official GhostPDL source archive.
The --accept-agpl flag confirms that you reviewed and accept the GNU AGPL terms
for this installation. Commercial/closed distribution may require an Artifex
commercial license.

Optional environment variables:
  JOBS=2                  Parallel compiler jobs
  BUILD_ROOT=${DEFAULT_BUILD_ROOT}
EOF
}

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

if [[ $# -ne 2 || $1 != --accept-agpl ]]; then
  usage >&2
  exit 2
fi

ARCHIVE=$(realpath "$2")
if [[ ! -f $ARCHIVE ]]; then
  echo "Archive not found: $ARCHIVE" >&2
  exit 1
fi

ACTUAL_SHA256=$(sha256sum "$ARCHIVE" | awk '{print $1}')
if [[ $ACTUAL_SHA256 != $EXPECTED_SHA256 ]]; then
  echo "SHA256 mismatch for $ARCHIVE" >&2
  echo "expected: $EXPECTED_SHA256" >&2
  echo "actual:   $ACTUAL_SHA256" >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential pkg-config xz-utils \
    libjpeg-dev libpng-dev zlib1g-dev libtiff-dev \
    libfontconfig1-dev libfreetype6-dev libidn-dev \
    libpaper-dev libopenjp2-7-dev
fi

BUILD_ROOT=${BUILD_ROOT:-$DEFAULT_BUILD_ROOT}
JOBS=${JOBS:-2}
rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT"
tar -xJf "$ARCHIVE" -C "$BUILD_ROOT"
SOURCE_DIR="$BUILD_ROOT/ghostpdl-${VERSION}"
if [[ ! -d $SOURCE_DIR ]]; then
  echo "Expected source directory missing: $SOURCE_DIR" >&2
  exit 1
fi

cd "$SOURCE_DIR"
./configure \
  --prefix=/usr/local \
  --disable-cups \
  --disable-gtk \
  --without-x \
  --without-tesseract
make -j"$JOBS" gpcl6
install -m 0755 bin/gpcl6 /usr/local/bin/gpcl6

/usr/local/bin/gpcl6 -h >/dev/null
echo "Installed: /usr/local/bin/gpcl6"
echo "Version source: GhostPDL $VERSION"
