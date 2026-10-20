# Localhost Development Setup

The Computer Engineering frontend is served by FastAPI on localhost. When
`SUPABASE_DB_URL` is set in the root `.env`, accounts, roles, question edits,
password-reset requests, and student mock results use Supabase PostgreSQL. If
it is not set, those records use the local SQLite database. When
`CPEDLE_ALLOW_OFFLINE_FALLBACK=true` is also set, a local app that cannot
connect to Supabase at startup switches to SQLite for that run. The question
bank comes from Supabase in cloud mode and from `databases/questionbank.db` in
local mode. Guest practice is anonymous and never creates a user or saved score.

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
This local-only command works once. Public registration creates Student
accounts or pending Examiner applications; only administrators can assign
Admin roles from `admin-accounts.html`.
Administrators go directly to the admin dashboard and cannot be sent to the
discipline profile page. Student and Examiner profiles require a discipline.
The Student/Examiner Profile page displays the saved sign-in email and lets
its owner correct it after entering the current password.

## Email verification with Brevo

New Student and Examiner registrations send a verification link through
Brevo's transactional email API over HTTPS. A Student cannot sign in before verifying. An Examiner can verify
their email while the application waits for administrator approval. Existing
accounts are treated as verified during the database migration.

1. In Brevo, add and verify the sender address you intend to use. For best
   deliverability, authenticate its sending domain if you control the DNS.
2. Create a Brevo **API key** with permission to send transactional emails.
   The app calls Brevo over HTTPS, so it does not need SMTP credentials.
3. In the ignored root `.env` file, set:

   ```dotenv
   BREVO_API_KEY=your_brevo_api_key
   BREVO_FROM_EMAIL=cpedle <your-verified-sender@example.com>
   PUBLIC_APP_URL=http://127.0.0.1:5000
   ```

   Replace these examples with your actual Brevo API key and verified sender
   address. Keep `.env` private; never commit or paste the API key into source
   code. The local URL works only when the email link is opened on the
   computer running the application.
4. Restart the app after changing `.env`, then register with an inbox you can
   access. The verification link expires after 24 hours. The verification
   page can request another link, with a one-minute cooldown per account.
5. For a deployed app, configure these same values in the hosting provider's
   environment-variable settings. Set `PUBLIC_APP_URL` to the app's public
   HTTPS origin (for example, `https://your-app.example.com`), not localhost.
   Do not commit `.env` or put the Brevo API key in browser JavaScript.
6. If the app uses Supabase, apply the new schema migration before deploying
   the code:

   ```powershell
   npx supabase db push
   ```

The HTTPS API works with Render's outbound network rules, including its
restriction on SMTP ports for Free web services. Check Brevo's transactional
email logs if a test message does not arrive.
Inbox delivery can be affected by domain reputation, recipient filtering, or
provider limits. A user can request a fresh link from the verification page
or the login/sign-up pages.

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

## Offline mode

For local development, set both `SUPABASE_DB_URL` and
`CPEDLE_ALLOW_OFFLINE_FALLBACK=true` in the ignored root `.env` file. The app
uses Supabase when it can connect at startup and otherwise logs that it has
switched to the local SQLite databases. Check `/api/health`: the `database`
value is `supabase`, `local`, or `local-offline-fallback`.

The selected database stays in use for the life of that server process. If
Supabase becomes unavailable after startup, stop and restart the local app to
select SQLite. Restart again when Supabase is available to return to it.
Writes made to SQLite while offline are **not** synchronized or merged into
Supabase; they remain on this computer. This fallback is for local offline use
only, not for Render. Do not set `CPEDLE_ALLOW_OFFLINE_FALLBACK` on Render,
whose service filesystem is ephemeral.

## Current boundary

At this milestone, the server stores password hashes (not passwords) and uses
an HttpOnly session cookie. Three failed logins lock an account. The
administrator can unlock it or review a proposed password reset. A reset
request does **not** verify email ownership; the administrator must confirm
identity outside the app before approval. New public registrations must verify
email ownership; existing accounts are grandfathered as verified.

The local accounts/results database is created automatically at
`databases/account_credential.sqlite3` and is ignored by Git. The committed
`databases/questionbank.db` fallback is opened read-only; its diagrams are
served from `static/images/`. It contains 1,200 questions across six
disciplines and supports five-choice, identification, and
combined-choice-or-written answers. Imported questions are labeled read-only
in the administrator/examiner bank view. Locally created questions remain
editable through the existing administrator approval workflow. The six
built-in demo questions remain available alongside the imported bank.
The app does not import accounts or data from the older Tkinter app or browser
`localStorage`.

## Preparing the application database for Supabase

The Supabase PostgreSQL schema is in
`supabase/migrations/20261020213000_create_application_schema.sql`. It enables
RLS and revokes Data API access from `anon` and `authenticated`; the FastAPI
backend is expected to connect with its private server-side PostgreSQL
connection string. No policies are defined for direct client access.

After installing the Supabase CLI and creating a Supabase project, link the
project and deploy the schema:

```powershell
npx supabase login
npx supabase link --project-ref YOUR_PROJECT_REF
npx supabase db push
```

Back up both local SQLite databases first. Preview the app and question-bank
row counts with:

```powershell
.\.venv\Scripts\python.exe scripts\import_sqlite_to_supabase.py
```

The importer refuses to write unless `--apply` is provided and all destination
application and question-bank tables are empty. It intentionally does not
copy session records, so users must sign in again after cutover. When applying,
it securely prompts for the database connection string copied from the
Supabase dashboard's **Connect** panel. Alternatively, place it in the ignored
root `.env` file as `SUPABASE_DB_URL=...`; do not commit or share that file.
Then run:

```powershell
.\.venv\Scripts\python.exe scripts\import_sqlite_to_supabase.py --apply
```

The importer loads the application tables and the question bank into the
`bank_*` PostgreSQL tables, but skips sessions. Once both Supabase migrations
are deployed and the import is verified, start the local app with
`SUPABASE_DB_URL` set in `.env`. The backend will use Supabase instead of the
local SQLite files. Keep those local files as backups until the remote app has
been tested thoroughly.

## Deploy to Render

After the app changes are committed and pushed to GitHub, create a Render
**Web Service** for the repository. Use the repository root as the root
directory, `pip install -r requirements.txt` as the build command, and:

```text
uvicorn server:app --host 0.0.0.0 --port $PORT
```

Set `SUPABASE_DB_URL` in the Render service's environment variables to the
private PostgreSQL connection string from Supabase's **Connect** panel. Keep
the value secret; do not use a Supabase anon/publishable key. Deploy the
migrations and import any needed SQLite data before the first web-service
deploy. Run `manage.py` locally with the Supabase URL configured if you need to
create the initial administrator in the cloud database.

Do not set `CPEDLE_ALLOW_OFFLINE_FALLBACK` on Render. The local SQLite fallback
is only for the local app and Render's filesystem is ephemeral. After deploy,
check `/api/health`; `database` should be `supabase`. Render's free web service
can spin down when idle, so its first request after inactivity may be slow.

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
