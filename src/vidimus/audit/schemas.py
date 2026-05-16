"""Pydantic schemas for Vidimus data structures.

These are the only data shapes that are hashed or signed. Their stability
is part of the public API contract: changes here require a version bump
in the ``Attestation.version`` field.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


class Span(BaseModel):
    """A single span within a trace.

    Spans form a tree (via parent_span_id) representing nested operations
    within an agent invocation.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    span_id: str = Field(default_factory=_new_id)
    parent_span_id: str | None = None
    name: str
    start_ns: int
    end_ns: int
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)
    status: Literal["ok", "error", "unset"] = "ok"

    @field_validator("end_ns")
    @classmethod
    def _end_after_start(cls, v: int, info: Any) -> int:
        start = info.data.get("start_ns")
        if start is not None and v < start:
            raise ValueError(f"end_ns ({v}) must be >= start_ns ({start})")
        return v


class Trace(BaseModel):
    """A single agent interaction.

    Traces are the atomic unit of audit: each one becomes a Merkle leaf and
    is uniquely addressable by ``trace_id``.
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=_new_id)
    workspace: str
    spans: list[Span] = Field(default_factory=list)
    input: str | dict[str, Any] = ""
    output: str | dict[str, Any] = ""
    model: str | None = None
    cost_usd: float | None = None
    captured_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CalibratedMetric(BaseModel):
    """A metric with explicit uncertainty.

    Vidimus never publishes a bare point estimate. Every metric carries a
    confidence interval (bootstrap by default) and, for LLM-as-judge metrics,
    an agreement coefficient between judges.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    point_estimate: float
    ci_low: float
    ci_high: float
    n: int = Field(gt=0, description="Sample size the metric was computed on")
    method: Literal["llm_judge", "heuristic", "human"]
    judges: list[str] = Field(default_factory=list)
    judge_agreement: float | None = Field(
        default=None,
        description="Cohen's/Fleiss's κ or Krippendorff's α, in [-1, 1]",
    )
    bootstrap_iterations: int = 1000

    @field_validator("ci_high")
    @classmethod
    def _ci_high_ge_low(cls, v: float, info: Any) -> float:
        low = info.data.get("ci_low")
        if low is not None and v < low:
            raise ValueError(f"ci_high ({v}) must be >= ci_low ({low})")
        return v


class OnchainAnchor(BaseModel):
    """Reference to an on-chain anchoring of an attestation root.

    Optional. When present, the attestation Merkle root has been committed
    to a public ledger at the given (chain, block, tx) coordinates.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    chain: Literal["bnb-chain", "ethereum", "base", "polygon", "custom"]
    chain_id: int
    contract_address: str
    block_number: int
    tx_hash: str
    anchored_at: datetime


class Attestation(BaseModel):
    """A signed, verifiable evaluation report over a set of traces.

    This is the artifact a regulator, an investor, or a customer ultimately
    consumes. Verification is offline: given the file and the issuer's
    public key, anyone can confirm the signature and recompute the metrics
    from the disclosed Merkle root.
    """

    model_config = ConfigDict(extra="forbid")

    version: Literal["vidimus.attestation.v1"] = "vidimus.attestation.v1"
    workspace: str
    issued_at: datetime = Field(default_factory=_utcnow)
    period_start: datetime
    period_end: datetime
    merkle_root: str = Field(description="hex-encoded SHA-256 of the Merkle root")
    trace_count: int = Field(ge=0)
    metrics: list[CalibratedMetric] = Field(default_factory=list)
    issuer_pubkey_fingerprint: str = Field(
        description="hex-encoded SHA-256 of the issuer's Ed25519 public key"
    )
    issuer_pubkey: str = Field(
        description="hex-encoded Ed25519 public key (32 bytes -> 64 hex chars)"
    )
    onchain_anchor: OnchainAnchor | None = None
    signature: str = Field(
        default="",
        description="hex-encoded Ed25519 signature over the canonical JSON of this "
        "object with signature='' (detached signature pattern)",
    )

    def to_signing_payload(self) -> bytes:
        """Return the canonical JSON bytes that get signed.

        The signature field is replaced with the empty string before
        canonicalization, then the result is hashed and signed.
        """
        from vidimus.audit.canonical import canonicalize

        d = self.model_dump(mode="json")
        d["signature"] = ""
        return canonicalize(d)
