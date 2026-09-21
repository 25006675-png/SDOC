-- Server-side runtime state: mailbox OAuth tokens, sync state, spend ledger.
-- Used when SDOC_STATE_BACKEND=supabase, so a restart on a disposable disk
-- does not disconnect the mailbox. Holds OAuth refresh tokens: server only.

create table if not exists public.sdoc_runtime_state (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);

-- No policies: only the service role (the server's secret key) can read or
-- write. The publishable key and signed-in browser users get nothing.
alter table public.sdoc_runtime_state enable row level security;
revoke all on table public.sdoc_runtime_state from public, anon, authenticated;
grant all on table public.sdoc_runtime_state to service_role;
