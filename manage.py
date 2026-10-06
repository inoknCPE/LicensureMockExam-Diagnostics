"""Create the first administrator locally; never expose this over HTTP."""

import getpass

from backend import create_initial_admin, initialize


if __name__ == "__main__":
    initialize()
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
