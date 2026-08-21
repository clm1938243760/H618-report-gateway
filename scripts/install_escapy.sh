#!/usr/bin/env bash
set -euo pipefail

VERSION=1.1.0
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="$ROOT/scripts/escapy_arm64_requirements.lock"
INSTALL_ROOT=${INSTALL_ROOT:-/opt/jvlei/escapy}
TARGET="$INSTALL_ROOT/$VERSION"
LINK_PATH=${LINK_PATH:-/usr/local/bin/escapy}
PROFILE_CONFIG_ROOT=${PROFILE_CONFIG_ROOT:-/etc/jvlei-escapy}

install_profile_configs() {
  local data_dir profile profile_dir
  data_dir=$(
    "$TARGET/bin/python" -c \
      'from importlib.resources import files; print(files("escapy").joinpath("data"))'
  )
  install -d -m 0755 "$PROFILE_CONFIG_ROOT"
  for profile in generic xp410 sr800; do
    profile_dir="$PROFILE_CONFIG_ROOT/$profile"
    install -d -m 0755 "$profile_dir/profiles"
    install -m 0644 "$data_dir/escapy.conf" "$profile_dir/escapy.conf"
    install -m 0644 \
      "$data_dir/profiles/generic.conf" \
      "$profile_dir/profiles/generic.conf"
    if [[ $profile != generic ]]; then
      install -m 0644 \
        "$data_dir/profiles/$profile.conf" \
        "$profile_dir/profiles/$profile.conf"
      printf '\n[printer]\nprofile = %s\n' "$profile" >>"$profile_dir/escapy.conf"
    fi
  done
}

usage() {
  cat <<EOF
Usage: sudo $0 --accept-agpl /path/to/arm64-wheelhouse

Installs EscaPy ${VERSION} and its pinned Python 3.12 ARM64 dependencies from an
offline wheelhouse. No package is downloaded by this script. The explicit flag
confirms that the operator reviewed and accepts EscaPy's AGPL-3.0-or-later terms
for this installation. A commercial licence is required when AGPL compliance is
not suitable for the product.

The wheelhouse can be prepared on Windows with:
  py -3.14 -m pip download --require-hashes \
    --dest escapy-arm64-wheelhouse \
    --platform manylinux2014_aarch64 --python-version 312 \
    --implementation cp --abi cp312 --only-binary=:all: \
    -r scripts/escapy_arm64_requirements.lock
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
if [[ ! -s $LOCK_FILE ]]; then
  echo "Pinned requirement lock is missing: $LOCK_FILE" >&2
  exit 1
fi

WHEELHOUSE=$(realpath "$2")
if [[ ! -d $WHEELHOUSE ]]; then
  echo "Wheelhouse not found: $WHEELHOUSE" >&2
  exit 1
fi
if [[ $(uname -m) != aarch64 ]]; then
  echo "EscaPy wheelhouse is pinned for ARM64/aarch64, found: $(uname -m)" >&2
  exit 1
fi
if [[ $(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') != 3.12 ]]; then
  echo "EscaPy wheelhouse requires Python 3.12." >&2
  exit 1
fi
if ! python3 -m venv --help >/dev/null 2>&1; then
  echo "python3-venv is required; install it before running this offline helper." >&2
  exit 1
fi

install -d -m 0755 "$INSTALL_ROOT"
if [[ -x $TARGET/bin/escapy ]] && [[ $($TARGET/bin/escapy --version) == *"$VERSION"* ]]; then
  install_profile_configs
  ln -sfn "$TARGET/bin/escapy" "$LINK_PATH"
  echo "EscaPy $VERSION is already installed: $TARGET"
  exit 0
fi

if [[ -e $TARGET ]]; then
  case "$TARGET" in
    "$INSTALL_ROOT"/*) rm -rf -- "$TARGET" ;;
    *)
      echo "Refusing to replace target outside the install root: $TARGET" >&2
      exit 1
      ;;
  esac
fi

cleanup() {
  rm -rf -- "$TARGET"
}
trap cleanup EXIT

# Python venv launchers contain absolute interpreter paths and cannot be moved
# after creation. Build in the final versioned directory, then publish only the
# stable command symlink after installation and the smoke test have succeeded.
python3 -m venv "$TARGET"
"$TARGET/bin/python" -m pip install \
  --no-index --no-cache-dir --require-hashes \
  --find-links "$WHEELHOUSE" \
  -r "$LOCK_FILE"

if [[ $($TARGET/bin/escapy --version) != *"$VERSION"* ]]; then
  echo "EscaPy version verification failed." >&2
  exit 1
fi

SMOKE_DIR="$TARGET/smoke-test"
mkdir -p "$SMOKE_DIR"
printf '\033@JVLEI ESC/P TEST\r\n\f' >"$SMOKE_DIR/input.prn"
(
  cd "$SMOKE_DIR"
  "$TARGET/bin/escapy" --pins 24 -o output.pdf input.prn >/dev/null
)
if [[ ! -s $SMOKE_DIR/output.pdf ]] || [[ $(head -c 5 "$SMOKE_DIR/output.pdf") != %PDF- ]]; then
  echo "EscaPy smoke test did not produce a PDF." >&2
  exit 1
fi
rm -rf -- "$SMOKE_DIR"

trap - EXIT
install_profile_configs
ln -sfn "$TARGET/bin/escapy" "$LINK_PATH"

echo "Installed EscaPy $VERSION: $TARGET"
echo "Command: $LINK_PATH"
echo "Source package: pyscape==$VERSION (AGPL-3.0-or-later or commercial licence)"
