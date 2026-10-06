"""Vidimus — The trust layer for agentic AI.

Tamper-evident traces, calibrated uncertainty, cryptographic attestations.

Quick start:
    >>> import vidimus
    >>> vidimus.init(workspace="my-workspace")
    >>> @vidimus.audit
    ... def my_agent(query: str) -> str:
    ...     return f"echo: {query}"

For full documentation, see https://docs.vidimus.ai
"""

from vidimus._version import __version__
from vidimus.audit.attest import attest, verify
from vidimus.audit.decorator import audit, trace
from vidimus.audit.schemas import (
    Attestation,
    CalibratedMetric,
    Span,
    Trace,
)
from vidimus.config import init

__all__ = [
    "Attestation",
    "CalibratedMetric",
    "Span",
    "Trace",
    "__version__",
    "attest",
    "audit",
    "init",
    "trace",
    "verify",
]
