import sqlite3
from dataclasses import dataclass
from typing import Any

import bcrypt
from pydantic import ValidationError

from logger import logger
from models.database import Database
from models.schemas import UserRegisterSchema


MAX_INVALID_ATTEMPTS = 3


@dataclass(frozen=True)
class AuthResult:
    success: bool
    message: str
    user: dict[str, Any] | None = None
    code: str | None = None


class AuthController:
    def __init__(self, database: Database):
        self.database = database

    def has_admin(self) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
            ).fetchone()
        return row is not None

    def create_initial_admin(
        self,
        username: str,
        email: str,
        password: str,
        confirm_password: str,
    ) -> AuthResult:
        if self.has_admin():
            return AuthResult(False, "The initial administrator already exists.")
        return self._register(
            username, email, password, confirm_password, role="admin"
        )

    def register_user(
        self,
        username: str,
        email: str,
        password: str,
        confirm_password: str,
    ) -> AuthResult:
        return self._register(username, email, password, confirm_password, role="user")

    def _register(
        self,
        username: str,
        email: str,
        password: str,
        confirm_password: str,
        role: str,
    ) -> AuthResult:
        if password != confirm_password:
            return AuthResult(False, "Password and confirm password do not match.")

        try:
            validated = UserRegisterSchema(
                username=username, email=email, password=password
            )
        except ValidationError as error:
            message = error.errors()[0]["msg"].removeprefix("Value error, ")
            return AuthResult(False, message)

        password_hash = bcrypt.hashpw(
            validated.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        try:
            with self.database.connect() as connection:
                existing = connection.execute(
                    """
                    SELECT username, email FROM users
                    WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE
                    """,
                    (validated.username, validated.email),
                ).fetchall()
                for row in existing:
                    if row["username"].casefold() == validated.username.casefold():
                        return AuthResult(False, "That username is already registered.")
                    if row["email"] and row["email"].casefold() == validated.email.casefold():
                        return AuthResult(False, "That email address is already registered.")

                cursor = connection.execute(
                    """
                    INSERT INTO users (username, email, password_hash, role)
                    VALUES (?, ?, ?, ?)
                    """,
                    (validated.username, validated.email, password_hash, role),
                )
            logger.info("%s account created: %s", role.capitalize(), validated.username)
            return AuthResult(
                True,
                "Registration successful. You may now log in.",
                {
                    "id": cursor.lastrowid,
                    "username": validated.username,
                    "email": validated.email,
                    "role": role,
                },
            )
        except sqlite3.IntegrityError:
            logger.warning("Registration rejected by a unique database constraint")
            return AuthResult(False, "That username or email is already registered.")
        except sqlite3.Error:
            logger.exception("Registration database error")
            return AuthResult(False, "Registration failed because of a database error.")

    def login_user(self, identifier: str, password: str) -> AuthResult:
        identifier = identifier.strip()
        if not identifier or not password:
            return AuthResult(False, "Enter your username or email and password.")

        try:
            with self.database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT id, username, email, password_hash, role,
                           invalid_attempts, is_locked
                    FROM users
                    WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE
                    """,
                    (identifier, identifier),
                ).fetchone()

                if row is None:
                    logger.warning("Login failed for unknown identifier: %s", identifier)
                    return AuthResult(False, "Invalid username/email or password.")

                if row["is_locked"]:
                    logger.warning("Login rejected for locked account: %s", row["username"])
                    return AuthResult(
                        False,
                        "This account is locked. Submit a password-reset request "
                        "for administrator review.",
                        code="account_locked",
                    )

                if not bcrypt.checkpw(
                    password.encode("utf-8"), row["password_hash"].encode("utf-8")
                ):
                    attempts = row["invalid_attempts"] + 1
                    locked = attempts >= MAX_INVALID_ATTEMPTS
                    connection.execute(
                        """
                        UPDATE users
                        SET invalid_attempts = ?, is_locked = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (attempts, int(locked), row["id"]),
                    )
                    logger.warning(
                        "Invalid login for %s (attempt %s/%s)",
                        row["username"],
                        attempts,
                        MAX_INVALID_ATTEMPTS,
                    )
                    if locked:
                        return AuthResult(
                            False,
                            "Account locked after 3 invalid attempts. "
                            "Submit a password-reset request for administrator review.",
                            code="account_locked",
                        )
                    remaining = MAX_INVALID_ATTEMPTS - attempts
                    return AuthResult(
                        False,
                        f"Invalid username/email or password. {remaining} attempt(s) remaining.",
                    )

                connection.execute(
                    """
                    UPDATE users
                    SET invalid_attempts = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (row["id"],),
                )
                user = {
                    "id": row["id"],
                    "username": row["username"],
                    "email": row["email"],
                    "role": row["role"],
                }
                logger.info("User logged in: %s", row["username"])
                return AuthResult(True, "Login successful.", user)
        except sqlite3.Error:
            logger.exception("Login database error")
            return AuthResult(False, "Login failed because of a database error.")

    def request_password_reset(
        self,
        identifier: str,
        new_password: str,
        confirm_password: str,
    ) -> AuthResult:
        identifier = identifier.strip()
        if not identifier:
            return AuthResult(False, "Enter your username or email address.")
        if new_password != confirm_password:
            return AuthResult(False, "New password and confirm password do not match.")

        try:
            # Reuse the registration validator so password rules never diverge.
            validated = UserRegisterSchema(
                username="resetuser",
                email="reset@example.com",
                password=new_password,
            )
        except ValidationError as error:
            message = error.errors()[0]["msg"].removeprefix("Value error, ")
            return AuthResult(False, message)

        new_password_hash = bcrypt.hashpw(
            validated.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        try:
            with self.database.connect() as connection:
                user = connection.execute(
                    """
                    SELECT id, username FROM users
                    WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE
                    """,
                    (identifier, identifier),
                ).fetchone()
                if user is None:
                    return AuthResult(False, "No account matches that username or email.")

                pending = connection.execute(
                    """
                    SELECT id FROM password_reset_requests
                    WHERE user_id = ? AND status = 'pending'
                    """,
                    (user["id"],),
                ).fetchone()
                if pending:
                    connection.execute(
                        """
                        UPDATE password_reset_requests
                        SET new_password_hash = ?, requested_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (new_password_hash, pending["id"]),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO password_reset_requests (user_id, new_password_hash)
                        VALUES (?, ?)
                        """,
                        (user["id"], new_password_hash),
                    )
            logger.info("Password-reset request submitted: %s", user["username"])
            return AuthResult(
                True,
                "Your password-reset request is pending administrator review.",
            )
        except sqlite3.Error:
            logger.exception("Password-reset request database error")
            return AuthResult(False, "The password-reset request could not be saved.")

    def list_locked_users(self, administrator_id: int) -> list[tuple[int, str, str, str]]:
        if not self._is_active_admin(administrator_id):
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, username, COALESCE(email, ''), role
                FROM users WHERE is_locked = 1
                ORDER BY username COLLATE NOCASE
                """
            ).fetchall()
        return [tuple(row) for row in rows]

    def unlock_user(self, administrator_id: int, user_id: int) -> AuthResult:
        if not self._is_active_admin(administrator_id):
            return AuthResult(False, "Administrator authorization is required.")
        with self.database.connect() as connection:
            target = connection.execute(
                "SELECT username, is_locked FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if target is None:
                return AuthResult(False, "The selected account no longer exists.")
            if not target["is_locked"]:
                return AuthResult(False, "The selected account is not locked.")
            connection.execute(
                """
                UPDATE users
                SET invalid_attempts = 0, is_locked = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (user_id,),
            )
        logger.info("Account unlocked by administrator: %s", target["username"])
        return AuthResult(True, f"Account '{target['username']}' has been unlocked.")

    def list_pending_password_resets(
        self, administrator_id: int
    ) -> list[tuple[int, str, str, str, str]]:
        if not self._is_active_admin(administrator_id):
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT requests.id, users.username, COALESCE(users.email, ''),
                       CASE users.is_locked WHEN 1 THEN 'Locked' ELSE 'Active' END,
                       requests.requested_at
                FROM password_reset_requests AS requests
                JOIN users ON users.id = requests.user_id
                WHERE requests.status = 'pending'
                ORDER BY requests.requested_at, requests.id
                """
            ).fetchall()
        return [tuple(row) for row in rows]

    def review_password_reset(
        self, administrator_id: int, request_id: int, approve: bool
    ) -> AuthResult:
        if not self._is_active_admin(administrator_id):
            return AuthResult(False, "Administrator authorization is required.")

        with self.database.connect() as connection:
            request = connection.execute(
                """
                SELECT requests.user_id, requests.new_password_hash,
                       requests.status, users.username
                FROM password_reset_requests AS requests
                JOIN users ON users.id = requests.user_id
                WHERE requests.id = ?
                """,
                (request_id,),
            ).fetchone()
            if request is None or request["status"] != "pending":
                return AuthResult(False, "That reset request is no longer pending.")

            decision = "approved" if approve else "rejected"
            if approve:
                connection.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, invalid_attempts = 0, is_locked = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (request["new_password_hash"], request["user_id"]),
                )
            connection.execute(
                """
                UPDATE password_reset_requests
                SET status = ?, reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
                WHERE id = ?
                """,
                (decision, administrator_id, request_id),
            )

        logger.info(
            "Password-reset request %s for %s by administrator",
            decision,
            request["username"],
        )
        if approve:
            return AuthResult(
                True,
                f"Password reset approved for '{request['username']}'. The account is unlocked.",
            )
        return AuthResult(
            True,
            f"Password reset rejected for '{request['username']}'.",
        )

    def _is_active_admin(self, user_id: int) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM users
                WHERE id = ? AND role = 'admin' AND is_locked = 0
                """,
                (user_id,),
            ).fetchone()
        return row is not None
