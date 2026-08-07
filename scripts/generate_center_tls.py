#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a self-signed TLS certificate for the update center")
    parser.add_argument("--cert", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--common-name", default="jvlei-update-center")
    args = parser.parse_args()
    cert = Path(args.cert).resolve()
    key = Path(args.key).resolve()
    if cert.exists() or key.exists():
        raise SystemExit("refusing to overwrite an existing TLS certificate or key")
    cert.parent.mkdir(parents=True, exist_ok=True)
    key.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "825", "-subj", f"/CN={args.common_name}", "-keyout", str(key), "-out", str(cert)],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout or "OpenSSL failed").strip())
    print(f"Certificate: {cert}")
    print(f"Private key: {key}")


if __name__ == "__main__":
    main()
