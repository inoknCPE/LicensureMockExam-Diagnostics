import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from logger import logger


class Database:
    def __init__(self, db_name: str | Path):
        self.db_name = Path(db_name)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_name.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_name)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the authentication table and safely upgrade the old foundation."""
        try:
            with self.connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT COLLATE NOCASE NOT NULL UNIQUE,
                        email TEXT COLLATE NOCASE NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL DEFAULT 'user'
                            CHECK (role IN ('user', 'admin')),
                        invalid_attempts INTEGER NOT NULL DEFAULT 0,
                        is_locked INTEGER NOT NULL DEFAULT 0
                            CHECK (is_locked IN (0, 1)),
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                self._upgrade_legacy_users_table(connection)
                connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique
                    ON users(email COLLATE NOCASE)
                    WHERE email IS NOT NULL
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS password_reset_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        new_password_hash TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'approved', 'rejected')),
                        requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        reviewed_at TEXT,
                        reviewed_by INTEGER,
                        FOREIGN KEY (user_id) REFERENCES users(id),
                        FOREIGN KEY (reviewed_by) REFERENCES users(id)
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_one_pending_reset_per_user
                    ON password_reset_requests(user_id)
                    WHERE status = 'pending'
                    """
                )
            logger.info("Database initialized successfully: %s", self.db_name)
        except sqlite3.Error:
            logger.exception("Database initialization failed")
            raise

    @staticmethod
    def _upgrade_legacy_users_table(connection: sqlite3.Connection) -> None:
        """Add authentication columns if the user's old database is reused."""
        existing = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        additions = {
            "email": "TEXT COLLATE NOCASE",
            "role": "TEXT NOT NULL DEFAULT 'user'",
            "invalid_attempts": "INTEGER NOT NULL DEFAULT 0",
            "is_locked": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT",
            "updated_at": "TEXT",
        }
        for column, definition in additions.items():
            if column not in existing:
                connection.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")


def init_db(db_name: str | Path = "licensure_exam.db") -> Database:
    database = Database(db_name)
    database.initialize()
    return database
