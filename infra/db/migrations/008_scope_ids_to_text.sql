-- 008_scope_ids_to_text.sql — align every application-written id/scope column with
-- the ORM (app/models/sqlalchemy_models.py) and the in-memory backend.
--
-- Root cause: migrations 002/005/006 typed id / tenant_id / user_id / memory_id /
-- loop_run_id / audit_event_id as `uuid` on the tables the application writes, but
-- the ORM types them all as String and provides client-generated ids from _uuid()
-- (a uuid-format *string*). SQLAlchemy binds those as varchar, so every INSERT on
-- the Postgres backend fails with "column is of type uuid but expression is of type
-- character varying" — i.e. the entire Postgres write path (chat, memory, audit,
-- loops, workers) was non-functional. Migrations 005+ already chose `text` for the
-- scope columns "to match the application-facing repository"; this retrofits the
-- id/uuid columns 002/005/006 left as uuid so the app path works end-to-end.
--
-- Also drops the FKs to tenants/users (never provisioned by the repository) and the
-- internal loop/feedback FKs (the app enforces those relationships; the in-memory
-- backend has no FKs, so dropping them keeps backend parity). id columns keep a text
-- default (gen_random_uuid()::text) so raw inserts that omit id still get an id.
--
-- The tenant-isolation RLS policies (migration 004) already compared on ::text, so
-- their semantics are unchanged; they are dropped/recreated only because a column
-- type cannot be altered while a policy references it.

begin;

-- ── drop policies + FKs that block the type changes ──────────────────────────
drop policy if exists memory_records_tenant_isolation    on memory_records;
drop policy if exists memory_audit_logs_tenant_isolation on memory_audit_logs;
drop policy if exists memory_feedback_tenant_isolation   on memory_feedback;
drop policy if exists memory_settings_tenant_isolation   on memory_settings;

alter table memory_records  drop constraint if exists memory_records_tenant_id_fkey;
alter table memory_records  drop constraint if exists memory_records_user_id_fkey;
alter table memory_feedback drop constraint if exists memory_feedback_memory_id_fkey;
alter table loop_events     drop constraint if exists loop_events_loop_run_id_fkey;

-- ── memory_records ───────────────────────────────────────────────────────────
alter table memory_records alter column id drop default;
alter table memory_records alter column id type text using id::text;
alter table memory_records alter column id set default gen_random_uuid()::text;
alter table memory_records alter column tenant_id type text using tenant_id::text;
alter table memory_records alter column user_id   type text using user_id::text;

-- ── memory_audit_logs ────────────────────────────────────────────────────────
alter table memory_audit_logs alter column id drop default;
alter table memory_audit_logs alter column id type text using id::text;
alter table memory_audit_logs alter column id set default gen_random_uuid()::text;
alter table memory_audit_logs alter column tenant_id type text using tenant_id::text;
alter table memory_audit_logs alter column user_id   type text using user_id::text;
alter table memory_audit_logs alter column memory_id type text using memory_id::text;

-- ── memory_feedback ──────────────────────────────────────────────────────────
alter table memory_feedback alter column id drop default;
alter table memory_feedback alter column id type text using id::text;
alter table memory_feedback alter column id set default gen_random_uuid()::text;
alter table memory_feedback alter column tenant_id type text using tenant_id::text;
alter table memory_feedback alter column user_id   type text using user_id::text;
alter table memory_feedback alter column memory_id type text using memory_id::text;

-- ── memory_settings ──────────────────────────────────────────────────────────
alter table memory_settings alter column id drop default;
alter table memory_settings alter column id type text using id::text;
alter table memory_settings alter column id set default gen_random_uuid()::text;
alter table memory_settings alter column tenant_id type text using tenant_id::text;
alter table memory_settings alter column user_id   type text using user_id::text;

-- ── loop_runs ────────────────────────────────────────────────────────────────
alter table loop_runs alter column id drop default;
alter table loop_runs alter column id type text using id::text;
alter table loop_runs alter column id set default gen_random_uuid()::text;

-- ── loop_events ──────────────────────────────────────────────────────────────
alter table loop_events alter column id drop default;
alter table loop_events alter column id type text using id::text;
alter table loop_events alter column id set default gen_random_uuid()::text;
alter table loop_events alter column loop_run_id    type text using loop_run_id::text;
alter table loop_events alter column audit_event_id type text using audit_event_id::text;

-- ── worker_runs ──────────────────────────────────────────────────────────────
alter table worker_runs alter column id drop default;
alter table worker_runs alter column id type text using id::text;
alter table worker_runs alter column id set default gen_random_uuid()::text;

-- ── recreate the tenant-isolation policies (identical semantics to migration 004)
create policy memory_records_tenant_isolation on memory_records
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));

create policy memory_audit_logs_tenant_isolation on memory_audit_logs
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));

create policy memory_feedback_tenant_isolation on memory_feedback
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));

create policy memory_settings_tenant_isolation on memory_settings
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));

commit;
