"""Ed25519 key management for Vidimus issuers.

Local mode only in v0.1: keys are generated and stored as PEM files in
``~/.vidimus/keys/`` with file permissions 0600. KMS-backed signing
(AWS KMS, GCP KMS, Azure Key Vault, Vault) is on the roadmap and will
share this interface.

Security notes:
  - Private keys are never logged or printed.
  - File permissions are enforced to 0600 on creation.
  - Public-key fingerprints are SHA-256 of the raw 32-byte public key,
    hex-encoded. This is the identifier used in attestations.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


@dataclass(frozen=True)
class KeyPair:
    """An Ed25519 keypair with derived fingerprint."""

    private_key: Ed25519PrivateKey
    public_key: Ed25519PublicKey
    fingerprint: str  # hex-encoded SHA-256 of the 32-byte raw public key

    @property
    def public_key_hex(self) -> str:
        raw = self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return raw.hex()


def _fingerprint(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


def generate_keypair() -> KeyPair:
    """Generate a fresh Ed25519 keypair in memory.

    The keypair is not persisted; call ``save_keypair`` to write it to disk.
    """
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    return KeyPair(
        private_key=private,
        public_key=public,
        fingerprint=_fingerprint(public),
    )


def save_keypair(keypair: KeyPair, keys_dir: Path) -> tuple[Path, Path]:
    """Persist a keypair to ``keys_dir``.

    Files are named by fingerprint to allow multiple keys side by side
    and to make rotation straightforward.

    Args:
        keypair: The keypair to save.
        keys_dir: Directory in which to write the PEM files. Created with
            mode 0700 if it does not exist.

    Returns:
        (private_pem_path, public_pem_path).
    """
    keys_dir.mkdir(parents=True, exist_ok=True)
    # Enforce 0700 on the directory.
    os.chmod(keys_dir, 0o700)

    priv_path = keys_dir / f"{keypair.fingerprint}.priv.pem"
    pub_path = keys_dir / f"{keypair.fingerprint}.pub.pem"

    priv_pem = keypair.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = keypair.public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Write private with 0600 immediately.
    fd = os.open(str(priv_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, priv_pem)
    finally:
        os.close(fd)

    pub_path.write_bytes(pub_pem)
    os.chmod(pub_path, 0o644)

    return priv_path, pub_path


def load_keypair(priv_path: Path) -> KeyPair:
    """Load a keypair from a PEM-encoded private key file."""
    pem = priv_path.read_bytes()
    private = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError(f"{priv_path} is not an Ed25519 private key")
    public = private.public_key()
    return KeyPair(
        private_key=private,
        public_key=public,
        fingerprint=_fingerprint(public),
    )


def load_public_key(pub_path: Path) -> tuple[Ed25519PublicKey, str]:
    """Load a public key from PEM. Returns the key and its fingerprint."""
    pem = pub_path.read_bytes()
    public = serialization.load_pem_public_key(pem)
    if not isinstance(public, Ed25519PublicKey):
        raise ValueError(f"{pub_path} is not an Ed25519 public key")
    return public, _fingerprint(public)


def public_key_from_hex(hex_str: str) -> Ed25519PublicKey:
    """Reconstruct a public key from its 64-character hex encoding."""
    raw = bytes.fromhex(hex_str)
    if len(raw) != 32:
        raise ValueError(f"Ed25519 public key must be 32 bytes, got {len(raw)}")
    return Ed25519PublicKey.from_public_bytes(raw)
