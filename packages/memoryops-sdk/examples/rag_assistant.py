"""RAG assistant: blend governed long-term memory with your own RAG context.

The pattern: retrieve durable user memory from MemoryOps, retrieve task documents
from your own vector store / RAG pipeline, then compose a prompt for your LLM.
MemoryOps governs the *user* memory (what is remembered about the person, with
policy + consent + audit); your RAG store holds the *knowledge* (docs, tickets).

This example stubs the LLM + doc retriever so it runs without keys; swap in your
provider and retriever.
"""

from __future__ import annotations

from memoryops import MemoryOpsClient

BASE_URL = "http://localhost:8000"


def retrieve_docs(query: str) -> list[str]:
    """Stub doc retriever — replace with your vector store / RAG pipeline."""
    corpus = {
        "refund": "Refunds are processed within 5 business days to the original method.",
        "shipping": "Standard shipping takes 3-5 days; express is next-day.",
    }
    return [text for key, text in corpus.items() if key in query.lower()]


def call_llm(system: str, user: str) -> str:
    """Stub LLM — replace with your provider (e.g. the latest Claude model)."""
    return f"[stub answer]\nSYSTEM:\n{system}\n\nUSER: {user}"


def answer(mo: MemoryOpsClient, question: str) -> str:
    # 1. Governed user memory (preferences, constraints) from MemoryOps.
    mem = mo.chat(question, temporary_chat=True)  # read-only: don't store the question
    user_facts = [u.content for u in mem.used_memories]

    # 2. Task knowledge from your own RAG store.
    docs = retrieve_docs(question)

    # 3. Compose and answer.
    system = "You are a support assistant.\n"
    if user_facts:
        system += "Known user preferences:\n- " + "\n- ".join(user_facts) + "\n"
    if docs:
        system += "Relevant policy:\n- " + "\n- ".join(docs) + "\n"
    return call_llm(system, question)


def main() -> None:
    with MemoryOpsClient(BASE_URL, tenant_id="tenant_demo", user_id="user_demo") as mo:
        # Seed a durable preference (governed write).
        mo.chat("Remember I always want express shipping.")
        print(answer(mo, "How long will shipping take?"))


if __name__ == "__main__":
    main()
