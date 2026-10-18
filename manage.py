"""Local-only administrator setup and recovery; never expose this over HTTP."""

import getpass
import sys

from backend import create_initial_admin, initialize, reset_admin_password_local


if __name__ == "__main__":
    initialize()
    if sys.argv[1:] == ["--reset-admin-password"]:
        print("Reset an existing administrator password on this computer.")
        identifier = input("Administrator username or email: ").strip()
        password = getpass.getpass("New password: ")
        confirm = getpass.getpass("Confirm new password: ")
        if password != confirm:
            raise SystemExit("Passwords do not match.")
        try:
            username = reset_admin_password_local(identifier, password)
        except Exception as error:
            raise SystemExit(str(error)) from error
        print(f"Password reset for '{username}'. Existing sessions were signed out.")
    elif not sys.argv[1:]:
        print("Create the initial administrator (available only once).")
        username = input("Username: ").strip()
        email = input("Email: ").strip()
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise SystemExit("Passwords do not match.")
        try:
            create_initial_admin(username, email, password)
        except Exception as error:
            raise SystemExit(str(error)) from error
        print("Administrator created. You can now sign in on localhost.")
    else:
        raise SystemExit("Usage: manage.py [--reset-admin-password]")
