"""Production-grade RAG instrumented with Vidimus.

This example uses a real production stack instead of the didactic TF-IDF
retriever shown in ``rag_with_vidimus.py``:

  - Embeddings: sentence-transformers (``all-MiniLM-L6-v2``, ~80 MB local model)
  - Vector store: FAISS (CPU)
  - Generator: Ollama if available locally, otherwise a context-aware stub

Both files instrument the agent identically through ``@vidimus.audit``. The
only thing that changes between the didactic and the production version is
the underlying retrieval/generation stack — Vidimus is unchanged.

Setup:
    pip install vidimus sentence-transformers faiss-cpu
    # Optionally, for a real LLM generator:
    #   curl -fsSL https://ollama.com/install.sh | sh
    #   ollama pull llama3.2:3b

Run:
    python examples/rag_production.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vidimus
from vidimus.audit import attest, verify
from vidimus.audit.keys import generate_keypair


# ─────────────────────────────────────────────────────────────────────────────
# Optional dependency detection
# ─────────────────────────────────────────────────────────────────────────────


def _check_deps() -> tuple[bool, bool, bool]:
    """Return (has_sentence_transformers, has_faiss, has_ollama_server)."""
    try:
        import sentence_transformers  # noqa: F401
        has_st = True
    except ImportError:
        has_st = False

    try:
        import faiss  # noqa: F401
        has_faiss = True
    except ImportError:
        has_faiss = False

    has_ollama = False
    try:
        import requests
        r = requests.get("http://localhost:11434/api/tags", timeout=1.0)
        has_ollama = r.status_code == 200
    except Exception:
        pass

    return has_st, has_faiss, has_ollama


# ─────────────────────────────────────────────────────────────────────────────
# Knowledge base
# ─────────────────────────────────────────────────────────────────────────────


KNOWLEDGE_BASE = [
    {"id": "doc-001", "title": "Vidimus overview",
     "text": "Vidimus is a Python library that adds cryptographic provenance and calibrated uncertainty to LLM evaluation pipelines. Every metric ships with a bootstrap confidence interval and a multi-judge agreement score, and every attestation is signed with Ed25519."},
    {"id": "doc-002", "title": "Merkle trees",
     "text": "Vidimus uses RFC 6962 Merkle trees. Each trace is hashed with SHA-256 to produce a leaf. Internal nodes are SHA-256 of left concatenated with right. The root is signed and included in every attestation."},
    {"id": "doc-003", "title": "Bootstrap CIs",
     "text": "For every aggregate metric, Vidimus computes a 95 percent non-parametric bootstrap confidence interval by resampling the underlying trace set 1000 times. The interval is reported alongside the point estimate."},
    {"id": "doc-004", "title": "Multi-judge agreement",
     "text": "When at least three LLM judges score the same metric, Vidimus reports Fleiss kappa for categorical labels and Krippendorff alpha for continuous outputs. Values below 0.4 trigger a warning."},
    {"id": "doc-005", "title": "On-chain anchoring",
     "text": "Optional anchoring publishes a Merkle root and an attestation hash on any EVM chain. The anchor adds non-repudiable timestamp to the attestation but no cryptographic strength."},
    {"id": "doc-006", "title": "OpenTelemetry",
     "text": "Vidimus consumes OpenTelemetry spans. Any framework that exports OTel can fan out to Vidimus with a one-line config change."},
    {"id": "doc-007", "title": "Threat model",
     "text": "Vidimus protects against post-hoc trace tampering, forged attestations, and cherry-picked metric publishing. It does not protect against a compromised signing key."},
    {"id": "doc-008", "title": "Roadmap",
     "text": "Module A (audit) is the current release. Module B (optimize) brings DRL-based prompt optimization in Q3 2026. Module C (federate) adds federated evaluation in 2027."},
]


# ─────────────────────────────────────────────────────────────────────────────
# Real embedding retriever (sentence-transformers + FAISS)
# ─────────────────────────────────────────────────────────────────────────────


class FaissRetriever:
    """Dense retrieval using sentence-transformers embeddings + FAISS index."""

    def __init__(self, documents: list[dict], model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        import faiss
        import numpy as np

        self.documents = documents
        self.model = SentenceTransformer(model_name)
        embeddings = self.model.encode([d["text"] for d in documents])
        # Normalize for cosine similarity via inner product
        faiss.normalize_L2(embeddings)
        self.index = faiss.IndexFlatIP(embeddings.shape[1])
        self.index.add(embeddings.astype("float32"))
        self._np = np

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        import faiss
        q_emb = self.model.encode([query])
        faiss.normalize_L2(q_emb)
        scores, indices = self.index.search(q_emb.astype("float32"), top_k)
        return [
            {**self.documents[int(i)], "score": float(s)}
            for s, i in zip(scores[0], indices[0])
            if i >= 0
        ]


# ─────────────────────────────────────────────────────────────────────────────
# Generators
# ─────────────────────────────────────────────────────────────────────────────


class OllamaGenerator:
    """Real LLM generator via local Ollama."""

    def __init__(self, model: str = "llama3.2:3b", base_url: str = "http://localhost:11434"):
        import requests
        self._requests = requests
        self.model = model
        self.base_url = base_url

    def generate(self, query: str, context: list[dict]) -> str:
        ctx_text = "\n\n".join(f"[{c['id']}] {c['text']}" for c in context)
        prompt = (
            f"Answer the question using only the provided context. Be concise.\n\n"
            f"Context:\n{ctx_text}\n\n"
            f"Question: {query}\n\n"
            f"Answer:"
        )
        r = self._requests.post(
            f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": prompt, "stream": False,
                  "options": {"temperature": 0.0, "num_predict": 200}},
            timeout=60,
        )
        r.raise_for_status()
        return r.json().get("response", "").strip()


class TemplateGenerator:
    """Fallback context-aware generator (no LLM call)."""

    def generate(self, query: str, context: list[dict]) -> str:
        if not context:
            return "I don't have information to answer that question."
        top = context[0]
        return f"Based on '{top['title']}': {top['text'][:180]}..."


# ─────────────────────────────────────────────────────────────────────────────
# Instrumented RAG pipeline
# ─────────────────────────────────────────────────────────────────────────────


class ProductionRAG:
    def __init__(self, retriever, generator):
        self.retriever = retriever
        self.generator = generator

    @vidimus.audit
    def answer(self, query: str) -> str:
        with vidimus.trace(name="embed_and_retrieve") as t:
            t.set_input(query)
            retrieved = self.retriever.retrieve(query, top_k=3)
            t.set_output({"doc_ids": [d["id"] for d in retrieved],
                          "top_score": retrieved[0]["score"] if retrieved else 0.0})

        with vidimus.trace(name="generate") as t:
            t.set_input({"query": query, "n_docs": len(retrieved)})
            answer = self.generator.generate(query, retrieved)
            t.set_output(answer)

        return answer


# ─────────────────────────────────────────────────────────────────────────────
# Fallback retriever (TF-IDF, identical to didactic example)
# ─────────────────────────────────────────────────────────────────────────────


class TfidfFallbackRetriever:
    def __init__(self, documents: list[dict]):
        import re
        from collections import Counter
        import math
        self._re = re
        self._Counter = Counter
        self._math = math
        self.documents = documents
        self._tokenized = [self._tokenize(d["text"]) for d in documents]
        n_docs = len(documents)
        df = Counter()
        for doc in self._tokenized:
            for tok in set(doc):
                df[tok] += 1
        self._idf = {t: math.log((n_docs + 1) / (c + 1)) + 1 for t, c in df.items()}

    def _tokenize(self, text: str) -> list[str]:
        return self._re.findall(r"[a-z]+", text.lower())

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        q_tokens = self._tokenize(query)
        scored = []
        for doc, doc_tokens in zip(self.documents, self._tokenized):
            tf = self._Counter(doc_tokens)
            score = sum(tf.get(t, 0) * self._idf.get(t, 0) for t in q_tokens)
            scored.append((score, doc))
        scored.sort(reverse=True, key=lambda x: x[0])
        return [{**d, "score": s} for s, d in scored[:top_k] if s > 0]


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 70)
    print("Production RAG instrumented with Vidimus")
    print("=" * 70)

    has_st, has_faiss, has_ollama = _check_deps()
    print(f"\nDependency check:")
    print(f"  sentence-transformers: {'✓' if has_st else '✗'}")
    print(f"  faiss-cpu:             {'✓' if has_faiss else '✗'}")
    print(f"  Ollama (local server): {'✓' if has_ollama else '✗'}")

    # Build retriever
    if has_st and has_faiss:
        print("\nBuilding FAISS index over knowledge base (this downloads the model once)...")
        retriever = FaissRetriever(KNOWLEDGE_BASE)
        print("  ✓ FAISS retriever ready")
    else:
        print("\nFalling back to TF-IDF retriever (install vidimus[rag] for FAISS)")
        retriever = TfidfFallbackRetriever(KNOWLEDGE_BASE)

    # Build generator
    if has_ollama:
        print("Using Ollama as generator (llama3.2:3b)")
        try:
            generator = OllamaGenerator(model="llama3.2:3b")
        except Exception:
            print("  Ollama model not available, falling back to template")
            generator = TemplateGenerator()
    else:
        print("Using template generator (start Ollama and `ollama pull llama3.2:3b` for real LLM)")
        generator = TemplateGenerator()

    # Initialize Vidimus
    vidimus.init(
        workspace="rag-production",
        judges=["stub:judge-a", "stub:judge-b", "stub:judge-c"],
    )
    rag = ProductionRAG(retriever, generator)

    # Demo queries
    queries = [
        "How does Vidimus prove integrity?",
        "What is Fleiss kappa used for?",
        "Tell me about the Vidimus roadmap.",
        "Does Vidimus protect against compromised keys?",
        "What kind of Merkle tree does Vidimus use?",
    ]

    print(f"\nRunning {len(queries)} queries through the RAG pipeline...")
    for q in queries:
        ans = rag.answer(q)
        print(f"\n  Q: {q}")
        print(f"  A: {ans[:150]}{'...' if len(ans) > 150 else ''}")

    # Attest
    print("\nGenerating Vidimus attestation...")
    keypair = generate_keypair()
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    start = end - timedelta(hours=1)

    attestation = attest(
        metrics=["answer_quality", "retrieval_precision"],
        period_start=start,
        period_end=end,
        keypair=keypair,
        seed=42,
    )

    out_path = Path("rag_production_attestation.json")
    out_path.write_text(attestation.model_dump_json(indent=2))
    print(f"  → {out_path}")
    print(f"  Trace count: {attestation.trace_count}")
    print(f"  Merkle root: {attestation.merkle_root[:32]}...")

    # Verify
    ok, issues, warnings = verify(attestation)
    if ok:
        print("\n✓ Cryptographic verification PASSED")
    for w in warnings:
        print(f"  ⚠ {w}")

    print("\n" + "=" * 70)
    print("This example uses production-grade retrieval (FAISS) and a real LLM")
    print("(Ollama) when available. The Vidimus instrumentation is identical")
    print("to the didactic TF-IDF example — only the underlying stack changes.")
    print("=" * 70)


if __name__ == "__main__":
    main()
