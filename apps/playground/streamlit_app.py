"""MemoryOps AI — Public Playground (v0.12).

An INTERACTIVE public demo that runs the *real* governed memory pipeline in
process, against a fresh **in-memory** store created per browser session. Visitors
can capture a memory, ask a question that uses it, then govern it — apply a legal
hold, withdraw consent, run the lifecycle workers — and watch the audit trace and
assistant behavior change live.

Safe to host:
  * No database, no secrets, no auth, no network calls (stub LLM + stub embeddings).
  * State is an in-memory repository held in ``st.session_state`` — it is
    per-session and ephemeral; nothing is persisted and there is no real user data.
  * The server-side governance is the *real* code from ``services/api`` (gateway,
    policy broker, governance, retention) — the playground does not reimplement it,
    it drives it. So what you see is how MemoryOps actually behaves.

This is a demo/evidence surface, like the v0.9 results dashboard — NOT the
production product. The Next.js app (``apps/web``) remains the official UI.

Run locally:
    cd apps/playground
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import streamlit as st

# The playground drives the real governed pipeline from services/api in-process.
os.environ.setdefault("MEMORYOPS_STORAGE", "memory")
_API_DIR = Path(__file__).resolve().parents[2] / "services" / "api"
if _API_DIR.is_dir() and str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from app.db import governance as gov  # noqa: E402
from app.db.memory_repo import InMemoryRepository  # noqa: E402
from app.schemas.memory import ChatRequest  # noqa: E402
from app.services.audit import AuditService  # noqa: E402
from app.services.gateway import Gateway  # noqa: E402
from app.services.retention import available_policies, evaluate, get_policy  # noqa: E402
from app.workers.runner import run_jobs  # noqa: E402

TENANT = "playground"
SEED_MESSAGES = [
    "Remember that I prefer metric units and dark mode.",
    "Remember my project is named Atlas and I deploy on Railway.",
    "By the way, my favorite color is teal.",
]


# ── per-session governed pipeline ────────────────────────────────────────────
def _session():
    """Return (repo, gateway, audit, user_id), creating a fresh stack per session."""
    if "repo" not in st.session_state:
        repo = InMemoryRepository()
        st.session_state.repo = repo
        st.session_state.gateway = Gateway(repo)
        st.session_state.audit = AuditService(repo)
        st.session_state.user_id = f"visitor_{uuid.uuid4().hex[:8]}"
        st.session_state.trace_n = 0
        st.session_state.last_chat = None
    return (
        st.session_state.repo,
        st.session_state.gateway,
        st.session_state.audit,
        st.session_state.user_id,
    )


def _reset() -> None:
    for key in ("repo", "gateway", "audit", "user_id", "trace_n", "last_chat"):
        st.session_state.pop(key, None)


def _trace() -> str:
    st.session_state.trace_n += 1
    return f"pg-{st.session_state.trace_n:04d}"


def _chat(message: str, *, temporary: bool = False):
    _, gateway, _, user_id = _session()
    req = ChatRequest(tenant_id=TENANT, user_id=user_id, message=message, temporary_chat=temporary)
    return gateway.handle_chat(req, trace_id=_trace())


def _active(repo, user_id):
    return repo.list_memories(TENANT, user_id, status="active")


def _badges(memory) -> str:
    out = []
    if gov.is_legal_hold(memory):
        out.append("🔒 legal hold")
    if gov.is_pinned(memory):
        out.append("📌 pinned")
    if gov.is_protected(memory):
        out.append("🛡 protected")
    consent = gov.consent_status(memory)
    if consent != gov.ConsentStatus.granted:
        out.append(f"⚠ consent:{consent}")
    return "  ".join(out)


# ── pages ─────────────────────────────────────────────────────────────────────
def page_capture() -> None:
    st.subheader("1 · Capture & ask")
    st.caption("Type something to remember, then ask a question that should use it. "
               "Every message runs through extraction + the policy broker.")

    with st.form("capture", clear_on_submit=True):
        msg = st.text_input("Message", placeholder="Remember that I prefer metric units…")
        temp = st.checkbox("Temporary chat (reads & writes nothing — invariant #6)")
        sent = st.form_submit_button("Send")
    if sent and msg.strip():
        st.session_state.last_chat = _chat(msg.strip(), temporary=temp)

    result = st.session_state.get("last_chat")
    if result is None:
        return
    st.markdown(f"**Assistant:** {result.assistant_message}")
    st.caption(f"retrieval_mode = `{result.retrieval_mode}` · trace = `{result.trace_id}`"
               + ("  ·  temporary (nothing stored)" if result.temporary_chat else ""))
    if result.candidate_memories:
        st.markdown("**Policy decisions on this message:**")
        st.dataframe(
            [{"content": c.content, "decision": c.decision, "reason": c.reason}
             for c in result.candidate_memories],
            use_container_width=True, hide_index=True,
        )
    if result.used_memories:
        st.markdown("**Memories used to answer:**")
        st.dataframe(
            [{"content": u.content, "score": round(u.score, 3)} for u in result.used_memories],
            use_container_width=True, hide_index=True,
        )


def page_memories() -> None:
    repo, _, audit, user_id = _session()
    st.subheader("2 · Memories & governance")
    st.caption("Apply a legal hold, pin/protect, withdraw consent, or delete. "
               "Legal hold is fail-closed: deletion is refused until released.")

    memories = _active(repo, user_id)
    if not memories:
        st.info("No active memories yet. Capture some on the **Capture & ask** tab "
                "or click **Seed demo memories** in the sidebar.")
        return

    for m in memories:
        with st.container(border=True):
            st.markdown(f"**{m.content}**")
            meta = f"`{m.memory_type}` · importance {m.importance} · {m.sensitivity}"
            badges = _badges(m)
            st.caption(meta + ("  —  " + badges if badges else ""))
            c1, c2, c3, c4 = st.columns(4)
            held = gov.is_legal_hold(m)
            if c1.button("Release hold" if held else "Legal hold", key=f"hold-{m.id}"):
                gov.set_legal_hold(m, on=not held, reason="playground demo")
                repo.update_memory(m)
                audit.record(tenant_id=TENANT, user_id=user_id, memory_id=m.id,
                             action="memory_legal_hold_set" if not held else
                             "memory_legal_hold_released", reason="playground", trace_id=_trace())
                st.rerun()
            if c2.button("Toggle pin", key=f"pin-{m.id}"):
                gov.set_pinned(m, on=not gov.is_pinned(m))
                repo.update_memory(m)
                st.rerun()
            if c3.button("Withdraw consent", key=f"consent-{m.id}"):
                gov.set_consent(m, status=gov.ConsentStatus.withdrawn)
                repo.update_memory(m)
                audit.record(tenant_id=TENANT, user_id=user_id, memory_id=m.id,
                             action="memory_consent_updated", reason="consent withdrawn",
                             trace_id=_trace())
                st.rerun()
            if c4.button("Delete", key=f"del-{m.id}"):
                if gov.is_legal_hold(m):
                    audit.record(tenant_id=TENANT, user_id=user_id, memory_id=m.id,
                                 action="memory_legal_hold_delete_blocked",
                                 reason="delete refused; memory under legal hold",
                                 trace_id=_trace())
                    st.error("Delete blocked — memory is under legal hold (HTTP 409). "
                             "Release the hold first.")
                else:
                    repo.soft_delete(TENANT, user_id, m.id)
                    audit.record(tenant_id=TENANT, user_id=user_id, memory_id=m.id,
                                 action="memory_deleted",
                                 reason="soft-deleted; excluded from all future retrieval",
                                 trace_id=_trace())
                    st.rerun()

    st.divider()
    st.markdown("**Run the lifecycle workers** (decay · archive · retention · "
                "deletion verification · compaction) over this session:")
    if st.button("▶ Run lifecycle workers"):
        report = run_jobs(repo, tenant_id=TENANT, user_id=user_id, jobs=["all"],
                          trace_id=_trace())
        st.success(f"Ran {len(report.results)} jobs · "
                   f"scanned={report.scanned_count} changed={report.changed_count}")
        st.dataframe(
            [{"job": r.job, "status": r.status, "scanned": r.scanned_count,
              "changed": r.changed_count, "skipped": r.skipped_count} for r in report.results],
            use_container_width=True, hide_index=True,
        )


def page_retention() -> None:
    repo, _, _, user_id = _session()
    st.subheader("3 · Retention preview")
    st.caption("Read-only preview of what the retention worker *would* do under a "
               "policy pack. Deletes nothing.")
    names = [p.name for p in available_policies()]
    policy = get_policy(st.selectbox("Policy pack", names))
    rows = _active(repo, user_id)
    if not rows:
        st.info("No active memories to evaluate.")
        return
    decisions = [evaluate(m, policy=policy) for m in rows]
    st.dataframe(
        [{"memory": d.memory_id[:8], "outcome": d.outcome.value,
          "eligible_for_deletion": d.eligible_for_deletion,
          "blocked_by": ", ".join(d.blocked_by) or "—", "reason": d.reason}
         for d in decisions],
        use_container_width=True, hide_index=True,
    )


def page_audit() -> None:
    repo, _, _, user_id = _session()
    st.subheader("4 · Audit trace")
    st.caption("Every governed action appends a content-free audit event (invariant #7).")
    events = repo.list_audit(TENANT, user_id, limit=200)
    if not events:
        st.info("No audit events yet — interact on the other tabs.")
        return
    st.dataframe(
        [{"action": e.action, "reason": e.reason, "memory": (e.memory_id or "")[:8]}
         for e in events],
        use_container_width=True, hide_index=True,
    )


# ── shell ───────────────────────────────────────────────────────────────────
def main() -> None:
    st.set_page_config(page_title="MemoryOps AI — Playground", page_icon="🧠", layout="wide")
    repo, _, _, user_id = _session()

    st.sidebar.title("🧠 MemoryOps Playground")
    st.sidebar.caption("Interactive public demo (v0.12) — runs the real governed "
                       "pipeline against a fresh in-memory store, per session.")
    st.sidebar.markdown(f"**Session scope:** `{TENANT} / {user_id}`")
    st.sidebar.metric("Active memories", len(_active(repo, user_id)))
    if st.sidebar.button("🌱 Seed demo memories"):
        for msg in SEED_MESSAGES:
            _chat(msg)
        st.rerun()
    if st.sidebar.button("♻ Reset session"):
        _reset()
        st.rerun()
    st.sidebar.divider()
    st.sidebar.caption(
        "Demo-only · in-memory · ephemeral · no DB · no secrets · no real user data.\n\n"
        "The Next.js app (`apps/web`) is the official product UI; the v0.9 results "
        "dashboard is the static evidence view."
    )

    st.title("MemoryOps AI — Playground")
    st.caption("Capture → ask → govern → audit. Watch governance change assistant "
               "behavior live, with a full audit trail.")
    tab1, tab2, tab3, tab4 = st.tabs(
        ["Capture & ask", "Memories & governance", "Retention preview", "Audit trace"]
    )
    with tab1:
        page_capture()
    with tab2:
        page_memories()
    with tab3:
        page_retention()
    with tab4:
        page_audit()


if __name__ == "__main__":
    main()
