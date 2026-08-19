#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the offline printer-driver pack signing key")
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--public-key", required=True)
    args = parser.parse_args()
    private_path = Path(args.private_key).resolve()
    public_path = Path(args.public_key).resolve()
    if private_path.exists() or public_path.exists():
        raise SystemExit("refusing to overwrite an existing signing key")
    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    try:
        os.chmod(private_path, 0o600)
        os.chmod(public_path, 0o644)
    except OSError:
        pass
    print(private_path)
    print(public_path)


if __name__ == "__main__":
    main()
