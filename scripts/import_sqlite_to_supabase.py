"""Copy local application records into an already-migrated Supabase database."""

from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import psycopg
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DEFAULT_SOURCE = ROOT / "databases" / "account_credential.sqlite3"
DEFAULT_BANK_SOURCE = ROOT / "databases" / "questionbank.db"
TABLES = (
    "users",
    "email_verification_tokens",
    "questions",
    "password_reset_requests",
    "imported_question_overrides",
    "question_change_requests",
    "exam_history",
    "licensure_attempts",
    "requests",
)
BANK_TABLES = {
    "bank_disciplines": "disciplines",
    "bank_domains": "domains",
    "bank_questions": "questions",
    "bank_choices": "choices",
    "bank_accepted_answers": "accepted_answers",
}
IDENTITY_TABLES = (
    "users",
    "password_reset_requests",
    "question_change_requests",
    "exam_history",
    "requests",
    *BANK_TABLES,
)
ALL_TABLES = ("sessions", *TABLES, *BANK_TABLES)
OPTIONAL_LOCAL_TABLES = {"email_verification_tokens"}
BATCH_SIZE = 500


def source_counts(source: Path, bank_source: Path = DEFAULT_BANK_SOURCE) -> dict[str, int]:
    if not source.is_file():
        raise FileNotFoundError(f"SQLite source database not found: {source}")
    if not bank_source.is_file():
        raise FileNotFoundError(f"Question bank source database not found: {bank_source}")
    with closing(sqlite3.connect(
        f"{source.resolve().as_uri()}?mode=ro", uri=True
    )) as connection:
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = {"sessions", *TABLES} - existing - OPTIONAL_LOCAL_TABLES
        if missing:
            raise RuntimeError(
                "The local database schema is outdated or incomplete; "
                f"missing tables: {', '.join(sorted(missing))}. "
                "Start the local app once to apply its schema updates, then retry."
            )
        counts = {
            table: (
                connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if table in existing else 0
            )
            for table in ("sessions", *TABLES)
        }
    with closing(sqlite3.connect(
        f"{bank_source.resolve().as_uri()}?mode=ro", uri=True
    )) as connection:
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = set(BANK_TABLES.values()) - existing
        if missing:
            raise RuntimeError(
                "The question bank schema is incomplete; missing tables: "
                + ", ".join(sorted(missing))
            )
        counts.update({
            target: connection.execute(f'SELECT COUNT(*) FROM "{source_table}"').fetchone()[0]
            for target, source_table in BANK_TABLES.items()
        })
    return counts


