// Automated tests for verifier/index.html (no browser needed: the page's <script id="core"> is
// executed in a Node vm with Node's WebCrypto).
//   node verifier/test.mjs            run the checks
//   node verifier/test.mjs --canon    read a JSON array on stdin, print each value's canonical form
import { readFileSync } from "node:fs";
import { webcrypto, generateKeyPairSync, sign as nodeSign } from "node:crypto";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "index.html"), "utf8");
const core = /<script id="core">([\s\S]*?)<\/script>/.exec(html)[1];
const ctx = vm.createContext({ TextEncoder, Uint8Array, BigInt, Error, JSON, Object, Array, Number, String, Math, parseInt });
const V = vm.runInContext(core + "\n;VidimusVerifier", ctx);

if (process.argv.includes("--canon")) {
  const input = JSON.parse(readFileSync(0, "utf8"));
  process.stdout.write(JSON.stringify(input.map((v) => V.canonicalize(v))));
  process.exit(0);
}

if (process.argv.includes("--verify")) {   // node test.mjs --verify <file> [--pin <fp>] → JSON of check statuses
  const a = process.argv; const file = a[a.indexOf("--verify") + 1];
  const pin = a.includes("--pin") ? [a[a.indexOf("--pin") + 1]] : undefined;
  const r = await V.verifyAttestation(webcrypto, JSON.parse(readFileSync(file, "utf8")), { trustedKeys: pin });
  process.stdout.write(JSON.stringify({ ok: r.ok, status: Object.fromEntries(r.checks.map((c) => [c.id, c.status])) }));
  process.exit(0);
}

let failed = 0;
const check = (name, ok, extra = "") => { console.log(`${ok ? "ok  " : "FAIL"} ${name}${ok ? "" : "  " + extra}`); if (!ok) failed++; };
const load = (f) => JSON.parse(readFileSync(join(here, "examples", f), "utf8"));
const status = (r, id) => r.checks.find((c) => c.id === id)?.status;
const FP = readFileSync(join(here, "examples", "trusted-keys.txt"), "utf8").split("\n").find((l) => l && !l.startsWith("#")).trim();

// --- Ed25519 engines ----------------------------------------------------------------------
const hexOf = (s) => V.unhex(s);
{ // RFC 8032 §7.1 test vector 1 (empty message)
  const pk = hexOf("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a");
  const sig = hexOf("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b");
  check("embedded Ed25519: RFC 8032 vector 1 verifies", await V.verifyEmbedded(webcrypto, pk, sig, new Uint8Array(0)));
  check("embedded Ed25519: same vector, other message rejected", !(await V.verifyEmbedded(webcrypto, pk, sig, new Uint8Array([1]))));
}
{
  let agree = true, neg = true;
  for (let i = 0; i < 25; i++) {
    const { publicKey, privateKey } = generateKeyPairSync("ed25519");
    const raw = new Uint8Array(publicKey.export({ format: "der", type: "spki" })).slice(-32);
    const msg = webcrypto.getRandomValues(new Uint8Array(1 + i * 7));
    const sig = new Uint8Array(nodeSign(null, msg, privateKey));
    const a = await V.verifyEd25519(webcrypto, raw, sig, msg, "webcrypto");
    const b = await V.verifyEd25519(webcrypto, raw, sig, msg, "embedded");
    if (!(a.ok && b.ok)) agree = false;
    const bad = sig.slice(); bad[(i * 5) % 64] ^= 1;
    if ((await V.verifyEd25519(webcrypto, raw, bad, msg, "webcrypto")).ok || (await V.verifyEd25519(webcrypto, raw, bad, msg, "embedded")).ok) neg = false;
  }
  check("25 random keys/messages: WebCrypto and embedded both accept the real signature", agree);
  check("25 random keys/messages: a flipped signature bit is rejected by both", neg);
}

// --- examples -------------------------------------------------------------------------------
for (const engine of ["webcrypto", "embedded"]) {
  const valid = await V.verifyAttestation(webcrypto, load("valid.json"), { engine });
  check(`[${engine}] valid.json: signature passes, overall ok`, status(valid, "signature") === "pass" && valid.ok, JSON.stringify(valid.checks.filter((c) => c.status === "fail")));
  check(`[${engine}] valid.json without a pinned key: pinned = not_checked (with the warning text)`,
    status(valid, "pinned") === "not_checked" && valid.checks.find((c) => c.id === "pinned").detail === V.NOT_PINNED);
  check(`[${engine}] valid.json: Merkle root and anchor are reported as not checked`,
    status(valid, "merkle") === "not_checked" && status(valid, "anchor") === "not_checked");

  const pinned = await V.verifyAttestation(webcrypto, load("valid.json"), { engine, trustedKeys: [FP] });
  check(`[${engine}] valid.json pinned to the right fingerprint: pinned = pass`, status(pinned, "pinned") === "pass" && pinned.ok && pinned.pinned);

  const t = await V.verifyAttestation(webcrypto, load("tampered.json"), { engine, trustedKeys: [FP] });
  check(`[${engine}] TAMPERED: signature fails and the attestation is rejected`, status(t, "signature") === "fail" && !t.ok);
  const t2 = await V.verifyAttestation(webcrypto, load("tampered.json"), { engine });
  check(`[${engine}] TAMPERED, no pinned key: still rejected`, status(t2, "signature") === "fail" && !t2.ok);
  check("TAMPERED: the edit left the interval well-formed, so only the signature caught it", status(t, "metrics") === "pass");

  const w = await V.verifyAttestation(webcrypto, load("wrong-key.json"), { engine });
  check(`[${engine}] wrong-key.json unpinned: signature is valid (integrity only), pinned = not_checked`, status(w, "signature") === "pass" && w.ok && status(w, "pinned") === "not_checked");
  const wp = await V.verifyAttestation(webcrypto, load("wrong-key.json"), { engine, trustedKeys: [FP] });
  check(`[${engine}] wrong-key.json pinned to the real issuer: REJECTED`, status(wp, "pinned") === "fail" && !wp.ok);
}
{
  const pkHex = load("valid.json").issuer_pubkey;
  const r = await V.verifyAttestation(webcrypto, load("valid.json"), { trustedKeys: [pkHex.toUpperCase()] });
  check("pinning also accepts the raw public key (any case)", r.pinned && r.ok);
  const bad = load("valid.json"); bad.issuer_pubkey_fingerprint = "00".repeat(32);
  check("fingerprint mismatch is a failure", !(await V.verifyAttestation(webcrypto, bad)).ok);
  const wrongVer = load("valid.json"); wrongVer.version = "other";
  check("unsupported version is a failure", !(await V.verifyAttestation(webcrypto, wrongVer)).ok);
}

// --- canonicalisation spot checks (full cross-check against Python lives in tests/test_browser_verifier.py)
check("canonical: sorted keys, no spaces", V.canonicalize({ b: 1, a: [true, null, "x"] }) === '{"a":[true,null,"x"],"b":1}');
check("canonical: Python-style float repr", ["1e-05", "0.0001", "1.5e-07", "1e+16", "0.1"].every((s) => V.fmtNumber(Number(s)) === s));
check("canonical: integer-valued float prints as integer", V.canonicalize(1.0) === "1" && V.canonicalize(-0) === "0");

if (failed) { console.error(`\n${failed} check(s) failed`); process.exit(1); }
console.log("\nall verifier tests passed");
