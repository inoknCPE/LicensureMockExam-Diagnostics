"""Local SQLite authentication and role API for the Computer Engineering prototype."""

from __future__ import annotations

from email.utils import parseaddr
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request as UrlRequest, urlopen
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DATABASE_URL = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
LOCAL_FALLBACK_ENABLED = os.environ.get(
    "CPEDLE_ALLOW_OFFLINE_FALLBACK", ""
).casefold() in {"1", "true", "yes"}
USING_OFFLINE_FALLBACK = False
DB_PATH = Path(os.environ.get(
    "CPEDLE_DB_PATH", ROOT / "databases" / "account_credential.sqlite3"
))
QUESTION_BANK_PATH = ROOT / "databases" / "questionbank.db"
REQUIRED_DATABASE_TABLES = {
    "users", "sessions", "password_reset_requests", "questions",
    "imported_question_overrides", "question_change_requests",
    "exam_history", "licensure_attempts", "requests",
    "email_verification_tokens", "bank_questions", "bank_choices", "bank_accepted_answers",
    "bank_domains", "bank_disciplines",
}
SESSION_SECONDS = 12 * 60 * 60
MAX_ATTEMPTS = 3
TERMS_VERSION = "2026-10-21"
PRIVACY_VERSION = "2026-10-21"
SPECIAL = set("!@#$%^&*()_+-=[]{};:'\"\\|,.<>/?`~")
DISCIPLINES = {
    "Network Engineer": [
        "Networking Fundamentals", "Data Communications and Network Protocols",
        "Routing and Switching", "Network Security", "Wireless and Network Technologies",
    ],
    "Systems Operations Engineer": [
        "Operating System Fundamentals", "Process and Thread Management",
        "Memory Management", "File Systems and Storage", "I/O and System Management",
    ],
    "Computer Systems Architect": [
        "Computer Organization and Architecture Fundamentals",
        "CPU and Instruction Set Architecture", "Memory Hierarchy and Cache",
        "I/O and Peripheral Organization", "Computer Arithmetic and Performance",
    ],
    "Software Developer": [
        "Software Engineering Fundamentals", "Software Development Life Cycle",
        "Requirements Analysis and Specification", "Software Design and Architecture",
        "Software Testing and Maintenance",
    ],
    "Algorithm Engineer": [
        "Algorithm Analysis and Complexity", "Linear Data Structures",
        "Non-Linear Data Structures", "Sorting and Searching Algorithms",
        "Algorithm Design Techniques",
    ],
    "Digital Design Engineer": [
        "Boolean Algebra and Logic Gates", "Combinational Logic Circuits",
        "Sequential Logic Circuits", "Switching Theory and Logic Minimization",
        "Digital System Design",
    ],
}
DOMAINS = {domain for domains in DISCIPLINES.values() for domain in domains}
COGNITIVE = {"Remember", "Understand", "Apply", "Analyze"}
DIFFICULTIES = {"Easy", "Medium", "Hard"}
ROLES = {"STUDENT", "EXAMINER", "ADMIN"}
TOS_BLUEPRINT = {
    "Network Engineer": ([15, 20, 25, 25, 15], [15, 20, 35, 30]),
    "Systems Operations Engineer": ([15, 25, 25, 20, 15], [15, 25, 35, 25]),
    "Computer Systems Architect": ([20, 25, 25, 15, 15], [15, 25, 30, 30]),
    "Software Developer": ([15, 20, 20, 25, 20], [15, 25, 35, 25]),
    "Algorithm Engineer": ([20, 15, 20, 20, 25], [15, 20, 35, 30]),
    "Digital Design Engineer": ([15, 25, 25, 20, 15], [20, 20, 35, 25]),
}
COGNITIVE_ORDER = ["Remember", "Understand", "Apply", "Analyze"]
DIFFICULTY_ORDER = ["Easy", "Medium", "Hard"]


def _postgres_connection_url(value: str) -> str:
    parsed = urlsplit(value)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    return urlunsplit(parsed._replace(query=urlencode(query)))


