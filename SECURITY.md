# Security Policy

## Reporting a vulnerability

Vidimus handles cryptographic primitives (Ed25519 signatures, SHA-256 Merkle trees, RFC 8785 canonical JSON). Bugs in these can cause undetectable trust failures. We take security reports seriously.

**Do not file public issues for security vulnerabilities.** Instead, please email **security@vidimus.ai** with:

- A description of the vulnerability
- Steps to reproduce
- An assessment of the impact
- Any suggested mitigation

You should receive an acknowledgement within 72 hours. We aim to issue a fix within 14 days for high-severity issues, 30 days for medium, and 90 days for low.

If you do not receive a response within 7 days, please contact the maintainer directly via the email listed in the GitHub profile of `@vidimus-ai` org owners.

## Disclosure policy

We follow coordinated disclosure:

1. The reporter contacts us privately.
2. We confirm the issue and develop a fix.
3. We publish a fix, a security advisory, and credit the reporter (unless they prefer to remain anonymous).
4. We request a 90-day embargo from the date of report before public disclosure, extendable if the fix requires complex coordination.

## In scope

- Cryptographic primitive implementations (`vidimus.audit.merkle`, `vidimus.audit.signing`, `vidimus.audit.canonical`)
- Attestation verification logic (`vidimus.audit.attest.verify`)
- Key management (`vidimus.audit.keys`)
- The on-chain anchor smart contract (`contracts/VidimusAnchor.sol`)
- Any path that could allow an attacker to:
  - Forge a valid attestation without the signing key
  - Cause `verify()` to return `True` on a tampered attestation
  - Cause `verify()` to return `False` on a valid attestation
  - Read private keys from disk despite documented permission requirements
  - Bypass canonical JSON determinism to construct hash collisions

## Out of scope

- Issues in dependencies (report those upstream; we will pull in fixes promptly)
- Denial-of-service attacks via resource exhaustion (Vidimus is not currently hardened for adversarial inputs at the ingestion layer; this is a known limitation)
- Issues in example code under `examples/`
- Social engineering attacks against maintainers
- Vulnerabilities requiring physical access to a developer's machine

## Supported versions

During alpha (0.x), only the latest released minor version receives security fixes.

After 1.0, the latest minor version and the previous minor receive fixes for 6 months.

## Cryptographic review

If you are a cryptographer interested in formally reviewing the Vidimus attestation protocol, please reach out at **security@vidimus.ai**. We welcome external review and can arrange paid engagement for in-depth audits.

## Bug bounty

We do not currently operate a paid bug bounty program. We will publicly credit reporters in release notes, the SECURITY-HALL-OF-FAME.md file, and the project Twitter, with the reporter's consent.
