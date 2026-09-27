# Login, Register, Forgot Password, and Account Recovery

## Included

- Separate login and registration screens
- Login with either username or email address
- Forgot Password requests with administrator approval or rejection
- First-run administrator creation (no hard-coded administrator password)
- Username validation: 8-30 letters, numbers, or underscores
- Case-insensitive duplicate username detection
- Email validation and case-insensitive duplicate detection
- Password and confirm-password fields
- Live check/cross indicators inside hoverable `?` help panels
- Passwords require 8-12 characters, a letter, an uppercase letter, a number,
  and a special character
- Gray disabled Login button until both credentials are entered, and a gray
  disabled Register button until the new-account form meets the current policy
- Inline validation, duplicate-account, and authentication messages
- Show-password checkbox
- Password hashing with bcrypt (plain-text passwords are never stored)
- Three-attempt account lockout
- Administrator dashboard for unlocking accounts
- Approved reset requests replace the password hash and unlock the account;
  rejected requests leave the existing password and lock state unchanged
- SQLite database and central file logging
- Safe migration support for the earlier basic `users` table

## Requirements

- Python 3.10 or newer (with Tkinter)
- Packages in `requirements.txt`

## Setup and run (Windows PowerShell)

The easiest option is to double-click `setup.bat` once, then double-click
`run.bat` whenever you want to launch the app.

The equivalent PowerShell commands are:

```powershell
cd "path\to\licensure_exam_app"
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py main.py
```

After the dependencies are installed, `run.bat` can also launch the app.

On the first launch, create the initial administrator. Later launches open the
normal login screen. A reviewee account locks on its third consecutive invalid
password attempt and is redirected to **Forgot Password**. The reviewee submits
a proposed new password, then an administrator reviews it under **Password Reset
Requests**. Approval changes the password and unlocks the account. Administrators
can also unlock an account without changing its password under **Locked Accounts**.

## Project structure

```text
licensure_exam_app/
├── controllers/
│   └── auth_controller.py
├── models/
│   ├── database.py
│   └── schemas.py
├── views/
│   └── auth_view.py
├── tests/
│   └── test_auth.py
├── logger.py
├── main.py
├── requirements.txt
└── run.bat
```

Runtime data is created automatically:

- Database: `data/licensure_exam.db`
- Log file: `app_logging/app.log`