def _postgres_placeholders(query: str) -> str:
    result = []
    quote = None
    index = 0
    while index < len(query):
        char = query[index]
        if quote:
            result.append(char)
            if char == quote:
                if index + 1 < len(query) and query[index + 1] == quote:
                    result.append(query[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in {"'", '"'}:
            quote = char
            result.append(char)
        elif char == "?":
            result.append("%s")
        else:
            result.append(char)
        index += 1
    return "".join(result)


class _PostgresConnection:
    def __init__(self, connection: psycopg.Connection):
        self._connection = connection

    def execute(self, query: str, params=()):
        if query.strip().upper() == "BEGIN IMMEDIATE":
            query = "BEGIN"
        try:
            return self._connection.execute(_postgres_placeholders(query), params)
        except psycopg.IntegrityError as error:
            raise sqlite3.IntegrityError(str(error)) from error

    def executemany(self, query: str, params):
        try:
            return self._connection.executemany(_postgres_placeholders(query), params)
        except psycopg.IntegrityError as error:
            raise sqlite3.IntegrityError(str(error)) from error

    def commit(self) -> None:
        self._connection.commit()


@contextmanager
def db() -> Iterator[sqlite3.Connection | _PostgresConnection]:
    if DATABASE_URL:
        with psycopg.connect(
            _postgres_connection_url(DATABASE_URL),
            connect_timeout=10,
            row_factory=dict_row,
        ) as connection:
            yield _PostgresConnection(connection)
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
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


@contextmanager
def question_bank() -> Iterator[sqlite3.Connection | _PostgresConnection | None]:
    """Open the imported bank in PostgreSQL or the local SQLite file read-only."""
    if DATABASE_URL:
        with db() as connection:
            yield connection
        return
    if not QUESTION_BANK_PATH.is_file():
        yield None
        return
    connection = sqlite3.connect(QUESTION_BANK_PATH.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def imported_questions(include_answers: bool = False) -> list[dict]:
    with question_bank() as bank:
        if bank is None:
            return []
        tables = (
            ("bank_questions", "bank_domains", "bank_choices")
            if DATABASE_URL else ("questions", "domains", "choices")
        )
        questions_table, domains_table, choices_table = tables
        rows = bank.execute("""
            SELECT q.id, q.question_text, q.question_type, q.image_path,
                   q.answer_letter, q.answer_text, q.cognitive_level, q.difficulty,
                   d.name AS domain
            FROM {questions_table} q JOIN {domains_table} d ON d.id=q.domain_id ORDER BY q.id
        """.format(
            questions_table=questions_table,
            domains_table=domains_table,
        )).fetchall()
        choices = {}
        for choice in bank.execute(
            f"SELECT question_id,letter,choice_text,image_path FROM {choices_table} "
            "ORDER BY question_id,letter"
        ):
            choices.setdefault(choice["question_id"], []).append(choice)
    result = []
    for row in rows:
        options = choices.get(row["id"], [])
        item = {
            "id": f"QB-{row['id']}", "q": row["question_text"],
            "opts": [option["choice_text"] or "" for option in options],
            "optionImages": [bank_image_url(option["image_path"]) for option in options],
            "imageUrl": bank_image_url(row["image_path"]),
            "questionType": row["question_type"], "source": "imported",
            "domain": row["domain"], "cognitive": row["cognitive_level"],
            "difficulty": row["difficulty"], "explanation": "",
        }
        if include_answers:
            item["ans"] = next((i for i, option in enumerate(options)
                                if option["letter"] == row["answer_letter"]), None)
            item["answerText"] = row["answer_text"] or ""
        result.append(item)
    with db() as connection:
        overrides = {row["question_id"]: row for row in connection.execute(
            "SELECT question_id,payload_json,is_deleted FROM imported_question_overrides"
        )}
    visible = []
    for item in result:
        override = overrides.get(item["id"])
        if override and override["is_deleted"]:
            continue
        if override:
            change = json.loads(override["payload_json"])
            item.update({key: change[key] for key in
                         ("q", "opts", "ans", "answerText", "domain", "cognitive",
                          "difficulty", "explanation") if key in change})
        if not include_answers:
            item.pop("ans", None)
            item.pop("answerText", None)
        visible.append(item)
    return visible


def bank_image_url(path: str | None) -> str | None:
    """Only expose image names within the committed static/images directory."""
    if not path or not path.startswith("images/"):
        return None
    relative = Path(path)
    if ".." in relative.parts or relative.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None
    return "/static/" + relative.as_posix()


def initialize() -> None:
    global DATABASE_URL, USING_OFFLINE_FALLBACK
    if DATABASE_URL:
        now = int(time.time())
        try:
            with db() as connection:
                rows = connection.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public' AND table_type='BASE TABLE'"
                )
                existing = {row["table_name"] for row in rows}
        except psycopg.OperationalError as error:
            if not LOCAL_FALLBACK_ENABLED:
                raise
            logging.warning(
                "Could not connect to Supabase at startup (%s); using local "
                "SQLite for this process. Local changes will not sync to Supabase.",
                error,
            )
            DATABASE_URL = None
            USING_OFFLINE_FALLBACK = True
        else:
            missing = REQUIRED_DATABASE_TABLES - existing
            if missing:
                raise RuntimeError(
                    "The Supabase database schema is incomplete. Deploy all project "
                    "migrations before starting the app. Missing tables: "
                    + ", ".join(sorted(missing))
                )
            return
    with db() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('STUDENT','EXAMINER','ADMIN')),
                name TEXT NOT NULL DEFAULT '',
                discipline TEXT NOT NULL DEFAULT '',
                professional_title TEXT NOT NULL DEFAULT '',
                license_number TEXT NOT NULL DEFAULT '',
                examiner_status TEXT NOT NULL DEFAULT 'approved'
                    CHECK(examiner_status IN ('pending','approved','rejected')),
                examiner_reviewed_at TEXT,
                examiner_reviewed_by INTEGER REFERENCES users(id),
                invalid_attempts INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
                email_verified INTEGER NOT NULL DEFAULT 1,
                terms_accepted_at INTEGER,
                terms_version TEXT,
                privacy_acknowledged_at INTEGER,
                privacy_version TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS password_reset_requests (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                new_password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                reviewed_by INTEGER REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at INTEGER NOT NULL,
                sent_at INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_pending_reset
                ON password_reset_requests(user_id) WHERE status = 'pending';
            CREATE TABLE IF NOT EXISTS questions (
                id TEXT PRIMARY KEY,
                q TEXT NOT NULL,
                opts_json TEXT NOT NULL,
                ans INTEGER NOT NULL CHECK(ans BETWEEN 0 AND 3),
                domain TEXT NOT NULL,
                cognitive TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS imported_question_overrides (
                question_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL DEFAULT '{}',
                is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1))
            );
            CREATE TABLE IF NOT EXISTS question_change_requests (
                id INTEGER PRIMARY KEY,
                proposer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action TEXT NOT NULL CHECK(action IN ('ADD','EDIT','DELETE')),
                target_question_id TEXT,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                reviewed_by INTEGER REFERENCES users(id),
                rejection_reason TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS exam_history (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                score_pct INTEGER NOT NULL,
                total_items INTEGER NOT NULL,
                correct_items INTEGER NOT NULL,
                domains_json TEXT NOT NULL,
                report_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS licensure_attempts (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                question_ids_json TEXT NOT NULL,
                planned_json TEXT,
                started_at INTEGER NOT NULL,
                submitted_at INTEGER,
                mode TEXT NOT NULL DEFAULT 'licensure',
                title TEXT NOT NULL DEFAULT 'Mock Licensure Exam',
                selected_domains_json TEXT,
                time_seconds INTEGER NOT NULL DEFAULT 3600,
                expires_at INTEGER,
                answers_json TEXT NOT NULL DEFAULT '{}',
                result_id INTEGER REFERENCES exam_history(id),
                abandoned_at INTEGER
            );
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pending',
                admin_comment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Older installations allowed only ADD and EDIT proposals. Preserve their
        # review history while extending the queue to examiner deletion requests.
        change_schema = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='question_change_requests'"
        ).fetchone()["sql"]
        if "'DELETE'" not in change_schema:
            connection.execute("""CREATE TABLE question_change_requests_v2 (
                id INTEGER PRIMARY KEY,
                proposer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action TEXT NOT NULL CHECK(action IN ('ADD','EDIT','DELETE')),
                target_question_id TEXT,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                reviewed_by INTEGER REFERENCES users(id),
                rejection_reason TEXT NOT NULL DEFAULT ''
            )""")
            connection.execute("""INSERT INTO question_change_requests_v2
                (id,proposer_id,action,target_question_id,payload_json,status,
                 submitted_at,reviewed_at,reviewed_by)
                SELECT id,proposer_id,action,target_question_id,payload_json,status,
                       submitted_at,reviewed_at,reviewed_by FROM question_change_requests""")
            connection.execute("DROP TABLE question_change_requests")
            connection.execute("ALTER TABLE question_change_requests_v2 RENAME TO question_change_requests")
        change_columns = {row["name"] for row in connection.execute("PRAGMA table_info(question_change_requests)")}
        if "rejection_reason" not in change_columns:
            connection.execute("ALTER TABLE question_change_requests ADD COLUMN rejection_reason TEXT NOT NULL DEFAULT ''")
        # Existing accounts predate examiner applications and remain approved.
        user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "email_verified" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1"
            )
        user_columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        user_acceptance_columns = {
            "terms_accepted_at": "INTEGER",
            "terms_version": "TEXT",
            "privacy_acknowledged_at": "INTEGER",
            "privacy_version": "TEXT",
        }
        for name, definition in user_acceptance_columns.items():
            if name not in user_columns:
                connection.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
        if "professional_title" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN professional_title TEXT NOT NULL DEFAULT ''")
            if "license_number" in user_columns:
                connection.execute("UPDATE users SET professional_title=discipline, discipline='' "
                                   "WHERE role='EXAMINER' AND license_number<>''")
        if "license_number" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN license_number TEXT NOT NULL DEFAULT ''")
        if "examiner_status" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN examiner_status TEXT NOT NULL DEFAULT 'approved'")
        if "examiner_reviewed_at" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN examiner_reviewed_at TEXT")
        if "examiner_reviewed_by" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN examiner_reviewed_by INTEGER")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS unique_examiner_license "
                           "ON users(license_number COLLATE NOCASE) WHERE license_number <> ''")
        # Existing local databases predate printable TOS reports.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(exam_history)")}
        if "report_json" not in columns:
            connection.execute("ALTER TABLE exam_history ADD COLUMN report_json TEXT")
        attempt_columns = {row["name"] for row in connection.execute("PRAGMA table_info(licensure_attempts)")}
        if "planned_json" not in attempt_columns:
            connection.execute("ALTER TABLE licensure_attempts ADD COLUMN planned_json TEXT")
        attempt_additions = {
            "mode": "TEXT NOT NULL DEFAULT 'licensure'",
            "title": "TEXT NOT NULL DEFAULT 'Mock Licensure Exam'",
            "selected_domains_json": "TEXT",
            "time_seconds": "INTEGER NOT NULL DEFAULT 3600",
            "expires_at": "INTEGER",
            "answers_json": "TEXT NOT NULL DEFAULT '{}'",
            "result_id": "INTEGER REFERENCES exam_history(id)",
            "abandoned_at": "INTEGER",
        }
        for name, definition in attempt_additions.items():
            if name not in attempt_columns:
                connection.execute(f"ALTER TABLE licensure_attempts ADD COLUMN {name} {definition}")
        connection.execute("UPDATE licensure_attempts SET expires_at=started_at+time_seconds "
                           "WHERE expires_at IS NULL")
        # The bank is deliberately small until the group supplies its real questions.
        if not connection.execute("SELECT 1 FROM questions LIMIT 1").fetchone():
            import json
            examples = [
                ("CPE-NET-001", "Which OSI layer is primarily responsible for routing packets between networks?",
                 ["A. Physical", "B. Data Link", "C. Network", "D. Application"], 2,
                 "Networking Fundamentals", "Remember", "Easy",
                 "The Network layer handles logical addressing and routing."),
                ("CPE-OPS-001", "What can occur when two threads update shared data without synchronization?",
                 ["A. Race condition", "B. Cache miss", "C. Dead code", "D. Packet loss"], 0,
                 "Process and Thread Management", "Understand", "Easy",
                 "The result can depend on timing, creating a race condition."),
                ("CPE-ARCH-001", "A cache hit takes 2 ns, a miss takes 42 ns, and the hit rate is 90%. What is the average access time?",
                 ["A. 2 ns", "B. 6 ns", "C. 10 ns", "D. 42 ns"], 1,
                 "Memory Hierarchy and Cache", "Apply", "Medium",
                 "0.9(2) + 0.1(42) = 6 ns."),
                ("CPE-SW-001", "Which test checks how several integrated modules work together?",
                 ["A. Unit test", "B. Integration test", "C. Syntax check", "D. Static lint"], 1,
                 "Software Testing and Maintenance", "Understand", "Easy",
                 "Integration testing checks interactions among combined modules."),
                ("CPE-ALG-001", "What is the worst-case complexity of binary search on a sorted array?",
                 ["A. O(1)", "B. O(log n)", "C. O(n)", "D. O(n²)"], 1,
                 "Sorting and Searching Algorithms", "Analyze", "Medium",
                 "Each comparison halves the remaining interval."),
                ("CPE-DIG-001", "Which circuit stores one bit of state?",
                 ["A. Multiplexer", "B. Decoder", "C. Flip-flop", "D. Adder"], 2,
                 "Sequential Logic Circuits", "Remember", "Easy",
                 "A flip-flop is a basic one-bit storage element."),
            ]
            connection.executemany(
                "INSERT INTO questions(id,q,opts_json,ans,domain,cognitive,difficulty,explanation) VALUES(?,?,?,?,?,?,?,?)",
                [(item[0], item[1], json.dumps(item[2]), *item[3:]) for item in examples],
            )


def database_mode() -> str:
    if USING_OFFLINE_FALLBACK:
        return "local-offline-fallback"
    return "supabase" if DATABASE_URL else "local"


def validate_username(value: str) -> str:
    value = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{8,30}", value):
        raise HTTPException(422, "Username must be 8–30 letters, numbers, or underscores.")
    return value


def validate_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
        value,
    ):
        raise HTTPException(422, "Enter a valid email address.")
    return value


def validate_password(value: str) -> None:
    if not (8 <= len(value) <= 30 and re.search(r"[A-Za-z]", value)
            and re.search(r"[A-Z]", value) and re.search(r"[0-9]", value)
            and any(char in SPECIAL for char in value)):
        raise HTTPException(
            422, "Password must be 8–30 characters and include a letter, uppercase letter, number, and special character."
        )


def hash_password(value: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(value.encode(), salt=salt, n=16384, r=8, p=1)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def check_password(value: str, stored: str) -> bool:
    try:
        method, n, r, p, salt_hex, digest_hex = stored.split("$")
        if method != "scrypt":
            return False
        candidate = hashlib.scrypt(
            value.encode(), salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p),
        )
        return hmac.compare_digest(candidate, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "username": row["username"], "email": row["email"],
        "name": row["name"], "role": row["role"], "discipline": row["discipline"],
        "professionalTitle": row["professional_title"],
        "licenseNumber": row["license_number"],
        "emailVerified": bool(row["email_verified"]),
    }


def current_session(request: Request) -> tuple[dict, str] | None:
    token = request.cookies.get("cpedle_session")
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with db() as connection:
        row = connection.execute("""
            SELECT u.*, s.csrf_token FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_locked = 0
              AND u.email_verified = 1
              AND (u.role != 'EXAMINER' OR u.examiner_status = 'approved')
        """, (token_hash, int(time.time()))).fetchone()
    return (public_user(row), row["csrf_token"]) if row else None


