// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/// @title VidimusAnchor
/// @notice Minimal contract for anchoring Vidimus attestations on-chain.
/// @dev By design this contract has no storage, no admin, no upgradability.
///      Its sole purpose is to emit a timestamped, signed event for each anchor.
///      Verification is done by reading the event log via any RPC.
///
///      The anchorHash is expected to be:
///          keccak256(abi.encodePacked(merkleRoot, attestationHash, periodEnd))
///      where merkleRoot and attestationHash are SHA-256 outputs from the
///      Vidimus attestation, and periodEnd is the unix timestamp of the
///      attested period's end.
///
///      The workspaceId is an arbitrary 32-byte identifier chosen by the
///      issuer. The convention used by the Vidimus CLI is:
///          keccak256(abi.encodePacked(workspaceName))
///
/// @author Vidimus contributors
contract VidimusAnchor {
    /// @notice Emitted when an attestation is anchored.
    /// @param issuer The address that submitted the anchor (msg.sender).
    /// @param workspaceId Caller-defined workspace identifier (e.g. keccak256("acme-prod")).
    /// @param anchorHash Cryptographic commitment to the attestation contents.
    /// @param timestamp Block timestamp at the moment of anchoring.
    event Anchored(
        address indexed issuer,
        bytes32 indexed workspaceId,
        bytes32 anchorHash,
        uint64 timestamp
    );

    /// @notice Anchor a Vidimus attestation on-chain.
    /// @dev This function does nothing but emit an event. No storage is written.
    ///      Gas cost is dominated by event emission (~25,000 gas).
    /// @param workspaceId Caller-defined workspace identifier.
    /// @param anchorHash Cryptographic commitment to the attestation.
    function anchor(bytes32 workspaceId, bytes32 anchorHash) external {
        emit Anchored(msg.sender, workspaceId, anchorHash, uint64(block.timestamp));
    }

    /// @notice Anchor multiple attestations in a single transaction.
    /// @dev Useful for batched daily anchoring across many workspaces.
    /// @param workspaceIds Array of workspace identifiers.
    /// @param anchorHashes Array of cryptographic commitments, same length as workspaceIds.
    function anchorBatch(
        bytes32[] calldata workspaceIds,
        bytes32[] calldata anchorHashes
    ) external {
        require(
            workspaceIds.length == anchorHashes.length,
            "VidimusAnchor: length mismatch"
        );
        uint64 ts = uint64(block.timestamp);
        for (uint256 i = 0; i < workspaceIds.length; i++) {
            emit Anchored(msg.sender, workspaceIds[i], anchorHashes[i], ts);
        }
    }
}
