-- 005_loop_engineering.sql — loop engineering traces (v0.2.2)
--
-- Loop runs/events are operational evidence, separate from governance audit logs.
-- tenant_id/user_id are text here to match the application-facing repository
-- contract used by the in-memory backend and demo identities.

create table if not exists loop_runs (
  id uuid primary key default gen_random_uuid(),
  loop_id text not null,
  trace_id text not null,
  tenant_id text,
  user_id text,
  status text not null,
  started_at timestamptz default now(),
  ended_at timestamptz,
  metadata jsonb default '{}'::jsonb
);

create table if not exists loop_events (
  id uuid primary key default gen_random_uuid(),
  loop_run_id uuid not null references loop_runs(id),
  loop_id text not null,
  trace_id text not null,
  state_from text,
  state_to text not null,
  event_type text not null,
  reason text not null,
  evidence jsonb default '{}'::jsonb,
  audit_event_id uuid,
  created_at timestamptz default now()
);

create index if not exists idx_loop_runs_trace_id
on loop_runs(trace_id);

create index if not exists idx_loop_runs_loop_id
on loop_runs(loop_id);

create index if not exists idx_loop_runs_tenant_user
on loop_runs(tenant_id, user_id);

create index if not exists idx_loop_events_run_id
on loop_events(loop_run_id);

create index if not exists idx_loop_events_trace_id
on loop_events(trace_id);

create index if not exists idx_loop_events_loop_id
on loop_events(loop_id);
