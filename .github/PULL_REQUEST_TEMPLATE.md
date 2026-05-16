<!-- Thank you for contributing to Vidimus. Please fill out every section. -->

## Motivation

Why is this change needed? Link the issue or discussion it addresses.

Fixes #

## Summary of changes

A clear description of what this PR does. Bullet points are fine.

-
-
-

## Breaking changes

- [ ] No breaking changes
- [ ] Yes, breaking changes (describe below and update `CHANGELOG.md`)

## How was this tested?

Describe the testing approach. Include new tests where applicable. For security-relevant changes, describe the threat model implications.

## Checklist

- [ ] I ran `make check` (lint + types + tests) locally and everything passes
- [ ] I added or updated tests for the change
- [ ] I updated documentation (README, ARCHITECTURE, docs/) if behavior visible to users changed
- [ ] I updated `CHANGELOG.md` under the `## [Unreleased]` section
- [ ] If this touches cryptographic primitives (Merkle, Ed25519, canonical JSON), I have flagged it for security review

## Cryptographic / security review

- [ ] This PR does not touch cryptographic code paths
- [ ] This PR touches cryptographic code; **two maintainer approvals required before merge**

## Additional context

Anything else reviewers should know.
