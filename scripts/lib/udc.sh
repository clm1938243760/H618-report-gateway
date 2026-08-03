#!/usr/bin/env bash

resolve_udc_name() {
  local configured="${1:-auto}"
  local path
  local -a candidates=()

  if [[ -n "$configured" && "${configured,,}" != "auto" ]]; then
    printf '%s\n' "$configured"
    return 0
  fi

  for path in /sys/class/udc/*; do
    [[ -e "$path" ]] || continue
    candidates+=("${path##*/}")
  done

  if (( ${#candidates[@]} == 1 )); then
    printf '%s\n' "${candidates[0]}"
    return 0
  fi
  if (( ${#candidates[@]} == 0 )); then
    echo "no USB device controller found in /sys/class/udc" >&2
    return 1
  fi

  echo "multiple USB device controllers found; configure one explicitly: ${candidates[*]}" >&2
  return 1
}
