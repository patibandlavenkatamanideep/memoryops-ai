-- 012_memory_revision.sql — optimistic-concurrency token for governed content updates
--
-- Without it, two writers that both read a memory and then edit it silently
-- produce a lost update: the second write wins and the first disappears with no
-- signal. The realistic collisions are a user editing while a lifecycle worker
-- decays or archives the same row, and a content edit racing a governance action.
--
-- A caller reads `revision`, sends it back as `expected_revision`, and receives a
-- 409 Conflict if anything changed underneath. Omitting `expected_revision` keeps
-- the previous last-write-wins behaviour, so existing clients are unaffected
-- (additive under the 1.x promise).
--
-- Backfilled to 1 for existing rows; NOT NULL with a server default so any insert
-- that predates the application change still succeeds.

begin;

alter table memory_records
  add column if not exists revision integer not null default 1;

-- ── schema version marker ───────────────────────────────────────────────────
create table if not exists memoryops_schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);

insert into memoryops_schema_migrations (version)
values ('012_memory_revision')
on conflict (version) do nothing;

commit;
