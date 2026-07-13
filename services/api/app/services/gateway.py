"""Gateway — orchestrates the read + write paths for a chat turn.

Order of operations (enforces several invariants):
  1. Load settings. If temporary_chat or memory disabled → no read, no write (#6).
  2. READ: retrieve → rank → compose context (wrapped for graceful degradation #4).
  3. Generate the assistant response (heuristic LLM by default).
  4. WRITE: extract → policy broker (before storage #5) → write service → audit (#7).
"""

from __future__ import annotations

import time

from ..compression import get_compressor
from ..compression.metrics import estimate_tokens
from ..core.config import get_settings as get_app_settings
from ..core.llm import get_llm
from ..core.logging import get_logger
from ..core.reliability import safe_call
from ..db.repository import Repository
from ..economics import build_request_economics
from ..llm import detect_conflicts, get_llm_provider
from ..loops.events import complete_loop_run_sync, emit_loop_event_sync, start_loop_run_sync
from ..loops.types import LoopId, LoopState, LoopStatus
from ..observability import (
    observe_economics,
    observe_retrieval,
    record_admission_decision,
    record_policy_decision,
    set_correlation_id,
    span,
)
from ..schemas.memory import (
    ChatRequest,
    ChatResponse,
    Compression,
    Economics,
    MemoryUsageTrace,
    OutputGateResult,
    Source,
    UsedMemory,
)
from .admission_gate import AdmissionGate
from .audit import AuditService
from .context_composer import ContextComposer
from .extractor import Extractor
from .output_gate import OutputGate
from .policy_broker import PolicyBroker
from .ranker import Ranker
from .recall_gate import RecallGate
from .retriever import Retriever
from .write_service import WriteService

logger = get_logger("memoryops.gateway")


