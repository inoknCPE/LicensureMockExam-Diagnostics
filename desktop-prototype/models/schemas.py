import re

from pydantic import BaseModel, field_validator


SPECIAL_CHARACTERS = "!@#$%^&*()_+-=[]{};:'\"\\|,.<>/?`~"


def password_requirements(password: str) -> dict[str, bool]:
    """Return the same password rules used by both the UI and backend."""
    return {
        "8-12 characters": 8 <= len(password) <= 12,
        "At least one letter (A-Z or a-z)": bool(re.search(r"[A-Za-z]", password)),
        "At least one uppercase letter (A-Z)": bool(re.search(r"[A-Z]", password)),
        "At least one number (0-9)": bool(re.search(r"[0-9]", password)),
        "At least one special character": any(
            character in SPECIAL_CHARACTERS for character in password
        ),
    }


def username_requirements(username: str) -> dict[str, bool]:
    value = username.strip()
    return {
        "At least 8 characters": len(value) >= 8,
        "No more than 30 characters": len(value) <= 30,
        "Only letters, numbers, and underscores": bool(
            re.fullmatch(r"[A-Za-z0-9_]+", value)
        ),
    }


def is_valid_email(email: str) -> bool:
    value = email.strip().lower()
    return len(value) <= 254 and bool(
        re.fullmatch(
            r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+",
            value,
        )
    )


class UserRegisterSchema(BaseModel):
    username: str
    email: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        failed = [
            requirement
            for requirement, passed in username_requirements(value).items()
            if not passed
        ]
        if failed:
            raise ValueError("Username requirement not met: " + failed[0] + ".")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not is_valid_email(value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        failed = [
            requirement
            for requirement, passed in password_requirements(value).items()
            if not passed
        ]
        if failed:
            raise ValueError("Password requirement not met: " + failed[0] + ".")
        return value
