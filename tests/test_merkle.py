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

    def test_three_leaves_rfc6962_split(self) -> None:
        # RFC 6962: split at the largest power of two < n; no duplication.
        t = MerkleTree([b"a", b"b", b"c"])
        la, lb, lc = _leaf(b"a"), _leaf(b"b"), _leaf(b"c")
        expected = _node(_node(la, lb), lc)
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


# --- RFC 6962 / Certificate Transparency reference vectors -------------------
# Leaves and roots as used by the Certificate Transparency reference test suite.
# Transcribed from memory; every root is confirmed by the naive RFC 6962
# transcription in TestAgainstNaiveRfc6962 below (an unconfirmed one must be removed).

CT_LEAVES = [
    b"",
    bytes.fromhex("00"),
    bytes.fromhex("10"),
    bytes.fromhex("2021"),
    bytes.fromhex("3031"),
    bytes.fromhex("40414243"),
    bytes.fromhex("5051525354555657"),
    bytes.fromhex("606162636465666768696a6b6c6d6e6f"),
]

CT_ROOTS = [
    "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125",
    "aeb6bcfe274b70a14fb067a5e5578264db0fa9b51af5e0ba159158f329e06e77",
    "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7",
    "4e3bbb1f7b478dcfe71fb631631519a3bca12c9aefca1612bfce4c13a86264d4",
    "76e67dadbcdf1e10e1b74ddc608abd2f98dfb16fbce75277b5232a127f2087ef",
    "ddb89be403809e325750d3d263cd78929c2942b7942a34b77e122c9594a74c8c",
    "5dc9da79a70659a9ad559cb701ded9a2ab9d823aad2f4960cfe370eff4604328",
]


class TestRfc6962Vectors:
    @pytest.mark.parametrize("n", range(1, 9))
    def test_ct_root_vectors(self, n: int) -> None:
        assert MerkleTree(CT_LEAVES[:n]).root_hex == CT_ROOTS[n - 1]

    @pytest.mark.parametrize("n", range(1, 9))
    def test_ct_inclusion_proofs_verify_for_all_leaves(self, n: int) -> None:
        tree = MerkleTree(CT_LEAVES[:n])
        for i in range(n):
            assert verify_inclusion(tree.proof(i), tree.root)

    def test_ct_audit_path_lengths(self) -> None:
        # RFC 6962 audit path lengths for an 8-leaf tree vs a 7-leaf tree.
        assert [len(MerkleTree(CT_LEAVES[:8]).proof(i).path) for i in range(8)] == [3] * 8
        assert [len(MerkleTree(CT_LEAVES[:7]).proof(i).path) for i in range(7)] == [
            3, 3, 3, 3, 3, 3, 2,
        ]

    def test_ct_inclusion_proof_known_path(self) -> None:
        # RFC 6962 audit path of leaf 0 in the 8-leaf tree: [H(1), H(2,3), H(4..7)].
        tree = MerkleTree(CT_LEAVES)
        leaf = [_leaf(x) for x in CT_LEAVES]
        n23 = _node(leaf[2], leaf[3])
        n4567 = _node(_node(leaf[4], leaf[5]), _node(leaf[6], leaf[7]))
        assert tree.proof(0).path == [leaf[1], n23, n4567]


class TestNoDuplicationAmbiguity:
    def test_abc_and_abcc_have_different_roots(self) -> None:
        # With "duplicate last node", these two trees collided (CVE-2012-2459 class).
        assert MerkleTree([b"a", b"b", b"c"]).root != MerkleTree([b"a", b"b", b"c", b"c"]).root


class TestVerifyInclusionStrictness:
    def test_leaf_index_must_be_below_tree_size(self) -> None:
        from dataclasses import replace

        tree = MerkleTree([b"a", b"b", b"c", b"d"])
        proof = tree.proof(1)
        assert not verify_inclusion(replace(proof, leaf_index=4), tree.root)
        assert not verify_inclusion(replace(proof, leaf_index=-1), tree.root)

    def test_path_with_wrong_length_rejected(self) -> None:
        from dataclasses import replace

        tree = MerkleTree([b"a", b"b", b"c", b"d"])
        proof = tree.proof(1)
        assert not verify_inclusion(replace(proof, path=proof.path[:-1]), tree.root)
        assert not verify_inclusion(replace(proof, path=[*proof.path, bytes(32)]), tree.root)

    def test_wrong_tree_size_rejected(self) -> None:
        from dataclasses import replace

        tree = MerkleTree([b"a", b"b", b"c", b"d"])
        proof = tree.proof(1)
        assert not verify_inclusion(replace(proof, tree_size=5), tree.root)

    def test_proof_for_every_size_and_index(self) -> None:
        for n in range(1, 34):
            tree = MerkleTree([f"x{i}".encode() for i in range(n)])
            for i in range(n):
                assert verify_inclusion(tree.proof(i), tree.root), (n, i)


# --- Cross-check against a naive, literal transcription of RFC 6962 §2.1 -----


def _mth(d: list[bytes]) -> bytes:
    """MTH(D[n]) exactly as written in RFC 6962 §2.1 (no caching, no cleverness)."""
    n = len(d)
    if n == 0:
        return _h(b"")
    if n == 1:
        return _leaf(d[0])
    k = 1
    while k * 2 < n:  # largest power of two strictly less than n
        k *= 2
    return _node(_mth(d[:k]), _mth(d[k:]))


def _path(m: int, d: list[bytes]) -> list[bytes]:
    """PATH(m, D[n]) exactly as written in RFC 6962 §2.1.1."""
    n = len(d)
    if n == 1:
        return []
    k = 1
    while k * 2 < n:
        k *= 2
    if m < k:
        return [*_path(m, d[:k]), _mth(d[k:])]
    return [*_path(m - k, d[k:]), _mth(d[:k])]


class TestAgainstNaiveRfc6962:
    def test_roots_and_proofs_for_all_sizes_1_to_200(self) -> None:
        for n in range(1, 201):
            data = [f"leaf-{n}-{i}".encode() for i in range(n)]
            tree = MerkleTree(data)
            assert tree.root == _mth(data), f"root differs at n={n}"
            for i in range(n):
                proof = tree.proof(i)
                assert proof.path == _path(i, data), f"path differs at n={n}, i={i}"
                assert verify_inclusion(proof, _mth(data)), f"verify failed at n={n}, i={i}"

    def test_memorised_ct_vectors_agree_with_naive_mth(self) -> None:
        # A vector that the naive transcription does not reproduce must be removed.
        for n in range(1, 9):
            assert _mth(CT_LEAVES[:n]).hex() == CT_ROOTS[n - 1], f"vector n={n} not confirmed"
