# Localhost Development Setup

The Computer Engineering frontend is served by FastAPI on localhost. Accounts,
roles, questions, requests, and student mock results now use a local SQLite
database. Guest practice is anonymous and never creates a user or saved score.

## First-time setup

Double-click `setup.bat`, or run it from PowerShell:

```powershell
.\setup.bat
```

PowerShell activation is not required. The scripts call the virtual
environment's Python executable directly.

## Create the first administrator

After setup, run `create-admin.bat` (or `.\.venv\Scripts\python.exe manage.py`).
Enter an 8–30 character username, valid email format, and an 8–12 character
password containing a letter, uppercase letter, number, and special character.
This local-only command works once. Public registration always creates a
Student account; the administrator can assign Examiner or Admin roles from
`admin-accounts.html`.

## Start the application

```powershell
.\run.bat
```

Then open:

- Application: http://127.0.0.1:8000
- Backend health check: http://127.0.0.1:8000/api/health
- Interactive API documentation: http://127.0.0.1:8000/api/docs

Stop the server by pressing `Ctrl+C` in its terminal window.

## Current boundary

At this milestone, the server stores password hashes (not passwords) and uses
an HttpOnly session cookie. Three failed logins lock an account. The
administrator can unlock it or review a proposed password reset. A reset
request does **not** verify email ownership; the administrator must confirm
identity outside the app before approval. Email syntax is checked, but no
verification email is sent.

The database is created in `data/cpedle.sqlite3` and is ignored by Git.
The six built-in questions are illustrative placeholders; the group question
bank can be imported later. The app does not import accounts or data from the
older Tkinter app or browser `localStorage`.

The frontend's six disciplines and 30 domains are defined in `js/data.js`;
the backend validates the same taxonomy in `backend.py`. Guest practice
results exist only in the current browser tab's session storage to display the
score, and are not written to SQLite.

This is a localhost prototype. Before deployment, add verified email-based
recovery, production session/CSRF review, audit logging, database migrations,
and server-controlled exam delivery.

## Checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_access.py"
node --test tests/taxonomy.test.js tests/auth-ui.test.js
```
