# Localhost Development Setup

The Computer Engineering frontend is served by FastAPI on localhost. Accounts,
roles, local question edits, password-reset requests, and student mock results use a local
SQLite database. The team's 1,200-question bank is read separately from
`data/questionbank.db`. Guest practice is anonymous and never creates a user
or saved score.

## First-time setup

Double-click `setup.bat`, or run it from PowerShell:

```powershell
.\setup.bat
```

PowerShell activation is not required. The scripts call the virtual
environment's Python executable directly.

## Create the first administrator

After setup, run `create-admin.bat` (or `.\.venv\Scripts\python.exe manage.py`).
Enter an 8–30 character username, valid email format, and an 8–30 character
password containing a letter, uppercase letter, number, and special character.
This local-only command works once. Public registration always creates a
Student account; the administrator can assign Examiner or Admin roles from
`admin-accounts.html`.
Administrators go directly to the admin dashboard and cannot be sent to the
discipline profile page. Student and Examiner profiles require a discipline.
The Student/Examiner Profile page displays the saved sign-in email and lets
its owner correct it after entering the current password. Email ownership
is still not verified.

Examiner additions, edits, and bulk imports go to an administrator approval
queue. They do not affect the active question bank until approved at
`admin-question-approvals.html`. Examiners cannot delete active questions.

Admin and Examiner accounts cannot generate or take exams. The fixed Mock Exam
issues each student a fresh 100-question, 60-minute set within their registered
discipline. It applies the approved domain × cognitive-level TOS weights, with
whole-question rounding, and refuses a shortage rather than silently changing
the required counts. Difficulty is observed, not a fixed quota for this exam.
There is no student-to-admin mock-set request or set-publishing flow.

The separate Practice Exam (`generator.html`) lets students choose any
combination of their discipline's five domains, 1–200 questions, 5–300 minutes,
and a difficulty target. It spreads questions as evenly as possible across the
selected domains and adjusts difficulty when the bank cannot meet the target.
Student practice results are saved in exam history but excluded from the admin
mock-exam roster. Guest practice drills remain limited to 10 questions and are
not saved.

Both the fixed Mock Licensure Exam and student-created Practice Exam now start
as server-tracked attempts. The server issues the deadline and stores answers
as the student works. At expiry, a background check finalizes the attempt from
answers already saved on the server, including if the browser was closed;
answers arriving after the deadline do not count. Exiting an exam before its
deadline discards the attempt and records no score. Guest drills remain
browser-only and are not part of this timed-attempt flow.

Students can print an individual diagnostic performance card from Results or
from any attempt in Exam History. The administrator's Reports tab provides a
filterable, printable cohort roster and per-attempt TOS compliance sheets.
The browser's print dialog can also save these as PDF. New mock attempts save
the server-calculated planned quotas and actual delivered question-tag counts;
older attempts and remediation drills have no planned TOS snapshot and are
marked unavailable rather than reconstructed. The TOS sheet is internal
distribution evidence, not an external accreditation certificate.

If you forget the only administrator's password, run
`reset-admin-password.bat` locally. It prompts for that administrator's
username or email and a new password, clears any lockout, and signs out
existing sessions. It does not delete accounts, questions, or results.
This developer-machine recovery command must not be exposed to web users.

## Start the application

```powershell
.\run.bat
```

Then open:

- Application: http://127.0.0.1:5000
- Backend health check: http://127.0.0.1:5000/api/health
- Interactive API documentation: http://127.0.0.1:5000/api/docs

Stop the server by pressing `Ctrl+C` in its terminal window.

## Current boundary

At this milestone, the server stores password hashes (not passwords) and uses
an HttpOnly session cookie. Three failed logins lock an account. The
administrator can unlock it or review a proposed password reset. A reset
request does **not** verify email ownership; the administrator must confirm
identity outside the app before approval. Email syntax is checked, but no
verification email is sent.

The accounts/results database is created in `data/cpedle.sqlite3` and is
ignored by Git. The team's committed `data/questionbank.db` is opened
read-only; its diagrams are served from `static/images/`. It contains 1,200
questions across six disciplines and supports five-choice, identification,
and combined-choice-or-written answers. Imported questions are labeled
read-only in the administrator/examiner bank view. Locally created questions
remain editable through the existing administrator approval workflow. The six
built-in demo questions remain available alongside the imported bank.
The app does not import accounts or data from the older Tkinter app or browser
`localStorage`.

The frontend's six disciplines and 30 domains are defined in `js/data.js`;
the backend validates the same taxonomy in `backend.py`. Guest practice
results exist only in the current browser tab's session storage to display the
score, and are not written to SQLite.

This is a localhost prototype. Before deployment, add verified email-based
recovery, production session/CSRF review, audit logging, database migrations,
and server-controlled exam delivery. The current client-side question
selection is suitable for the prototype, not for a high-stakes exam.
Editable system settings and assigned remediation scheduling are later
milestones; the current administrator pages cover accounts, roles, lockouts,
password requests, and examiner question approvals.

## Checks

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_access.py"
node --test tests/*.test.js
```
