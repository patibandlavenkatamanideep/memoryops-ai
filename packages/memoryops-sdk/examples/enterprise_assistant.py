"""Example: an enterprise assistant with governed, evidence-backed memory.

Shows the full enterprise story end-to-end: governed memory, audience-scoped recall,
a right-to-be-forgotten deletion with a verifiable proof, and a tamper-evident audit
chain — all through the public API.

Run a MemoryOps API first:
    cd services/api && MEMORYOPS_STORAGE=memory uvicorn app.main:app
Then:
    python packages/memoryops-sdk/examples/enterprise_assistant.py
"""

from __future__ import annotations

import httpx

from memoryops import GovernedMemory, MemoryOpsClient

BASE_URL = "http://localhost:8000"
TENANT, USER = "acme", "alice"


def evidence(path: str) -> dict:
    r = httpx.get(f"{BASE_URL}/api/evidence/{path}",
                  params={"tenant_id": TENANT, "user_id": USER}, timeout=10)
    r.raise_for_status()
    return r.json()


def main() -> None:
    with MemoryOpsClient(BASE_URL, tenant_id=TENANT, user_id=USER) as mo:
        memory = GovernedMemory(mo, audience="private")

        # 1. Remember durable facts (policy-before-storage decides what is kept).
        memory.remember("Alice manages the payments platform team.")
        memory.remember("Alice prefers concise, bulleted status updates.")

        # 2. Recall governs what enters context.
        print("recall:", memory.recall("how should I format updates for Alice?"))

        # 3. Public-audience recall keeps higher-sensitivity memory out of context.
        print("public recall:", memory.for_audience("public").recall("who is Alice?"))

        # 4. Right-to-be-forgotten + a verifiable deletion proof.
        target = mo.list_memories()[0]
        mo.delete_memory(target.id)
        proof = evidence(f"deletion/{target.id}")
        print("deletion proven:", proof.get("proven"), "| checks:", proof.get("checks"))

        # 5. The audit trail is tamper-evident.
        print("audit chain intact:", evidence("audit/verify").get("ok"))


if __name__ == "__main__":
    main()
