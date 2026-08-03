#!/usr/bin/env bash
set -euo pipefail

CERT="${1:-/etc/gadget-msc-printer/tls.crt}"
KEY="${2:-/etc/gadget-msc-printer/tls.key}"
HOST="$(hostname)"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

mkdir -p "$(dirname "$CERT")" "$(dirname "$KEY")"
if [[ -s "$CERT" && -s "$KEY" ]]; then
  exit 0
fi

SAN="DNS:$HOST"
[[ -n "$IP" ]] && SAN="$SAN,IP:$IP"
openssl req -x509 -nodes -newkey rsa:2048 -sha256 -days 3650 \
  -keyout "$KEY" -out "$CERT" -subj "/CN=$HOST" \
  -addext "subjectAltName=$SAN"
chmod 600 "$KEY"
chmod 644 "$CERT"
