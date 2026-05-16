"""
RAG pipeline instrumented with Vidimus.

This example shows how to wrap a Retrieval-Augmented Generation pipeline with
Vidimus to get a signed, tamper-evident, calibration-aware attestation of the
RAG system's behavior over a batch of queries.

The retrieval and generation components are deliberately minimal (TF-IDF cosine
similarity + a stub generator) so the example runs with zero external
dependencies beyond Vidimus and numpy. In a real production setting you would
swap in:

    - Retriever:  FAISS / Chroma / pgvector / Pinecone / Weaviate
    - Embedder:   OpenAI text-embedding-3 / Cohere / sentence-transformers
    - Generator:  GPT-4o / Claude / Gemini / Llama / any LLM
    - Judges:     real Anthropic/OpenAI/Gemini judges (currently stubbed)

The Vidimus instrumentation pattern stays identical regardless of which
components you plug in. That is the point of being OpenTelemetry-native.

Run with:
    python examples/rag_with_vidimus.py

Expected output:
    - 20 queries answered with retrieved context
    - Signed attestation written to ./rag_attestation.json
    - Offline verification confirms cryptographic integrity
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

import vidimus
from vidimus.audit import attest, verify
from vidimus.audit.keys import generate_keypair


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge base
# ─────────────────────────────────────────────────────────────────────────────

KNOWLEDGE_BASE = [
    {
        "id": "doc-001",
        "title": "Vidimus overview",
        "text": (
            "Vidimus is a Python library that adds cryptographic provenance "
            "and calibrated uncertainty to LLM evaluation pipelines. Every "
            "metric ships with a bootstrap confidence interval and a "
            "multi-judge agreement score, and every attestation is signed "
            "with Ed25519."
        ),
    },
    {
        "id": "doc-002",
        "title": "Merkle tree construction",
        "text": (
            "Vidimus uses RFC 6962 Merkle trees. Each trace is hashed with "
            "SHA-256 to produce a leaf. Internal nodes are SHA-256(left || "
            "right). The root is signed and included in every attestation."
        ),
    },
    {
        "id": "doc-003",
        "title": "Bootstrap confidence intervals",
        "text": (
            "For every aggregate metric, Vidimus computes a 95 percent "
            "non-parametric bootstrap confidence interval by resampling the "
            "underlying trace set 1000 times. The interval is reported "
            "alongside the point estimate."
        ),
    },
    {
        "id": "doc-004",
        "title": "Multi-judge agreement",
        "text": (
            "When at least three LLM judges score the same metric, Vidimus "
            "reports Fleiss kappa for categorical labels and Krippendorff "
            "alpha for ordinal or continuous outputs. Values below 0.4 "
            "trigger a warning in the attestation."
        ),
    },
    {
        "id": "doc-005",
        "title": "On-chain anchoring",
        "text": (
            "Optional anchoring publishes a Merkle root and an attestation "
            "hash on any EVM chain. The anchor adds non-repudiable timestamp "
            "to the attestation but no cryptographic strength: the Ed25519 "
            "signature is already unforgeable."
        ),
    },
    {
        "id": "doc-006",
        "title": "OpenTelemetry integration",
        "text": (
            "Vidimus consumes OpenTelemetry spans. Any framework that exports "
            "OTel (LangChain, LlamaIndex, raw OpenTelemetry SDK, Opik, "
            "Langfuse via their OTel exporters) can fan out to Vidimus with "
            "a one-line config change."
        ),
    },
    {
        "id": "doc-007",
        "title": "Threat model",
        "text": (
            "Vidimus protects against post-hoc trace tampering, forged "
            "attestations, backdated reports, and cherry-picked metric "
            "publishing. It does not protect against a compromised signing "
            "key or against a malicious agent at trace-creation time."
        ),
    },
    {
        "id": "doc-008",
        "title": "License and roadmap",
        "text": (
            "Vidimus is Apache 2.0 licensed. Module A (audit) is the current "
            "release. Module B (optimize) brings DRL-based prompt and agent "
            "optimization in Q3 2026. Module C (federate) adds federated "
            "evaluation with secure aggregation and differential privacy in "
            "2027."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# TF-IDF retriever (pure numpy)
# ─────────────────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[A-Za-z]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class TfIdfRetriever:
    """Minimal TF-IDF retriever. Replace with FAISS/Chroma/pgvector in prod."""

    documents: list[dict]
    _vocab: dict[str, int] = None  # type: ignore
    _idf: np.ndarray = None  # type: ignore
    _doc_vectors: np.ndarray = None  # type: ignore

    def fit(self) -> "TfIdfRetriever":
        tokenized_docs = [tokenize(d["text"]) for d in self.documents]
        vocab = sorted({tok for doc in tokenized_docs for tok in doc})
        self._vocab = {tok: i for i, tok in enumerate(vocab)}

        n_docs = len(self.documents)
        df = np.zeros(len(vocab))
        for doc in tokenized_docs:
            for tok in set(doc):
                df[self._vocab[tok]] += 1
        self._idf = np.log((n_docs + 1) / (df + 1)) + 1

        doc_vectors = np.zeros((n_docs, len(vocab)))
        for i, doc in enumerate(tokenized_docs):
            counts = Counter(doc)
            for tok, c in counts.items():
                if tok in self._vocab:
                    doc_vectors[i, self._vocab[tok]] = c * self._idf[self._vocab[tok]]
        norms = np.linalg.norm(doc_vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1
        self._doc_vectors = doc_vectors / norms
        return self

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        if self._doc_vectors is None:
            raise RuntimeError("retriever not fitted; call .fit() first")
        q_tokens = tokenize(query)
        q_vec = np.zeros(len(self._vocab))
        for tok in q_tokens:
            if tok in self._vocab:
                q_vec[self._vocab[tok]] += self._idf[self._vocab[tok]]
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec /= q_norm
        scores = self._doc_vectors @ q_vec
        top_idx = np.argsort(-scores)[:top_k]
        return [
            {**self.documents[i], "score": float(scores[i])}
            for i in top_idx
            if scores[i] > 0
        ]


# ─────────────────────────────────────────────────────────────────────────────
# RAG pipeline
# ─────────────────────────────────────────────────────────────────────────────

class StubGenerator:
    """Deterministic stub generator. Replace with GPT-4o/Claude/etc. in prod."""

    def generate(self, query: str, context: list[dict]) -> str:
        if not context:
            return "I don't have information to answer that question."
        primary = context[0]
        return (
            f"Based on '{primary['title']}': {primary['text'][:160]}... "
            f"[answered using {len(context)} retrieved document(s)]"
        )


@dataclass
class RAGPipeline:
    retriever: TfIdfRetriever
    generator: StubGenerator

    @vidimus.audit
    def answer(self, query: str) -> str:
        """Top-level RAG entry point — instrumented by Vidimus."""
        with vidimus.trace(name="retrieve") as t:
            t.set_input(query)
            retrieved = self.retriever.retrieve(query, top_k=3)
            t.set_output({"doc_ids": [d["id"] for d in retrieved]})

        with vidimus.trace(name="generate") as t:
            t.set_input({"query": query, "n_docs": len(retrieved)})
            response = self.generator.generate(query, retrieved)
            t.set_output(response)

        return response


# ─────────────────────────────────────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────────────────────────────────────

DEMO_QUERIES = [
    "How does Vidimus compute confidence intervals?",
    "What cryptographic primitives are used for signing?",
    "Is there a license restriction?",
    "How does Vidimus handle OpenTelemetry spans?",
    "What does Vidimus not protect against?",
    "When is Module B released?",
    "How are Merkle trees constructed?",
    "What is multi-judge agreement?",
    "Can I anchor reports on Ethereum?",
    "What replaces the StubJudge in production?",
    "How is the Merkle root signed?",
    "Does Vidimus require ClickHouse?",
    "What kappa threshold triggers a warning?",
    "Is Krippendorff alpha used for ordinal metrics?",
    "Does on-chain anchoring add cryptographic strength?",
    "What happens if a signing key is compromised?",
    "When does Module C ship?",
    "Can Langfuse traces be ingested?",
    "What library implements Ed25519?",
    "How many bootstrap iterations by default?",
]


def main() -> None:
    print("=" * 70)
    print("RAG pipeline instrumented with Vidimus")
    print("=" * 70)

    # 1. Initialize Vidimus
    vidimus.init(
        workspace="rag-demo",
        judges=["stub:judge-a", "stub:judge-b", "stub:judge-c"],
    )

    # 2. Build the RAG pipeline
    retriever = TfIdfRetriever(documents=KNOWLEDGE_BASE).fit()
    pipeline = RAGPipeline(retriever=retriever, generator=StubGenerator())

    # 3. Run a batch of queries — each one is automatically traced by Vidimus
    print(f"\nRunning {len(DEMO_QUERIES)} queries through the RAG pipeline...")
    for i, query in enumerate(DEMO_QUERIES, 1):
        response = pipeline.answer(query)
        if i <= 3:
            print(f"\n  Q{i}: {query}")
            print(f"  A{i}: {response[:120]}...")
    print(f"  ... ({len(DEMO_QUERIES) - 3} more queries)")

    # 4. Generate a signed attestation over all of today's traces
    print("\nGenerating signed attestation...")
    keypair = generate_keypair()
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    start = end - timedelta(hours=1)
    report = attest(
        metrics=["answer_relevance", "retrieval_quality"],
        period_start=start,
        period_end=end,
        keypair=keypair,
        seed=42,
    )
    out_path = Path("rag_attestation.json")
    out_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2))
    print(f"  → {out_path}")
    print(f"  Merkle root: {report.merkle_root[:32]}...")
    print(f"  Signed by:   {report.issuer_pubkey_fingerprint[:32]}...")
    print(f"  Trace count: {report.trace_count}")
    for m in report.metrics:
        ci = f"[{m.ci_low:.2%}, {m.ci_high:.2%}]"
        k = f"κ={m.judge_agreement:.2f}" if m.judge_agreement is not None else "κ=n/a"
        print(f"    {m.name:<22} {m.point_estimate:>6.2%}  CI {ci}  n={m.n}  {k}")

    # 5. Verify offline — no network, no server
    print("\nVerifying attestation offline...")
    ok, issues, warnings = verify(report)
    if ok:
        print("  ✓ Cryptographic verification PASSED")
    else:
        print("  ✗ Cryptographic verification FAILED")
        for issue in issues:
            print(f"    - {issue}")
    for w in warnings:
        print(f"  ⚠ {w}")

    print("\n" + "=" * 70)
    print("Done. The attestation is portable and verifiable by any third party.")
    print("=" * 70)


if __name__ == "__main__":
    main()
