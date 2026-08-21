#!/usr/bin/env bash
set -euo pipefail

VERSION=10.07.1
RELEASE_SHA256=56f6a82907c3a73bba95de1319e029adf16477e34df2dea180d390e71e7c4053
TAG_ARCHIVE_SHA256=d7aa9a1926d936ae0cefec31b3b768071da3516ad7f3dfe298a27f13f24a7d01
DEFAULT_BUILD_ROOT=/var/tmp/ghostpdl-build-${VERSION}

usage() {
  cat <<EOF
Usage: sudo $0 --accept-agpl /path/to/ghostpdl-${VERSION}.tar.xz
       sudo $0 --accept-agpl /path/to/ghostpdl-${VERSION}-gitlab.tar.gz

This helper builds and installs gpcl6 and gxps from a verified GhostPDL source archive.
The --accept-agpl flag confirms that you reviewed and accept the GNU AGPL terms
for this installation. Commercial/closed distribution may require an Artifex
commercial license.

GhostPCL's bundled PCL/XL fonts are covered by the AFPL. Functional use is not
restricted, but commercial redistribution is restricted. This helper is for
authorized internal testing or deployments with an appropriate license review.

Accepted source snapshots:
  Artifex release archive: SHA-256 ${RELEASE_SHA256}
  freedesktop-sdk GitLab mirror of Artifex tag ghostpdl-10.07.1,
  commit 9a39d68ca934f8e9343f46a2803e765122a3b4a9:
  SHA-256 ${TAG_ARCHIVE_SHA256}

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
case "$ACTUAL_SHA256" in
  "$RELEASE_SHA256")
    ARCHIVE_FORMAT=xz
    SOURCE_NAME=ghostpdl-${VERSION}
    ;;
  "$TAG_ARCHIVE_SHA256")
    ARCHIVE_FORMAT=gz
    SOURCE_NAME=ghostpdl-ghostpdl-${VERSION}
    ;;
  *)
    echo "SHA256 mismatch for $ARCHIVE" >&2
    echo "expected release: $RELEASE_SHA256" >&2
    echo "expected tag:     $TAG_ARCHIVE_SHA256" >&2
    echo "actual:           $ACTUAL_SHA256" >&2
    exit 1
    ;;
esac

if command -v apt-get >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential autoconf automake pkg-config xz-utils \
    libjpeg-dev libpng-dev zlib1g-dev libtiff-dev \
    libfontconfig1-dev libfreetype6-dev libidn-dev \
    libpaper-dev libopenjp2-7-dev
fi

BUILD_ROOT=${BUILD_ROOT:-$DEFAULT_BUILD_ROOT}
JOBS=${JOBS:-2}
rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT"
if [[ $ARCHIVE_FORMAT == xz ]]; then
  tar -xJf "$ARCHIVE" -C "$BUILD_ROOT"
else
  tar -xzf "$ARCHIVE" -C "$BUILD_ROOT"
fi
SOURCE_DIR="$BUILD_ROOT/$SOURCE_NAME"
if [[ ! -d $SOURCE_DIR ]]; then
  echo "Expected source directory missing: $SOURCE_DIR" >&2
  exit 1
fi

cd "$SOURCE_DIR"
if [[ ! -x ./configure ]]; then
  NOCONFIGURE=1 sh ./autogen.sh
fi
./configure \
  --prefix=/usr/local \
  --disable-cups \
  --disable-gtk \
  --without-x \
  --without-tesseract
make -j"$JOBS" gpcl6 gxps
install -m 0755 bin/gpcl6 /usr/local/bin/gpcl6
install -m 0755 bin/gxps /usr/local/bin/gxps

/usr/local/bin/gpcl6 -h >/dev/null
/usr/local/bin/gxps -h >/dev/null
echo "Installed: /usr/local/bin/gpcl6"
echo "Installed: /usr/local/bin/gxps"
echo "Version source: GhostPDL $VERSION"
