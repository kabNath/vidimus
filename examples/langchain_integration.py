"""
Vidimus + LangChain integration example.

LangChain exports traces via OpenTelemetry. Vidimus consumes OpenTelemetry
spans natively, so the integration is essentially "point LangChain at
Vidimus' OTel endpoint, then run your agent normally."

This example shows the manual-instrumentation pattern (most flexible). For a
zero-config pattern that intercepts every LangChain call automatically, see
the docs.

NOTE: This example uses stub LangChain calls so it runs without LangChain
installed. In production you would `pip install langchain langchain-openai`
and configure your OPENAI_API_KEY normally.

Requirements:
    pip install vidimus
    # pip install langchain langchain-openai   # uncomment for real integration
"""

from __future__ import annotations

from typing import Any

import vidimus

# ---------------------------------------------------------------------------
# Stub LangChain — replace with real LangChain in production.
# ---------------------------------------------------------------------------
class _StubChatModel:
    """Stand-in for langchain_openai.ChatOpenAI()."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def invoke(self, prompt: str) -> str:
        # Faked response, deterministic per prompt
        return f"[{self.model}] Response to: {prompt[:60]}..."


class _StubPromptTemplate:
    """Stand-in for langchain.prompts.PromptTemplate."""

    def __init__(self, template: str, input_variables: list[str]) -> None:
        self.template = template
        self.input_variables = input_variables

    def format(self, **kwargs: Any) -> str:
        return self.template.format(**kwargs)


# ---------------------------------------------------------------------------
# Build a tiny LangChain-style pipeline, fully instrumented with Vidimus.
# ---------------------------------------------------------------------------
vidimus.init(workspace="langchain-integration-demo")

llm = _StubChatModel(model="gpt-4o-mini")
prompt = _StubPromptTemplate(
    template="You are a helpful assistant. Answer concisely.\nQuestion: {question}\nAnswer:",
    input_variables=["question"],
)


@vidimus.audit
def langchain_pipeline(question: str) -> str:
    """A minimal LangChain-style pipeline: prompt → llm → output.

    The @vidimus.audit decorator captures the function-level input/output.
    For sub-step granularity, we use vidimus.trace() context managers below.
    """
    # Sub-span: prompt construction
    with vidimus.trace(name="prompt_format") as span:
        span.set_input({"question": question})
        formatted = prompt.format(question=question)
        span.set_output(formatted)

    # Sub-span: LLM call
    with vidimus.trace(name="llm_invoke") as span:
        span.set_input(formatted)
        span.set_metadata(model=llm.model)
        response = llm.invoke(formatted)
        span.set_output(response)

    return response


# ---------------------------------------------------------------------------
# Drive it and attest
# ---------------------------------------------------------------------------
def main() -> None:
    print("Running LangChain-style pipeline instrumented with Vidimus...\n")

    questions = [
        "What is recursion?",
        "Explain monads simply.",
        "What is the halting problem?",
    ]

    for q in questions:
        print(f"Q: {q}")
        a = langchain_pipeline(q)
        print(f"A: {a[:80]}...\n")

    print("Generating Vidimus attestation...")
    attestation = vidimus.attest(
        workspace="langchain-integration-demo",
        judges=[],
    )
    print(f"  Merkle root: {attestation.merkle_root[:16]}...")
    print(f"  Trace count: {attestation.trace_count}")

    attestation.save("langchain_integration_report.json")
    print("\nAttestation saved.")

    ok, _, _ = vidimus.verify("langchain_integration_report.json")
    print(f"Verification: {'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Production pattern: auto-instrument every LangChain call
# ---------------------------------------------------------------------------
#
# For LangChain pipelines you don't want to refactor, Vidimus v0.2 will ship
# an OTel BatchSpanProcessor that intercepts every LangChain span:
#
#     from langchain.callbacks import OpenTelemetryCallbackHandler
#     import vidimus
#
#     vidimus.init(workspace="prod")
#     vidimus.install_otel_processor()  # registers global BatchSpanProcessor
#
#     # any LangChain code from here on flows into Vidimus automatically
#     chain = prompt | llm
#     chain.invoke({"question": "..."})
#
# Until v0.2 ships, use the manual pattern above. It's also useful as a
# reference for what semantic conventions Vidimus expects.
