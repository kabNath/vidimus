"""Vidimus instrumenting a LangChain agent.

This example shows how to wrap a LangChain agent or chain with Vidimus so
that every invocation produces an auditable trace, eventually rolled up into
a signed attestation.

Pattern: the user keeps their LangChain code unchanged and adds a single
``@vidimus.audit`` decorator on the outer chain method. Vidimus captures the
input/output and any spans the user adds inside.

This file gracefully handles the case where LangChain is not installed; it
demonstrates the pattern symbolically so the example is useful even without
the heavy dependency.

Setup:
    pip install vidimus langchain langchain-openai
    export OPENAI_API_KEY=...

Run:
    python examples/langchain_integration.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import vidimus
from vidimus.audit import attest, verify
from vidimus.audit.keys import generate_keypair


# ─────────────────────────────────────────────────────────────────────────────
# Detect LangChain availability
# ─────────────────────────────────────────────────────────────────────────────


def _langchain_available() -> bool:
    try:
        import langchain_core  # noqa: F401
        return True
    except ImportError:
        return False


def _openai_available() -> bool:
    try:
        import langchain_openai  # noqa: F401
        return True
    except ImportError:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# A LangChain-style agent, instrumented with Vidimus
# ─────────────────────────────────────────────────────────────────────────────


class InstrumentedQAAgent:
    """A retrieval-augmented Q&A agent wrapping LangChain.

    The agent's public method ``answer`` is decorated with ``@vidimus.audit``
    so each invocation produces a trace. Internal steps (retrieve, generate)
    can be marked as child spans via ``vidimus.trace()``.

    If LangChain is not installed, falls back to a simple stub so the demo
    runs end-to-end regardless.
    """

    def __init__(self, knowledge_base: list[dict]):
        self.knowledge_base = knowledge_base
        self._use_real_langchain = _langchain_available() and _openai_available() and \
            os.environ.get("OPENAI_API_KEY")

        if self._use_real_langchain:
            self._init_langchain()

    def _init_langchain(self) -> None:
        """Set up a minimal LangChain RetrievalQA-style chain."""
        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.runnables import RunnablePassthrough
        from langchain_core.output_parsers import StrOutputParser
        from langchain_openai import ChatOpenAI

        # Simple in-memory retriever based on keyword overlap
        def retrieve(query: str) -> str:
            scores = []
            q_words = set(query.lower().split())
            for doc in self.knowledge_base:
                doc_words = set(doc["text"].lower().split())
                scores.append((len(q_words & doc_words), doc))
            scores.sort(reverse=True, key=lambda x: x[0])
            top = [d for _, d in scores[:3]]
            return "\n\n".join(f"[{d['id']}] {d['text']}" for d in top)

        prompt = ChatPromptTemplate.from_messages([
            ("system", "Answer the question using only the provided context. Be concise."),
            ("user", "Context:\n{context}\n\nQuestion: {question}"),
        ])
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

        self._chain = (
            {"context": retrieve, "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser()
        )

    @vidimus.audit
    def answer(self, query: str) -> str:
        """The public entry point. Instrumented by Vidimus."""
        with vidimus.trace(name="retrieve") as t:
            t.set_input(query)
            context = self._retrieve(query)
            t.set_output({"context_length": len(context)})

        with vidimus.trace(name="generate") as t:
            t.set_input({"query": query, "context_length": len(context)})
            if self._use_real_langchain:
                response = self._chain.invoke(query)
            else:
                response = self._stub_generate(query, context)
            t.set_output(response)

        return response

    def _retrieve(self, query: str) -> str:
        """Internal retrieval, used by both the real and stub generators."""
        q_words = set(query.lower().split())
        scored = []
        for doc in self.knowledge_base:
            doc_words = set(doc["text"].lower().split())
            scored.append((len(q_words & doc_words), doc))
        scored.sort(reverse=True, key=lambda x: x[0])
        top = [d for _, d in scored[:3] if _ > 0]
        return "\n\n".join(f"[{d['id']}] {d['text']}" for d in top)

    def _stub_generate(self, query: str, context: str) -> str:
        if not context:
            return f"I don't have information to answer: {query}"
        snippet = context.split("\n\n")[0][:150]
        return f"Based on retrieved context: {snippet}..."


# ─────────────────────────────────────────────────────────────────────────────
# Demo
# ─────────────────────────────────────────────────────────────────────────────


KNOWLEDGE_BASE = [
    {"id": "001", "text": "Vidimus produces Ed25519-signed attestations of LLM evaluations with bootstrap confidence intervals."},
    {"id": "002", "text": "Merkle trees in Vidimus follow RFC 6962. Each leaf is SHA-256 of canonical JSON. Internal nodes prepend 0x01."},
    {"id": "003", "text": "Multi-judge agreement uses Fleiss kappa for categorical labels and Krippendorff alpha for continuous."},
    {"id": "004", "text": "On-chain anchoring is optional and adds timestamp non-repudiation, not cryptographic strength."},
    {"id": "005", "text": "LangChain integrates with Vidimus through OpenTelemetry export or direct decorator."},
]


def main() -> None:
    print("=" * 70)
    print("LangChain agent instrumented with Vidimus")
    print("=" * 70)

    if _langchain_available() and _openai_available() and os.environ.get("OPENAI_API_KEY"):
        print("\n✓ LangChain + OpenAI detected — running with real LLM")
    elif _langchain_available():
        print("\n⚠ LangChain installed but no OPENAI_API_KEY — using stub generator")
        print("  Set OPENAI_API_KEY to use a real LLM via langchain-openai")
    else:
        print("\n⚠ LangChain not installed — using stub generator")
        print("  Install with: pip install langchain langchain-openai")

    vidimus.init(
        workspace="langchain-demo",
        judges=["stub:judge-a", "stub:judge-b", "stub:judge-c"],
    )

    agent = InstrumentedQAAgent(knowledge_base=KNOWLEDGE_BASE)

    queries = [
        "How does Vidimus sign attestations?",
        "What does Fleiss kappa measure?",
        "Are Merkle leaves prefixed with anything?",
        "Is on-chain anchoring required?",
        "Can LangChain integrate with Vidimus?",
    ]

    print(f"\nRunning {len(queries)} queries...")
    for q in queries:
        ans = agent.answer(q)
        print(f"\n  Q: {q}")
        print(f"  A: {ans[:120]}...")

    # Attest
    print("\nGenerating Vidimus attestation...")
    keypair = generate_keypair()
    end = datetime.now(timezone.utc) + timedelta(seconds=1)
    start = end - timedelta(hours=1)

    attestation = attest(
        metrics=["answer_quality", "retrieval_relevance"],
        period_start=start,
        period_end=end,
        keypair=keypair,
        seed=42,
    )

    out_path = Path("langchain_attestation.json")
    out_path.write_text(attestation.model_dump_json(indent=2))
    print(f"  → {out_path}")
    print(f"  Trace count: {attestation.trace_count}")
    print(f"  Merkle root: {attestation.merkle_root[:32]}...")

    # Verify
    ok, issues, warnings = verify(attestation)
    if ok:
        print("\n✓ Verification PASSED")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
