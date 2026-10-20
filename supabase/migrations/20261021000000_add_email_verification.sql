alter table public.users
    add column if not exists email_verified smallint not null default 1
    check (email_verified in (0, 1));

create table if not exists public.email_verification_tokens (
    user_id bigint primary key references public.users(id) on delete cascade,
    token_hash text not null unique,
    expires_at bigint not null,
    sent_at bigint not null
);

alter table public.email_verification_tokens enable row level security;
revoke all on public.email_verification_tokens from anon, authenticated;
