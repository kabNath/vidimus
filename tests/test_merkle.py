"""Tests for the SHA-256 Merkle tree."""

from __future__ import annotations

import hashlib

import pytest

from vidimus.audit.merkle import MerkleTree, verify_inclusion


def _h(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def _leaf(b: bytes) -> bytes:
    return _h(b"\x00" + b)


def _node(l: bytes, r: bytes) -> bytes:  # noqa: E741
    return _h(b"\x01" + l + r)


class TestConstruction:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            MerkleTree([])

    def test_single_leaf_root_is_leaf_hash(self) -> None:
        t = MerkleTree([b"abc"])
        assert t.root == _leaf(b"abc")
        assert t.size == 1

    def test_two_leaves(self) -> None:
        t = MerkleTree([b"a", b"b"])
        expected = _node(_leaf(b"a"), _leaf(b"b"))
        assert t.root == expected

    def test_three_leaves_duplicates_last(self) -> None:
        # With our chosen convention, an unpaired leaf duplicates itself.
        t = MerkleTree([b"a", b"b", b"c"])
        la, lb, lc = _leaf(b"a"), _leaf(b"b"), _leaf(b"c")
        ab = _node(la, lb)
        cc = _node(lc, lc)
        expected = _node(ab, cc)
        assert t.root == expected

    def test_four_leaves(self) -> None:
        t = MerkleTree([b"a", b"b", b"c", b"d"])
        la, lb, lc, ld = (_leaf(x) for x in (b"a", b"b", b"c", b"d"))
        ab = _node(la, lb)
        cd = _node(lc, ld)
        expected = _node(ab, cd)
        assert t.root == expected


class TestInclusionProofs:
    def test_proof_for_each_leaf_verifies(self) -> None:
        leaves = [f"item-{i}".encode() for i in range(7)]
        tree = MerkleTree(leaves)
        for i in range(7):
            proof = tree.proof(i)
            assert verify_inclusion(proof, tree.root), f"failed at index {i}"

    def test_proof_with_wrong_root_fails(self) -> None:
        leaves = [b"a", b"b", b"c", b"d"]
        tree = MerkleTree(leaves)
        proof = tree.proof(2)
        bogus_root = bytes(32)  # all zeros
        assert not verify_inclusion(proof, bogus_root)

    def test_proof_with_tampered_leaf_fails(self) -> None:
        leaves = [b"a", b"b", b"c", b"d"]
        tree = MerkleTree(leaves)
        proof = tree.proof(1)
        from dataclasses import replace

        tampered = replace(proof, leaf_hash=_leaf(b"x"))
        assert not verify_inclusion(tampered, tree.root)

    def test_proof_out_of_range(self) -> None:
        tree = MerkleTree([b"a", b"b"])
        with pytest.raises(IndexError):
            tree.proof(2)
        with pytest.raises(IndexError):
            tree.proof(-1)


class TestRootStability:
    def test_root_is_deterministic(self) -> None:
        leaves = [f"item-{i}".encode() for i in range(100)]
        r1 = MerkleTree(leaves).root
        r2 = MerkleTree(leaves).root
        assert r1 == r2

    def test_different_leaves_different_root(self) -> None:
        r1 = MerkleTree([b"a", b"b"]).root
        r2 = MerkleTree([b"a", b"c"]).root
        assert r1 != r2

    def test_hex_root_is_64_chars(self) -> None:
        t = MerkleTree([b"hello"])
        assert len(t.root_hex) == 64
        assert all(c in "0123456789abcdef" for c in t.root_hex)
