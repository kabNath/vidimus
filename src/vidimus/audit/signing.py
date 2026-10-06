"""Ed25519 signature primitives.

Thin wrappers over ``cryptography.hazmat.primitives.asymmetric.ed25519``
to keep call sites clean and to centralize the byte/hex encoding choices.
"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def sign(private_key: Ed25519PrivateKey, message: bytes) -> bytes:
    """Sign ``message`` with the given Ed25519 private key. Returns 64 bytes."""
    return private_key.sign(message)


def verify(public_key: Ed25519PublicKey, signature: bytes, message: bytes) -> bool:
    """Verify a signature. Returns True on success, False on failure.

    Note: we deliberately catch ``InvalidSignature`` and return a bool
    instead of raising, because verification is often a control-flow
    decision (e.g. CLI exit code) rather than an exceptional case.
    """
    try:
        public_key.verify(signature, message)
        return True
    except InvalidSignature:
        return False


def sign_hex(private_key: Ed25519PrivateKey, message: bytes) -> str:
    """Sign and return the hex-encoded signature."""
    return sign(private_key, message).hex()


def verify_hex(public_key: Ed25519PublicKey, signature_hex: str, message: bytes) -> bool:
    """Verify a hex-encoded signature."""
    try:
        sig = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    if len(sig) != 64:
        return False
    return verify(public_key, sig, message)
