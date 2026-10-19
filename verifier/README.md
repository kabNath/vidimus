# Browser verifier

`index.html` is a single static page (no backend, no CDN, no network: its CSP forbids connections). Open it
locally (`file://`), via `http://localhost`, or over HTTPS (WebCrypto needs a secure context), load an
attestation, optionally paste the issuer fingerprint you trust, and press **Verify**.

It recomputes the canonical payload (same rules as `vidimus.audit.canonical`), verifies the Ed25519 signature
(WebCrypto, or an embedded BigInt implementation when the browser lacks Ed25519), the key/fingerprint match,
metric intervals, and the pinned issuer. It shows each check as **passed / failed / warning / not checked**.

**Not checked here, and shown as such:** the Merkle root against the traces (use `vidimus verify --traces`) and
the on-chain anchor (use `vidimus verify --check-anchor`). Without a pinned key the page says the signature
proves integrity, not identity.

`examples/` — `valid.json`, `tampered.json` (headline number edited after signing: signature fails),
`wrong-key.json` (valid signature by another key: passes unpinned, rejected when you pin `trusted-keys.txt`).
The keys are public demo keys derived from seed strings; regenerate with `python verifier/make_examples.py`.

Tests: `node verifier/test.mjs` (and `pytest tests/test_browser_verifier.py`, which also checks the page's
canonical form against Python on random values).
