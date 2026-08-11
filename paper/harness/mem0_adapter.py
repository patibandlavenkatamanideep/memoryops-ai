"""S4 — Mem0, driven through its real API with no paid provider (protocol §3).

Mem0 is a *comparison subject*, not a MemoryOps dependency. This adapter drives the
real `mem0.Memory` object: storage, retrieval and deletion all go through Mem0's own
API, and nothing here reaches past it into the underlying vector store.

Running it for free
-------------------
Mem0 defaults to OpenAI for both its LLM and its embedder, and it constructs the LLM
**eagerly in `Memory.__init__`** — so `infer=False` alone is not enough to avoid a
provider. Both model objects are therefore injected through Mem0's sanctioned
`langchain` provider:

* **embedder** — the repository's own deterministic embedding function, the same one
  the S2 plain-vector baseline uses. Holding the embedder constant is deliberate: the
  benchmark is meant to compare *memory-system semantics*, not which embedding model
  is better.
* **LLM** — `NeverCalledChatModel`, which raises if Mem0 ever invokes it. Deterministic
  ingestion uses `infer=False`, so no LLM call should occur; if one does, the run
  fails loudly rather than silently reaching for a network provider.

Vector state lives in a temporary directory, created per adapter instance and removed
on `reset()`/`close()`, so nothing is written to the repository, the user's home, or
any production store.

What this measures, and what it does not
----------------------------------------
`infer=False` bypasses Mem0's LLM-driven memory deduction. This adapter therefore
evaluates the deterministic behaviour the current invariant cases probe — storage,
retrieval, deletion, and scope separation — and says nothing about Mem0's extraction,
consolidation or memory-rewrite quality, which are the parts an LLM drives. Any
comparison drawn from it must be limited accordingly; see `benchmark/COMPARISON.md`.

Scope mapping
-------------
The harness `Scope(tenant_id, user_id)` is mapped onto Mem0's identity model as
`user_id="{tenant_id}:{user_id}"`. Mem0 has no tenant construct, so a compound
identity is the closest honest expression of the boundary the cases probe. That is
API-level scoping, not database-enforced isolation — it is not equivalent to
MemoryOps' Postgres `FORCE ROW LEVEL SECURITY`, and a PASS here must not be read as
the same guarantee.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from .types import (
    Capability,
    EvidenceResult,
    ForgetResult,
    IngestResult,
    MemoryRef,
    OpStatus,
    QueryResult,
    Scope,
    UpdateResult,
)

_API = Path(__file__).resolve().parents[2] / "services" / "api"
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))

#: Mem0's embedder config wants a fixed dimension; the repository's stub embedder
#: produces this many components.
_EMBED_DIMS = 1536


def _deterministic_embeddings():
    """LangChain ``Embeddings`` backed by the repository's stub embedder.

    The same function S2 uses, so the two systems differ by memory semantics rather
    than by embedding quality.
    """
    from langchain.embeddings.base import Embeddings

    from app.embeddings import embed

    class _RepoEmbeddings(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [embed(t) for t in texts]

        def embed_query(self, text: str) -> list[float]:
            return embed(text)

    return _RepoEmbeddings()


def _build_never_called_model():
    """A LangChain chat model that refuses to be used.

    Mem0 requires an LLM object to construct even when every call site passes
    ``infer=False``. Supplying one that raises turns "an unexpected LLM call" into a
    loud failure instead of a silent network request — the difference between a
    benchmark that is provider-free and one that merely looks it.

    Built lazily so importing this module does not require LangChain.
    """
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatResult

    class _NeverCalled(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "never-called"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
            raise AssertionError(
                "Mem0 invoked the LLM during a deterministic benchmark run; this run is "
                "not provider-free. Ingestion must use infer=False."
            )

    return _NeverCalled()


def available() -> bool:
    """Whether the benchmark extra is installed. Keeps S4 optional for normal runs."""
    try:
        import langchain  # noqa: F401
        import langchain_core  # noqa: F401
        import mem0  # noqa: F401
    except Exception:  # noqa: BLE001 — absence is a configuration state, not an error
        return False
    return True


def mem0_version() -> str:
    import importlib.metadata as md

    try:
        return md.version("mem0ai")
    except Exception:  # noqa: BLE001
        return "unknown"


class Mem0Adapter:
    """S4 — the real Mem0, configured to run offline."""

    name = "S4"

    def __init__(self) -> None:
        self._dir: str | None = None
        self._memory = None
        self._build()

    # ── lifecycle ────────────────────────────────────────────────────────────
    def _build(self) -> None:
        from mem0 import Memory

        self._dir = tempfile.mkdtemp(prefix="memoryops-bench-mem0-")
        config = {
            "llm": {"provider": "langchain", "config": {"model": _build_never_called_model()}},
            "embedder": {
                "provider": "langchain",
                "config": {"model": _deterministic_embeddings()},
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "memoryops_benchmark",
                    "embedding_model_dims": _EMBED_DIMS,
                    "path": self._dir,
                },
            },
        }
        self._memory = Memory.from_config(config)

    def close(self) -> None:
        """Drop the on-disk vector state. Idempotent."""
        self._memory = None
        if self._dir:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    def reset(self) -> None:
        """Rebuild from empty. A fresh directory guarantees no case inherits state."""
        self.close()
        self._build()

    # ── contract ─────────────────────────────────────────────────────────────
    def capabilities(self) -> set[Capability]:
        # No governance/audit export: Mem0 is not a governance product, and claiming
        # otherwise would turn a legitimate `unsupported` into a false comparison.
        return {Capability.INGEST, Capability.QUERY, Capability.FORGET, Capability.UPDATE}

    @staticmethod
    def _identity(scope: Scope) -> str:
        """Mem0 has no tenant concept; a compound id is the closest honest mapping."""
        return f"{scope.tenant_id}:{scope.user_id}"

    def ingest(self, scope: Scope, message: str) -> IngestResult:
        try:
            # infer=False: store the supplied fact verbatim, no LLM deduction.
            result = self._memory.add(message, user_id=self._identity(scope), infer=False)
        except Exception as exc:  # noqa: BLE001 — integration failure, not "unsupported"
            return IngestResult(status=OpStatus.ERROR, detail=f"{type(exc).__name__}: {exc}")
        ids = [r["id"] for r in (result or {}).get("results", []) if r.get("id")]
        return IngestResult(status=OpStatus.OK, memory_ids=ids)

    def query(self, scope: Scope, question: str) -> QueryResult:
        try:
            found = self._memory.search(
                question, filters={"user_id": self._identity(scope)}
            )
        except Exception as exc:  # noqa: BLE001
            return QueryResult(status=OpStatus.ERROR, detail=f"{type(exc).__name__}: {exc}")

        rows = (found or {}).get("results", [])
        refs = [
            MemoryRef(
                memory_id=r.get("id", ""),
                content=r.get("memory", ""),
                score=r.get("score"),
            )
            for r in rows
        ]
        # The runner scores retrieved memory, not answer prose, so the context is
        # returned directly rather than spending an LLM call to phrase it.
        return QueryResult(
            status=OpStatus.OK,
            answer="\n".join(r.content or "" for r in refs),
            used_memory_ids=[r.memory_id for r in refs],
            retrieved=refs,
        )

    def forget(self, scope: Scope, memory_id: str) -> ForgetResult:
        try:
            # Mem0's own delete API — never the vector store underneath it.
            self._memory.delete(memory_id=memory_id)
        except Exception as exc:  # noqa: BLE001
            return ForgetResult(status=OpStatus.ERROR, detail=f"{type(exc).__name__}: {exc}")
        return ForgetResult(status=OpStatus.OK)

    def update(self, scope: Scope, memory_id: str, content: str) -> UpdateResult:
        try:
            self._memory.update(memory_id=memory_id, data=content)
        except Exception as exc:  # noqa: BLE001
            return UpdateResult(status=OpStatus.ERROR, detail=f"{type(exc).__name__}: {exc}")
        return UpdateResult(status=OpStatus.OK)

    def export_evidence(self, scope: Scope) -> EvidenceResult:
        return EvidenceResult(
            status=OpStatus.UNSUPPORTED, detail="Mem0 exports no governance evidence"
        )


def s4() -> Mem0Adapter:
    return Mem0Adapter()
