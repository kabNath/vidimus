"""Module A — vidimus.audit.

Tamper-evident traces, calibrated uncertainty, cryptographic attestations.
"""

from vidimus.audit.attest import attest, verify
from vidimus.audit.decorator import audit, trace
from vidimus.audit.schemas import (
    Attestation,
    CalibratedMetric,
    OnchainAnchor,
    Span,
    Trace,
)

__all__ = [
    "Attestation",
    "CalibratedMetric",
    "OnchainAnchor",
    "Span",
    "Trace",
    "attest",
    "audit",
    "trace",
    "verify",
]
