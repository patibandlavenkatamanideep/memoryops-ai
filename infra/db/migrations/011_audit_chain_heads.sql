-- 011_audit_chain_heads.sql — tenant-locked audit hash-chain head (P0)
--
-- Migration 010 persists prev_hash/entry_hash on every audit event, but the
-- "what is the current head?" read was derived from `order by created_at desc`.
-- Two concurrent audited mutations could read the same head and each compute a
-- successor, forking the chain. This table gives every tenant exactly one head
-- row that the append path locks with SELECT ... FOR UPDATE, so concurrent
-- appends serialize onto a single continuous chain.
--
-- The row is content-free (a hash + timestamp) and tenant-scoped under the same
-- RLS boundary as the audit log itself.

begin;

create table if not exists audit_chain_heads (
  tenant_id  text primary key,
  head_hash  text not null default '',
  updated_at timestamptz not null default now()
);

alter table audit_chain_heads enable row level security;
alter table audit_chain_heads force row level security;

drop policy if exists audit_chain_heads_tenant_isolation on audit_chain_heads;
create policy audit_chain_heads_tenant_isolation on audit_chain_heads
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));

-- ── schema version marker ───────────────────────────────────────────────────
create table if not exists memoryops_schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);

insert into memoryops_schema_migrations (version)
values ('011_audit_chain_heads')
on conflict (version) do nothing;

commit;
