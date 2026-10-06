"""SHA-256 Merkle tree with inclusion proofs (RFC 6962 convention).

We follow the Certificate Transparency convention for tie-breaking and
node hashing because it has the broadest interoperability and known
test vectors. Specifically:

  leaf_hash = SHA-256(0x00 || data)
  node_hash = SHA-256(0x01 || left || right)

For n > 1 leaves the tree splits at k, the largest power of two strictly
less than n (RFC 6962 §2.1):

  MTH(D[n]) = node_hash(MTH(D[0:k]), MTH(D[k:n]))

No node is ever duplicated, so ``[a, b, c]`` and ``[a, b, c, c]`` have
different roots. (Duplicating the last node makes those two collide.)

Reference: RFC 6962 §2 (https://www.rfc-editor.org/rfc/rfc6962#section-2)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class InclusionProof:
    """Merkle inclusion proof for a single leaf.

    Given the proof, the leaf data, the leaf index, and the tree size,
    a verifier can recompute the Merkle root and check it matches.
    """

    leaf_index: int
    tree_size: int
    leaf_hash: bytes
    path: list[bytes]  # sibling hashes, bottom to top


def _hash_leaf(data: bytes) -> bytes:
    """RFC 6962 leaf hash: SHA-256(0x00 || data)."""
    return hashlib.sha256(b"\x00" + data).digest()


def _hash_node(left: bytes, right: bytes) -> bytes:
    """RFC 6962 node hash: SHA-256(0x01 || left || right)."""
    return hashlib.sha256(b"\x01" + left + right).digest()


def _split(n: int) -> int:
    """Largest power of two strictly less than ``n`` (``n`` >= 2)."""
    return 1 << ((n - 1).bit_length() - 1)


def _path_length(index: int, size: int) -> int:
    """Number of hashes in the RFC 6962 audit path of leaf ``index`` in a tree of ``size``."""
    length = 0
    while size > 1:
        k = _split(size)
        if index < k:
            size = k
        else:
            index -= k
            size -= k
        length += 1
    return length


class MerkleTree:
    """A SHA-256 Merkle tree built from a list of byte-string leaves.

    The tree follows RFC 6962 §2.1. It is built eagerly. For incremental
    construction (e.g. streaming trace ingestion), a future version will
    expose ``append`` and a Sparse Merkle Tree variant.
    """

    def __init__(self, leaves: list[bytes]):
        """Build a tree from the given list of leaf byte-strings.

        Args:
            leaves: Raw byte strings to be hashed as leaves. The hashing
                of each leaf with the 0x00 prefix is handled internally;
                pass the data as-is.

        Raises:
            ValueError: If ``leaves`` is empty.
        """
        if not leaves:
            raise ValueError("MerkleTree requires at least one leaf")
        self._leaves = list(leaves)
        self._leaf_hashes = [_hash_leaf(d) for d in leaves]
        self._cache: dict[tuple[int, int], bytes] = {}
        self._root = self._mth(0, len(self._leaf_hashes))

    def _mth(self, lo: int, hi: int) -> bytes:
        """Merkle tree hash of leaf hashes ``[lo, hi)``."""
        if hi - lo == 1:
            return self._leaf_hashes[lo]
        key = (lo, hi)
        cached = self._cache.get(key)
        if cached is None:
            mid = lo + _split(hi - lo)
            cached = _hash_node(self._mth(lo, mid), self._mth(mid, hi))
            self._cache[key] = cached
        return cached

    @property
    def root(self) -> bytes:
        """The Merkle root as raw bytes."""
        return self._root

    @property
    def root_hex(self) -> str:
        """The Merkle root as a hex string (lowercase)."""
        return self.root.hex()

    @property
    def size(self) -> int:
        """Number of leaves."""
        return len(self._leaves)

    def proof(self, index: int) -> InclusionProof:
        """Generate an inclusion proof for the leaf at ``index``.

        The path is the RFC 6962 audit path, ordered from the leaf's
        sibling up to the child of the root.

        Args:
            index: Zero-based leaf index.

        Returns:
            An InclusionProof that can be verified independently.

        Raises:
            IndexError: If ``index`` is out of range.
        """
        if not 0 <= index < self.size:
            raise IndexError(f"Leaf index {index} out of range [0, {self.size})")

        # Walk down from the root collecting siblings, then reverse to bottom-up.
        path: list[bytes] = []
        lo, hi, idx = 0, self.size, index
        while hi - lo > 1:
            mid = lo + _split(hi - lo)
            if idx < mid:
                path.append(self._mth(mid, hi))
                hi = mid
            else:
                path.append(self._mth(lo, mid))
                lo = mid
        path.reverse()

        return InclusionProof(
            leaf_index=index,
            tree_size=self.size,
            leaf_hash=self._leaf_hashes[index],
            path=path,
        )


def verify_inclusion(proof: InclusionProof, root: bytes) -> bool:
    """Verify an inclusion proof against an expected root (RFC 9162 §2.1.3.2).

    Rejects proofs whose ``leaf_index`` is outside ``[0, tree_size)`` or whose
    path length differs from the one required for that index and tree size.

    Args:
        proof: An InclusionProof produced by ``MerkleTree.proof()``.
        root: The expected Merkle root bytes.

    Returns:
        True if the proof reconstructs the given root, False otherwise.
    """
    if not 0 <= proof.leaf_index < proof.tree_size:
        return False
    if len(proof.path) != _path_length(proof.leaf_index, proof.tree_size):
        return False

    fn = proof.leaf_index
    sn = proof.tree_size - 1
    computed = proof.leaf_hash
    for sibling in proof.path:
        if sn == 0:
            return False
        if fn & 1 or fn == sn:
            computed = _hash_node(sibling, computed)
            if not fn & 1:
                while not fn & 1 and fn != 0:
                    fn >>= 1
                    sn >>= 1
        else:
            computed = _hash_node(computed, sibling)
        fn >>= 1
        sn >>= 1

    return sn == 0 and computed == root