class Gateway:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo
        self._audit = AuditService(repo)
        self._extractor = Extractor()
        self._policy = PolicyBroker(repo)
        self._writer = WriteService(repo, self._audit)
        self._retriever = Retriever(repo)
        self._ranker = Ranker()
        self._admission_gate = AdmissionGate()
        self._recall_gate = RecallGate()  # v1.9 audience-aware recall (ADR-023)
        self._composer = ContextComposer()
        self._compressor = get_compressor()
        self._llm = get_llm()
        # v0.4: provider-neutral LLM used for advisory conflict detection on the
        # write path. Stub by default; never overrides the policy broker (ADR-008).
        self._llm_provider = get_llm_provider()

    @staticmethod
    def _embedding_model(settings) -> str:
        """Model name for embedding-cost estimation; "" (unpriced) for stub."""
        return settings.openai_embedding_model if settings.embeddings_provider == "openai" else ""

    @staticmethod
    def _llm_model(settings) -> str:
        """Model name for LLM-cost estimation; "" (unpriced) for stub/heuristic."""
        return {
            "openai": settings.openai_model,
            "anthropic": settings.anthropic_model,
            "gemini": settings.gemini_model,
        }.get(settings.llm_provider, "")

    def handle_chat(self, req: ChatRequest, trace_id: str) -> ChatResponse:
        start = time.monotonic()
        # v1.8: this turn's trace_id is the tracing correlation id; set it here too so
        # spans correlate even when the gateway is driven directly (not via HTTP).
        set_correlation_id(trace_id)
        settings = self._repo.get_settings(req.tenant_id, req.user_id)

        # ── Invariant #6: temporary chat / memory off → no read, no write ──────
        if req.temporary_chat or not settings.memory_enabled:
            reason = "temporary_chat" if req.temporary_chat else "memory_disabled"
            self._audit.record(
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                action="temporary_chat_skipped",
                reason=f"memory bypassed: {reason}",
                trace_id=trace_id,
            )
            answer = self._llm.complete(system="", user=req.message)
            return ChatResponse(
                assistant_message=answer,
                used_memories=[],
                candidate_memories=[],
                audit_event_ids=[],
                temporary_chat=req.temporary_chat,
                retrieval_mode="none",
                loop_evidence={"memory.read": "skipped", "memory.write": "skipped"},
                trace_id=trace_id,
            )

        # ── READ path (graceful degradation: never blocks the response) ────────
        used_memories: list[UsedMemory] = []
        context_block = ""
        read_loop = start_loop_run_sync(
            self._repo,
            LoopId.MEMORY_READ,
            trace_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            metadata={
                "temporary_chat": req.temporary_chat,
                "memory_enabled": settings.memory_enabled,
            },
        )
        emit_loop_event_sync(
            self._repo,
            read_loop,
            LoopState.OBSERVED,
            event_type="memory_read_observed",
            reason="user query received for memory read loop",
            evidence={"message_present": bool(req.message.strip())},
        )
        emit_loop_event_sync(
            self._repo,
            read_loop,
            LoopState.POLICY_CHECKED,
            event_type="memory_read_policy_checked",
            reason="tenant/user/status/deleted filters applied",
            evidence={"tenant_scoped": True, "user_scoped": True, "active_only": True},
        )

        def _read():
            # v1.8: each read stage is a span under this turn's correlation id, so a
            # trace shows retrieve → rank → admission → recall → compose (ADR-022/023).
            with span("memory.read"):
                with span("retrieve") as sp:
                    result = self._retriever.retrieve(req.tenant_id, req.user_id, req.message)
                    if sp is not None:
                        sp.attributes.update(mode=result.mode, candidates=len(result.candidates))
                with span("rank"):
                    ranked = self._ranker.rank(result.candidates)
                # Context Admission Gate (v1.3, ADR-017): permissioned entry into
                # context. Runs after rank / before compose; only ALLOW memories are
                # composed (or all, in observe-only mode). Defense-in-depth: it only
                # ever removes memory, never adds.
                with span("admission") as sp:
                    admission = self._admission_gate.evaluate(
                        ranked,
                        tenant_id=req.tenant_id,
                        user_id=req.user_id,
                        # Resolve lineage ancestry (incl. soft-deleted rows) so a memory
                        # derived from a deleted ancestor is blocked (tombstone lineage,
                        # v1.4, ADR-018). Scoped to this tenant/user (invariant #1).
                        ancestor_lookup=lambda mid: self._repo.get_memory(
                            req.tenant_id, req.user_id, mid
                        ),
                    )
                    if sp is not None:
                        sp.attributes.update(
                            admitted=len(admission.admitted),
                            blocked=len(admission.blocked_records),
                        )
                # Recall Gate (v1.9, ADR-023): audience-aware entry — re-blocks any
                # admitted memory whose sensitivity exceeds this session's clearance.
                admitted_records = admission.admitted_records
                recall_blocked: list = []
                if get_app_settings().recall_gate_enabled:
                    with span("recall") as sp:
                        recall = self._recall_gate.evaluate(
                            admitted_records, audience=req.audience
                        )
                        admitted_records = recall.allowed
                        recall_blocked = recall.blocked
                        if sp is not None:
                            sp.attributes.update(
                                audience=req.audience, blocked=len(recall_blocked)
                            )
                with span("compose"):
                    block, used = self._composer.compose([r.ranked for r in admitted_records])
            return block, used, result.mode, admission, admitted_records, recall_blocked

        _read_start = time.monotonic()
        (
            context_block, used_memories, retrieval_mode,
            admission, admitted_records, recall_blocked,
        ) = safe_call(_read, default=("", [], "none", None, [], []), label="retrieval")
        observe_retrieval(retrieval_mode, (time.monotonic() - _read_start) * 1000)

        # ── Admission accounting: metrics, audit, and the memory usage trace ────
        trace: MemoryUsageTrace | None = None
        if admission is not None:
            for record in admission.records:
                record_admission_decision(record.decision.value)
            # v1.9: the Recall Gate's audience blocks join the admission blocks, so
            # the trace, metrics, and audit explain them uniformly (ADR-023).
            for record in recall_blocked:
                record_admission_decision(record.decision.value)
            blocked = admission.blocked_records + recall_blocked
            if blocked:
                counts = admission.counts()
                if recall_blocked:
                    counts["BLOCK_AUDIENCE"] = counts.get("BLOCK_AUDIENCE", 0) + len(recall_blocked)
                self._audit.record(
                    tenant_id=req.tenant_id,
                    user_id=req.user_id,
                    action="context_admission_blocked",
                    reason=f"{len(blocked)} memory(ies) denied context admission",
                    trace_id=trace_id,
                    metadata={
                        "blocked_count": len(blocked),
                        "decisions": counts,
                        "blocked_memory_ids": [r.memory.id for r in blocked],
                    },
                )
            if get_app_settings().memory_trace_enabled:
                counts = admission.counts()
                if recall_blocked:
                    counts["BLOCK_AUDIENCE"] = counts.get("BLOCK_AUDIENCE", 0) + len(recall_blocked)
                trace = MemoryUsageTrace(
                    response_id=trace_id,
                    memories_used=[r.to_trace_entry() for r in admitted_records],
                    memories_blocked=[r.to_trace_entry() for r in blocked],
                    admission_counts=counts,
                )
        emit_loop_event_sync(
            self._repo,
            read_loop,
            LoopState.EXECUTED,
            event_type="memory_read_executed",
            reason="retrieval, ranking, admission, and context composition executed",
            evidence={
                "used_memory_count": len(used_memories),
                "retrieval_mode": retrieval_mode,
                "admission_decisions": admission.counts() if admission is not None else {},
            },
        )
        read_audit_id: str | None = None
        if used_memories:
            read_audit = self._audit.record(
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                action="memory_retrieved",
                reason=f"retrieved {len(used_memories)} memory(ies) for context",
                trace_id=trace_id,
                metadata={"memory_count": len(used_memories), "retrieval_mode": retrieval_mode},
            )
            read_audit_id = read_audit.id
        if retrieval_mode == "fallback":
            # Embedding failed → keyword-only retrieval (invariant #4). Track for ops.
            fallback_audit = self._audit.record(
                tenant_id=req.tenant_id,
                user_id=req.user_id,
                action="retrieval_fallback",
                reason="embedding unavailable; degraded to keyword-only retrieval",
                trace_id=trace_id,
            )
            read_audit_id = fallback_audit.id

        # ── Context compression (after governance/composition, before LLM) ──────
        # Only the governed, composed context block is compressed — never the raw
        # user message and never pre-policy content (ADR-007). Failure degrades to
        # the uncompressed block; it must never block the response.
        llm_context = context_block
        compression: Compression | None = None
        compression_failed = False
        if context_block:
            result = self._compressor.compress_context(context_block, trace_id=trace_id)
            if result.failed:
                compression_failed = True
                logger.warning(
                    "context compression failed; using uncompressed context",
                    extra={
                        "event": "context_compression_failed",
                        "provider": result.provider,
                        "reason": result.reason,
                        "fallback": True,
                    },
                )
            elif result.provider != "noop":
                llm_context = result.compressed_text
                logger.info(
                    "context compressed",
                    extra={
                        "event": "context_compression",
                        "provider": result.provider,
                        "original_tokens_estimate": result.original_tokens_estimate,
                        "compressed_tokens_estimate": result.compressed_tokens_estimate,
                        "tokens_saved_estimate": result.tokens_saved_estimate,
                        "compression_ratio": result.compression_ratio,
                        "fallback": False,
                    },
                )
            if result.provider != "noop":
                compression = Compression(
                    enabled=True,
                    provider=result.provider,
                    original_tokens_estimate=result.original_tokens_estimate,
                    compressed_tokens_estimate=result.compressed_tokens_estimate,
                    tokens_saved_estimate=result.tokens_saved_estimate,
                    compression_ratio=result.compression_ratio,
                    fallback=result.failed,
                )
        # ── Economics (advisory token + cost estimate, v1.2, ADR-016) ───────────
        # Reuses the deterministic token estimator + compression result; no-throw
        # so it can never affect the chat path (invariant #4). Records content-free
        # Prometheus counters and attaches an economics block to the response.
        economics: Economics | None = None
        try:
            if compression is not None:
                ctx_tokens = compression.original_tokens_estimate
                comp_tokens = compression.compressed_tokens_estimate
                saved = compression.tokens_saved_estimate
            else:
                ctx_tokens = estimate_tokens(context_block)
                comp_tokens = ctx_tokens
                saved = 0
            app_settings = get_app_settings()
            req_econ = build_request_economics(
                embedding_model=self._embedding_model(app_settings),
                llm_model=self._llm_model(app_settings),
                query_text=req.message,
                context_tokens=ctx_tokens,
                compressed_tokens=comp_tokens,
                tokens_saved=saved,
                llm_context_text=llm_context,
                embedded=(retrieval_mode == "hybrid"),
                overrides_json=app_settings.pricing_overrides_json,
            )
            observe_economics(req_econ)
            economics = Economics(**req_econ.as_dict())
        except Exception:  # noqa: BLE001 — economics is advisory, never fatal
            logger.debug("economics estimate skipped", extra={"event": "economics"})

        if retrieval_mode == "fallback" or compression_failed:
            emit_loop_event_sync(
                self._repo,
                read_loop,
                LoopState.SAFE_DEGRADED,
                event_type="memory_read_safe_degraded",
                reason="read loop used a safe fallback",
                evidence={
                    "retrieval_mode": retrieval_mode,
                    "compression_failed": compression_failed,
                },
            )
            read_status = LoopStatus.SAFE_DEGRADED
        else:
            emit_loop_event_sync(
                self._repo,
                read_loop,
                LoopState.VERIFIED,
                event_type="memory_read_verified",
                reason="retrieval results validated for scoped active memory use",
                evidence={"used_memory_ids": [u.memory_id for u in used_memories]},
            )
            read_status = LoopStatus.COMPLETED
        emit_loop_event_sync(
            self._repo,
            read_loop,
            LoopState.AUDITED,
            event_type="memory_read_audited",
            reason="read loop audit evidence linked",
            evidence={"audit_linked": read_audit_id is not None},
            audit_event_id=read_audit_id,
        )
        emit_loop_event_sync(
            self._repo,
            read_loop,
            LoopState.COMPLETED,
            event_type="memory_read_completed",
            reason="memory read loop completed",
            evidence={"status": read_status.value},
        )
        complete_loop_run_sync(
            self._repo,
            read_loop,
            status=read_status,
            metadata={"used_memory_count": len(used_memories), "retrieval_mode": retrieval_mode},
        )

        # ── Response generation ────────────────────────────────────────────────
        answer = self._llm.complete(system=llm_context, user=req.message)

        # ── Output Gate (v1.9, ADR-023): the mirror of the Recall/Admission gates on
        # the way out — inspect the generated answer and redact/refuse any content
        # that would disclose a memory those gates blocked. No-throw; only ever
        # removes information from the answer, never adds.
        output_gate_result: OutputGateResult | None = None
        if get_app_settings().output_gate_enabled and admission is not None:
            protected = admission.blocked_records + recall_blocked
            with span("output_gate") as _sp:
                review = OutputGate(mode=get_app_settings().output_gate_mode).review(
                    answer, protected=protected
                )
                if _sp is not None:
                    _sp.attributes.update(action=review.action, disclosures=review.disclosures)
            if review.action != "allow":
                answer = review.answer
                output_gate_result = OutputGateResult(
                    action=review.action,
                    disclosures=review.disclosures,
                    escalated=review.escalated,
                )
                self._audit.record(
                    tenant_id=req.tenant_id,
                    user_id=req.user_id,
                    action="output_gate_blocked",
                    reason=f"output gate {review.action}: {review.disclosures} disclosure(s)",
                    trace_id=trace_id,
                    metadata={
                        "action": review.action,
                        "disclosures": review.disclosures,
                        "protected_memory_ids": review.protected_ids,
                    },
                )

        # ── WRITE path (policy before storage) ─────────────────────────────────
        write_loop = start_loop_run_sync(
            self._repo,
            LoopId.MEMORY_WRITE,
            trace_id,
            tenant_id=req.tenant_id,
            user_id=req.user_id,
            metadata={"temporary_chat": False, "memory_enabled": settings.memory_enabled},
        )
        emit_loop_event_sync(
            self._repo,
            write_loop,
            LoopState.OBSERVED,
            event_type="memory_write_observed",
            reason="user message received for memory write loop",
            evidence={"message_present": bool(req.message.strip())},
        )
        source = Source(kind="chat", excerpt=req.message, conversation_id=req.conversation_id)
        # v1.8: trace the write path (extract → policy → commit) under this turn's
        # correlation id (ADR-022).
        with span("memory.write.extract") as _sp:
            candidates = self._extractor.extract(req.message, source)
            if _sp is not None:
                _sp.attributes.update(candidates=len(candidates))
        # v0.4: advisory conflict detection against existing active memories.
        # Observability only — it logs `conflict_detection_result` and never
        # changes the policy decision (broker stays authoritative). Wrapped so a
        # provider hiccup can never block the write path (invariant #4).
        if candidates:
            existing = safe_call(
                lambda: [
                    (m.id, m.content)
                    for m in self._repo.retrieve_active(req.tenant_id, req.user_id)
                ],
                default=[],
                label="conflict_existing",
            )
            for cand in candidates:
                safe_call(
                    lambda c=cand: detect_conflicts(self._llm_provider, c.content, existing),
                    default=None,
                    label="conflict_detection",
                )
        emit_loop_event_sync(
            self._repo,
            write_loop,
            LoopState.CLASSIFIED,
            event_type="memory_write_classified",
            reason="candidate memories extracted",
            evidence={
                "candidate_count": len(candidates),
                "types": [c.type.value for c in candidates],
            },
        )
        # Pass 1 — evaluate the policy broker for every candidate. The loop state
        # machine models a *single* policy gate per write loop, so POLICY_CHECKED is
        # emitted exactly once (below), independent of how many memories a single
        # message extracts. Emitting it per candidate produced an invalid
        # policy_checked -> policy_checked transition that 500-d any multi-memory
        # write (reachable since multi-memory extraction, P1.3).
        outcomes = []
        policy_decisions = []
        for cand in candidates:
            outcome = self._policy.evaluate(
                cand, tenant_id=req.tenant_id, user_id=req.user_id, settings=settings
            )
            record_policy_decision(outcome.decision.value)
            outcomes.append(outcome)
            policy_decisions.append(
                {
                    "decision": outcome.decision.value,
                    "type": cand.type.value,
                    "sensitivity": outcome.candidate.sensitivity.value,
                }
            )
        emit_loop_event_sync(
            self._repo,
            write_loop,
            LoopState.POLICY_CHECKED,
            event_type="memory_write_policy_checked",
            reason=(
                "policy broker decision made"
                if candidates
                else "no candidate memory required policy action"
            ),
            evidence={"candidate_count": len(candidates), "decisions": policy_decisions},
        )
        # Pass 2 — commit each policy outcome.
        decisions = []
        audit_ids: list[str] = []
        for outcome in outcomes:
            with span("memory.write.commit") as _sp:
                decision_view, ids = self._writer.commit(
                    outcome, tenant_id=req.tenant_id, user_id=req.user_id, trace_id=trace_id
                )
                if _sp is not None:
                    _sp.attributes.update(decision=outcome.decision.value)
            decisions.append(decision_view)
            audit_ids.extend(ids)
        emit_loop_event_sync(
            self._repo,
            write_loop,
            LoopState.EXECUTED,
            event_type="memory_write_executed",
            reason="write loop executed storage or no-op decision",
            evidence={
                "decision_count": len(decisions),
                "decisions": [d.decision.value for d in decisions],
                "memory_ids": [d.memory_id for d in decisions if d.memory_id],
            },
        )
        emit_loop_event_sync(
            self._repo,
            write_loop,
            LoopState.VERIFIED,
            event_type="memory_write_verified",
            reason="write decisions verified",
            evidence={"audit_event_count": len(audit_ids)},
        )
        emit_loop_event_sync(
            self._repo,
            write_loop,
            LoopState.AUDITED,
            event_type="memory_write_audited",
            reason="write loop audit evidence linked",
            evidence={"audit_event_ids": audit_ids},
            audit_event_id=audit_ids[-1] if audit_ids else None,
        )
        emit_loop_event_sync(
            self._repo,
            write_loop,
            LoopState.COMPLETED,
            event_type="memory_write_completed",
            reason="memory write loop completed",
            evidence={"decision_count": len(decisions)},
        )
        complete_loop_run_sync(
            self._repo,
            write_loop,
            metadata={"decision_count": len(decisions), "audit_event_count": len(audit_ids)},
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "chat handled",
            extra={
                "event": "chat",
                "latency_ms": latency_ms,
                "memory_count": len(used_memories),
                "status": "success",
            },
        )

        return ChatResponse(
            assistant_message=answer,
            used_memories=used_memories,
            candidate_memories=decisions,
            audit_event_ids=audit_ids,
            temporary_chat=False,
            retrieval_mode=retrieval_mode,
            compression=compression,
            economics=economics,
            trace=trace,
            output_gate=output_gate_result,
            loop_evidence={
                "memory.read": read_status.value,
                "memory.write": LoopStatus.COMPLETED.value,
                "context.compression": (
                    "safe_degraded"
                    if compression_failed
                    else "completed"
                    if compression
                    else "skipped"
                ),
            },
            trace_id=trace_id,
        )
