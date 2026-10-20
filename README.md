# Licensure Examination Diagnostic and Mock Testing System

Web-based examination practice with Table of Specifications mapping,
competency-gap analytics, and remediation scheduling.

## Run locally

1. Run `setup.bat`.
2. Create the initial administrator with `create-admin.bat`.
3. Start the app with `run.bat` and open http://127.0.0.1:5000.

Set `SUPABASE_DB_URL` in the ignored root `.env` file to use Supabase. Without
it, the backend uses local SQLite. See [LOCALHOST.md](LOCALHOST.md) for setup,
database migration, and development details.

Account registration requires an email verification link. See
[LOCALHOST.md](LOCALHOST.md#email-verification-with-brevo) to configure Brevo
and apply the Supabase migration.

## Project layout

- `pages/` — HTML pages
- `css/`, `js/` — frontend styles and scripts
- `static/images/` — question-bank images
- `databases/` — local SQLite fallback and migration sources
- `scripts/` — database maintenance utilities
- `supabase/migrations/` — PostgreSQL schema migrations
- `tests/` — Python and JavaScript tests
