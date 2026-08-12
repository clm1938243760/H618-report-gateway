#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/bootstrap_company_updater.sh" >&2
  exit 1
fi

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPDATER_SOURCE="$SOURCE_ROOT/src/jvlei_update"
CONFIG_SOURCE="$SOURCE_ROOT/updater.example.yaml"
UNIT_SOURCE="$SOURCE_ROOT/systemd/jvlei-updater.service"
BOOTSTRAP_VERSION="company-bootstrap-0.22.0"
UPDATER_ROOT=/usr/local/libexec/jvlei-updater
CONFIG_ROOT=/etc/jvlei-updater
STATE_ROOT=/var/lib/jvlei-updater
BACKUP_ROOT=/var/backups/jvlei-updater-company-bootstrap

for required in "$UPDATER_SOURCE/updater_main.py" "$CONFIG_SOURCE" "$UNIT_SOURCE"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing bootstrap input: $required" >&2
    exit 1
  fi
done

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="$BACKUP_ROOT/$timestamp"
install -d -m 0700 "$backup"
if [[ -d "$CONFIG_ROOT" ]]; then
  cp -a "$CONFIG_ROOT" "$backup/config"
fi
if [[ -f "$STATE_ROOT/state.json" ]]; then
  install -m 0600 "$STATE_ROOT/state.json" "$backup/state.json"
fi
systemctl is-enabled jvlei-updater.service >"$backup/service-enabled.txt" 2>&1 || true
systemctl is-active jvlei-updater.service >"$backup/service-active.txt" 2>&1 || true

release="$UPDATER_ROOT/releases/$BOOTSTRAP_VERSION"
staging="$UPDATER_ROOT/releases/.$BOOTSTRAP_VERSION.staging-$$"
rm -rf "$staging"
install -d -m 0755 "$staging"
cp -a "$UPDATER_SOURCE" "$staging/jvlei_update"
printf '%s\n' "$BOOTSTRAP_VERSION" >"$staging/VERSION"
rm -rf "$release"
mv "$staging" "$release"

install -d -m 0755 "$CONFIG_ROOT" "$STATE_ROOT" "$UPDATER_ROOT/releases"
install -m 0640 "$CONFIG_SOURCE" "$CONFIG_ROOT/config.yaml.next"
mv -f "$CONFIG_ROOT/config.yaml.next" "$CONFIG_ROOT/config.yaml"
ln -sfn "$release" "$UPDATER_ROOT/current.next"
mv -Tf "$UPDATER_ROOT/current.next" "$UPDATER_ROOT/current"
install -m 0644 "$UNIT_SOURCE" /etc/systemd/system/jvlei-updater.service

systemctl daemon-reload
systemctl enable jvlei-updater.service
systemctl restart jvlei-updater.service

for _ in {1..20}; do
  if curl -fsS --max-time 2 http://127.0.0.1:8765/status >/tmp/jvlei-updater-bootstrap-status.json; then
    cat /tmp/jvlei-updater-bootstrap-status.json
    printf '\nBackup: %s\n' "$backup"
    exit 0
  fi
  sleep 1
done

systemctl status jvlei-updater.service --no-pager >&2 || true
journalctl -u jvlei-updater.service -n 100 --no-pager >&2 || true
echo "Company updater did not become ready; backup is $backup" >&2
exit 1
