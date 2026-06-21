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
from ..core.llm import get_llm
from ..core.logging import get_logger
from ..core.reliability import safe_call
from ..db.repository import Repository
from ..loops.events import complete_loop_run_sync, emit_loop_event_sync, start_loop_run_sync
from ..loops.types import LoopId, LoopState, LoopStatus
from ..schemas.memory import (
    ChatRequest,
    ChatResponse,
    Compression,
    Source,
    UsedMemory,
)
from .audit import AuditService
from .context_composer import ContextComposer
from .extractor import Extractor
from .policy_broker import PolicyBroker
from .ranker import Ranker
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
        self._composer = ContextComposer()
        self._compressor = get_compressor()
        self._llm = get_llm()

    def handle_chat(self, req: ChatRequest, trace_id: str) -> ChatResponse:
        start = time.monotonic()
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

        def _read() -> tuple[str, list[UsedMemory], str]:
            result = self._retriever.retrieve(req.tenant_id, req.user_id, req.message)
            ranked = self._ranker.rank(result.candidates)
            block, used = self._composer.compose(ranked)
            return block, used, result.mode

        context_block, used_memories, retrieval_mode = safe_call(
            _read, default=("", [], "none"), label="retrieval"
        )
        emit_loop_event_sync(
            self._repo,
            read_loop,
            LoopState.EXECUTED,
            event_type="memory_read_executed",
            reason="retrieval, ranking, and context composition executed",
            evidence={"used_memory_count": len(used_memories), "retrieval_mode": retrieval_mode},
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
        candidates = self._extractor.extract(req.message, source)
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
        decisions = []
        audit_ids: list[str] = []
        for cand in candidates:
            outcome = self._policy.evaluate(
                cand, tenant_id=req.tenant_id, user_id=req.user_id, settings=settings
            )
            emit_loop_event_sync(
                self._repo,
                write_loop,
                LoopState.POLICY_CHECKED,
                event_type="memory_write_policy_checked",
                reason="policy broker decision made",
                evidence={
                    "decision": outcome.decision.value,
                    "type": cand.type.value,
                    "sensitivity": outcome.candidate.sensitivity.value,
                },
            )
            decision_view, ids = self._writer.commit(
                outcome, tenant_id=req.tenant_id, user_id=req.user_id, trace_id=trace_id
            )
            decisions.append(decision_view)
            audit_ids.extend(ids)
        if not candidates:
            emit_loop_event_sync(
                self._repo,
                write_loop,
                LoopState.POLICY_CHECKED,
                event_type="memory_write_policy_checked",
                reason="no candidate memory required policy action",
                evidence={"candidate_count": 0},
            )
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
