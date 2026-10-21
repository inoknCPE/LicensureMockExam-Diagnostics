"""Offline checks for the Supabase schema and SQLite importer."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("SUPABASE_DB_URL", None)
os.environ.pop("DATABASE_URL", None)
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

from scripts import import_sqlite_to_supabase as migration  # noqa: E402


class SupabaseMigrationTests(unittest.TestCase):
    def test_importer_targets_every_application_table_but_not_sessions(self):
        self.assertEqual(
            set(migration.TABLES),
            {
                "users",
                "email_verification_tokens",
                "questions",
                "password_reset_requests",
                "imported_question_overrides",
                "question_change_requests",
                "exam_history",
                "licensure_attempts",
                "requests",
            },
        )
        self.assertNotIn("sessions", migration.TABLES)
        self.assertIn("sessions", migration.ALL_TABLES)

    def test_local_database_inventory_is_readable_without_writing(self):
        counts = migration.source_counts(migration.DEFAULT_SOURCE)
        self.assertEqual(counts["users"], 1)
        self.assertEqual(counts["questions"], 6)
        self.assertEqual(counts["sessions"], 2)
        self.assertEqual(counts["bank_questions"], 1200)
        self.assertEqual(counts["bank_disciplines"], 6)

    def test_postgres_schema_creates_rls_protected_application_tables(self):
        migrations = ROOT / "supabase" / "migrations"
        schema = "\n".join(path.read_text(encoding="utf-8") for path in migrations.glob("*.sql"))
        for table in migration.ALL_TABLES:
            self.assertIn(f"public.{table}", schema)
            self.assertIn(
                f"alter table public.{table} enable row level security;",
                schema,
            )
        self.assertIn("revoke all on all tables in schema public from anon, authenticated;", schema)
        self.assertIn("opts_json text not null", schema)
        self.assertIn("answers_json text not null default '{}'", schema)
        self.assertIn("email_verified", schema)
        self.assertIn("terms_accepted_at", schema)
        self.assertIn("privacy_acknowledged_at", schema)

    def test_postgres_query_adapter_preserves_question_marks_in_strings(self):
        from backend import _postgres_placeholders

        query = "SELECT '?' AS literal, value FROM items WHERE id=? AND note='it''s?'"
        self.assertEqual(
            _postgres_placeholders(query),
            "SELECT '?' AS literal, value FROM items WHERE id=%s AND note='it''s?'",
        )


if __name__ == "__main__":
    unittest.main()
