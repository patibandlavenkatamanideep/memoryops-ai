"""Vector / content purge verification (v0.7, ADR-011).

Unit-level proof that ``verify_purged`` is fail-closed: it passes only when a
compacted memory is unreachable on every surface, the tombstone is present, and
content + vector material are cleared. Anything else — reachable, material intact,
missing tombstone, or an error in the verification path — is ``fail``.
"""

from __future__ import annotations

from app.schemas.memory import Status
from app.workers.schemas import PurgeVerification
from app.workers.vector_purge import verify_purged

from ._worker_helpers import seed_memory


def _compact(repo, mem):
    return repo.compact_deleted_memory("t1", "u1", mem.id, reason="test")


def test_passes_for_compacted_deleted_memory(repo) -> None:
    mem = seed_memory(repo, content="gone now", status=Status.deleted)
    mem.embedding = [0.1, 0.2]
    _compact(repo, mem)

    check = verify_purged(repo, tenant_id="t1", user_id="u1", memory_id=mem.id)
    assert check.passed
    assert check.result == PurgeVerification.passed.value
    assert check.content_cleared and check.vector_cleared and check.tombstone_present
    assert check.reachable_surfaces == []


def test_fails_when_content_not_cleared(repo) -> None:
    # Deleted but NOT compacted: content still present → fail-closed.
    mem = seed_memory(repo, content="still here", status=Status.deleted)
    check = verify_purged(repo, tenant_id="t1", user_id="u1", memory_id=mem.id)
    assert not check.passed
    assert check.result == PurgeVerification.failed.value
    assert not check.content_cleared


def test_fails_when_reachable_in_a_surface(repo) -> None:
    mem = seed_memory(repo, content="gone", status=Status.deleted)
    _compact(repo, mem)

    class _Leaky:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def retrieve_active(self, t, u):
            return [self._inner.get_memory(t, u, mem.id)]

    check = verify_purged(_Leaky(repo), tenant_id="t1", user_id="u1", memory_id=mem.id)
    assert not check.passed
    assert "active_retrieval" in check.reachable_surfaces


def test_fails_when_tombstone_missing(repo) -> None:
    mem = seed_memory(repo, content="gone", status=Status.deleted)
    _compact(repo, mem)

    class _NoTombstone:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def get_memory(self, t, u, mid):
            return None  # tombstone vanished

    check = verify_purged(_NoTombstone(repo), tenant_id="t1", user_id="u1", memory_id=mem.id)
    assert not check.passed
    assert not check.tombstone_present


def test_fails_closed_on_verification_error(repo) -> None:
    mem = seed_memory(repo, content="gone", status=Status.deleted)
    _compact(repo, mem)

    class _Broken:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def search_candidates(self, *a, **kw):
            raise RuntimeError("index unavailable")

    check = verify_purged(_Broken(repo), tenant_id="t1", user_id="u1", memory_id=mem.id)
    assert check.result == PurgeVerification.failed.value
    assert "verification path error" in check.reason
