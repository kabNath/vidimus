# Vidimus Smart Contracts

This directory contains the on-chain components of Vidimus.

## VidimusAnchor.sol

A minimal contract for anchoring attestation hashes on-chain. See [ARCHITECTURE.md §7](../ARCHITECTURE.md) for the rationale.

### Properties

- **No storage.** The contract writes nothing to chain state. It only emits events.
- **No admin.** No owner, no upgradability, no kill switch.
- **No proxy.** Direct deployment, immutable bytecode.
- **Tiny.** ~80 lines of Solidity, ~25,000 gas per anchor.

These properties are intentional. The contract is a public timestamp service, nothing more. Anyone can deploy a copy.

### Planned canonical deployments

| Chain | Status | Address |
|---|---|---|
| BNB Chain mainnet (56) | Planned Phase 2 | TBD |
| Base mainnet (8453) | Planned Phase 2 | TBD |
| Ethereum mainnet (1) | Planned Phase 3 | TBD |

Until these are deployed, users can compile and deploy the contract themselves. The SDK will accept any contract address that matches the bytecode hash.

### Build & deploy

```bash
# Install Foundry if you don't have it
curl -L https://foundry.paradigm.xyz | bash
foundryup

# From the contracts/ directory
forge build
forge test  # (tests TBD)

# Deploy
forge create VidimusAnchor.sol:VidimusAnchor \
  --rpc-url $RPC_URL \
  --private-key $PRIVATE_KEY \
  --verify --etherscan-api-key $ETHERSCAN_API_KEY
```

### Verify integrity

Before trusting a deployed contract:

```bash
# 1. Compile locally and compute bytecode hash
forge inspect VidimusAnchor bytecode | sha256sum

# 2. Fetch deployed bytecode and compare
cast code <CONTRACT_ADDRESS> --rpc-url $RPC_URL | sha256sum
```

Hashes must match. If they don't, the deployment is not the canonical contract.

### Verification on block explorers

All canonical deployments will be verified on the respective block explorer (Etherscan, BscScan, BaseScan). The verified source matches this directory exactly.
