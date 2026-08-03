#!/usr/bin/env bash
set -euo pipefail

SRC="${1:-/var/lib/gadget-msc-printer/print_jobs}"
OUT="${2:-/var/lib/gadget-msc-printer/reports_pdf}"
mkdir -p "$OUT"

if command -v gpcl6 >/dev/null 2>&1; then
  GPCL="$(command -v gpcl6)"
elif command -v pcl6 >/dev/null 2>&1; then
  GPCL="$(command -v pcl6)"
else
  echo "GhostPCL not found. Install ghostpcl, then retry."
  exit 1
fi

find "$SRC" -type f -name '*.prn' | sort | while read -r prn; do
  base="$(basename "$prn" .prn)"
  pdf="$OUT/${base}.pdf"
  echo "convert: $prn -> $pdf"
  "$GPCL" -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -sPAPERSIZE=a4 "-sOutputFile=$pdf" "$prn"
  ls -lh "$pdf"
done
