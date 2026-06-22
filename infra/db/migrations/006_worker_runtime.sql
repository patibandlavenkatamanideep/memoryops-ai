-- 006_worker_runtime.sql — worker runtime: leases + run history (v0.8, ADR-012)
--
-- The worker orchestrator runs lifecycle jobs on a schedule for explicit scopes.
-- A lease prevents duplicate concurrent runs of the same scope; run history is
-- content-free operational evidence (ids/counts/status only — never memory
-- content). A dead-letter run is just a run row with status='dead_letter'.

create table if not exists worker_leases (
  key text primary key,
  owner text not null,
  acquired_at timestamptz not null default now(),
  expires_at timestamptz not null
);

create index if not exists idx_worker_leases_expires_at
on worker_leases(expires_at);

create table if not exists worker_runs (
  id uuid primary key default gen_random_uuid(),
  tenant_id text not null,
  user_id text not null,
  status text not null,
  jobs jsonb default '[]'::jsonb,
  attempts integer not null default 0,
  scanned_count integer not null default 0,
  changed_count integer not null default 0,
  skipped_count integer not null default 0,
  error_count integer not null default 0,
  owner text not null default '',
  trace_id text,
  error text,
  metadata jsonb default '{}'::jsonb,
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists idx_worker_runs_tenant_user
on worker_runs(tenant_id, user_id);

create index if not exists idx_worker_runs_status
on worker_runs(status);

create index if not exists idx_worker_runs_started_at
on worker_runs(started_at desc);
