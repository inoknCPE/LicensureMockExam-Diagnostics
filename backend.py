"""Local SQLite authentication and role API for the Computer Engineering prototype."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CPEDLE_DB_PATH", ROOT / "data" / "cpedle.sqlite3"))
QUESTION_BANK_PATH = ROOT / "data" / "questionbank.db"
SESSION_SECONDS = 12 * 60 * 60
MAX_ATTEMPTS = 3
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


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
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
def question_bank() -> Iterator[sqlite3.Connection | None]:
    """Open the team-supplied bank read-only; never mix it with account data."""
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
        rows = bank.execute("""
            SELECT q.id, q.question_text, q.question_type, q.image_path,
                   q.answer_letter, q.answer_text, q.cognitive_level, q.difficulty,
                   d.name AS domain
            FROM questions q JOIN domains d ON d.id=q.domain_id ORDER BY q.id
        """).fetchall()
        choices = {}
        for choice in bank.execute(
            "SELECT question_id,letter,choice_text,image_path FROM choices ORDER BY question_id,letter"
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
            item["answerText"] = row["answer_text"]
        result.append(item)
    return result


def bank_image_url(path: str | None) -> str | None:
    """Only expose image names within the committed static/images directory."""
    if not path or not path.startswith("images/"):
        return None
    relative = Path(path)
    if ".." in relative.parts or relative.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return None
    return "/static/" + relative.as_posix()


def initialize() -> None:
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
                invalid_attempts INTEGER NOT NULL DEFAULT 0,
                is_locked INTEGER NOT NULL DEFAULT 0,
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
            CREATE TABLE IF NOT EXISTS question_change_requests (
                id INTEGER PRIMARY KEY,
                proposer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                action TEXT NOT NULL CHECK(action IN ('ADD','EDIT')),
                target_question_id TEXT,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT,
                reviewed_by INTEGER REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS exam_history (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                score_pct INTEGER NOT NULL,
                total_items INTEGER NOT NULL,
                correct_items INTEGER NOT NULL,
                domains_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    if not (8 <= len(value) <= 12 and re.search(r"[A-Za-z]", value)
            and re.search(r"[A-Z]", value) and re.search(r"[0-9]", value)
            and any(char in SPECIAL for char in value)):
        raise HTTPException(
            422, "Password must be 8–12 characters and include a letter, uppercase letter, number, and special character."
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


class RegisterIn(BaseModel):
    username: str
    email: str
    password: str
    confirm_password: str


class LoginIn(BaseModel):
    identifier: str
    password: str


class ResetIn(BaseModel):
    identifier: str
    password: str
    confirm_password: str


class ProfileIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    discipline: str = ""


class EmailChangeIn(BaseModel):
    email: str
    current_password: str


class RoleIn(BaseModel):
    role: str


class DecisionIn(BaseModel):
    approve: bool


class QuestionIn(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,40}$")
    q: str = Field(min_length=3, max_length=2000)
    opts: list[str]
    ans: int
    domain: str
    cognitive: str
    difficulty: str
    explanation: str = ""


class RequestIn(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    domain: str
    difficulty: str
    notes: str = Field(default="", max_length=2000)


class RequestStatusIn(BaseModel):
    status: str
    admin_comment: str = Field(default="", max_length=1000)


class AnswerIn(BaseModel):
    id: str
    userAns: int | str | None = None


class ExamSubmission(BaseModel):
    title: str = Field(max_length=160)
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
        requests = []
        history = []
        if user and user["role"] in {"STUDENT", "ADMIN"}:
            where = "" if user["role"] == "ADMIN" else "WHERE r.user_id = ?"
            params = () if user["role"] == "ADMIN" else (user["id"],)
            requests = [dict(row) for row in connection.execute(
                f"""SELECT r.id, u.name AS examineeName, r.title, r.domain, r.difficulty,
                       r.notes, r.status, r.admin_comment AS adminComment,
                       r.created_at AS timestamp
                    FROM requests r JOIN users u ON u.id=r.user_id {where}
                    ORDER BY r.id DESC""", params
            )]
            where_h = "" if user["role"] == "ADMIN" else "WHERE user_id = ?"
            history = [
                {**dict(row), "domains": json.loads(row["domains_json"])}
                for row in connection.execute(
                    f"""SELECT id,title,created_at AS date,score_pct AS scorePct,
                               total_items AS totalItems,correct_items AS correctItems,
                               domains_json FROM exam_history {where_h} ORDER BY id DESC""",
                    params,
                )
            ]
            for item in history:
                item.pop("domains_json", None)
    return {
        "user": user, "csrf": session[1] if session else None,
        "questions": questions, "requests": requests, "history": history,
    }


@router.post("/auth/register")
def register(payload: RegisterIn, request: Request, response: Response) -> dict:
    require_same_origin(request)
    if payload.password != payload.confirm_password:
        raise HTTPException(422, "Passwords do not match.")
    username = validate_username(payload.username)
    email = validate_email(payload.email)
    validate_password(payload.password)
    try:
        with db() as connection:
            existing = connection.execute(
                "SELECT username,email FROM users WHERE username=? OR email=?",
                (username, email),
            ).fetchone()
            if existing:
                field = "Username" if existing["username"].casefold() == username.casefold() else "Email"
                raise HTTPException(409, f"{field} is already registered.")
            cursor = connection.execute(
                "INSERT INTO users(username,email,password_hash,role) VALUES(?,?,?,'STUDENT')",
                (username, email, hash_password(payload.password)),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username or email is already registered.") from None
    _, csrf = set_session(response, cursor.lastrowid, request.url.scheme == "https")
    return {"user": {"id": cursor.lastrowid, "username": username, "email": email,
                     "role": "STUDENT", "name": "", "discipline": ""}, "csrf": csrf}


@router.post("/auth/login")
def login(payload: LoginIn, request: Request, response: Response) -> dict:
    require_same_origin(request)
    identifier = payload.identifier.strip()
    if not identifier or not payload.password:
        raise HTTPException(422, "Enter your username/email and password.")
    with db() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM users WHERE username=? OR email=?",
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
            "SELECT id FROM users WHERE username=? OR email=?",
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
    if user["role"] != "ADMIN" and payload.discipline not in DISCIPLINES:
        raise HTTPException(422, "Select a listed Computer Engineering discipline.")
    name = payload.name.strip()
    if len(name) < 2:
        raise HTTPException(422, "Enter your name.")
    discipline = "" if user["role"] == "ADMIN" else payload.discipline
    with db() as connection:
        connection.execute(
            "UPDATE users SET name=?, discipline=? WHERE id=?",
            (name, discipline, user["id"]),
        )
    return {"user": {**user, "name": name, "discipline": discipline}}


@router.put("/profile/email")
def change_own_email(payload: EmailChangeIn, user: dict = Depends(require_user)) -> dict:
    email = validate_email(payload.email)
    try:
        with db() as connection:
            row = connection.execute(
                "SELECT password_hash FROM users WHERE id=?", (user["id"],)
            ).fetchone()
            if row is None or not check_password(payload.current_password, row["password_hash"]):
                raise HTTPException(403, "Current password is incorrect.")
            connection.execute("UPDATE users SET email=? WHERE id=?", (email, user["id"]))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Email is already registered.") from None
    return {"user": {**user, "email": email}}


@router.get("/admin/users")
def admin_users(admin: dict = Depends(role_required("ADMIN"))) -> list[dict]:
    with db() as connection:
        return [dict(row) for row in connection.execute(
            "SELECT id,username,email,name,discipline,role,invalid_attempts,is_locked FROM users ORDER BY id"
        )]


@router.patch("/admin/users/{user_id}/role")
def change_role(user_id: int, payload: RoleIn, admin: dict = Depends(role_required("ADMIN"))) -> dict:
    if payload.role not in ROLES:
        raise HTTPException(422, "Role must be STUDENT, EXAMINER, or ADMIN.")
    if user_id == admin["id"]:
        raise HTTPException(400, "You cannot change your own role.")
    with db() as connection:
        target = connection.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "Account not found.")
        connection.execute("UPDATE users SET role=? WHERE id=?", (payload.role, user_id))
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return {"ok": True}


@router.post("/admin/users/{user_id}/unlock")
def unlock(user_id: int, admin: dict = Depends(role_required("ADMIN"))) -> dict:
    with db() as connection:
        cursor = connection.execute(
            "UPDATE users SET is_locked=0,invalid_attempts=0 WHERE id=? AND is_locked=1",
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


def queue_question_change(connection: sqlite3.Connection, payload: QuestionIn,
                          action: str, target_id: str | None, user_id: int) -> dict:
    """Keep examiner changes separate from the live bank until admin review."""
    if action == "ADD":
        payload = payload.model_copy(update={"id": payload.id or "CPE-" + secrets.token_hex(5).upper()})
        if connection.execute("SELECT 1 FROM questions WHERE id=?", (payload.id,)).fetchone():
            raise HTTPException(409, "Question ID already exists.")
    elif not connection.execute("SELECT 1 FROM questions WHERE id=?", (target_id,)).fetchone():
        raise HTTPException(404, "Question not found.")
    cursor = connection.execute(
        "INSERT INTO question_change_requests(proposer_id,action,target_question_id,payload_json) "
        "VALUES(?,?,?,?)",
        (user_id, action, target_id, payload.model_dump_json()),
    )
    return {"id": payload.id or target_id, "pending": True, "request_id": cursor.lastrowid}


@router.get("/questions/change-requests")
def question_change_requests(user: dict = Depends(role_required("EXAMINER", "ADMIN"))) -> list[dict]:
    import json
    with db() as connection:
        where = "WHERE c.status='pending'" if user["role"] == "ADMIN" else "WHERE c.proposer_id=?"
        params = () if user["role"] == "ADMIN" else (user["id"],)
        rows = connection.execute(
            f"""SELECT c.id,c.action,c.target_question_id,c.payload_json,c.status,
                       c.submitted_at,u.username AS proposer
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
def decide_question_change(change_id: int, payload: DecisionIn,
                           admin: dict = Depends(role_required("ADMIN"))) -> dict:
    import json
    try:
        with db() as connection:
            row = connection.execute(
                "SELECT * FROM question_change_requests WHERE id=? AND status='pending'",
                (change_id,),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Pending question change not found.")
            question = QuestionIn.model_validate_json(row["payload_json"])
            validate_question(question)
            if payload.approve:
                if row["action"] == "ADD":
                    connection.execute(
                        "INSERT INTO questions(id,q,opts_json,ans,domain,cognitive,difficulty,explanation) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        (question.id, question.q.strip(), json.dumps(question.opts), question.ans,
                         question.domain, question.cognitive, question.difficulty, question.explanation),
                    )
                else:
                    cursor = connection.execute(
                        "UPDATE questions SET q=?,opts_json=?,ans=?,domain=?,cognitive=?,difficulty=?,"
                        "explanation=? WHERE id=?",
                        (question.q.strip(), json.dumps(question.opts), question.ans,
                         question.domain, question.cognitive, question.difficulty,
                         question.explanation, row["target_question_id"]),
                    )
                    if not cursor.rowcount:
                        raise HTTPException(409, "Original question no longer exists. Reject this change.")
            connection.execute(
                "UPDATE question_change_requests SET status=?,reviewed_at=CURRENT_TIMESTAMP,reviewed_by=? "
                "WHERE id=?",
                ("approved" if payload.approve else "rejected", admin["id"], change_id),
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
def delete_question(question_id: str, user: dict = Depends(role_required("ADMIN"))) -> dict:
    with db() as connection:
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


@router.post("/requests")
def submit_request(payload: RequestIn, student: dict = Depends(role_required("STUDENT"))) -> dict:
    if payload.domain not in DOMAINS or payload.difficulty not in DIFFICULTIES:
        raise HTTPException(422, "Select a valid domain and difficulty.")
    with db() as connection:
        cursor = connection.execute(
            "INSERT INTO requests(user_id,title,domain,difficulty,notes) VALUES(?,?,?,?,?)",
            (student["id"], payload.title.strip(), payload.domain,
             payload.difficulty, payload.notes.strip()),
        )
    return {"id": cursor.lastrowid}


@router.patch("/admin/requests/{request_id}")
def review_request(request_id: int, payload: RequestStatusIn,
                   admin: dict = Depends(role_required("ADMIN"))) -> dict:
    if payload.status not in {"Pending", "Approved", "Rejected"}:
        raise HTTPException(422, "Invalid request status.")
    with db() as connection:
        cursor = connection.execute(
            "UPDATE requests SET status=?,admin_comment=? WHERE id=?",
            (payload.status, payload.admin_comment.strip(), request_id),
        )
    if not cursor.rowcount:
        raise HTTPException(404, "Request not found.")
    return {"ok": True}


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
            f"SELECT id,ans,domain FROM questions WHERE id IN ({','.join('?' for _ in local_ids)})",
            local_ids,
        ).fetchall()
        lookup.update({row["id"]: {**dict(row), "type": "local"} for row in rows})
    if imported_ids:
        numbers = [item[3:] for item in imported_ids]
        if any(not number.isdigit() for number in numbers):
            raise HTTPException(422, "Invalid question ID.")
        with question_bank() as bank:
            if bank is not None:
                rows = bank.execute(
                    f"""SELECT q.id,q.question_type,q.answer_letter,d.name AS domain
                        FROM questions q JOIN domains d ON d.id=q.domain_id
                        WHERE q.id IN ({','.join('?' for _ in numbers)})""",
                    numbers,
                ).fetchall()
                for row in rows:
                    number = row["id"]
                    answer_rows = bank.execute(
                        "SELECT answer_norm FROM accepted_answers WHERE question_id=?", (number,)
                    ).fetchall()
                    letters = [item["letter"] for item in bank.execute(
                        "SELECT letter FROM choices WHERE question_id=? ORDER BY letter", (number,)
                    )]
                    lookup[f"QB-{number}"] = {
                        "domain": row["domain"], "type": row["question_type"],
                        "answer_index": letters.index(row["answer_letter"])
                        if row["answer_letter"] in letters else None,
                        "accepted": {normalize_answer(item["answer_norm"]) for item in answer_rows},
                    }
    if len(lookup) != len(ids):
        raise HTTPException(422, "One or more questions no longer exist.")
    stats: dict[str, dict[str, int]] = {}
    correct = 0
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
    }


def normalize_answer(value: str) -> str:
    # Match the source bank's answer_norm convention (lowercase, trimmed spaces).
    return " ".join(value.lower().split())


@router.post("/exams/practice-score")
def practice_score(payload: ExamSubmission, request: Request) -> dict:
    require_same_origin(request)
    session = current_session(request)
    if session is None and len(payload.answers) > 10:
        raise HTTPException(422, "Guest practice drills are limited to 10 questions.")
    if session and session[0]["role"] not in {"STUDENT"}:
        raise HTTPException(403, "This role cannot take practice drills.")
    with db() as connection:
        return score_exam_payload(connection, payload)


@router.post("/exams/submit")
def submit_exam(payload: ExamSubmission, student: dict = Depends(role_required("STUDENT"))) -> dict:
    import json
    with db() as connection:
        result = score_exam_payload(connection, payload)
        cursor = connection.execute(
            "INSERT INTO exam_history(user_id,title,score_pct,total_items,correct_items,domains_json) VALUES(?,?,?,?,?,?)",
            (student["id"], result["title"], result["scorePct"], result["totalItems"],
             result["correctItems"], json.dumps(result["domains"])),
        )
    return {"id": cursor.lastrowid, **result}


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
