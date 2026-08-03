#!/usr/bin/env bash
set -euo pipefail

OVERLAY_NAME="k2b-usb0-peripheral"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DTS="${SCRIPT_DIR}/../overlays/${OVERLAY_NAME}.dts"
ARMBIAN_ENV="/boot/armbianEnv.txt"
OVERLAY_DIR="/boot/overlay-user"
TARGET_DTBO="${OVERLAY_DIR}/${OVERLAY_NAME}.dtbo"
DTB="/boot/dtb/allwinner/sun50i-h618-kickpi-k2b-v2.dtb"
BACKUP_ROOT="/boot/k2b-usb0-peripheral-backups"

usage() {
    cat <<'EOF'
Usage: sudo k2b_usb0_peripheral_overlay.sh install|remove|status

install  Back up boot files, compile the overlay, and enable it in armbianEnv.txt.
remove   Disable and remove the overlay. The latest backup is kept for recovery.
status   Show whether the overlay is installed and whether USB0 enumerated as a device.
EOF
}

require_root() {
    if [[ ${EUID} -ne 0 ]]; then
        echo "Run this command as root." >&2
        exit 1
    fi
}

check_board() {
    local model
    model="$(tr -d '\0' </proc/device-tree/model 2>/dev/null || true)"
    if [[ ${model} != *"KICKPI K2B"* ]]; then
        echo "Unsupported board: ${model:-unknown}" >&2
        exit 1
    fi
}

overlay_enabled() {
    awk -v wanted="${OVERLAY_NAME}" '
        /^user_overlays=/ {
            count = split(substr($0, index($0, "=") + 1), names, /[[:space:]]+/)
            for (i = 1; i <= count; i++) {
                if (names[i] == wanted) {
                    found = 1
                }
            }
        }
        END { exit found ? 0 : 1 }
    ' "${ARMBIAN_ENV}"
}

enable_overlay() {
    local tmp
    tmp="$(mktemp /boot/armbianEnv.txt.XXXXXX)"
    awk -v wanted="${OVERLAY_NAME}" '
        BEGIN { updated = 0 }
        /^user_overlays=/ && !updated {
            value = substr($0, index($0, "=") + 1)
            padded = " " value " "
            if (padded !~ " " wanted " ") {
                value = value ? value " " wanted : wanted
            }
            print "user_overlays=" value
            updated = 1
            next
        }
        { print }
        END {
            if (!updated) {
                print "user_overlays=" wanted
            }
        }
    ' "${ARMBIAN_ENV}" >"${tmp}"
    chmod --reference="${ARMBIAN_ENV}" "${tmp}"
    chown --reference="${ARMBIAN_ENV}" "${tmp}"
    mv "${tmp}" "${ARMBIAN_ENV}"
}

disable_overlay() {
    local tmp
    tmp="$(mktemp /boot/armbianEnv.txt.XXXXXX)"
    awk -v unwanted="${OVERLAY_NAME}" '
        /^user_overlays=/ {
            count = split(substr($0, index($0, "=") + 1), names, /[[:space:]]+/)
            value = ""
            for (i = 1; i <= count; i++) {
                if (names[i] != "" && names[i] != unwanted) {
                    value = value ? value " " names[i] : names[i]
                }
            }
            if (value != "") {
                print "user_overlays=" value
            }
            next
        }
        { print }
    ' "${ARMBIAN_ENV}" >"${tmp}"
    chmod --reference="${ARMBIAN_ENV}" "${tmp}"
    chown --reference="${ARMBIAN_ENV}" "${tmp}"
    mv "${tmp}" "${ARMBIAN_ENV}"
}

install_overlay() {
    command -v dtc >/dev/null || {
        echo "dtc is required (package: device-tree-compiler)." >&2
        exit 1
    }
    [[ -f ${SOURCE_DTS} ]] || {
        echo "Overlay source not found: ${SOURCE_DTS}" >&2
        exit 1
    }
    [[ -f ${ARMBIAN_ENV} ]] || {
        echo "Armbian environment not found: ${ARMBIAN_ENV}" >&2
        exit 1
    }

    local stamp backup_dir tmp_dtbo
    tmp_dtbo="$(mktemp /tmp/${OVERLAY_NAME}.XXXXXX.dtbo)"
    if ! dtc -@ -I dts -O dtb -o "${tmp_dtbo}" "${SOURCE_DTS}"; then
        rm -f "${tmp_dtbo}"
        exit 1
    fi
    if [[ -f ${TARGET_DTBO} ]] \
        && cmp -s "${tmp_dtbo}" "${TARGET_DTBO}" \
        && overlay_enabled; then
        rm -f "${tmp_dtbo}"
        echo "${OVERLAY_NAME} is already installed and enabled."
        return
    fi

    stamp="$(date +%Y%m%d_%H%M%S)"
    backup_dir="${BACKUP_ROOT}/${stamp}"
    mkdir -p "${backup_dir}" "${OVERLAY_DIR}"
    cp -a "${ARMBIAN_ENV}" "${backup_dir}/armbianEnv.txt"
    if [[ -f ${DTB} ]]; then
        cp -a "${DTB}" "${backup_dir}/$(basename "${DTB}")"
    fi
    if [[ -f ${TARGET_DTBO} ]]; then
        cp -a "${TARGET_DTBO}" "${backup_dir}/${OVERLAY_NAME}.dtbo.previous"
    fi

    install -m 0644 "${tmp_dtbo}" "${TARGET_DTBO}"
    rm -f "${tmp_dtbo}"
    enable_overlay
    sync

    echo "Installed ${TARGET_DTBO}"
    echo "Enabled user overlay: ${OVERLAY_NAME}"
    echo "Backup: ${backup_dir}"
    echo "Reboot is required."
}

remove_overlay() {
    [[ -f ${ARMBIAN_ENV} ]] || {
        echo "Armbian environment not found: ${ARMBIAN_ENV}" >&2
        exit 1
    }
    disable_overlay
    rm -f "${TARGET_DTBO}"
    sync
    echo "Disabled ${OVERLAY_NAME}. Reboot is required."
}

show_status() {
    if [[ -f ${TARGET_DTBO} ]]; then
        echo "overlay_file=present"
    else
        echo "overlay_file=missing"
    fi
    if overlay_enabled; then
        echo "overlay_config=enabled"
    else
        echo "overlay_config=disabled"
    fi
    if compgen -G '/sys/class/udc/*' >/dev/null; then
        local udc
        udc="$(basename "$(find /sys/class/udc -mindepth 1 -maxdepth 1 -print -quit)")"
        echo "udc=${udc}"
        echo "udc_state=$(cat "/sys/class/udc/${udc}/state")"
        echo "udc_speed=$(cat "/sys/class/udc/${udc}/current_speed")"
    else
        echo "udc=missing"
    fi
    if [[ -r /sys/class/extcon/extcon0/state ]]; then
        sed 's/^/extcon_/' /sys/class/extcon/extcon0/state
    fi
}

main() {
    require_root
    check_board
    case "${1:-}" in
        install) install_overlay ;;
        remove) remove_overlay ;;
        status) show_status ;;
        *) usage; exit 2 ;;
    esac
}

main "$@"
