-- 010_transactional_audit_chain.sql — persisted audit hash-chain links (P0)
--
-- In-memory audit events already carry prev_hash/entry_hash. Postgres must
-- persist the same evidence so memory mutation + audit append + hash-chain
-- advance can commit atomically in one repository transaction.

begin;

alter table memory_audit_logs
  add column if not exists prev_hash text not null default '',
  add column if not exists entry_hash text not null default '';

create index if not exists idx_memory_audit_logs_tenant_hash_head
on memory_audit_logs(tenant_id, created_at desc)
where entry_hash <> '';

create table if not exists memoryops_schema_migrations (
  version text primary key,
  applied_at timestamptz not null default now()
);

insert into memoryops_schema_migrations (version)
values ('010_transactional_audit_chain')
on conflict (version) do nothing;

commit;
