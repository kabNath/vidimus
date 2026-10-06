"""Tests for Ed25519 signing and key management."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from vidimus.audit.keys import (
    generate_keypair,
    load_keypair,
    public_key_from_hex,
    save_keypair,
)
from vidimus.audit.signing import sign, sign_hex, verify, verify_hex


class TestKeypair:
    def test_generate(self) -> None:
        kp = generate_keypair()
        assert len(kp.fingerprint) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in kp.fingerprint)
        assert len(kp.public_key_hex) == 64  # 32 bytes hex

    def test_generate_produces_unique_keys(self) -> None:
        kps = {generate_keypair().fingerprint for _ in range(5)}
        assert len(kps) == 5

    def test_save_and_load_roundtrip(self) -> None:
        kp = generate_keypair()
        with tempfile.TemporaryDirectory() as tmp:
            priv_path, pub_path = save_keypair(kp, Path(tmp))
            assert priv_path.exists()
            assert pub_path.exists()

            loaded = load_keypair(priv_path)
            assert loaded.fingerprint == kp.fingerprint

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions not applicable on Windows")
    def test_private_key_has_restrictive_perms(self) -> None:
        kp = generate_keypair()
        with tempfile.TemporaryDirectory() as tmp:
            priv_path, _ = save_keypair(kp, Path(tmp))
            mode = priv_path.stat().st_mode & 0o777
            assert mode == 0o600, f"private key should be 0600, got {oct(mode)}"

    def test_public_key_from_hex_roundtrip(self) -> None:
        kp = generate_keypair()
        pubkey2 = public_key_from_hex(kp.public_key_hex)
        from cryptography.hazmat.primitives import serialization

        raw1 = kp.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        raw2 = pubkey2.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        assert raw1 == raw2

    def test_public_key_from_hex_rejects_wrong_length(self) -> None:
        with pytest.raises(ValueError):
            public_key_from_hex("ab" * 16)  # only 16 bytes


class TestSignVerify:
    def test_sign_verify_roundtrip(self) -> None:
        kp = generate_keypair()
        msg = b"hello, world"
        sig = sign(kp.private_key, msg)
        assert len(sig) == 64
        assert verify(kp.public_key, sig, msg)

    def test_verify_with_wrong_key_fails(self) -> None:
        kp1 = generate_keypair()
        kp2 = generate_keypair()
        msg = b"x"
        sig = sign(kp1.private_key, msg)
        assert not verify(kp2.public_key, sig, msg)

    def test_verify_with_tampered_message_fails(self) -> None:
        kp = generate_keypair()
        sig = sign(kp.private_key, b"original")
        assert not verify(kp.public_key, sig, b"tampered")

    def test_verify_with_tampered_signature_fails(self) -> None:
        kp = generate_keypair()
        msg = b"x"
        sig = sign(kp.private_key, msg)
        bad = bytearray(sig)
        bad[0] ^= 0x01
        assert not verify(kp.public_key, bytes(bad), msg)

    def test_hex_sign_verify_roundtrip(self) -> None:
        kp = generate_keypair()
        msg = b"hex-test"
        sig_hex = sign_hex(kp.private_key, msg)
        assert len(sig_hex) == 128  # 64 bytes hex
        assert verify_hex(kp.public_key, sig_hex, msg)

    def test_hex_verify_invalid_hex_returns_false(self) -> None:
        kp = generate_keypair()
        assert not verify_hex(kp.public_key, "not-hex", b"x")

    def test_hex_verify_wrong_length_returns_false(self) -> None:
        kp = generate_keypair()
        assert not verify_hex(kp.public_key, "ab" * 30, b"x")  # 60 bytes
