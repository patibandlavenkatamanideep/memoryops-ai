# Deletion Compaction — Clearing Deleted Memory's Content + Vector Material (v0.7)

> Part of the [background lifecycle workers](background-lifecycle-workers.md).
> Decision record: [ADR-011](../infra/adr/ADR-011-physical-deletion-compaction-vector-purge.md).
> See also: [deletion-verification.md](deletion-verification.md),
> [vector-purge-verification.md](vector-purge-verification.md),
> [security.md](security.md), [governance.md](governance.md).

v0.6 proved **logical** deletion: a `status='deleted'` memory is unreachable
(invariant #2). v0.7 adds the next layer — the **deletion compaction worker**
clears the deleted memory's retrievable content and vector material, preserves the
governance tombstone, and records audit evidence for every step.

## What it does

For each soft-deleted memory in a `(tenant_id, user_id)` scope that is past its
retention/grace window (`workers_compaction_min_age_days`), the worker:

1. compacts the row via `Repository.compact_deleted_memory`;
2. emits `memory_content_compacted` and `memory_vector_purge_attempted`;
3. **verifies** the purge (`verify_purged`, see
   [vector-purge-verification.md](vector-purge-verification.md));
4. on success emits `memory_vector_purge_verified` +
   `memory_purge_tombstone_preserved`; on failure emits
   `memory_vector_purge_failed` and the run is `completed_with_findings`.

It only ever touches `status='deleted'` rows. Active and archived (not-deleted)
memory is never compacted; deleted memory is never resurrected.

## Cleared vs preserved

| Cleared (payload) | Preserved (governance tombstone) |
|--|--|
| `content`, `normalized_content` | memory id |
| embedding / vector material | `tenant_id`, `user_id` |
| `source.excerpt` (content excerpt) | `status` (stays `deleted`), `deleted_at`, `created_at` |
| | `source.kind` (provenance, invariant #3) |
| | full audit trail + `metadata.compaction.*` marker |

> Compaction must never destroy governance evidence. The row remains as a
> content-free tombstone: you can still prove *that* a memory existed and *when /
> why* it was deleted — you just can't read *what* it said.

## Eligibility

- status must be `deleted`;
- deleted for at least `workers_compaction_min_age_days` (default `0`);
- not already compacted (the repository filters those out → **idempotent**).

## Running

```bash
cd services/api
# compaction only, one scope
.venv/bin/python -m app.workers.runner --tenant t1 --user u1 --job deletion_compaction
# dry run: count eligible candidates, clear nothing
.venv/bin/python -m app.workers.runner --tenant t1 --user u1 --job deletion_compaction --dry-run
```

`all` runs compaction **before** deletion verification so verification observes
the compacted state. The CLI exits non-zero if any purge fails to verify.

## Configuration

| Setting | Default | Meaning |
|---------|---------|---------|
| `workers_compaction_min_age_days` | 0 | min days since `deleted_at` before a deleted memory is compaction-eligible (retention/grace window) |

## Guarantees (enforced in code + tests)

- **Tenant scoped** (invariant #1) — only the given scope is read/written.
- **Idempotent + retry-safe** — re-running compacts nothing already compacted and
  never corrupts the tombstone; a failed compaction can be retried safely.
- **Never resurrects / reactivates** (invariant #2) — status stays `deleted`.
- **Policy broker stays authoritative** — compaction is destructive-of-payload
  only; it never creates or promotes memory.
- **Audited, content-free** (invariant #7) — ids/counts/flags only, never the
  cleared content.
- **Never blocks chat** (invariant #4) — off the request path; failures are caught.

## Limitations (kept honest)

v0.7 is **auditable content/vector compaction + verification**. It is **not**:

- cryptographic erasure (crypto-shred);
- guaranteed physical disk / database-page byte reclamation;
- pgvector ANN-index reindex / `VACUUM` orchestration;
- a destructive hard `DELETE` (the tombstone is deliberately kept).

See [vector-purge-verification.md](vector-purge-verification.md) for exactly what
"purge" is verified at the application + repository level, and ADR-011 for the
boundary between what we clear and what the storage engine owns.
