alter table public.users
    add column if not exists terms_accepted_at bigint,
    add column if not exists terms_version text,
    add column if not exists privacy_acknowledged_at bigint,
    add column if not exists privacy_version text;
