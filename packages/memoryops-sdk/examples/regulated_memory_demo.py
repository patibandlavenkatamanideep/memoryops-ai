"""Example: domain-safe memory for regulated settings (healthcare / legal / finance).

Regulated assistants need memory that respects consent, minimizes disclosure, proves
deletion, and never leaks sensitive context to the wrong audience. This walks a
healthcare-flavored scenario, but the same controls apply to legal and finance.

Run a MemoryOps API first, then:
    python packages/memoryops-sdk/examples/regulated_memory_demo.py
"""

from __future__ import annotations

import httpx

from memoryops import GovernedMemory, MemoryOpsClient

BASE_URL = "http://localhost:8000"
TENANT, USER = "clinic", "patient-123"


def _evidence(path: str) -> dict:
    r = httpx.get(f"{BASE_URL}/api/evidence/{path}",
                  params={"tenant_id": TENANT, "user_id": USER}, timeout=10)
    r.raise_for_status()
    return r.json()


def main() -> None:
    with MemoryOpsClient(BASE_URL, tenant_id=TENANT, user_id=USER) as mo:
        clinician = GovernedMemory(mo, audience="private")   # full clearance
        front_desk = GovernedMemory(mo, audience="public")   # low-sensitivity only

        # A sensitive clinical fact. The policy broker classifies sensitivity; the
        # Recall Gate then keeps it out of a public-audience context.
        clinician.remember("The patient is allergic to penicillin.")

        print("clinician recall:", clinician.recall("what are the patient's allergies?"))
        # The front desk (public audience) should not surface high-sensitivity memory.
        print("front-desk recall:", front_desk.recall("what are the patient's allergies?"))

        # Consent withdrawal (data-subject request) → gated out immediately, then
        # retention-eligible; nothing waits on a nightly job to stop using it.
        mem = mo.list_memories()[0]
        clinician.withdraw_consent(mem.id)
        print("after consent withdrawal:", clinician.recall("what allergies?"))

        # Right-to-erasure with a verifiable deletion proof to hand to compliance.
        mo.delete_memory(mem.id)
        proof = _evidence(f"deletion/{mem.id}")
        print("erasure proven:", proof.get("proven"))
        print("audit chain intact:", _evidence("audit/verify").get("ok"))

    print(
        "\nControls demonstrated: consent-aware recall, audience-scoped disclosure, "
        "verifiable erasure, tamper-evident audit — the same set legal/finance need."
    )


if __name__ == "__main__":
    main()