def read_source_rows(
    source_connection: sqlite3.Connection, table: str
) -> tuple[list[str], list[tuple[object, ...]]]:
    existing = {
        row[0] for row in source_connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    if table == "email_verification_tokens" and table not in existing:
        return ["user_id", "token_hash", "expires_at", "sent_at"], []
    cursor = source_connection.execute(f'SELECT * FROM "{table}"')
    columns = [item[0] for item in cursor.description]
    return columns, cursor.fetchall()


def migrate(
    source: Path,
    bank_source: Path,
    database_url: str,
) -> dict[str, int]:
    from psycopg import sql

    counts = source_counts(source, bank_source)
    migrated_counts: dict[str, int] = {}

    with closing(sqlite3.connect(
        f"{source.resolve().as_uri()}?mode=ro", uri=True
    )) as local:
        local.row_factory = None
        with closing(sqlite3.connect(
            f"{bank_source.resolve().as_uri()}?mode=ro", uri=True
        )) as local_bank:
            local_bank.row_factory = None
            with psycopg.connect(database_url, connect_timeout=15, sslmode="require") as remote:
                with remote.cursor() as cursor:
                    cursor.execute(
                        """
                        select table_name
                        from information_schema.tables
                        where table_schema = 'public' and table_type = 'BASE TABLE'
                        """
                    )
                    target_tables = {row[0] for row in cursor.fetchall()}
                    missing = set(ALL_TABLES) - target_tables
                    if missing:
                        raise RuntimeError(
                            "Supabase is missing application or question-bank tables. "
                            "Apply project migrations with 'npx supabase db push' first. "
                            f"Missing: {', '.join(sorted(missing))}."
                        )

                    existing_rows: dict[str, int] = {}
                    for table in ALL_TABLES:
                        cursor.execute(
                            sql.SQL("select count(*) from {}").format(
                                sql.Identifier("public", table)
                            )
                        )
                        existing_rows[table] = cursor.fetchone()[0]
                    nonempty = [table for table, count in existing_rows.items() if count]
                    if nonempty:
                        raise RuntimeError(
                            "Migration stopped because Supabase application or bank tables "
                            "are not empty: "
                            + ", ".join(f"{table}={existing_rows[table]}" for table in nonempty)
                            + ". This import is intentionally insert-only; back up and "
                            "resolve existing data before retrying."
                        )

                    cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                    for table in TABLES:
                        source_columns, rows = read_source_rows(local, table)
                        _copy_table(cursor, sql, table, source_columns, rows)
                        migrated_counts[table] = len(rows)

                    for target_table, source_table in BANK_TABLES.items():
                        source_columns, rows = read_source_rows(local_bank, source_table)
                        _copy_table(cursor, sql, target_table, source_columns, rows)
                        migrated_counts[target_table] = len(rows)

                    for table in IDENTITY_TABLES:
                        cursor.execute(
                            sql.SQL(
                                """
                                select setval(
                                    pg_get_serial_sequence(%s, 'id'),
                                    coalesce(max(id), 1),
                                    max(id) is not null
                                )
                                from {}
                                """
                            ).format(sql.Identifier("public", table)),
                            (f"public.{table}",),
                        )
                remote.commit()

    migrated_counts["sessions_skipped"] = counts["sessions"]
    return migrated_counts


def _copy_table(cursor, sql, table, columns, rows) -> None:
    cursor.execute(
        """
        select column_name
        from information_schema.columns
        where table_schema = 'public' and table_name = %s
        order by ordinal_position
        """,
        (table,),
    )
    target_columns = {row[0] for row in cursor.fetchall()}
    unsupported = set(columns) - target_columns
    if unsupported:
        raise RuntimeError(
            f"Supabase table {table} lacks local columns: "
            f"{', '.join(sorted(unsupported))}."
        )
    if rows:
        insert = sql.SQL("insert into {} ({}) values ({})").format(
            sql.Identifier("public", table),
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        for start in range(0, len(rows), BATCH_SIZE):
            cursor.executemany(insert, rows[start : start + BATCH_SIZE])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Import local SQLite application data into an empty Supabase "
            "PostgreSQL schema. Session rows are intentionally not copied."
        )
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help=f"SQLite source file (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument(
        "--bank-source",
        type=Path,
        default=DEFAULT_BANK_SOURCE,
        help=f"Question bank SQLite file (default: {DEFAULT_BANK_SOURCE})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the import. Without this flag, only show source row counts.",
    )
    args = parser.parse_args()

    try:
        counts = source_counts(args.source, args.bank_source)
        print(f"Application source: {args.source.resolve()}")
        print(f"Question bank source: {args.bank_source.resolve()}")
        for table in ALL_TABLES:
            suffix = " (not copied; users must sign in again)" if table == "sessions" else ""
            print(f"  {table}: {counts[table]} rows{suffix}")

        if not args.apply:
            print("Dry run only. Add --apply to import into Supabase.")
            return 0

        database_url = os.environ.get("SUPABASE_DB_URL")
        if not database_url:
            database_url = getpass.getpass(
                "Supabase Postgres connection string (input hidden): "
            ).strip()
        if not database_url.startswith(("postgres://", "postgresql://")):
            raise RuntimeError(
                "A PostgreSQL connection string is required. Copy it from the "
                "Supabase dashboard's Connect panel."
            )

        migrated = migrate(args.source, args.bank_source, database_url)
        print("Import committed successfully:")
        for table, count in migrated.items():
            print(f"  {table}: {count} rows")
        return 0
    except (OSError, sqlite3.Error, RuntimeError, psycopg.Error) as error:
        print(f"Migration failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
