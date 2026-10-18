# Localhost Development Setup

The Computer Engineering frontend is served by FastAPI on localhost. Accounts,
roles, local question edits, requests, and student mock results use a local
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
Enter an 8–30 character username, valid email format, and an 8–12 character
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

The administrator generator assembles a temporary, reviewable set on its own
page. It does not open the answer-taking exam, save results, or publish a set
to students. Admin and Examiner accounts cannot access exam-taking pages.
Set publishing is not implemented.

The student generator uses the draft TOS weights in `js/data.js`: five domain
weights and four cognitive-level weights for each discipline, plus the chosen
Easy/Medium/Hard profile. Students choose 1–200 questions; 1–10 is an unsaved
practice drill, while larger sets are scored as mock exams. Whole-question
quotas use largest-remainder rounding. The generator checks all three margins
against the question bank and refuses an impossible mix instead of silently
substituting questions. Some combinations, especially Easy-heavy profiles,
are unavailable because the imported bank's difficulty and cognitive tags
are correlated. The on-page TOS preview shows targets, not a feasibility
guarantee; feasibility is checked when the student generates the set.

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
