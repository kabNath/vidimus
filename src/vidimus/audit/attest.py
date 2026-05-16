"""High-level attestation orchestration: build, sign, and verify reports.

This module is the user-visible glue layer over the cryptographic and
statistical primitives. ``attest()`` produces a signed Attestation;
``verify()`` checks one offline given only the file and the issuer's
public key (which is also embedded in the attestation, so verification
is fully self-contained for casual checks; a separate ``keys.txt`` lookup
is recommended for higher-assurance verification).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from vidimus.audit.canonical import canonicalize
from vidimus.audit.judges import Judge, build_judges
from vidimus.audit.keys import KeyPair, public_key_from_hex
from vidimus.audit.merkle import MerkleTree
from vidimus.audit.schemas import (
    Attestation,
    CalibratedMetric,
)
from vidimus.audit.signing import sign_hex, verify_hex
from vidimus.audit.uncertainty import (
    bootstrap_ci,
    cohens_kappa,
    fleiss_kappa,
)
from vidimus.config import get_config


def attest(
    metrics: Sequence[str],
    period_start: datetime,
    period_end: datetime,
    keypair: KeyPair,
    judges: list[str] | list[Judge] | None = None,
    bootstrap_iterations: int = 1000,
    workspace: str | None = None,
    seed: int | None = None,
) -> Attestation:
    """Build, evaluate, and sign an attestation over a time window.

    The function:
      1. Pulls all traces in ``[period_start, period_end]`` from the active store.
      2. Builds a Merkle tree over their canonical JSON forms.
      3. Runs each ``metric`` through each configured ``judge``.
      4. Computes a calibrated CI for each metric.
      5. Computes inter-judge agreement (Cohen's κ for 2 judges, Fleiss's κ for 3+).
      6. Signs the resulting Attestation with the issuer's private key.

    Args:
        metrics: List of metric names to evaluate (e.g. ["hallucination"]).
        period_start: Inclusive start of the audit window.
        period_end: Inclusive end of the audit window.
        keypair: Issuer's Ed25519 keypair.
        judges: List of judge identifiers (strings) or instantiated Judges.
            Defaults to those configured in ``vidimus.init()``.
        bootstrap_iterations: Number of bootstrap resamples per metric.
        workspace: Override the workspace name. Defaults to config.
        seed: Optional RNG seed for reproducible bootstrap CIs.

    Returns:
        A signed Attestation.

    Raises:
        ValueError: If no traces are found in the window, or if metric
            evaluation fails for all judges.
    """
    config = get_config()
    workspace = workspace or config.workspace

    # Step 1: gather traces.
    traces = config.store.list_traces(
        workspace=workspace,
        start=period_start,
        end=period_end,
    )
    if not traces:
        raise ValueError(
            f"No traces found in window [{period_start.isoformat()}, "
            f"{period_end.isoformat()}] for workspace '{workspace}'"
        )

    # Step 2: build Merkle tree over canonical-JSON traces.
    leaves = [canonicalize(t.model_dump(mode="json")) for t in traces]
    tree = MerkleTree(leaves)

    # Step 3: instantiate judges.
    if judges is None:
        judge_instances = build_judges(config.judges)
    elif isinstance(judges[0], str):
        judge_instances = build_judges(judges)
    else:
        judge_instances = list(judges)

    # Step 4–5: evaluate metrics with multi-judge agreement.
    calibrated: list[CalibratedMetric] = []
    for metric in metrics:
        per_judge_scores: list[list[float]] = []
        for j in judge_instances:
            per_judge_scores.append([j.score(t, metric) for t in traces])

        # Aggregate per trace (majority vote / median).
        aggregated: list[float] = []
        for i in range(len(traces)):
            values = [scores[i] for scores in per_judge_scores]
            aggregated.append(_aggregate(values))

        # Bootstrap CI on the aggregated values.
        ci = bootstrap_ci(
            aggregated,
            iterations=bootstrap_iterations,
            seed=seed,
        )

        # Inter-judge agreement.
        agreement = _judge_agreement(per_judge_scores)

        calibrated.append(
            CalibratedMetric(
                name=metric,
                point_estimate=ci.point_estimate,
                ci_low=ci.ci_low,
                ci_high=ci.ci_high,
                n=ci.n,
                method="llm_judge",
                judges=[j.name for j in judge_instances],
                judge_agreement=agreement,
                bootstrap_iterations=bootstrap_iterations,
            )
        )

    # Step 6: build & sign the attestation.
    attestation = Attestation(
        workspace=workspace,
        period_start=period_start,
        period_end=period_end,
        merkle_root=tree.root_hex,
        trace_count=tree.size,
        metrics=calibrated,
        issuer_pubkey_fingerprint=keypair.fingerprint,
        issuer_pubkey=keypair.public_key_hex,
        onchain_anchor=None,
    )
    payload = attestation.to_signing_payload()
    sig_hex = sign_hex(keypair.private_key, payload)

    # Re-create the Attestation with the signature populated. Pydantic models
    # are frozen at the field level only where declared; Attestation isn't,
    # so we can model_copy.
    signed = attestation.model_copy(update={"signature": sig_hex})
    return signed


def verify(attestation: Attestation) -> tuple[bool, list[str], list[str]]:
    """Verify an attestation cryptographically and statistically.

    Checks performed:
      1. The embedded public key matches the embedded fingerprint.   (fatal)
      2. Ed25519 signature is valid over canonical JSON.              (fatal)
      3. Metric CIs are well-formed (low <= point <= high).           (fatal)
      4. Inter-judge agreement >= 0.4 on LLM-judge metrics.           (warning)

    The distinction matters: a valid signature with low judge agreement
    means the attestation is *cryptographically authentic* but its metric
    values should be treated as low-confidence. A failed signature means
    the document has been tampered with or fabricated.

    Returns:
        ``(ok, issues, warnings)``.
        ``ok`` is True iff no fatal issues were found.
        ``issues`` lists fatal problems (signature, fingerprint, malformed CI).
        ``warnings`` lists non-fatal concerns (low agreement, etc.).
    """
    issues: list[str] = []
    warnings: list[str] = []

    # 1. Fingerprint consistency.
    try:
        pubkey = public_key_from_hex(attestation.issuer_pubkey)
    except ValueError as e:
        return False, [f"invalid public key encoding: {e}"], []

    import hashlib

    raw_pk = bytes.fromhex(attestation.issuer_pubkey)
    derived_fp = hashlib.sha256(raw_pk).hexdigest()
    if derived_fp != attestation.issuer_pubkey_fingerprint:
        issues.append(
            f"fingerprint mismatch: embedded={attestation.issuer_pubkey_fingerprint}, "
            f"derived={derived_fp}"
        )

    # 2. Signature check.
    payload = attestation.to_signing_payload()
    if not verify_hex(pubkey, attestation.signature, payload):
        issues.append("Ed25519 signature does not verify")

    # 3. Metric CIs (fatal: malformed CI is a structural bug).
    for m in attestation.metrics:
        if not (m.ci_low <= m.point_estimate <= m.ci_high):
            issues.append(
                f"metric '{m.name}': point estimate {m.point_estimate} is outside "
                f"CI [{m.ci_low}, {m.ci_high}]"
            )

    # 4. Inter-judge agreement (non-fatal).
    for m in attestation.metrics:
        if m.judge_agreement is not None and m.judge_agreement < 0.4:
            warnings.append(
                f"metric '{m.name}': low inter-judge agreement (κ={m.judge_agreement:.2f}); "
                f"interpret with extra caution"
            )

    return len(issues) == 0, issues, warnings


# --- Helpers ----------------------------------------------------------


def _aggregate(values: list[float]) -> float:
    """Aggregate per-judge scores for a single trace.

    For binary-valued judges, this is majority vote (with ties broken by
    rounding 0.5 up to 1.0). For continuous scores, median.
    """
    if not values:
        return 0.0
    # Heuristic: if all values are in {0.0, 1.0}, treat as binary.
    if all(v in (0.0, 1.0) for v in values):
        return 1.0 if sum(values) >= len(values) / 2 else 0.0
    sorted_v = sorted(values)
    mid = len(sorted_v) // 2
    if len(sorted_v) % 2 == 0:
        return (sorted_v[mid - 1] + sorted_v[mid]) / 2
    return sorted_v[mid]


def _judge_agreement(per_judge_scores: list[list[float]]) -> float | None:
    """Compute the appropriate agreement coefficient given the judge count and scale."""
    if len(per_judge_scores) < 2:
        return None

    # If all scores are binary, use kappa.
    all_binary = all(v in (0.0, 1.0) for scores in per_judge_scores for v in scores)
    if all_binary:
        int_scores = [[int(v) for v in scores] for scores in per_judge_scores]
        if len(int_scores) == 2:
            return cohens_kappa(int_scores[0], int_scores[1])
        # Reshape to per-item lists for Fleiss.
        n_items = len(int_scores[0])
        per_item = [[int_scores[r][i] for r in range(len(int_scores))] for i in range(n_items)]
        return fleiss_kappa(per_item)

    # Continuous scale: use a simple Pearson correlation as a placeholder.
    # Krippendorff's alpha is also computable; we defer the full implementation
    # to v0.2 where it'll be plumbed through with a level argument.
    import numpy as np

    arr = np.asarray(per_judge_scores)
    if arr.shape[0] == 2:
        # Pearson between two raters.
        x, y = arr[0], arr[1]
        if np.std(x) < 1e-12 or np.std(y) < 1e-12:
            return 1.0 if np.allclose(x, y) else 0.0
        return float(np.corrcoef(x, y)[0, 1])
    # 3+ raters with continuous: average pairwise Pearson.
    pairs: list[float] = []
    for i in range(arr.shape[0]):
        for j in range(i + 1, arr.shape[0]):
            x, y = arr[i], arr[j]
            if np.std(x) < 1e-12 or np.std(y) < 1e-12:
                pairs.append(1.0 if np.allclose(x, y) else 0.0)
            else:
                pairs.append(float(np.corrcoef(x, y)[0, 1]))
    return float(np.mean(pairs)) if pairs else None
