"""On-chain anchoring of Vidimus attestations.

Publishes the Merkle root + attestation hash to an EVM chain via the
``VidimusAnchor`` contract. This provides non-repudiable timestamping: the
issuer cannot later claim a different state of affairs because the on-chain
event predates any later modification.

The anchor adds **no cryptographic strength** to the attestation — the
Ed25519 signature is already unforgeable. What the anchor adds is a
publicly-verifiable, immutable timestamp.

Requires the optional dependency:

    pip install vidimus[onchain]

Supported chains (RPC URLs are configurable):
  - BNB Chain (mainnet + testnet)
  - Ethereum (mainnet + Sepolia)
  - Base (mainnet)
  - Any EVM-compatible chain

Example:

    from vidimus.audit.anchor import OnchainAnchorer

    anchorer = OnchainAnchorer(
        rpc_url="https://bsc-dataseed.binance.org/",
        contract_address="0x...",
        private_key=os.environ["ANCHOR_KEY"],
    )
    tx_hash = anchorer.anchor(attestation)
    print(f"Anchored at {tx_hash}")

    # Later, anyone can verify:
    found = anchorer.verify_anchor(attestation)
    assert found.timestamp <= attestation.issued_at
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from vidimus.audit.canonical import canonicalize
from vidimus.audit.schemas import Attestation

if TYPE_CHECKING:
    from web3 import Web3  # noqa: F401

logger = logging.getLogger(__name__)


# Minimal ABI for the VidimusAnchor contract (matches contracts/VidimusAnchor.sol)
VIDIMUS_ANCHOR_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "issuer", "type": "address"},
            {"indexed": True, "internalType": "bytes32", "name": "workspaceId", "type": "bytes32"},
            {"indexed": False, "internalType": "bytes32", "name": "anchorHash", "type": "bytes32"},
            {"indexed": False, "internalType": "uint64", "name": "timestamp", "type": "uint64"},
        ],
        "name": "Anchored",
        "type": "event",
    },
    {
        "inputs": [
            {"internalType": "bytes32", "name": "workspaceId", "type": "bytes32"},
            {"internalType": "bytes32", "name": "anchorHash", "type": "bytes32"},
        ],
        "name": "anchor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


# Default RPC endpoints for common chains. Users can override.
DEFAULT_RPC_URLS = {
    "bsc-mainnet":     "https://bsc-dataseed.binance.org/",
    "bsc-testnet":     "https://data-seed-prebsc-1-s1.binance.org:8545/",
    "ethereum":        "https://eth.llamarpc.com",
    "ethereum-sepolia": "https://rpc.sepolia.org",
    "base":            "https://mainnet.base.org",
}


@dataclass(frozen=True)
class AnchorEvent:
    """A successful on-chain anchoring event."""

    chain_id: int
    block_number: int
    tx_hash: str
    issuer_address: str
    workspace_id: str
    anchor_hash: str
    timestamp: datetime


def compute_anchor_hash(attestation: Attestation) -> bytes:
    """Compute the 32-byte hash that gets anchored on-chain.

    keccak256-like but using SHA-256 for consistency with the rest of Vidimus:
      anchor_hash = SHA-256(merkle_root || attestation_canonical_hash)
    """
    merkle_root_bytes = bytes.fromhex(attestation.merkle_root)
    att_payload = attestation.model_dump(mode="json")
    att_payload["signature"] = ""  # detached-signature pattern
    att_hash = hashlib.sha256(canonicalize(att_payload)).digest()
    return hashlib.sha256(merkle_root_bytes + att_hash).digest()


def workspace_to_bytes32(workspace: str) -> bytes:
    """Map an arbitrary-length workspace name to a deterministic 32-byte id."""
    return hashlib.sha256(workspace.encode("utf-8")).digest()


class OnchainAnchorer:
    """Anchor and verify Vidimus attestations on an EVM chain.

    Args:
        rpc_url: HTTP(S) URL of the chain's JSON-RPC endpoint.
        contract_address: Deployed ``VidimusAnchor`` contract address.
        private_key: Hex-encoded private key of the issuer account. Optional —
            only needed for anchoring (writes). Verification (reads) does not.
        chain_id: Override the chain id auto-detected from the RPC. Optional.
        gas_limit: Per-transaction gas cap. Default 100k (plenty for the anchor).
    """

    def __init__(
        self,
        rpc_url: str,
        contract_address: str,
        private_key: str | None = None,
        chain_id: int | None = None,
        gas_limit: int = 100_000,
    ):
        try:
            from web3 import Web3
        except ImportError as exc:
            raise ImportError(
                "OnchainAnchorer requires the 'web3' package. "
                "Install with: pip install vidimus[onchain]"
            ) from exc

        self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        if not self._w3.is_connected():
            raise ConnectionError(f"Could not connect to RPC at {rpc_url}")

        self._contract = self._w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=VIDIMUS_ANCHOR_ABI,
        )
        self._private_key = private_key
        self._chain_id = chain_id if chain_id is not None else self._w3.eth.chain_id
        self._gas_limit = gas_limit
        self._account_address: str | None = None
        if private_key:
            account = self._w3.eth.account.from_key(private_key)
            self._account_address = account.address

    def anchor(self, attestation: Attestation) -> str:
        """Anchor an attestation on-chain. Returns the transaction hash."""
        if not self._private_key or not self._account_address:
            raise RuntimeError(
                "anchor() requires a private_key in the constructor; "
                "this instance is read-only"
            )

        workspace_id = workspace_to_bytes32(attestation.workspace)
        anchor_hash = compute_anchor_hash(attestation)

        nonce = self._w3.eth.get_transaction_count(self._account_address)
        tx = self._contract.functions.anchor(workspace_id, anchor_hash).build_transaction(
            {
                "from": self._account_address,
                "nonce": nonce,
                "chainId": self._chain_id,
                "gas": self._gas_limit,
                "gasPrice": self._w3.eth.gas_price,
            }
        )
        signed = self._w3.eth.account.sign_transaction(tx, self._private_key)
        # web3.py 6.x uses .rawTransaction, 7.x uses .raw_transaction
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
        tx_hash = self._w3.eth.send_raw_transaction(raw)
        logger.info("Anchored attestation %s on chain %d (tx=%s)",
                    attestation.workspace, self._chain_id, tx_hash.hex())
        return tx_hash.hex()

    def verify_anchor(
        self,
        attestation: Attestation,
        from_block: int | str = "earliest",
        to_block: int | str = "latest",
    ) -> AnchorEvent | None:
        """Search the chain for an anchor event matching this attestation.

        Returns the matching ``AnchorEvent`` or ``None`` if no anchor is found.
        """
        workspace_id = workspace_to_bytes32(attestation.workspace)
        anchor_hash = compute_anchor_hash(attestation)

        event_filter = self._contract.events.Anchored.create_filter(
            from_block=from_block,
            to_block=to_block,
            argument_filters={"workspaceId": workspace_id},
        )

        for log in event_filter.get_all_entries():
            if log["args"]["anchorHash"] == anchor_hash:
                return AnchorEvent(
                    chain_id=self._chain_id,
                    block_number=log["blockNumber"],
                    tx_hash=log["transactionHash"].hex(),
                    issuer_address=log["args"]["issuer"],
                    workspace_id=workspace_id.hex(),
                    anchor_hash=anchor_hash.hex(),
                    timestamp=datetime.fromtimestamp(log["args"]["timestamp"], tz=timezone.utc),
                )
        return None