def require_user(request: Request) -> dict:
    session = current_session(request)
    if not session:
        raise HTTPException(401, "Sign in is required.")
    if request.method not in {"GET", "HEAD"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(csrf, session[1]):
            raise HTTPException(403, "Invalid request token. Refresh the page and try again.")
    return session[0]


def role_required(*roles: str):
    def dependency(user: dict = Depends(require_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, "Your account does not have access to this action.")
        return user
    return dependency


def set_session(response: Response, user_id: int, secure: bool) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    with db() as connection:
        connection.execute(
            "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES(?,?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf, int(time.time()) + SESSION_SECONDS),
        )
    response.set_cookie(
        "cpedle_session", token, httponly=True, samesite="lax",
        secure=secure, max_age=SESSION_SECONDS, path="/",
    )
    return token, csrf


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Cross-origin request rejected.")


def _create_verification_token(connection, user_id: int, now: int) -> str:
    token = secrets.token_urlsafe(32)
    connection.execute(
        """INSERT INTO email_verification_tokens(user_id,token_hash,expires_at,sent_at)
           VALUES(?,?,?,?)
           ON CONFLICT(user_id) DO UPDATE SET
               token_hash=excluded.token_hash,
               expires_at=excluded.expires_at,
               sent_at=excluded.sent_at""",
        (user_id, hashlib.sha256(token.encode()).hexdigest(), now + 24 * 60 * 60, now),
    )
    return token


def _clear_verification_send_cooldown(user_id: int) -> None:
    with db() as connection:
        connection.execute(
            "UPDATE email_verification_tokens SET sent_at=0 WHERE user_id=?",
            (user_id,),
        )


def _log_brevo_error(error: HTTPError) -> None:
    try:
        details = json.loads(error.read(4096).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        details = {}
    code = details.get("code", "unknown") if isinstance(details, dict) else "unknown"
    message = details.get("message", "No provider message") if isinstance(details, dict) else "No provider message"
    logging.error(
        "Brevo rejected verification email: HTTP %s, code=%s, message=%s",
        error.code, str(code)[:100], str(message)[:500],
    )


def send_verification_email(email: str, token: str) -> None:
    api_key = os.environ.get("BREVO_API_KEY", "").strip()
    sender = os.environ.get("BREVO_FROM_EMAIL", "").strip()
    if not api_key or not sender:
        raise HTTPException(
            503,
            "Email verification is not configured. Set BREVO_API_KEY and BREVO_FROM_EMAIL, then try again.",
        )
    sender_name, sender_email = parseaddr(sender)
    if not sender_email or "@" not in sender_email:
        raise HTTPException(503, "BREVO_FROM_EMAIL must be a valid verified sender address.")
    app_url = os.environ.get("PUBLIC_APP_URL", "http://127.0.0.1:5000").rstrip("/")
    verify_url = f"{app_url}/verify-email.html#token={token}"
    escaped_url = html.escape(verify_url, quote=True)
    escaped_email = html.escape(email)
    sender_details = {"email": sender_email}
    if sender_name:
        sender_details["name"] = sender_name
    payload = json.dumps({
        "sender": sender_details,
        "to": [{"email": email}],
        "subject": "Verify your cpedle email address",
        "textContent": (
            "Verify your email address to finish creating your cpedle account.\n\n"
            f"Open this link to verify: {verify_url}\n\n"
            "This link expires in 24 hours. If you did not create an account, "
            "you can ignore this message."
        ),
        "htmlContent": (
            "<p>Verify your email address to finish creating your cpedle account.</p>"
            f'<p><a href="{escaped_url}">Verify email address</a></p>'
            "<p>This link expires in 24 hours. If you did not create an account, "
            "you can ignore this message.</p>"
            f"<p>Sent to {escaped_email}.</p>"
        ),
    }).encode()
    request = UrlRequest(
        "https://api.brevo.com/v3/smtp/email",
        data=payload,
        headers={
            "api-key": api_key,
            "accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            if response.status not in {200, 201, 202}:
                logging.error("Brevo rejected verification email with HTTP %s", response.status)
                raise HTTPException(502, "The verification email could not be sent. Please try again.")
    except HTTPError as error:
        _log_brevo_error(error)
        raise HTTPException(502, "The verification email could not be sent. Please try again.") from None
    except (URLError, TimeoutError) as error:
        logging.error("Could not reach Brevo to send verification email: %s", error)
        raise HTTPException(502, "The verification email could not be sent. Please try again.") from None


class RegisterIn(BaseModel):
    username: str
    email: str
    password: str
    confirm_password: str
    accept_terms: bool = False
    acknowledge_privacy: bool = False


class ExaminerRegisterIn(RegisterIn):
    name: str = Field(min_length=2, max_length=100)
    title: str = Field(min_length=2, max_length=100)
    license_number: str = Field(min_length=3, max_length=50)


class LoginIn(BaseModel):
    identifier: str
    password: str


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class EmailVerificationResendIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    identifier: str
    password: str
    confirm_password: str


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    discipline: str = ""


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class DecisionIn(BaseModel):
    approve: bool


class QuestionDecisionIn(DecisionIn):
    reason: str = Field(default="", max_length=500)


class QuestionIn(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,40}$")
    q: str = Field(min_length=3, max_length=2000)
    opts: list[str]
    ans: int | None = None
    answerText: str = ""
    questionType: str = "multiple_choice"
    domain: str
    cognitive: str
    difficulty: str
    explanation: str = ""


class AnswerIn(BaseModel):
    id: str
    userAns: int | str | None = None


class ExamSubmission(BaseModel):
    title: str = Field(max_length=160)
    answers: list[AnswerIn]
    mode: str | None = None
    scope: str | None = None
    difficulty_weights: list[int] | None = None
    selected_domains: list[str] | None = None
    attempt_id: str | None = None


class PracticeAttemptIn(BaseModel):
    question_ids: list[str]
    selected_domains: list[str]
    time_minutes: int = Field(ge=5, le=300)


class AttemptAnswersIn(BaseModel):
    answers: list[AnswerIn]


router = APIRouter(prefix="/api")


@router.get("/bootstrap")
def bootstrap(request: Request) -> dict:
    import json
    session = current_session(request)
    user = session[0] if session else None
    with db() as connection:
        questions = [
            {**dict(row), "opts": json.loads(row["opts_json"])}
            for row in connection.execute("SELECT * FROM questions ORDER BY id")
        ]
        for q in questions:
            q.pop("opts_json", None)
            q["questionType"] = "multiple_choice"
            q["source"] = "local"
            if not user or user["role"] not in {"ADMIN", "EXAMINER"}:
                q.pop("ans", None)
                q.pop("explanation", None)
        questions.extend(imported_questions(bool(user and user["role"] in {"ADMIN", "EXAMINER"})))
        if user and user["role"] == "STUDENT":
            allowed_domains = DISCIPLINES.get(user["discipline"], [])
            questions = [question for question in questions if question["domain"] in allowed_domains]
        history = []
        if user and user["role"] in {"STUDENT", "ADMIN"}:
            params = () if user["role"] == "ADMIN" else (user["id"],)
            where_h = "" if user["role"] == "ADMIN" else "WHERE user_id = ?"
            history = [
                {**dict(row), "domains": json.loads(row["domains_json"])}
                for row in connection.execute(
                    f"""SELECT id,title,created_at AS date,score_pct AS "scorePct",
                               total_items AS "totalItems",correct_items AS "correctItems",
                               domains_json,report_json FROM exam_history {where_h} ORDER BY id DESC""",
                    params,
                )
            ]
            for item in history:
                item.pop("domains_json", None)
                report_json = item.pop("report_json")
                snapshot = json.loads(report_json) if report_json else None
                item["mode"] = snapshot.get("mode", "legacy") if snapshot else "legacy"
    return {
        "user": user, "csrf": session[1] if session else None,
        "questions": questions, "history": history,
    }


@router.post("/auth/register")
def register(payload: RegisterIn, request: Request, response: Response) -> dict:
    require_same_origin(request)
    if not payload.accept_terms or not payload.acknowledge_privacy:
        raise HTTPException(422, "Accept the Terms and acknowledge the Privacy Notice before registering.")
    if payload.password != payload.confirm_password:
        raise HTTPException(422, "Passwords do not match.")
    username = validate_username(payload.username)
    email = validate_email(payload.email)
    validate_password(payload.password)
    accepted_at = int(time.time())
    try:
        with db() as connection:
            existing = connection.execute(
                "SELECT username,email FROM users "
                "WHERE lower(username)=lower(?) OR lower(email)=lower(?)",
                (username, email),
            ).fetchone()
            if existing:
                field = "Username" if existing["username"].casefold() == username.casefold() else "Email"
                raise HTTPException(409, f"{field} is already registered.")
            cursor = connection.execute(
                "INSERT INTO users(username,email,password_hash,role,email_verified,"
                "terms_accepted_at,terms_version,privacy_acknowledged_at,privacy_version) "
                "VALUES(?,?,?,'STUDENT',0,?,?,?,?) RETURNING id",
                (username, email, hash_password(payload.password), accepted_at,
                 TERMS_VERSION, accepted_at, PRIVACY_VERSION),
            )
            user_id = cursor.fetchone()["id"]
            token = _create_verification_token(connection, user_id, int(time.time()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username or email is already registered.") from None
    try:
        send_verification_email(email, token)
    except HTTPException as error:
        _clear_verification_send_cooldown(user_id)
        raise HTTPException(
            error.status_code,
            "Your account was created, but the verification email could not be sent. "
            "Use the 'Resend it' link on the sign-up or login page to retry. "
            f"{error.detail}",
        ) from error
    return {"message": "Account created. Check your email for a verification link."}


@router.post("/auth/register-examiner")
def register_examiner(payload: ExaminerRegisterIn, request: Request) -> dict:
    """Create a pending examiner application without issuing a login session."""
    require_same_origin(request)
    if not payload.accept_terms or not payload.acknowledge_privacy:
        raise HTTPException(422, "Accept the Terms and acknowledge the Privacy Notice before registering.")
    if payload.password != payload.confirm_password:
        raise HTTPException(422, "Passwords do not match.")
    username = validate_username(payload.username)
    email = validate_email(payload.email)
    validate_password(payload.password)
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(422, "Enter your full name.")
    title = payload.title.strip()
    if len(title) < 2 or len(title) > 100 or any(ord(char) < 32 for char in title):
        raise HTTPException(422, "Enter a valid professional title (2–100 characters).")
    license_number = payload.license_number.strip()
    if len(license_number) < 3 or len(license_number) > 50 or any(ord(char) < 32 for char in license_number):
        raise HTTPException(422, "Enter a valid license number (3–50 characters).")
    now = int(time.time())
    accepted_at = now
    try:
        with db() as connection:
            if connection.execute("SELECT 1 FROM users WHERE lower(username)=lower(?)",
                                  (username,)).fetchone():
                raise HTTPException(409, "Username is already registered.")
            if connection.execute("SELECT 1 FROM users WHERE lower(email)=lower(?)",
                                  (email,)).fetchone():
                raise HTTPException(409, "Email is already registered.")
            if connection.execute("SELECT 1 FROM users WHERE lower(license_number)=lower(?)",
                                  (license_number,)).fetchone():
                raise HTTPException(409, "License number is already registered.")
            cursor = connection.execute(
                "INSERT INTO users(username,email,password_hash,role,name,professional_title,license_number,"
                "examiner_status,email_verified,terms_accepted_at,terms_version,"
                "privacy_acknowledged_at,privacy_version) "
                "VALUES(?,?,?,'EXAMINER',?,?,?,'pending',0,?,?,?,?) RETURNING id",
                (username, email, hash_password(payload.password), name, title, license_number,
                 accepted_at, TERMS_VERSION, accepted_at, PRIVACY_VERSION),
            )
            user_id = cursor.fetchone()["id"]
            token = _create_verification_token(connection, user_id, now)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username, email, or license number is already registered.") from None
    try:
        send_verification_email(email, token)
    except HTTPException as error:
        _clear_verification_send_cooldown(user_id)
        raise HTTPException(
            error.status_code,
            "Your examiner application was created, but the verification email could not be sent. "
            "Use the 'Resend it' link on the sign-up or login page to retry. "
            f"{error.detail}",
        ) from error
    return {"message": "Application submitted. Verify your email; administrator review follows."}


@router.post("/auth/verify-email")
def verify_email(payload: VerifyEmailIn, request: Request) -> dict:
    require_same_origin(request)
    now = int(time.time())
    token_hash = hashlib.sha256(payload.token.encode()).hexdigest()
    with db() as connection:
        token_row = connection.execute(
            "SELECT user_id,expires_at FROM email_verification_tokens WHERE token_hash=?",
            (token_hash,),
        ).fetchone()
        if not token_row or token_row["expires_at"] <= now:
            raise HTTPException(400, "This verification link is invalid or expired. Request a new one.")
        connection.execute("UPDATE users SET email_verified=1 WHERE id=?", (token_row["user_id"],))
        connection.execute("DELETE FROM email_verification_tokens WHERE user_id=?", (token_row["user_id"],))
    return {"message": "Email verified. You can now sign in."}


@router.post("/auth/resend-verification")
def resend_verification(payload: EmailVerificationResendIn, request: Request) -> dict:
    require_same_origin(request)
    email = validate_email(payload.email)
    now = int(time.time())
    message = (
        "If an unverified account exists for that address, a verification email may be sent. "
        "If you do not receive one, try again in a minute."
    )
    with db() as connection:
        user = connection.execute(
            "SELECT id,email,email_verified FROM users WHERE lower(email)=lower(?)"
            + (" FOR UPDATE" if DATABASE_URL else ""),
            (email,),
        ).fetchone()
        if not user or user["email_verified"]:
            return {"message": message}
        previous = connection.execute(
            "SELECT sent_at FROM email_verification_tokens WHERE user_id=?",
            (user["id"],),
        ).fetchone()
        if previous and previous["sent_at"] > now - 60:
            return {"message": message}
        token = _create_verification_token(connection, user["id"], now)
        recipient = user["email"]
    try:
        send_verification_email(recipient, token)
    except HTTPException:
        _clear_verification_send_cooldown(user["id"])
        raise
    return {"message": message}


@router.post("/auth/login")
def login(payload: LoginIn, request: Request, response: Response) -> dict:
    require_same_origin(request)
    identifier = payload.identifier.strip()
    if not identifier or not payload.password:
        raise HTTPException(422, "Enter your username/email and password.")
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM users WHERE lower(username)=lower(?) OR lower(email)=lower(?)"
            + (" FOR UPDATE" if DATABASE_URL else ""),
            (identifier, identifier),
        ).fetchone()
        if not row:
            raise HTTPException(401, "Invalid username/email or password.")
        if row["is_locked"]:
            raise HTTPException(423, "Account locked. Submit a password-reset request for administrator review.")
        if not check_password(payload.password, row["password_hash"]):
            attempts = row["invalid_attempts"] + 1
            connection.execute(
                "UPDATE users SET invalid_attempts=?,is_locked=? WHERE id=?",
                (attempts, int(attempts >= MAX_ATTEMPTS), row["id"]),
            )
            if attempts >= MAX_ATTEMPTS:
                connection.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
            # Explicit commit before raising so the failed attempt is durable.
            connection.commit()
            if attempts >= MAX_ATTEMPTS:
                raise HTTPException(423, "Account locked after 3 invalid attempts.")
            raise HTTPException(401, f"Invalid username/email or password. {MAX_ATTEMPTS-attempts} attempt(s) remaining.")
        connection.execute("UPDATE users SET invalid_attempts=0 WHERE id=?", (row["id"],))
    if not row["email_verified"]:
        raise HTTPException(
            403,
            "Verify your email before signing in. Use the verification page to request another link.",
        )
    if row["role"] == "EXAMINER" and row["examiner_status"] != "approved":
        message = ("Your examiner registration is awaiting administrator approval." if
                   row["examiner_status"] == "pending" else
                   "Your examiner registration was not approved. Contact an administrator.")
        raise HTTPException(403, message)
    _, csrf = set_session(response, row["id"], request.url.scheme == "https")
    return {"user": public_user(row), "csrf": csrf}


@router.post("/auth/logout")
def logout(request: Request, response: Response, user: dict = Depends(require_user)) -> dict:
    token = request.cookies.get("cpedle_session", "")
    with db() as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash=?",
                           (hashlib.sha256(token.encode()).hexdigest(),))
    response.delete_cookie("cpedle_session", path="/")
    return {"ok": True}


@router.post("/auth/reset-request")
def request_reset(payload: ResetIn, request: Request) -> dict:
    require_same_origin(request)
    if payload.password != payload.confirm_password:
        raise HTTPException(422, "Passwords do not match.")
    validate_password(payload.password)
    with db() as connection:
        user = connection.execute(
            "SELECT id FROM users WHERE lower(username)=lower(?) OR lower(email)=lower(?)",
            (payload.identifier.strip(), payload.identifier.strip()),
        ).fetchone()
        if user:
            connection.execute(
                "UPDATE password_reset_requests SET status='rejected',reviewed_at=CURRENT_TIMESTAMP WHERE user_id=? AND status='pending'",
                (user["id"],),
            )
            connection.execute(
                "INSERT INTO password_reset_requests(user_id,new_password_hash) VALUES(?,?)",
                (user["id"], hash_password(payload.password)),
            )
    # Avoid exposing whether an account exists.
    return {"message": "If the account exists, the request is pending administrator review."}


@router.put("/profile")
def save_profile(payload: ProfileIn, user: dict = Depends(require_user)) -> dict:
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(422, "Enter your name.")
    discipline = user["discipline"]
    if user["role"] == "STUDENT":
        if discipline:
            if payload.discipline and payload.discipline != discipline:
                raise HTTPException(409, "Your registered discipline cannot be changed.")
        elif payload.discipline in DISCIPLINES:
            discipline = payload.discipline
        else:
            raise HTTPException(422, "Select a listed Computer Engineering discipline.")
    with db() as connection:
        connection.execute(
            "UPDATE users SET name=?, discipline=? WHERE id=?",
            (name, discipline, user["id"]),
        )
    return {"user": {**user, "name": name, "discipline": discipline}}


@router.put("/profile/password")
def change_own_password(payload: PasswordChangeIn, request: Request,
                        user: dict = Depends(require_user)) -> dict:
    if payload.new_password != payload.confirm_password:
        raise HTTPException(422, "New passwords do not match.")
    validate_password(payload.new_password)
    with db() as connection:
        row = connection.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
        if row is None or not check_password(payload.current_password, row["password_hash"]):
            raise HTTPException(403, "Current password is incorrect.")
        if check_password(payload.new_password, row["password_hash"]):
            raise HTTPException(422, "Choose a different password.")
        connection.execute("UPDATE users SET password_hash=? WHERE id=?",
                           (hash_password(payload.new_password), user["id"]))
        current_token = request.cookies.get("cpedle_session", "")
        current_hash = hashlib.sha256(current_token.encode()).hexdigest()
        connection.execute("DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
                           (user["id"], current_hash))
    return {"ok": True}


@router.get("/admin/users")
def admin_users(admin: dict = Depends(role_required("ADMIN"))) -> list[dict]:
    with db() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT id,username,email,name,discipline,role,professional_title,license_number,"
            "examiner_status,invalid_attempts,is_locked "
            "FROM users ORDER BY id"
        )]


@router.get("/admin/examiner-applications")
def examiner_applications(admin: dict = Depends(role_required("ADMIN"))) -> list[dict]:
    with db() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT id,username,email,name,professional_title AS title,license_number,created_at "
            "FROM users WHERE role='EXAMINER' AND examiner_status='pending' ORDER BY id DESC"
        )]


@router.post("/admin/examiner-applications/{user_id}/decision")
def decide_examiner_application(user_id: int, payload: DecisionIn,
                                admin: dict = Depends(role_required("ADMIN"))) -> dict:
    with db() as connection:
        cursor = connection.execute(
            "UPDATE users SET examiner_status=?,examiner_reviewed_at=CURRENT_TIMESTAMP,examiner_reviewed_by=? "
            "WHERE id=? AND role='EXAMINER' AND examiner_status='pending'",
            ("approved" if payload.approve else "rejected", admin["id"], user_id),
        )
        if not cursor.rowcount:
            raise HTTPException(404, "Pending examiner registration not found.")
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return {"ok": True}


@router.post("/admin/users/{user_id}/lock")
def lock_user(user_id: int, admin: dict = Depends(role_required("ADMIN"))) -> dict:
    with db() as connection:
        cursor = connection.execute(
            "UPDATE users SET is_locked=1 WHERE id=? AND role IN ('STUDENT','EXAMINER') AND is_locked=0",
            (user_id,),
        )
        if not cursor.rowcount:
            raise HTTPException(404, "Active student or examiner account not found.")
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return {"ok": True}


@router.post("/admin/users/{user_id}/unlock")
def unlock(user_id: int, admin: dict = Depends(role_required("ADMIN"))) -> dict:
    with db() as connection:
        cursor = connection.execute(
            "UPDATE users SET is_locked=0,invalid_attempts=0 WHERE id=? AND role IN ('STUDENT','EXAMINER') AND is_locked=1",
            (user_id,),
        )
    if not cursor.rowcount:
        raise HTTPException(404, "Locked account not found.")
    return {"ok": True}


@router.get("/admin/reset-requests")
def pending_resets(admin: dict = Depends(role_required("ADMIN"))) -> list[dict]:
    with db() as connection:
        return [dict(row) for row in connection.execute("""
            SELECT r.id,u.username,u.email,r.requested_at,u.is_locked
            FROM password_reset_requests r JOIN users u ON u.id=r.user_id
            WHERE r.status='pending' ORDER BY r.id DESC
        """)]


@router.post("/admin/reset-requests/{request_id}/decision")
def decide_reset(request_id: int, payload: DecisionIn, admin: dict = Depends(role_required("ADMIN"))) -> dict:
    with db() as connection:
        row = connection.execute(
            "SELECT * FROM password_reset_requests WHERE id=? AND status='pending'",
            (request_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Pending request not found.")
        if payload.approve:
            connection.execute(
                "UPDATE users SET password_hash=?,is_locked=0,invalid_attempts=0 WHERE id=?",
                (row["new_password_hash"], row["user_id"]),
            )
            connection.execute("DELETE FROM sessions WHERE user_id=?", (row["user_id"],))
        connection.execute(
            "UPDATE password_reset_requests SET status=?,reviewed_at=CURRENT_TIMESTAMP,reviewed_by=? WHERE id=?",
            ("approved" if payload.approve else "rejected", admin["id"], request_id),
        )
    return {"ok": True}


def validate_question(payload: QuestionIn) -> None:
    if payload.id and payload.id.startswith("QB-"):
        raise HTTPException(422, "QB- IDs are reserved for the imported question bank.")
    if (len(payload.opts) != 4 or any(not option.strip() or len(option) > 500 for option in payload.opts)
            or payload.ans not in range(4) or payload.domain not in DOMAINS
            or payload.cognitive not in COGNITIVE or payload.difficulty not in DIFFICULTIES):
        raise HTTPException(422, "Invalid question options, answer, domain, cognitive level, or difficulty.")


def validate_imported_edit(question_id: str, payload: QuestionIn) -> None:
    original = next((item for item in imported_questions(True) if item["id"] == question_id), None)
    if original is None:
        raise HTTPException(404, "Imported question not found.")
    kind = original["questionType"]
    if (payload.id != question_id or payload.questionType != kind or
            payload.domain not in DOMAINS or payload.cognitive not in COGNITIVE or
            payload.difficulty not in DIFFICULTIES or not payload.q.strip()):
        raise HTTPException(422, "Invalid imported question details or question type.")
    if kind in {"multiple_choice", "both"} and (
            len(payload.opts) != len(original["opts"]) or
            any(not option.strip() or len(option) > 500 for option in payload.opts) or
            payload.ans not in range(len(payload.opts))):
        raise HTTPException(422, "Keep the imported item's choices and select a valid answer.")
    if kind in {"identification", "both"} and not payload.answerText.strip():
        raise HTTPException(422, "An accepted identification answer is required.")


def save_imported_override(connection: sqlite3.Connection, question_id: str,
                           payload: QuestionIn | None = None, deleted: bool = False) -> None:
    if deleted:
        existing = connection.execute(
            "SELECT payload_json FROM imported_question_overrides WHERE question_id=?", (question_id,)
        ).fetchone()
        saved_payload = existing["payload_json"] if existing else "{}"
    else:
        saved_payload = payload.model_dump_json()
    connection.execute(
        "INSERT INTO imported_question_overrides(question_id,payload_json,is_deleted) VALUES(?,?,?) "
        "ON CONFLICT(question_id) DO UPDATE SET payload_json=excluded.payload_json,is_deleted=excluded.is_deleted",
        (question_id, saved_payload, int(deleted)),
    )


def queue_question_change(connection: sqlite3.Connection, payload: QuestionIn,
                          action: str, target_id: str | None, user_id: int) -> dict:
    """Keep examiner changes separate from the live bank until admin review."""
    if action == "ADD":
        payload = payload.model_copy(update={"id": payload.id or "CPE-" + secrets.token_hex(5).upper()})
        if connection.execute("SELECT 1 FROM questions WHERE id=?", (payload.id,)).fetchone():
            raise HTTPException(409, "Question ID already exists.")
    elif not target_id.startswith("QB-") and not connection.execute("SELECT 1 FROM questions WHERE id=?", (target_id,)).fetchone():
        raise HTTPException(404, "Question not found.")
    cursor = connection.execute(
        "INSERT INTO question_change_requests(proposer_id,action,target_question_id,payload_json) "
        "VALUES(?,?,?,?) RETURNING id",
        (user_id, action, target_id, payload.model_dump_json()),
    )
    return {"id": payload.id or target_id, "pending": True, "request_id": cursor.fetchone()["id"]}


@router.get("/questions/change-requests")
def question_change_requests(user: dict = Depends(role_required("EXAMINER", "ADMIN"))) -> list[dict]:
    import json
    with db() as connection:
        where = "WHERE c.status='pending'" if user["role"] == "ADMIN" else "WHERE c.proposer_id=?"
        params = () if user["role"] == "ADMIN" else (user["id"],)
        rows = connection.execute(
            f"""SELECT c.id,c.action,c.target_question_id,c.payload_json,c.status,
                       c.submitted_at,c.rejection_reason,u.username AS proposer
                FROM question_change_requests c JOIN users u ON u.id=c.proposer_id
                {where} ORDER BY c.id DESC""", params,
        ).fetchall()
    changes = []
    for row in rows:
        change = dict(row)
        change["question"] = json.loads(change.pop("payload_json"))
        changes.append(change)
    return changes


@router.post("/admin/questions/change-requests/{change_id}/decision")
def decide_question_change(change_id: int, payload: QuestionDecisionIn,
                           admin: dict = Depends(role_required("ADMIN"))) -> dict:
    import json
    reason = payload.reason.strip()
    if not payload.approve and not reason:
        raise HTTPException(422, "A rejection reason is required.")
    try:
        with db() as connection:
            row = connection.execute(
                "SELECT * FROM question_change_requests WHERE id=? AND status='pending'",
                (change_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Pending question change not found.")
            question = QuestionIn.model_validate_json(row["payload_json"])
            imported = bool(row["target_question_id"] and row["target_question_id"].startswith("QB-"))
            if imported:
                if row["action"] == "EDIT":
                    validate_imported_edit(row["target_question_id"], question)
                elif not any(item["id"] == row["target_question_id"] for item in imported_questions(True)):
                    raise HTTPException(409, "Imported question no longer exists. Reject this change.")
            else:
                validate_question(question)
            if payload.approve:
                if imported and row["action"] == "EDIT":
                    save_imported_override(connection, row["target_question_id"], question)
                elif imported and row["action"] == "DELETE":
                    save_imported_override(connection, row["target_question_id"], deleted=True)
                elif row["action"] == "ADD":
                    connection.execute(
                        "INSERT INTO questions(id,q,opts_json,ans,domain,cognitive,difficulty,explanation) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (question.id, question.q.strip(), json.dumps(question.opts), question.ans,
                         question.domain, question.cognitive, question.difficulty, question.explanation),
                    )
                elif row["action"] == "EDIT":
                    cursor = connection.execute(
                        "UPDATE questions SET q=?,opts_json=?,ans=?,domain=?,cognitive=?,difficulty=?,"
                        "explanation=? WHERE id=?",
                        (question.q.strip(), json.dumps(question.opts), question.ans,
                         question.domain, question.cognitive, question.difficulty,
                         question.explanation, row["target_question_id"]),
                    )
                    if not cursor.rowcount:
                        raise HTTPException(409, "Original question no longer exists. Reject this change.")
                elif row["action"] == "DELETE":
                    cursor = connection.execute(
                        "DELETE FROM questions WHERE id=?", (row["target_question_id"],)
                    )
                    if not cursor.rowcount:
                        raise HTTPException(409, "Original question no longer exists. Reject this change.")
            connection.execute(
                "UPDATE question_change_requests SET status=?,reviewed_at=CURRENT_TIMESTAMP,reviewed_by=?,rejection_reason=? "
                "WHERE id=?",
                ("approved" if payload.approve else "rejected", admin["id"],
                 "" if payload.approve else reason, change_id),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Question ID is already in the live bank. Reject this change.") from None
    return {"ok": True}


@router.post("/questions")
def add_question(payload: QuestionIn, user: dict = Depends(role_required("EXAMINER", "ADMIN"))) -> dict:
    import json
    validate_question(payload)
    if user["role"] == "EXAMINER":
        with db() as connection:
            return queue_question_change(connection, payload, "ADD", None, user["id"])
    question_id = payload.id or ("CPE-" + secrets.token_hex(5).upper())
    try:
        with db() as connection:
            connection.execute(
                "INSERT INTO questions(id,q,opts_json,ans,domain,cognitive,difficulty,explanation) VALUES(?,?,?,?,?,?,?,?)",
                (question_id, payload.q.strip(), json.dumps(payload.opts), payload.ans,
                 payload.domain, payload.cognitive, payload.difficulty, payload.explanation),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Question ID already exists.") from None
    return {"id": question_id}


@router.put("/questions/{question_id}")
def edit_question(question_id: str, payload: QuestionIn, user: dict = Depends(role_required("EXAMINER", "ADMIN"))) -> dict:
    import json
    if question_id.startswith("QB-"):
        validate_imported_edit(question_id, payload)
        if user["role"] == "EXAMINER":
            with db() as connection:
                return queue_question_change(connection, payload, "EDIT", question_id, user["id"])
        with db() as connection:
            save_imported_override(connection, question_id, payload)
        return {"id": question_id}
    validate_question(payload)
    if user["role"] == "EXAMINER":
        with db() as connection:
            return queue_question_change(connection, payload, "EDIT", question_id, user["id"])
    with db() as connection:
        cursor = connection.execute(
            "UPDATE questions SET q=?,opts_json=?,ans=?,domain=?,cognitive=?,difficulty=?,explanation=? WHERE id=?",
            (payload.q.strip(), json.dumps(payload.opts), payload.ans, payload.domain,
             payload.cognitive, payload.difficulty, payload.explanation, question_id),
        )
    if not cursor.rowcount:
        raise HTTPException(404, "Question not found.")
    return {"id": question_id}


@router.delete("/questions/{question_id}")
def delete_question(question_id: str, user: dict = Depends(role_required("EXAMINER", "ADMIN"))) -> dict:
    if question_id.startswith("QB-"):
        original = next((item for item in imported_questions(True) if item["id"] == question_id), None)
        if original is None:
            raise HTTPException(404, "Imported question not found.")
        if user["role"] == "EXAMINER":
            question = QuestionIn(**{key: original[key] for key in
                ("id", "q", "opts", "ans", "answerText", "domain", "cognitive",
                 "difficulty", "explanation", "questionType")})
            with db() as connection:
                return queue_question_change(connection, question, "DELETE", question_id, user["id"])
        with db() as connection:
            save_imported_override(connection, question_id, deleted=True)
        return {"ok": True}
    with db() as connection:
        if user["role"] == "EXAMINER":
            row = connection.execute("SELECT * FROM questions WHERE id=?", (question_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "Question not found.")
            import json
            question = QuestionIn(
                id=row["id"], q=row["q"], opts=json.loads(row["opts_json"]),
                ans=row["ans"], domain=row["domain"], cognitive=row["cognitive"],
                difficulty=row["difficulty"], explanation=row["explanation"],
            )
            return queue_question_change(connection, question, "DELETE", question_id, user["id"])
        cursor = connection.execute("DELETE FROM questions WHERE id=?", (question_id,))
    if not cursor.rowcount:
        raise HTTPException(404, "Question not found.")
    return {"ok": True}


@router.post("/questions/import")
def import_questions(items: list[QuestionIn], user: dict = Depends(role_required("EXAMINER", "ADMIN"))) -> dict:
    import json
    if len(items) > 500:
        raise HTTPException(422, "Import at most 500 questions at a time.")
    for item in items:
        validate_question(item)
    with db() as connection:
        for item in items:
            if user["role"] == "EXAMINER":
                queue_question_change(connection, item, "ADD", None, user["id"])
                continue
            connection.execute(
                "INSERT INTO questions(id,q,opts_json,ans,domain,cognitive,difficulty,explanation) VALUES(?,?,?,?,?,?,?,?)",
                (item.id or "CPE-" + secrets.token_hex(5).upper(), item.q.strip(),
                 json.dumps(item.opts), item.ans, item.domain, item.cognitive,
                 item.difficulty, item.explanation),
            )
    return {"added": len(items) if user["role"] == "ADMIN" else 0,
            "pending": len(items) if user["role"] == "EXAMINER" else 0}


def score_exam_payload(connection: sqlite3.Connection, payload: ExamSubmission) -> dict:
    if not payload.answers or len(payload.answers) > 500:
        raise HTTPException(422, "Submit 1–500 answers.")
    ids = [item.id for item in payload.answers]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "Duplicate question IDs are not allowed.")
    local_ids = [item for item in ids if not item.startswith("QB-")]
    imported_ids = [item for item in ids if item.startswith("QB-")]
    lookup = {}
    if local_ids:
        rows = connection.execute(
            f"SELECT id,q,opts_json,ans,domain,cognitive,difficulty,explanation "
            f"FROM questions WHERE id IN ({','.join('?' for _ in local_ids)})",
            local_ids,
        ).fetchall()
        lookup.update({
            row["id"]: {
                **dict(row), "type": "local", "options": json.loads(row["opts_json"]),
            }
            for row in rows
        })
    if imported_ids:
        numbers = [item[3:] for item in imported_ids]
        if any(not number.isdigit() for number in numbers):
            raise HTTPException(422, "Invalid question ID.")
        bank_question_table = "bank_questions" if DATABASE_URL else "questions"
        bank_domain_table = "bank_domains" if DATABASE_URL else "domains"
        bank_answer_table = "bank_accepted_answers" if DATABASE_URL else "accepted_answers"
        bank_choice_table = "bank_choices" if DATABASE_URL else "choices"
        with question_bank() as bank:
            if bank is not None:
                rows = bank.execute(
                    f"""SELECT q.id,q.question_text,q.question_type,q.answer_letter,q.answer_text,
                               q.image_path,q.cognitive_level AS cognitive,q.difficulty,d.name AS domain
                        FROM {bank_question_table} q
                        JOIN {bank_domain_table} d ON d.id=q.domain_id
                        WHERE q.id IN ({','.join('?' for _ in numbers)})""",
                    numbers,
                ).fetchall()
                for row in rows:
                    number = row["id"]
                    answer_rows = bank.execute(
                        f"SELECT answer_norm FROM {bank_answer_table} WHERE question_id=?",
                        (number,),
                    ).fetchall()
                    choices = bank.execute(
                        f"SELECT letter,choice_text,image_path FROM {bank_choice_table} "
                        "WHERE question_id=? ORDER BY letter",
                        (number,),
                    ).fetchall()
                    letters = [item["letter"] for item in choices]
                    lookup[f"QB-{number}"] = {
                        "domain": row["domain"], "cognitive": row["cognitive"],
                        "difficulty": row["difficulty"], "type": row["question_type"],
                        "q": row["question_text"],
                        "options": [item["choice_text"] or "" for item in choices],
                        "imageUrl": bank_image_url(row["image_path"]),
                        "optionImages": [bank_image_url(item["image_path"]) for item in choices],
                        "explanation": "",
                        "answer_index": letters.index(row["answer_letter"])
                        if row["answer_letter"] in letters else None,
                        "accepted": {normalize_answer(item["answer_norm"]) for item in answer_rows},
                        "canonical_answer": row["answer_text"] or "",
                    }
        overrides = connection.execute(
            f"SELECT question_id,payload_json FROM imported_question_overrides WHERE question_id IN ({','.join('?' for _ in imported_ids)})",
            imported_ids,
        ).fetchall()
        for override in overrides:
            if override["question_id"] not in lookup or override["payload_json"] == "{}":
                continue
            changed = json.loads(override["payload_json"])
            scored = lookup[override["question_id"]]
            scored.update(domain=changed["domain"], cognitive=changed["cognitive"],
                          difficulty=changed["difficulty"])
            scored.update({key: changed[key] for key in ("q", "opts", "explanation")
                           if key in changed})
            if "opts" in changed:
                scored["options"] = changed["opts"]
            if scored["type"] in {"multiple_choice", "both"}:
                scored["answer_index"] = changed["ans"]
            if (scored["type"] in {"identification", "both"} and
                    normalize_answer(changed["answerText"]) != normalize_answer(scored["canonical_answer"])):
                scored["canonical_answer"] = changed["answerText"]
                scored["accepted"] = {normalize_answer(changed["answerText"])}
    if len(lookup) != len(ids):
        raise HTTPException(422, "One or more questions no longer exist.")
    stats: dict[str, dict[str, int]] = {}
    actual = {"domains": {}, "cognitive": {}, "difficulty": {}, "joint": {}}
    correct = 0
    question_review = []
    for answer in payload.answers:
        row = lookup[answer.id]
        if row["type"] == "local":
            if answer.userAns is not None and (not isinstance(answer.userAns, int) or answer.userAns not in range(4)):
                raise HTTPException(422, "Invalid answer index.")
            match = answer.userAns is not None and answer.userAns == row["ans"]
        elif isinstance(answer.userAns, int):
            if answer.userAns not in range(5) or row["type"] == "identification":
                raise HTTPException(422, "Invalid answer index.")
            match = answer.userAns == row["answer_index"]
        elif isinstance(answer.userAns, str):
            if row["type"] == "multiple_choice" or len(answer.userAns) > 500:
                raise HTTPException(422, "Invalid identification answer.")
            match = bool(answer.userAns.strip()) and normalize_answer(answer.userAns) in row["accepted"]
        else:
            match = False
        correct += int(match)
        options = row.get("options", [])
        correct_index = row.get("ans") if row["type"] == "local" else row.get("answer_index")
        correct_answer = (options[correct_index] if isinstance(correct_index, int) and
                          0 <= correct_index < len(options) else row.get("canonical_answer", ""))
        user_answer = (
            options[answer.userAns] if isinstance(answer.userAns, int) and
            0 <= answer.userAns < len(options) else
            answer.userAns.strip() if isinstance(answer.userAns, str) and answer.userAns.strip()
            else "Not answered"
        )
        if isinstance(answer.userAns, str) and row.get("canonical_answer"):
            correct_answer = row["canonical_answer"]
        question_review.append({
            "id": answer.id,
            "question": row.get("q", ""),
            "userAnswer": user_answer,
            "correctAnswer": correct_answer or "Correct answer unavailable",
            "isCorrect": bool(match),
            "explanation": row.get("explanation", ""),
            "imageUrl": row.get("imageUrl"),
        })
        for category, label in (("domains", row["domain"]),
                                ("cognitive", row["cognitive"]),
                                ("difficulty", row["difficulty"])):
            actual[category][label] = actual[category].get(label, 0) + 1
        joint_label = f"{row['domain']} — {row['cognitive']}"
        actual["joint"][joint_label] = actual["joint"].get(joint_label, 0) + 1
        stat = stats.setdefault(row["domain"], {"total": 0, "correct": 0})
        stat["total"] += 1
        stat["correct"] += int(match)
    domains = []
    for name, stat in stats.items():
        pct = round(100 * stat["correct"] / stat["total"])
        domains.append({
            "name": name, **stat, "scorePct": pct,
            "tag": "Proficient" if pct >= 75 else "Satisfactory" if pct >= 60 else "Deficient",
        })
    pct = round(100 * correct / len(ids))
    return {
        "title": payload.title or "Practice Drill", "scorePct": pct,
        "totalItems": len(ids), "correctItems": correct, "domains": domains,
        "distribution": actual, "questionReview": question_review,
    }


def normalize_answer(value: str) -> str:
    # Match the source bank's answer_norm convention (lowercase, trimmed spaces).
    return " ".join(value.lower().split())


def allocate_report_counts(labels: list[str], weights: list[int], count: int) -> dict[str, int]:
    """Match the generator's largest-remainder allocation, including tie order."""
    total = sum(weights)
    rows = [(index, count * weight // total, count * weight % total)
            for index, weight in enumerate(weights)]
    result = {label: amount for label, (_, amount, _) in zip(labels, rows)}
    remainder = count - sum(result.values())
    for index, _, _ in sorted(rows, key=lambda row: (-row[2], row[0]))[:remainder]:
        result[labels[index]] += 1
    return result


def build_exam_report(payload: ExamSubmission, student: dict, result: dict) -> dict:
    actual = result["distribution"]
    report = {"mode": "licensure" if payload.mode == "licensure" else
              ("practice" if payload.mode == "student_practice" else
              ("mock" if payload.scope else
               ("remediation" if payload.mode == "remediation" else "unclassified"))),
              "scope": payload.scope, "planned": None, "actual": actual,
              "status": "unavailable", "studentNameAtExam": student.get("name", ""),
              "disciplineAtExam": student.get("discipline", ""),
              "questionReview": result.get("questionReview", [])}
    if payload.scope is None and payload.difficulty_weights is None:
        return report
    discipline = student["discipline"]
    if payload.scope not in [discipline, *DISCIPLINES[discipline]]:
        raise HTTPException(422, "The report scope must be within your discipline.")
    weights = payload.difficulty_weights
    if (weights is None or len(weights) != 3 or
            any(weight < 0 or weight > 100 for weight in weights) or sum(weights) != 100):
        raise HTTPException(422, "Report difficulty percentages must total 100%.")
    if not 11 <= result["totalItems"] <= 200:
        raise HTTPException(422, "TOS mock reports require 11–200 questions.")
    domains = DISCIPLINES[discipline]
    blueprint_domains, blueprint_cognitive = TOS_BLUEPRINT[discipline]
    planned = {
        "domains": allocate_report_counts(domains, blueprint_domains, result["totalItems"])
        if payload.scope == discipline else {payload.scope: result["totalItems"]},
        "cognitive": allocate_report_counts(COGNITIVE_ORDER, blueprint_cognitive,
                                            result["totalItems"]),
        "difficulty": allocate_report_counts(DIFFICULTY_ORDER, weights,
                                             result["totalItems"]),
    }
    report["planned"] = planned
    report["difficultyWeights"] = weights
    report["status"] = "met" if all(
        all(actual[axis].get(label, 0) == target for label, target in expected.items()) and
        all(label in expected for label in actual[axis])
        for axis, expected in planned.items()
    ) else "not_met"
    return report


@router.post("/exams/practice-score")
def practice_score(payload: ExamSubmission, request: Request) -> dict:
    require_same_origin(request)
    session = current_session(request)
    if session is None and len(payload.answers) > 10:
        raise HTTPException(422, "Guest practice drills are limited to 10 questions.")
    if session:
        raise HTTPException(403, "Practice drills are for guests. Students take mock exams within their discipline.")
    with db() as connection:
        return score_exam_payload(connection, payload)


def licensure_cell_quotas(discipline: str, available: dict[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    """Round domain × cognitive products while preserving both 100-item margins."""
    domains = DISCIPLINES[discipline]
    domain_weights, cognitive_weights = TOS_BLUEPRINT[discipline]
    quotas = {}
    row_left = dict(zip(domains, domain_weights))
    column_left = dict(zip(COGNITIVE_ORDER, cognitive_weights))
    for domain, domain_weight in zip(domains, domain_weights):
        for level, cognitive_weight in zip(COGNITIVE_ORDER, cognitive_weights):
            base = domain_weight * cognitive_weight // 100
            if available.get((domain, level), 0) < base:
                raise HTTPException(503, f"The bank lacks {domain} / {level} questions for this TOS.")
            quotas[(domain, level)] = base
            row_left[domain] -= base
            column_left[level] -= base

    # Each fractional cell may receive one extra question. An augmenting-path
    # flow preserves every domain and cognitive total despite linked rounding.
    sink = 1 + len(domains) + len(COGNITIVE_ORDER)
    graph: list[list[dict]] = [[] for _ in range(sink + 1)]
    def edge(source: int, target: int, capacity: int) -> dict:
        forward = {"to": target, "remaining": capacity, "reverse": len(graph[target])}
        backward = {"to": source, "remaining": 0, "reverse": len(graph[source])}
        graph[source].append(forward)
        graph[target].append(backward)
        return forward

    for index, domain in enumerate(domains):
        edge(0, 1 + index, row_left[domain])
    cell_edges = {}
    for domain_index, domain in enumerate(domains):
        ranked_levels = sorted(enumerate(COGNITIVE_ORDER),
                               key=lambda item: -(domain_weights[domain_index] *
                                                  cognitive_weights[item[0]] % 100))
        for level_index, level in ranked_levels:
            product = domain_weights[domain_index] * cognitive_weights[level_index]
            if product % 100 and available.get((domain, level), 0) > quotas[(domain, level)]:
                cell_edges[(domain, level)] = edge(1 + domain_index,
                    1 + len(domains) + level_index, 1)
    for index, level in enumerate(COGNITIVE_ORDER):
        edge(1 + len(domains) + index, sink, column_left[level])

    required = sum(row_left.values())
    sent = 0
    while sent < required:
        parent = {0: None}
        queue = [0]
        for node in queue:
            if sink in parent:
                break
            for index, branch in enumerate(graph[node]):
                if branch["remaining"] > 0 and branch["to"] not in parent:
                    parent[branch["to"]] = (node, index)
                    queue.append(branch["to"])
        if sink not in parent:
            raise HTTPException(503, "The bank cannot meet the combined domain and cognitive TOS quotas.")
        amount = 1
        at = sink
        while at:
            node, index = parent[at]
            branch = graph[node][index]
            branch["remaining"] -= amount
            graph[at][branch["reverse"]]["remaining"] += amount
            at = node
        sent += amount
    for cell, branch in cell_edges.items():
        quotas[cell] += 1 - branch["remaining"]
    return quotas


@router.post("/exams/licensure/start")
def start_licensure_exam(student: dict = Depends(role_required("STUDENT"))) -> dict:
    """Issue a fresh 100-item set matching joint domain/cognitive TOS quotas."""
    discipline = student.get("discipline")
    if discipline not in DISCIPLINES:
        raise HTTPException(403, "Complete your profile before taking an exam.")
    domains = DISCIPLINES[discipline]
    by_cell: dict[tuple[str, str], list[dict]] = {
        (domain, level): [] for domain in domains for level in COGNITIVE_ORDER}
    for question in imported_questions():
        cell = (question["domain"], question["cognitive"])
        if cell in by_cell:
            by_cell[cell].append(question)
    with db() as connection:
        for row in connection.execute(
            "SELECT id,q,opts_json,domain,cognitive,difficulty FROM questions"
        ):
            cell = (row["domain"], row["cognitive"])
            if cell in by_cell:
                by_cell[cell].append({"id": row["id"], "q": row["q"],
                    "opts": json.loads(row["opts_json"]), "domain": row["domain"],
                    "cognitive": row["cognitive"], "difficulty": row["difficulty"],
                    "questionType": "multiple_choice", "source": "local"})
    randomizer = secrets.SystemRandom()
    quotas = licensure_cell_quotas(discipline, {cell: len(items) for cell, items in by_cell.items()})
    selected = [question for cell, quota in quotas.items()
                for question in randomizer.sample(by_cell[cell], quota)]
    randomizer.shuffle(selected)
    planned = {"domains": dict(zip(domains, TOS_BLUEPRINT[discipline][0])),
               "cognitive": dict(zip(COGNITIVE_ORDER, TOS_BLUEPRINT[discipline][1])),
               "joint": {f"{domain} — {level}": quota for (domain, level), quota in quotas.items()}}
    attempt_id = secrets.token_urlsafe(24)
    started_at = int(time.time())
    with db() as connection:
        connection.execute(
            "INSERT INTO licensure_attempts(id,user_id,question_ids_json,planned_json,started_at,expires_at) VALUES(?,?,?,?,?,?)",
            (attempt_id, student["id"], json.dumps([item["id"] for item in selected]),
             json.dumps(planned), started_at, started_at + 3600),
        )
    return {"attemptId": attempt_id, "startedAt": started_at, "expiresAt": started_at + 3600,
            "serverNow": started_at, "timeSeconds": 3600,
            "title": "Mock Licensure Exam", "questions": selected}


@router.post("/exams/practice/start")
def start_practice_exam(payload: PracticeAttemptIn,
                        student: dict = Depends(role_required("STUDENT"))) -> dict:
    allowed = DISCIPLINES.get(student.get("discipline", ""))
    selected = payload.selected_domains
    ids = payload.question_ids
    if (not allowed or not selected or len(selected) > 5 or len(selected) != len(set(selected)) or
            any(domain not in allowed for domain in selected) or
            len(ids) > 200 or len(ids) != len(set(ids))):
        raise HTTPException(422, "Choose unique questions from selected domains in your discipline.")
    if len(ids) < len(selected):
        raise HTTPException(422, "Include at least one question from every selected domain.")
    with db() as connection:
        local = {row["id"]: row["domain"] for row in connection.execute(
            "SELECT id,domain FROM questions")}
        available = {**local, **{item["id"]: item["domain"] for item in imported_questions()}}
        domains = [available.get(question_id) for question_id in ids]
        if any(domain not in selected for domain in domains) or set(domains) != set(selected):
            raise HTTPException(422, "Practice questions must match the selected domains.")
        title = (f"{selected[0]} Practice Exam" if len(selected) == 1 else
                 f"{student['discipline']} Practice Exam ({len(selected)} domains)")
        started_at = int(time.time())
        seconds = payload.time_minutes * 60
        attempt_id = secrets.token_urlsafe(24)
        connection.execute(
            "INSERT INTO licensure_attempts(id,user_id,question_ids_json,started_at,mode,title,"
            "selected_domains_json,time_seconds,expires_at) VALUES(?,?,?,?,'student_practice',?,?,?,?)",
            (attempt_id, student["id"], json.dumps(ids), started_at, title,
             json.dumps(selected), seconds, started_at + seconds),
        )
    return {"attemptId": attempt_id, "startedAt": started_at,
            "expiresAt": started_at + seconds, "serverNow": started_at,
            "timeSeconds": seconds, "title": title}


def owned_attempt(connection: sqlite3.Connection, attempt_id: str, student: dict) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM licensure_attempts WHERE id=? AND user_id=?"
        + (" FOR UPDATE" if DATABASE_URL else ""),
        (attempt_id, student["id"]),
    ).fetchone()
    if row is None or row["abandoned_at"] is not None:
        raise HTTPException(404, "Exam attempt not found.")
    if row["submitted_at"] is not None and row["result_id"] is None:
        raise HTTPException(409, "This older exam attempt was already submitted.")
    return row


def finalize_timed_attempt(connection: sqlite3.Connection, row: sqlite3.Row,
                           student: dict) -> dict:
    if row["result_id"] is not None:
        saved = connection.execute(
            "SELECT * FROM exam_history WHERE id=?", (row["result_id"],)
        ).fetchone()
        if saved is None:
            raise HTTPException(409, "Saved exam result is unavailable.")
        return {"id": saved["id"], "title": saved["title"], "scorePct": saved["score_pct"],
                "totalItems": saved["total_items"], "correctItems": saved["correct_items"],
                "domains": json.loads(saved["domains_json"]),
                "expired": row["submitted_at"] >= row["expires_at"]}
    ids = json.loads(row["question_ids_json"])
    saved_answers = json.loads(row["answers_json"] or "{}")
    selected_domains = json.loads(row["selected_domains_json"]) if row["selected_domains_json"] else None
    exam = ExamSubmission(title=row["title"], mode=row["mode"], attempt_id=row["id"],
                          selected_domains=selected_domains,
                          answers=[AnswerIn(id=question_id, userAns=saved_answers.get(question_id))
                                   for question_id in ids])
    result = score_exam_payload(connection, exam)
    result["title"] = row["title"]
    if any(domain["name"] not in DISCIPLINES.get(student.get("discipline", ""), [])
           for domain in result["domains"]):
        raise HTTPException(403, "Exam questions must belong to your selected discipline.")
    report = build_exam_report(exam, student, result)
    if row["mode"] == "licensure" and row["planned_json"]:
        planned = json.loads(row["planned_json"])
        report["planned"] = planned
        report["status"] = "met" if all(
            result["distribution"][axis] == targets for axis, targets in planned.items()
        ) else "not_met"
    now = int(time.time())
    cursor = connection.execute(
        "INSERT INTO exam_history(user_id,title,score_pct,total_items,correct_items,domains_json,report_json) "
        "VALUES(?,?,?,?,?,?,?) RETURNING id",
        (student["id"], result["title"], result["scorePct"], result["totalItems"],
         result["correctItems"], json.dumps(result["domains"]), json.dumps(report)),
    )
    result_id = cursor.fetchone()["id"]
    connection.execute("UPDATE licensure_attempts SET submitted_at=?,result_id=? WHERE id=?",
                       (now, result_id, row["id"]))
    return {"id": result_id, **result, "expired": now >= row["expires_at"]}


def finalize_expired_attempts() -> int:
    """Finalize saved answers even if the examinee closes the browser."""
    import logging
    completed = 0
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            "SELECT * FROM licensure_attempts WHERE result_id IS NULL AND submitted_at IS NULL "
            "AND abandoned_at IS NULL "
            "AND expires_at<=?"
            + (" FOR UPDATE SKIP LOCKED" if DATABASE_URL else ""),
            (int(time.time()),),
        ).fetchall()
        for row in rows:
            student = connection.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
            if student is None:
                continue
            connection.execute("SAVEPOINT timed_exam_finalize")
            try:
                finalize_timed_attempt(connection, row, dict(student))
                connection.execute("RELEASE SAVEPOINT timed_exam_finalize")
                completed += 1
            except Exception:
                connection.execute("ROLLBACK TO SAVEPOINT timed_exam_finalize")
                connection.execute("RELEASE SAVEPOINT timed_exam_finalize")
                logging.exception("Could not finalize timed exam attempt %s", row["id"])
    return completed


@router.get("/exams/attempts/{attempt_id}")
def exam_attempt_status(attempt_id: str, student: dict = Depends(role_required("STUDENT"))) -> dict:
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = owned_attempt(connection, attempt_id, student)
        if row["result_id"] is None and time.time() >= row["expires_at"]:
            result = finalize_timed_attempt(connection, row, student)
            result_id = result["id"]
        else:
            result_id = row["result_id"]
        return {"attemptId": attempt_id, "expiresAt": row["expires_at"],
                "serverNow": int(time.time()), "resultId": result_id,
                "answers": json.loads(row["answers_json"] or "{}")}


@router.put("/exams/attempts/{attempt_id}/answers")
def save_exam_answers(attempt_id: str, payload: AttemptAnswersIn,
                      student: dict = Depends(role_required("STUDENT"))) -> dict:
    if len(payload.answers) > 200 or len({answer.id for answer in payload.answers}) != len(payload.answers):
        raise HTTPException(422, "Answers must have unique question IDs.")
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = owned_attempt(connection, attempt_id, student)
        if row["result_id"] is not None:
            raise HTTPException(409, "This exam has already been submitted.")
        if time.time() >= row["expires_at"]:
            result = finalize_timed_attempt(connection, row, student)
            return {"saved": False, "expired": True, "resultId": result["id"]}
        issued = set(json.loads(row["question_ids_json"]))
        if any(answer.id not in issued or
               (isinstance(answer.userAns, int) and not 0 <= answer.userAns <= 4) or
               (isinstance(answer.userAns, str) and len(answer.userAns) > 500)
               for answer in payload.answers):
            raise HTTPException(422, "An answer is invalid or was not issued for this exam.")
        # Reject answers that the scorer cannot handle before they become the
        # only copy available to the deadline finalizer.
        if payload.answers:
            score_exam_payload(connection, ExamSubmission(title=row["title"], answers=payload.answers))
        saved = json.loads(row["answers_json"] or "{}")
        saved.update({answer.id: answer.userAns for answer in payload.answers})
        connection.execute("UPDATE licensure_attempts SET answers_json=? WHERE id=?",
                           (json.dumps(saved), attempt_id))
    return {"saved": True, "expiresAt": row["expires_at"]}


@router.post("/exams/attempts/{attempt_id}/submit")
def submit_timed_attempt(attempt_id: str,
                         student: dict = Depends(role_required("STUDENT"))) -> dict:
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = owned_attempt(connection, attempt_id, student)
        return finalize_timed_attempt(connection, row, student)


@router.delete("/exams/attempts/{attempt_id}")
def abandon_timed_attempt(attempt_id: str,
                          student: dict = Depends(role_required("STUDENT"))) -> dict:
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = owned_attempt(connection, attempt_id, student)
        if row["result_id"] is not None:
            raise HTTPException(409, "This exam has already been submitted.")
        if time.time() >= row["expires_at"]:
            result = finalize_timed_attempt(connection, row, student)
            return {"ok": False, "expired": True, "resultId": result["id"]}
        connection.execute("UPDATE licensure_attempts SET abandoned_at=? WHERE id=?",
                           (int(time.time()), attempt_id))
    return {"ok": True}


@router.post("/exams/submit")
def submit_exam(payload: ExamSubmission, student: dict = Depends(role_required("STUDENT"))) -> dict:
    allowed_domains = DISCIPLINES.get(student.get("discipline", ""))
    if not allowed_domains:
        raise HTTPException(403, "Choose your discipline in your profile before submitting a mock exam.")
    if payload.mode in {"licensure", "student_practice"}:
        if not payload.attempt_id:
            raise HTTPException(422, "A server-issued timed exam attempt is required.")
        with db() as connection:
            connection.execute("BEGIN IMMEDIATE")
            attempt = owned_attempt(connection, payload.attempt_id, student)
            if attempt["mode"] != payload.mode or attempt["result_id"] is not None:
                raise HTTPException(422, "This exam attempt is unavailable or already submitted.")
            issued_ids = json.loads(attempt["question_ids_json"])
            if payload.mode == "licensure" and student.get("discipline") not in DISCIPLINES:
                raise HTTPException(403, "Complete your profile before taking an exam.")
            if payload.mode == "student_practice" and payload.selected_domains != json.loads(attempt["selected_domains_json"]):
                raise HTTPException(422, "The selected practice domains cannot be changed.")
            if time.time() < attempt["expires_at"]:
                if (len(payload.answers) != len(issued_ids) or
                        {answer.id for answer in payload.answers} != set(issued_ids)):
                    raise HTTPException(422, "Submit only the questions issued for this attempt.")
                connection.execute("UPDATE licensure_attempts SET answers_json=? WHERE id=?",
                                   (json.dumps({answer.id: answer.userAns for answer in payload.answers}),
                                    payload.attempt_id))
            return finalize_timed_attempt(connection, attempt, student)
    with db() as connection:
        if payload.mode == "licensure":
            attempt = connection.execute(
                "SELECT * FROM licensure_attempts WHERE id=? AND user_id=? AND submitted_at IS NULL",
                (payload.attempt_id, student["id"]),
            ).fetchone()
            if not attempt or len(payload.answers) != 100 or payload.scope is not None or payload.difficulty_weights is not None:
                raise HTTPException(422, "This mock licensure attempt is unavailable or invalid.")
            issued_ids = json.loads(attempt["question_ids_json"])
            if {answer.id for answer in payload.answers} != set(issued_ids):
                raise HTTPException(422, "Submit the questions issued for this mock licensure attempt.")
            if time.time() < attempt["started_at"]:
                raise HTTPException(422, "Invalid mock licensure attempt time.")
        result = score_exam_payload(connection, payload)
        if payload.mode == "licensure":
            result["title"] = "Mock Licensure Exam"
        if any(domain["name"] not in allowed_domains for domain in result["domains"]):
            raise HTTPException(403, "Mock exam questions must belong to your selected discipline.")
        if payload.mode == "student_practice":
            selected = payload.selected_domains or []
            if (not selected or len(selected) > 5 or len(selected) != len(set(selected)) or
                    any(domain not in allowed_domains for domain in selected) or
                    len(payload.answers) > 200 or
                    {domain["name"] for domain in result["domains"]} != set(selected) or
                    payload.scope is not None or payload.difficulty_weights is not None):
                raise HTTPException(422, "Practice exams must contain the selected domains within your discipline.")
            result["title"] = (f"{selected[0]} Practice Exam" if len(selected) == 1 else
                               f"{student['discipline']} Practice Exam ({len(selected)} domains)")
        report = build_exam_report(payload, student, result)
        if payload.mode == "licensure" and attempt["planned_json"]:
            planned = json.loads(attempt["planned_json"])
            report["planned"] = planned
            report["status"] = "met" if all(
                result["distribution"][axis] == targets for axis, targets in planned.items()
            ) else "not_met"
        cursor = connection.execute(
            """INSERT INTO exam_history(user_id,title,score_pct,total_items,correct_items,
                                        domains_json,report_json) VALUES(?,?,?,?,?,?,?) RETURNING id""",
            (student["id"], result["title"], result["scorePct"], result["totalItems"],
             result["correctItems"], json.dumps(result["domains"]), json.dumps(report)),
        )
        result_id = cursor.fetchone()["id"]
        if payload.mode == "licensure":
            connection.execute("UPDATE licensure_attempts SET submitted_at=? WHERE id=?",
                               (int(time.time()), payload.attempt_id))
    return {"id": result_id, **result}


@router.get("/reports/exams/{exam_id}")
def exam_report(exam_id: int, user: dict = Depends(role_required("STUDENT", "ADMIN"))) -> dict:
    with db() as connection:
        row = connection.execute(
            """SELECT h.id,h.user_id,h.title,h.created_at AS date,h.score_pct AS "scorePct",
                      h.total_items AS "totalItems",h.correct_items AS "correctItems",
                      h.domains_json,h.report_json,u.name AS "studentName",
                      u.username,u.discipline
               FROM exam_history h JOIN users u ON u.id=h.user_id WHERE h.id=?""", (exam_id,)
        ).fetchone()
    if row is None or (user["role"] != "ADMIN" and row["user_id"] != user["id"]):
        raise HTTPException(404, "Exam report not found.")
    item = dict(row)
    item["domains"] = json.loads(item.pop("domains_json"))
    report_json = item.pop("report_json")
    snapshot = json.loads(report_json) if report_json else None
    if snapshot:
        item["studentName"] = snapshot.get("studentNameAtExam") or item["studentName"]
        item["discipline"] = snapshot.get("disciplineAtExam") or item["discipline"]
        item["questionReview"] = snapshot.get("questionReview", [])
    else:
        item["questionReview"] = []
    item["report"] = snapshot if user["role"] == "ADMIN" else None
    return item


@router.get("/admin/reports/roster")
def cohort_roster(admin: dict = Depends(role_required("ADMIN"))) -> list[dict]:
    with db() as connection:
        rows = connection.execute(
            """SELECT h.id,h.title,h.created_at AS date,h.score_pct AS "scorePct",
                      h.total_items AS "totalItems",h.correct_items AS "correctItems",
                      h.domains_json,h.report_json,u.name AS "studentName",u.username,u.discipline
               FROM exam_history h JOIN users u ON u.id=h.user_id
               ORDER BY h.created_at DESC,h.id DESC"""
        ).fetchall()
    roster = []
    for row in rows:
        item = {key: value for key, value in dict(row).items() if key not in {"report_json", "domains_json"}}
        item["domains"] = json.loads(row["domains_json"])
        snapshot = json.loads(row["report_json"]) if row["report_json"] else None
        item["mode"] = snapshot.get("mode", "unclassified") if snapshot else "legacy"
        if snapshot:
            item["studentName"] = snapshot.get("studentNameAtExam") or item["studentName"]
            item["discipline"] = snapshot.get("disciplineAtExam") or item["discipline"]
        roster.append(item)
    return roster


def create_initial_admin(username: str, email: str, password: str) -> None:
    username = validate_username(username)
    email = validate_email(email)
    validate_password(password)
    with db() as connection:
        if connection.execute("SELECT 1 FROM users WHERE role='ADMIN' LIMIT 1").fetchone():
            raise ValueError("An administrator already exists.")
        connection.execute(
            "INSERT INTO users(username,email,password_hash,role,name) VALUES(?,?,?,'ADMIN',?)",
            (username, email, hash_password(password), username),
        )


def reset_admin_password_local(identifier: str, password: str) -> str:
    """Recover an existing admin from the local machine, never from an HTTP route."""
    validate_password(password)
    identifier = identifier.strip()
    with db() as connection:
        admin = connection.execute(
            "SELECT id,username FROM users WHERE role='ADMIN' AND (username=? OR email=?)",
            (identifier, identifier),
        ).fetchone()
        if admin is None:
            raise ValueError("Administrator account not found.")
        connection.execute(
            "UPDATE users SET password_hash=?,invalid_attempts=0,is_locked=0 WHERE id=?",
            (hash_password(password), admin["id"]),
        )
        connection.execute("DELETE FROM sessions WHERE user_id=?", (admin["id"],))
        connection.execute(
            "UPDATE password_reset_requests SET status='rejected',reviewed_at=CURRENT_TIMESTAMP "
            "WHERE user_id=? AND status='pending'",
            (admin["id"],),
        )
    return admin["username"]
