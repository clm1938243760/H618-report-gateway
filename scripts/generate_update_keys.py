#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout or "OpenSSL command failed").strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Ed25519 update signing keys")
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--public-key", required=True)
    args = parser.parse_args()
    private_key = Path(args.private_key).resolve()
    public_key = Path(args.public_key).resolve()
    if private_key.exists() or public_key.exists():
        raise SystemExit("refusing to overwrite an existing update key")
    private_key.parent.mkdir(parents=True, exist_ok=True)
    public_key.parent.mkdir(parents=True, exist_ok=True)
    run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private_key)])
    run(["openssl", "pkey", "-in", str(private_key), "-pubout", "-out", str(public_key)])
    try:
        os.chmod(private_key, 0o600)
        os.chmod(public_key, 0o644)
    except OSError:
        pass
    print(f"Private key: {private_key}")
    print(f"Public key:  {public_key}")


if __name__ == "__main__":
    main()
