"""Quickstart: capture, retrieve, govern, and forget — in ~20 lines.

Run a MemoryOps API first (no infra needed):

    cd services/api && MEMORYOPS_STORAGE=memory uvicorn app.main:app --reload

Then:

    python examples/quickstart.py
"""

from __future__ import annotations

from memoryops import LegalHoldError, MemoryOpsClient

BASE_URL = "http://localhost:8000"


def main() -> None:
    with MemoryOpsClient(BASE_URL, tenant_id="tenant_demo", user_id="user_demo") as mo:
        # 1. Capture — the message flows through extraction + the policy broker.
        result = mo.chat("Remember that I prefer metric units and dark mode.")
        print("assistant:", result.assistant_message)
        print("stored candidates:", [c.decision for c in result.candidate_memories])

        # 2. Retrieve — later turns get the governed memory context.
        answer = mo.chat("What units should I use in the summary?")
        print("retrieval_mode:", answer.retrieval_mode)
        for used in answer.used_memories:
            print("  used:", used.content, f"(score={used.score:.2f})")

        # 3. Inspect what is stored.
        memories = mo.list_memories()
        print(f"\n{len(memories)} memories:")
        for m in memories:
            print(f"  [{m.memory_type}] {m.content}  (status={m.status})")

        if not memories:
            return
        first = memories[0]

        # 4. Govern — put a memory on legal hold; deletion is now refused.
        mo.set_legal_hold(first.id, on=True, reason="demo hold")
        try:
            mo.delete_memory(first.id)
        except LegalHoldError:
            print(f"\ndelete of {first.id} blocked by legal hold (as expected)")

        # 5. Release the hold and forget.
        mo.set_legal_hold(first.id, on=False)
        mo.delete_memory(first.id)
        print("deleted after releasing hold")


if __name__ == "__main__":
    main()
