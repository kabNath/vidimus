"""SHA-256 Merkle tree with inclusion proofs (RFC 6962 convention).

We follow the Certificate Transparency convention for tie-breaking and
node hashing because it has the broadest interoperability and known
test vectors. Specifically:

  leaf_hash = SHA-256(0x00 || data)
  node_hash = SHA-256(0x01 || left || right)

Odd levels duplicate the last node (rather than promoting it untouched).
This is a deliberate choice over the alternative "promote unpaired" rule;
it makes inclusion proofs uniform in length within a tree but slightly
inflates the tree. For our use case (auditable agent traces), uniformity
of proofs is more valuable than tree compactness.

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


class MerkleTree:
    """A SHA-256 Merkle tree built from a list of byte-string leaves.

    The tree is built eagerly. For incremental construction (e.g. streaming
    trace ingestion), a future version will expose ``append`` and a
    Sparse Merkle Tree variant.
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
        self._levels: list[list[bytes]] = [self._leaf_hashes]
        self._build()

    def _build(self) -> None:
        current = self._leaf_hashes
        while len(current) > 1:
            nxt: list[bytes] = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else current[i]
                nxt.append(_hash_node(left, right))
            self._levels.append(nxt)
            current = nxt

    @property
    def root(self) -> bytes:
        """The Merkle root as raw bytes."""
        return self._levels[-1][0]

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

        Args:
            index: Zero-based leaf index.

        Returns:
            An InclusionProof that can be verified independently.

        Raises:
            IndexError: If ``index`` is out of range.
        """
        if not 0 <= index < self.size:
            raise IndexError(f"Leaf index {index} out of range [0, {self.size})")

        path: list[bytes] = []
        idx = index
        for level in self._levels[:-1]:
            sibling_idx = idx ^ 1  # flip last bit
            if sibling_idx < len(level):
                path.append(level[sibling_idx])
            else:
                # Duplicate the last node (our chosen convention).
                path.append(level[idx])
            idx //= 2

        return InclusionProof(
            leaf_index=index,
            tree_size=self.size,
            leaf_hash=self._leaf_hashes[index],
            path=path,
        )


def verify_inclusion(proof: InclusionProof, root: bytes) -> bool:
    """Verify an inclusion proof against an expected root.

    Args:
        proof: An InclusionProof produced by ``MerkleTree.proof()``.
        root: The expected Merkle root bytes.

    Returns:
        True if the proof reconstructs the given root, False otherwise.
    """
    computed = proof.leaf_hash
    idx = proof.leaf_index

    for sibling in proof.path:
        if idx % 2 == 0:
            # We are the left child.
            computed = _hash_node(computed, sibling)
        else:
            # We are the right child.
            computed = _hash_node(sibling, computed)
        idx //= 2

    return computed == root
