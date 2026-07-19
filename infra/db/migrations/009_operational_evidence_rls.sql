-- 009_operational_evidence_rls.sql — RLS for operational evidence (P0)
--
-- Loop and worker history are operational evidence. They carry tenant/user
-- scope and must be protected by the same database tenant boundary as memory
-- records and audit logs. Loop events intentionally inherit scope from their
-- parent loop_run rather than duplicating tenant/user columns.

begin;

-- ── loop_runs ────────────────────────────────────────────────────────────────
alter table loop_runs enable row level security;
alter table loop_runs force row level security;

drop policy if exists loop_runs_tenant_isolation on loop_runs;
create policy loop_runs_tenant_isolation on loop_runs
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));

-- ── loop_events ──────────────────────────────────────────────────────────────
alter table loop_events enable row level security;
alter table loop_events force row level security;

drop policy if exists loop_events_parent_tenant_isolation on loop_events;
create policy loop_events_parent_tenant_isolation on loop_events
  using (
    exists (
      select 1
      from loop_runs
      where loop_runs.id = loop_events.loop_run_id
        and loop_runs.tenant_id = current_setting('app.tenant_id', true)
    )
  )
  with check (
    exists (
      select 1
      from loop_runs
      where loop_runs.id = loop_events.loop_run_id
        and loop_runs.tenant_id = current_setting('app.tenant_id', true)
    )
  );

-- ── worker_runs ──────────────────────────────────────────────────────────────
alter table worker_runs enable row level security;
alter table worker_runs force row level security;

drop policy if exists worker_runs_tenant_isolation on worker_runs;
create policy worker_runs_tenant_isolation on worker_runs
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));

-- ── schema version marker ───────────────────────────────────────────────────
create table if not exists memoryops_schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);

insert into memoryops_schema_migrations (version)
values ('009_operational_evidence_rls')
on conflict (version) do nothing;

commit;
