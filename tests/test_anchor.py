"""Tests for the on-chain anchoring module.

These tests mock web3.py so they run without a live RPC endpoint.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from vidimus.audit.schemas import Attestation


def _make_attestation() -> Attestation:
    """Build a minimal valid Attestation for testing."""
    return Attestation(
        version="vidimus.attestation.v1",
        workspace="test-workspace",
        issued_at=datetime.now(timezone.utc),
        period_start=datetime.now(timezone.utc),
        period_end=datetime.now(timezone.utc),
        merkle_root="ab" * 32,
        trace_count=42,
        metrics=[],
        issuer_pubkey_fingerprint="cd" * 32,
        issuer_pubkey="11" * 32,
        onchain_anchor=None,
        signature="ef" * 32,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pure functions (no web3 required)
# ─────────────────────────────────────────────────────────────────────────────


class TestPureFunctions:
    def test_workspace_to_bytes32_deterministic(self):
        from vidimus.audit.anchor import workspace_to_bytes32

        a = workspace_to_bytes32("acme-prod")
        b = workspace_to_bytes32("acme-prod")
        assert a == b
        assert len(a) == 32

    def test_workspace_to_bytes32_different_inputs(self):
        from vidimus.audit.anchor import workspace_to_bytes32

        assert workspace_to_bytes32("ws-a") != workspace_to_bytes32("ws-b")

    def test_compute_anchor_hash_deterministic(self):
        from vidimus.audit.anchor import compute_anchor_hash

        att = _make_attestation()
        h1 = compute_anchor_hash(att)
        h2 = compute_anchor_hash(att)
        assert h1 == h2
        assert len(h1) == 32

    def test_compute_anchor_hash_excludes_signature(self):
        """Two attestations differing only in signature should produce
        the same anchor hash, because we want the anchor to be stable
        independent of the signature field."""
        from vidimus.audit.anchor import compute_anchor_hash

        att1 = _make_attestation()
        att2 = att1.model_copy(update={"signature": "00" * 32})
        assert compute_anchor_hash(att1) == compute_anchor_hash(att2)


# ─────────────────────────────────────────────────────────────────────────────
# OnchainAnchorer (mocked web3)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_web3():
    """Patch web3.Web3 with a controlled mock."""
    # We need web3 to be importable; the real package may not be installed.
    # Inject a fake web3 module if absent.
    if "web3" not in sys.modules:
        fake_web3 = MagicMock()
        fake_web3.Web3.HTTPProvider = MagicMock(return_value=MagicMock())
        sys.modules["web3"] = fake_web3

    with patch("web3.Web3") as MockWeb3:
        w3_instance = MagicMock()
        w3_instance.is_connected.return_value = True
        w3_instance.eth.chain_id = 56  # BSC mainnet
        w3_instance.eth.gas_price = 5_000_000_000
        w3_instance.eth.get_transaction_count.return_value = 7
        w3_instance.eth.send_raw_transaction.return_value = b"\xaa" * 32
        contract = MagicMock()
        contract.functions.anchor.return_value.build_transaction.return_value = {
            "to": "0xanchor",
            "value": 0,
            "data": "0x",
        }
        w3_instance.eth.contract.return_value = contract
        w3_instance.eth.account.from_key.return_value.address = "0xDeadBeef"
        signed_tx = MagicMock()
        signed_tx.raw_transaction = b"\xbb" * 100
        w3_instance.eth.account.sign_transaction.return_value = signed_tx

        MockWeb3.return_value = w3_instance
        MockWeb3.HTTPProvider = MagicMock(return_value=MagicMock())
        MockWeb3.to_checksum_address = lambda x: x

        yield w3_instance, contract


class TestAnchorer:
    def test_import_error_without_web3(self):
        # Hide web3 module entirely
        with patch.dict("sys.modules", {"web3": None}):
            from vidimus.audit.anchor import OnchainAnchorer

            with pytest.raises(ImportError, match="vidimus\\[onchain\\]"):
                OnchainAnchorer(
                    rpc_url="https://example.com",
                    contract_address="0x0000000000000000000000000000000000000000",
                )

    def test_anchor_returns_tx_hash(self, mock_web3):
        from vidimus.audit.anchor import OnchainAnchorer

        _w3_instance, contract = mock_web3
        anchorer = OnchainAnchorer(
            rpc_url="https://example.com",
            contract_address="0x0000000000000000000000000000000000000000",
            private_key="0x" + "00" * 32,
        )
        att = _make_attestation()
        tx_hash = anchorer.anchor(att)
        assert tx_hash == "aa" * 32
        contract.functions.anchor.assert_called_once()

    def test_anchor_without_private_key_raises(self, mock_web3):
        from vidimus.audit.anchor import OnchainAnchorer

        anchorer = OnchainAnchorer(
            rpc_url="https://example.com",
            contract_address="0x0000000000000000000000000000000000000000",
        )
        att = _make_attestation()
        with pytest.raises(RuntimeError, match="read-only"):
            anchorer.anchor(att)

    def test_verify_anchor_found(self, mock_web3):
        from vidimus.audit.anchor import OnchainAnchorer, compute_anchor_hash, workspace_to_bytes32

        _w3_instance, contract = mock_web3

        att = _make_attestation()
        expected_hash = compute_anchor_hash(att)

        # Mock event filter to return one matching event
        matching_event = {
            "blockNumber": 12345,
            "transactionHash": b"\xcc" * 32,
            "args": {
                "issuer": "0xIssuer",
                "workspaceId": workspace_to_bytes32(att.workspace),
                "anchorHash": expected_hash,
                "timestamp": 1700000000,
            },
        }
        event_filter = MagicMock()
        event_filter.get_all_entries.return_value = [matching_event]
        contract.events.Anchored.create_filter.return_value = event_filter

        anchorer = OnchainAnchorer(
            rpc_url="https://example.com",
            contract_address="0x0000000000000000000000000000000000000000",
        )
        found = anchorer.verify_anchor(att)
        assert found is not None
        assert found.block_number == 12345
        assert found.anchor_hash == expected_hash.hex()

    def test_verify_anchor_not_found(self, mock_web3):
        from vidimus.audit.anchor import OnchainAnchorer

        _w3_instance, contract = mock_web3

        event_filter = MagicMock()
        event_filter.get_all_entries.return_value = []
        contract.events.Anchored.create_filter.return_value = event_filter

        anchorer = OnchainAnchorer(
            rpc_url="https://example.com",
            contract_address="0x0000000000000000000000000000000000000000",
        )
        assert anchorer.verify_anchor(_make_attestation()) is None
