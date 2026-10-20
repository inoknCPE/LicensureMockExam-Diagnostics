"""Direct backend tests; no HTTP test client dependency is required."""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi import Response
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("SUPABASE_DB_URL", None)
os.environ.pop("DATABASE_URL", None)
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import backend  # noqa: E402
from server import health_check, home_page, html_page  # noqa: E402

DEFAULT_DB_PATH = backend.DB_PATH


def request(cookie="", method="GET", csrf=""):
    headers = [(b"host", b"localhost")]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if csrf:
        headers.append((b"x-csrf-token", csrf.encode()))
    return Request({
        "type": "http", "method": method, "scheme": "http",
        "server": ("localhost", 80), "path": "/", "root_path": "",
        "query_string": b"", "headers": headers,
    })


class AccessTests(unittest.TestCase):
    def test_account_database_path_and_automatic_creation(self):
        self.assertEqual(
            DEFAULT_DB_PATH,
            ROOT / "databases" / "account_credential.sqlite3",
        )
        generated_path = Path(self.temp.name) / "databases" / "account_credential.sqlite3"
        with patch.object(backend, "DB_PATH", generated_path):
            backend.initialize()
        self.assertTrue(generated_path.is_file())

    def test_supabase_connection_failure_uses_local_database_when_enabled(self):
        local_path = Path(self.temp.name) / "offline.sqlite3"
        with (
            patch.object(backend, "DATABASE_URL", "postgresql://unavailable"),
            patch.object(backend, "LOCAL_FALLBACK_ENABLED", True),
            patch.object(backend, "USING_OFFLINE_FALLBACK", False),
            patch.object(backend, "DB_PATH", local_path),
            patch.object(
                backend.psycopg,
                "connect",
                side_effect=backend.psycopg.OperationalError("database unavailable"),
            ),
        ):
            backend.initialize()
            self.assertTrue(local_path.is_file())
            self.assertEqual(backend.DATABASE_URL, None)
            self.assertEqual(backend.database_mode(), "local-offline-fallback")
            self.assertEqual(
                health_check()["database"],
                "local-offline-fallback",
            )

    def test_supabase_connection_failure_still_fails_without_local_fallback(self):
        with (
            patch.object(backend, "DATABASE_URL", "postgresql://unavailable"),
            patch.object(backend, "LOCAL_FALLBACK_ENABLED", False),
            patch.object(
                backend.psycopg,
                "connect",
                side_effect=backend.psycopg.OperationalError("database unavailable"),
            ),
        ):
            with self.assertRaises(backend.psycopg.OperationalError):
                backend.initialize()

    def test_pages_are_served_from_pages_directory(self):
        self.assertEqual(Path(home_page().path), ROOT / "pages" / "index.html")
        self.assertEqual(Path(html_page("faq", request()).path), ROOT / "pages" / "faq.html")
        self.assertEqual(
            Path(html_page("verify-email", request()).path),
            ROOT / "pages" / "verify-email.html",
        )

    def test_password_length_allows_thirty_but_not_thirty_one_characters(self):
        backend.validate_password("A" + "a" * 27 + "@1")
        with self.assertRaises(HTTPException) as rejected:
            backend.validate_password("A" + "a" * 28 + "@1")
        self.assertEqual(rejected.exception.status_code, 422)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        backend.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        backend.initialize()
        backend.create_initial_admin("adminuser", "admin@example.com", "Admin@123")

    def tearDown(self):
        self.temp.cleanup()

    def register_student(self):
        with patch.object(backend, "send_verification_email") as send_email:
            backend.register(backend.RegisterIn(
                username="student01", email="student@example.com",
                password="Valid@123", confirm_password="Valid@123",
            ), request(method="POST"), Response())
        backend.verify_email(backend.VerifyEmailIn(token=send_email.call_args.args[1]),
                             request(method="POST"))
        response = Response()
        result = backend.login(backend.LoginIn(
            identifier="student@example.com", password="Valid@123",
        ), request(method="POST"), response)
        cookie = response.headers["set-cookie"].split(";", 1)[0]
        return result, cookie

    def login_admin(self):
        response = Response()
        result = backend.login(backend.LoginIn(
            identifier="admin@example.com", password="Admin@123",
        ), request(method="POST"), response)
        return result, response.headers["set-cookie"].split(";", 1)[0]

    def register_examiner(self, username="examiner01", license_number="PRC-12345"):
        with patch.object(backend, "send_verification_email") as send_email:
            result = backend.register_examiner(backend.ExaminerRegisterIn(
                username=username, email=f"{username}@example.com",
                password="Valid@123", confirm_password="Valid@123",
                name="Examiner Example", title="Licensed Professional Teacher",
                license_number=license_number,
            ), request(method="POST"))
        backend.verify_email(backend.VerifyEmailIn(token=send_email.call_args.args[1]),
                             request(method="POST"))
        return result

    def test_examiner_registration_requires_admin_approval(self):
        submitted = self.register_examiner()
        self.assertIn("administrator review", submitted["message"])
        with backend.db() as connection:
            row = connection.execute(
                "SELECT id,role,name,discipline,professional_title,license_number,examiner_status FROM users WHERE username=?",
                ("examiner01",),
            ).fetchone()
            examiner_id = row["id"]
            self.assertEqual((row["role"], row["name"], row["discipline"], row["professional_title"], row["license_number"], row["examiner_status"]),
                             ("EXAMINER", "Examiner Example", "", "Licensed Professional Teacher", "PRC-12345", "pending"))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions WHERE user_id=?", (examiner_id,)).fetchone()[0], 0)
        with self.assertRaises(HTTPException) as pending_login:
            backend.login(backend.LoginIn(identifier="examiner01", password="Valid@123"),
                          request(method="POST"), Response())
        self.assertEqual(pending_login.exception.status_code, 403)
        admin, cookie = self.login_admin()
        admin_user = backend.require_user(request(cookie))
        applications = backend.examiner_applications(admin_user)
        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0]["title"], "Licensed Professional Teacher")
        self.assertEqual(applications[0]["license_number"], "PRC-12345")
        self.assertNotIn("/api/admin/users/{user_id}/role", {route.path for route in backend.router.routes})
        backend.decide_examiner_application(examiner_id, backend.DecisionIn(approve=True), admin_user)
        self.assertEqual(backend.examiner_applications(admin_user), [])
        response = Response()
        result = backend.login(backend.LoginIn(identifier="examiner01", password="Valid@123"),
                               request(method="POST"), response)
        self.assertEqual(result["user"]["role"], "EXAMINER")
        self.assertEqual(result["user"]["professionalTitle"], "Licensed Professional Teacher")
        self.assertEqual(result["user"]["discipline"], "")
        self.assertIn("cpedle_session", response.headers["set-cookie"])

    def test_rejected_examiner_cannot_sign_in_and_license_is_unique(self):
        self.register_examiner()
        with self.assertRaises(HTTPException) as duplicate:
            self.register_examiner("examiner02", "prc-12345")
        self.assertEqual(duplicate.exception.status_code, 409)
        with backend.db() as connection:
            examiner_id = connection.execute("SELECT id FROM users WHERE username='examiner01'").fetchone()[0]
        _, cookie = self.login_admin()
        admin_user = backend.require_user(request(cookie))
        backend.decide_examiner_application(examiner_id, backend.DecisionIn(approve=False), admin_user)
        with self.assertRaises(HTTPException) as rejected_login:
            backend.login(backend.LoginIn(identifier="examiner01", password="Valid@123"),
                          request(method="POST"), Response())
        self.assertEqual(rejected_login.exception.status_code, 403)
        with self.assertRaises(HTTPException) as repeat:
            backend.decide_examiner_application(examiner_id, backend.DecisionIn(approve=True), admin_user)
        self.assertEqual(repeat.exception.status_code, 404)

    def test_guest_has_no_account_and_cannot_submit(self):
        guest = backend.bootstrap(request())
        self.assertIsNone(guest["user"])
        self.assertTrue(guest["questions"])
        self.assertNotIn("ans", guest["questions"][0])
        with backend.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        self.assertIsNone(backend.current_session(request()))
        with self.assertRaises(HTTPException) as error:
            backend.require_user(request(method="POST"))
        self.assertEqual(error.exception.status_code, 401)
        score = backend.practice_score(backend.ExamSubmission(
            title="Anonymous practice",
            answers=[backend.AnswerIn(id="CPE-NET-001", userAns=2)],
        ), request(method="POST"))
        self.assertEqual(score["scorePct"], 100)
        with self.assertRaises(HTTPException) as error:
            backend.practice_score(backend.ExamSubmission(
                title="Oversized anonymous drill",
                answers=[backend.AnswerIn(id="CPE-NET-001", userAns=2) for _ in range(11)],
            ), request(method="POST"))
        self.assertEqual(error.exception.status_code, 422)
        with backend.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exam_history").fetchone()[0], 0)

    def test_registration_and_server_role_guard(self):
        student, cookie = self.register_student()
        self.assertEqual(student["user"]["role"], "STUDENT")
        self.assertEqual(backend.current_session(request(cookie))[0]["role"], "STUDENT")
        with self.assertRaises(HTTPException) as error:
            html_page("admin-dashboard", request(cookie))
        self.assertEqual(error.exception.status_code, 403)
        with self.assertRaises(HTTPException) as approval_page:
            html_page("admin-question-approvals", request(cookie))
        self.assertEqual(approval_page.exception.status_code, 403)
        with self.assertRaises(HTTPException) as error:
            backend.register(backend.RegisterIn(
                username="STUDENT01", email="other@example.com",
                password="Valid@123", confirm_password="Valid@123",
            ), request(method="POST"), Response())
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException) as error:
            backend.register(backend.RegisterIn(
                username="student02", email="STUDENT@EXAMPLE.COM",
                password="Valid@123", confirm_password="Valid@123",
            ), request(method="POST"), Response())
        self.assertEqual(error.exception.status_code, 409)
        with self.assertRaises(HTTPException) as error:
            backend.require_user(request(cookie, method="POST"))
        self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(
            backend.require_user(request(cookie, method="POST", csrf=student["csrf"]))["role"],
            "STUDENT",
        )

    def test_student_registration_requires_single_use_email_verification(self):
        with patch.object(backend, "send_verification_email") as send_email:
            result = backend.register(backend.RegisterIn(
                username="student01", email="student@example.com",
                password="Valid@123", confirm_password="Valid@123",
            ), request(method="POST"), Response())
        self.assertIn("Check your email", result["message"])
        token = send_email.call_args.args[1]
        with backend.db() as connection:
            user = connection.execute(
                "SELECT id,email_verified FROM users WHERE username='student01'"
            ).fetchone()
            self.assertEqual(user["email_verified"], 0)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM sessions WHERE user_id=?", (user["id"],)
                ).fetchone()[0],
                0,
            )
        with self.assertRaises(HTTPException) as unverified_login:
            backend.login(backend.LoginIn(
                identifier="student01", password="Valid@123",
            ), request(method="POST"), Response())
        self.assertEqual(unverified_login.exception.status_code, 403)

        with backend.db() as connection:
            connection.execute(
                "UPDATE email_verification_tokens SET sent_at=? WHERE user_id=?",
                (int(time.time()) - 61, user["id"]),
            )
        with patch.object(backend, "send_verification_email") as resend:
            response = backend.resend_verification(
                backend.EmailVerificationResendIn(email="student@example.com"),
                request(method="POST"),
            )
        self.assertIn("If an unverified account exists", response["message"])
        fresh_token = resend.call_args.args[1]
        with self.assertRaises(HTTPException):
            backend.verify_email(backend.VerifyEmailIn(token=token), request(method="POST"))
        verified = backend.verify_email(
            backend.VerifyEmailIn(token=fresh_token), request(method="POST")
        )
        self.assertIn("Email verified", verified["message"])
        with self.assertRaises(HTTPException):
            backend.verify_email(
                backend.VerifyEmailIn(token=fresh_token), request(method="POST")
            )
        signed_in = backend.login(backend.LoginIn(
            identifier="student01", password="Valid@123",
        ), request(method="POST"), Response())
        self.assertEqual(signed_in["user"]["role"], "STUDENT")

    def test_failed_registration_send_allows_immediate_resend(self):
        with patch.object(
            backend,
            "send_verification_email",
            side_effect=HTTPException(502, "Provider rejected the request."),
        ):
            with self.assertRaises(HTTPException) as failed_send:
                backend.register(backend.RegisterIn(
                    username="student01", email="student@example.com",
                    password="Valid@123", confirm_password="Valid@123",
                ), request(method="POST"), Response())
        self.assertIn("account was created", failed_send.exception.detail.lower())
        self.assertIn("Resend it", failed_send.exception.detail)
        with backend.db() as connection:
            user_id, sent_at = connection.execute(
                """SELECT users.id,email_verification_tokens.sent_at
                   FROM users JOIN email_verification_tokens ON users.id=email_verification_tokens.user_id
                   WHERE users.username='student01'"""
            ).fetchone()
            self.assertEqual(sent_at, 0)
        with patch.object(backend, "send_verification_email") as resend:
            response = backend.resend_verification(
                backend.EmailVerificationResendIn(email="student@example.com"),
                request(method="POST"),
            )
        self.assertIn("If an unverified account exists", response["message"])
        resend.assert_called_once()
        self.assertEqual(resend.call_args.args[0], "student@example.com")
        with backend.db() as connection:
            saved_sent_at = connection.execute(
                "SELECT sent_at FROM email_verification_tokens WHERE user_id=?",
                (user_id,),
            ).fetchone()["sent_at"]
            self.assertGreater(saved_sent_at, 0)

    def test_failed_resend_does_not_start_cooldown(self):
        with patch.object(backend, "send_verification_email"):
            backend.register(backend.RegisterIn(
                username="student01", email="student@example.com",
                password="Valid@123", confirm_password="Valid@123",
            ), request(method="POST"), Response())
        with backend.db() as connection:
            user_id = connection.execute(
                "SELECT id FROM users WHERE username='student01'"
            ).fetchone()["id"]
            connection.execute(
                "UPDATE email_verification_tokens SET sent_at=? WHERE user_id=?",
                (int(time.time()) - 61, user_id),
            )
        with patch.object(
            backend,
            "send_verification_email",
            side_effect=HTTPException(502, "Provider rejected the request."),
        ):
            with self.assertRaises(HTTPException):
                backend.resend_verification(
                    backend.EmailVerificationResendIn(email="student@example.com"),
                    request(method="POST"),
                )
        with backend.db() as connection:
            sent_at = connection.execute(
                "SELECT sent_at FROM email_verification_tokens WHERE user_id=?",
                (user_id,),
            ).fetchone()["sent_at"]
            self.assertEqual(sent_at, 0)
        with patch.object(backend, "send_verification_email") as retry:
            backend.resend_verification(
                backend.EmailVerificationResendIn(email="student@example.com"),
                request(method="POST"),
            )
        retry.assert_called_once()

    def test_verification_links_expire(self):
        with patch.object(backend, "send_verification_email") as send_email:
            backend.register(backend.RegisterIn(
                username="student01", email="student@example.com",
                password="Valid@123", confirm_password="Valid@123",
            ), request(method="POST"), Response())
        token = send_email.call_args.args[1]
        with backend.db() as connection:
            connection.execute(
                "UPDATE email_verification_tokens SET expires_at=?",
                (int(time.time()) - 1,),
            )
        with self.assertRaises(HTTPException) as expired:
            backend.verify_email(
                backend.VerifyEmailIn(token=token), request(method="POST")
            )
        self.assertEqual(expired.exception.status_code, 400)
        with backend.db() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT email_verified FROM users WHERE username='student01'"
                ).fetchone()["email_verified"],
                0,
            )

    def test_brevo_api_sends_verification_message_using_configured_sender(self):
        class AcceptedResponse:
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        with (
            patch.dict("os.environ", {
                "BREVO_API_KEY": "brevo-api-secret",
                "BREVO_FROM_EMAIL": "cpedle <no-reply@example.com>",
                "PUBLIC_APP_URL": "https://cpedle.example.com/",
            }),
            patch.object(backend, "urlopen", return_value=AcceptedResponse()) as send,
        ):
            backend.send_verification_email("student@example.com", "opaque-token")
        outbound = send.call_args.args[0]
        self.assertEqual(outbound.full_url, "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(outbound.get_header("Api-key"), "brevo-api-secret")
        payload = json.loads(outbound.data)
        self.assertEqual(payload["sender"], {"name": "cpedle", "email": "no-reply@example.com"})
        self.assertEqual(payload["to"], [{"email": "student@example.com"}])
        self.assertEqual(payload["subject"], "Verify your cpedle email address")
        self.assertIn(
            "https://cpedle.example.com/verify-email.html#token=opaque-token",
            payload["htmlContent"],
        )

    def test_brevo_api_error_logs_provider_code_and_message(self):
        error = backend.HTTPError(
            "https://api.brevo.com/v3/smtp/email",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"code":"unauthorized","message":"Invalid API key"}'),
        )
        with self.assertLogs(level="ERROR") as logs:
            backend._log_brevo_error(error)
        self.assertIn("HTTP 401", logs.output[0])
        self.assertIn("unauthorized", logs.output[0])
        self.assertIn("Invalid API key", logs.output[0])
        error.close()

    def test_three_failures_lock_and_admin_reset_approval(self):
        self.register_student()
        for attempt in range(3):
            with self.assertRaises(HTTPException) as error:
                backend.login(backend.LoginIn(
                    identifier="STUDENT01", password="Wrong@123",
                ), request(method="POST"), Response())
            self.assertEqual(error.exception.status_code, 423 if attempt == 2 else 401)
        with self.assertRaises(HTTPException) as error:
            backend.login(backend.LoginIn(
                identifier="student01", password="Valid@123",
            ), request(method="POST"), Response())
        self.assertEqual(error.exception.status_code, 423)
        backend.request_reset(backend.ResetIn(
            identifier="student@example.com",
            password="Newpass@1", confirm_password="Newpass@1",
        ), request(method="POST"))
        admin, cookie = self.login_admin()
        admin_user = backend.require_user(request(cookie))
        pending = backend.pending_resets(admin_user)
        self.assertEqual(len(pending), 1)
        backend.decide_reset(
            pending[0]["id"], backend.DecisionIn(approve=True), admin_user)
        result = backend.login(backend.LoginIn(
            identifier="student01", password="Newpass@1",
        ), request(method="POST"), Response())
        self.assertEqual(result["user"]["role"], "STUDENT")

    def test_examiner_questions_require_admin_approval(self):
        student, _ = self.register_student()
        admin, cookie = self.login_admin()
        admin_user = backend.require_user(request(cookie))
        with self.assertRaises(HTTPException):
            backend.role_required("ADMIN")(user=student["user"])
        self.register_examiner()
        with backend.db() as connection:
            examiner_id = connection.execute("SELECT id FROM users WHERE username='examiner01'").fetchone()[0]
        backend.decide_examiner_application(examiner_id, backend.DecisionIn(approve=True), admin_user)
        response = Response()
        examiner = backend.login(backend.LoginIn(
            identifier="examiner01", password="Valid@123",
        ), request(method="POST"), response)
        self.assertEqual(examiner["user"]["role"], "EXAMINER")
        examiner_cookie = response.headers["set-cookie"].split(";", 1)[0]
        self.assertEqual(html_page("examiner-question-submissions", request(examiner_cookie)).status_code, 200)
        with self.assertRaises(HTTPException) as admin_page:
            html_page("examiner-question-submissions", request(cookie))
        self.assertEqual(admin_page.exception.status_code, 403)
        proposal = backend.add_question(backend.QuestionIn(
            q="What does DNS resolve?",
            opts=["Names", "Voltages", "Threads", "Files"], ans=0,
            domain="Networking Fundamentals", cognitive="Understand",
            difficulty="Easy",
        ), examiner["user"])
        self.assertTrue(proposal["pending"])
        self.assertEqual(backend.question_change_requests(examiner["user"])[0]["status"], "pending")
        with backend.db() as connection:
            self.assertIsNone(connection.execute(
                "SELECT id FROM questions WHERE id=?", (proposal["id"],)).fetchone())
        pending = backend.question_change_requests(admin_user)
        self.assertEqual(len(pending), 1)
        backend.decide_question_change(
            proposal["request_id"], backend.QuestionDecisionIn(approve=True), admin_user)
        self.assertEqual(backend.question_change_requests(examiner["user"])[0]["status"], "approved")
        with backend.db() as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT id FROM questions WHERE id=?", (proposal["id"],)).fetchone())
        edit = backend.edit_question(proposal["id"], backend.QuestionIn(
            id=proposal["id"], q="Which name does DNS resolve?",
            opts=["Names", "Voltages", "Threads", "Files"], ans=0,
            domain="Networking Fundamentals", cognitive="Understand", difficulty="Easy",
        ), examiner["user"])
        self.assertTrue(edit["pending"])
        with self.assertRaises(HTTPException) as missing_reason:
            backend.decide_question_change(
                edit["request_id"], backend.QuestionDecisionIn(approve=False), admin_user)
        self.assertEqual(missing_reason.exception.status_code, 422)
        backend.decide_question_change(
            edit["request_id"], backend.QuestionDecisionIn(approve=False, reason="Incorrect explanation"), admin_user)
        rejected = next(item for item in backend.question_change_requests(examiner["user"])
                        if item["id"] == edit["request_id"])
        self.assertEqual(rejected["rejection_reason"], "Incorrect explanation")
        with backend.db() as connection:
            self.assertEqual(connection.execute(
                "SELECT q FROM questions WHERE id=?", (proposal["id"],)).fetchone()[0],
                "What does DNS resolve?")
        with self.assertRaises(HTTPException):
            backend.role_required("ADMIN")(user=examiner["user"])
        imported = backend.import_questions([backend.QuestionIn(
            q="Which protocol resolves hostnames?",
            opts=["DNS", "HTTP", "TCP", "UDP"], ans=0,
            domain="Networking Fundamentals", cognitive="Remember", difficulty="Easy",
        )], examiner["user"])
        self.assertEqual(imported, {"added": 0, "pending": 1})
        with backend.db() as connection:
            self.assertIsNone(connection.execute(
                "SELECT id FROM questions WHERE q='Which protocol resolves hostnames?'"
            ).fetchone())

        deletion = backend.delete_question(proposal["id"], examiner["user"])
        self.assertTrue(deletion["pending"])
        with backend.db() as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT id FROM questions WHERE id=?", (proposal["id"],)
            ).fetchone())
        backend.decide_question_change(
            deletion["request_id"], backend.QuestionDecisionIn(approve=False, reason="Retain this item"), admin_user)
        with backend.db() as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT id FROM questions WHERE id=?", (proposal["id"],)
            ).fetchone())
        deletion = backend.delete_question(proposal["id"], examiner["user"])
        backend.decide_question_change(
            deletion["request_id"], backend.QuestionDecisionIn(approve=True), admin_user)
        with backend.db() as connection:
            self.assertIsNone(connection.execute(
                "SELECT id FROM questions WHERE id=?", (proposal["id"],)
            ).fetchone())
        imported_item = next(q for q in backend.imported_questions(True) if q["id"] == "QB-1")
        imported_edit = backend.QuestionIn(**{
            key: imported_item[key] for key in
            ("id", "q", "opts", "ans", "answerText", "domain", "cognitive",
             "difficulty", "explanation", "questionType")
        })
        imported_edit.q = "Updated imported question?"
        proposal = backend.edit_question("QB-1", imported_edit, examiner["user"])
        self.assertTrue(proposal["pending"])
        self.assertEqual(next(q for q in backend.imported_questions(True) if q["id"] == "QB-1")["q"],
                         imported_item["q"])
        backend.decide_question_change(
            proposal["request_id"], backend.QuestionDecisionIn(approve=True), admin_user)
        self.assertEqual(next(q for q in backend.imported_questions(True) if q["id"] == "QB-1")["q"],
                         "Updated imported question?")
        removal = backend.delete_question("QB-1", examiner["user"])
        self.assertTrue(removal["pending"])
        self.assertTrue(any(q["id"] == "QB-1" for q in backend.imported_questions()))
        backend.decide_question_change(
            removal["request_id"], backend.QuestionDecisionIn(approve=True), admin_user)
        self.assertFalse(any(q["id"] == "QB-1" for q in backend.imported_questions()))
        self.assertEqual(backend.delete_question("QB-2", admin_user), {"ok": True})
        self.assertFalse(any(q["id"] == "QB-2" for q in backend.imported_questions()))
        direct = backend.add_question(backend.QuestionIn(
            q="Direct admin item", opts=["A", "B", "C", "D"], ans=0,
            domain="Networking Fundamentals", cognitive="Remember", difficulty="Easy",
        ), admin_user)
        self.assertEqual(backend.delete_question(direct["id"], admin_user), {"ok": True})
        with backend.db() as connection:
            self.assertIsNone(connection.execute(
                "SELECT id FROM questions WHERE id=?", (direct["id"],)
            ).fetchone())

    def test_admin_profile_needs_no_discipline_and_student_discipline_is_fixed(self):
        admin, cookie = self.login_admin()
        profile_page = html_page("profile", request(cookie))
        self.assertEqual(profile_page.status_code, 303)
        self.assertEqual(profile_page.headers["location"], "/admin-dashboard.html")
        saved = backend.save_profile(backend.ProfileIn(
            name="System Administrator", discipline=""), admin["user"])
        self.assertEqual(saved["user"]["discipline"], "")
        student, _ = self.register_student()
        with self.assertRaises(HTTPException) as invalid_student:
            backend.save_profile(backend.ProfileIn(
                name="Student Name", discipline=""), student["user"])
        self.assertEqual(invalid_student.exception.status_code, 422)
        assigned = backend.save_profile(backend.ProfileIn(
            name="Student Name", discipline="Network Engineer"), student["user"])["user"]
        with self.assertRaises(HTTPException) as changed:
            backend.save_profile(backend.ProfileIn(
                name="Student Name", discipline="Software Developer"), assigned)
        self.assertEqual(changed.exception.status_code, 409)
        self.assertNotIn("/api/profile/email", {route.path for route in backend.router.routes})

    def test_student_and_examiner_accounts_can_be_locked_and_unlocked(self):
        student, student_cookie = self.register_student()
        self.register_examiner()
        _, admin_cookie = self.login_admin()
        admin_user = backend.require_user(request(admin_cookie))
        with backend.db() as connection:
            examiner_id = connection.execute("SELECT id FROM users WHERE username='examiner01'").fetchone()[0]
        backend.decide_examiner_application(examiner_id, backend.DecisionIn(approve=True), admin_user)
        users = backend.admin_users(admin_user)
        examiner = next(item for item in users if item["id"] == examiner_id)
        self.assertEqual(examiner["professional_title"], "Licensed Professional Teacher")
        self.assertEqual(examiner["license_number"], "PRC-12345")
        for user_id, username in [(student["user"]["id"], "student01"), (examiner_id, "examiner01")]:
            backend.lock_user(user_id, admin_user)
            with self.assertRaises(HTTPException) as locked:
                backend.login(backend.LoginIn(identifier=username, password="Valid@123"),
                              request(method="POST"), Response())
            self.assertEqual(locked.exception.status_code, 423)
            backend.unlock(user_id, admin_user)
            self.assertEqual(backend.login(backend.LoginIn(identifier=username, password="Valid@123"),
                                           request(method="POST"), Response())["user"]["username"], username)
        with self.assertRaises(HTTPException):
            backend.lock_user(admin_user["id"], admin_user)
        with self.assertRaises(HTTPException):
            backend.require_user(request(student_cookie))  # Locking revoked the old session.

    def test_student_can_change_password_with_current_password_only(self):
        student, cookie = self.register_student()
        with self.assertRaises(HTTPException) as wrong:
            backend.change_own_password(backend.PasswordChangeIn(
                current_password="Wrong@123", new_password="Updated@1", confirm_password="Updated@1"),
                request(cookie, method="PUT"), student["user"])
        self.assertEqual(wrong.exception.status_code, 403)
        with self.assertRaises(HTTPException) as mismatch:
            backend.change_own_password(backend.PasswordChangeIn(
                current_password="Valid@123", new_password="Updated@1", confirm_password="Updated@2"),
                request(cookie, method="PUT"), student["user"])
        self.assertEqual(mismatch.exception.status_code, 422)
        backend.change_own_password(backend.PasswordChangeIn(
            current_password="Valid@123", new_password="Updated@1", confirm_password="Updated@1"),
            request(cookie, method="PUT"), student["user"])
        with self.assertRaises(HTTPException):
            backend.login(backend.LoginIn(identifier="student01", password="Valid@123"),
                          request(method="POST"), Response())
        self.assertEqual(backend.login(backend.LoginIn(identifier="student01", password="Updated@1"),
                                       request(method="POST"), Response())["user"]["role"], "STUDENT")

    def test_admin_cannot_open_exam_or_results_pages(self):
        _, cookie = self.login_admin()
        for page in ("exam", "results"):
            with self.subTest(page=page), self.assertRaises(HTTPException) as error:
                html_page(page, request(cookie))
            self.assertEqual(error.exception.status_code, 403)
        self.assertEqual(html_page("exam", request()).status_code, 200)

    def test_mock_set_request_and_admin_generation_routes_are_retired(self):
        student, student_cookie = self.register_student()
        _, admin_cookie = self.login_admin()
        for page, cookie in (("admin-generator", admin_cookie),
                             ("admin-requests", admin_cookie),
                             ("request-form", student_cookie)):
            with self.subTest(page=page), self.assertRaises(HTTPException) as error:
                html_page(page, request(cookie))
            self.assertEqual(error.exception.status_code, 404)
        paths = {route.path for route in backend.router.routes}
        self.assertNotIn("/api/requests", paths)
        self.assertNotIn("/api/admin/requests/{request_id}", paths)
        self.assertIn("/api/admin/reset-requests", paths)
        self.assertEqual(student["user"]["role"], "STUDENT")

    def test_student_mock_score_is_saved_by_server(self):
        student, _ = self.register_student()
        student_user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        result = backend.submit_exam(backend.ExamSubmission(
            title="Network mock",
            answers=[backend.AnswerIn(id="CPE-NET-001", userAns=2)],
        ), student_user)
        self.assertEqual(result["scorePct"], 100)
        with backend.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exam_history").fetchone()[0], 1)

        card = backend.exam_report(result["id"], student_user)
        self.assertEqual(card["studentName"], "Network Student")
        self.assertEqual(card["domains"][0]["scorePct"], 100)
        self.assertIsNone(card["report"])
        admin, _ = self.login_admin()
        admin_report = backend.exam_report(result["id"], admin["user"])
        self.assertEqual(admin_report["report"]["status"], "unavailable")
        self.assertEqual(backend.cohort_roster(admin["user"])[0]["mode"], "unclassified")

        with self.assertRaises(HTTPException) as wrong_discipline:
            backend.submit_exam(backend.ExamSubmission(
                title="Operations mock",
                answers=[backend.AnswerIn(id="CPE-OPS-001", userAns=0)],
            ), student_user)
        self.assertEqual(wrong_discipline.exception.status_code, 403)
        with backend.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exam_history").fetchone()[0], 1)

    def test_old_history_schema_is_migrated_without_losing_attempts(self):
        with backend.db() as connection:
            connection.execute("DROP TABLE exam_history")
            connection.execute("""CREATE TABLE exam_history (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL,
                score_pct INTEGER NOT NULL, total_items INTEGER NOT NULL,
                correct_items INTEGER NOT NULL, domains_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            connection.execute("""INSERT INTO exam_history(user_id,title,score_pct,total_items,
                              correct_items,domains_json) VALUES(1,'Old mock',50,2,1,'[]')""")
        backend.initialize()
        with backend.db() as connection:
            row = connection.execute("SELECT title,report_json FROM exam_history").fetchone()
        self.assertEqual(row["title"], "Old mock")
        self.assertIsNone(row["report_json"])

    def test_old_question_queue_is_migrated_without_losing_requests(self):
        import json
        admin, _ = self.login_admin()
        with backend.db() as connection:
            connection.execute("DROP TABLE question_change_requests")
            connection.execute("""CREATE TABLE question_change_requests (
                id INTEGER PRIMARY KEY, proposer_id INTEGER NOT NULL REFERENCES users(id),
                action TEXT NOT NULL CHECK(action IN ('ADD','EDIT')),
                target_question_id TEXT, payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT, reviewed_by INTEGER REFERENCES users(id))""")
            connection.execute("""INSERT INTO question_change_requests
                (proposer_id,action,payload_json) VALUES(?,?,?)""", (
                admin["user"]["id"], "ADD", json.dumps({
                    "q": "A saved proposal", "opts": ["A", "B", "C", "D"], "ans": 0,
                    "domain": "Networking Fundamentals", "cognitive": "Remember",
                    "difficulty": "Easy", "explanation": ""
                })
            ))
        backend.initialize()
        with backend.db() as connection:
            rows = connection.execute("SELECT action,payload_json FROM question_change_requests").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action"], "ADD")
            self.assertEqual(json.loads(rows[0]["payload_json"])["q"], "A saved proposal")
            schema = connection.execute("SELECT sql FROM sqlite_master WHERE name='question_change_requests'").fetchone()[0]
            self.assertIn("'DELETE'", schema)

    def test_tos_sheet_marks_exact_and_mismatched_distributions(self):
        user = {"name": "Network Student", "discipline": "Network Engineer"}
        payload = backend.ExamSubmission(
            title="Network mock", scope="Network Engineer", difficulty_weights=[30, 50, 20],
            answers=[backend.AnswerIn(id="CPE-NET-001")],
        )
        actual = {
            "domains": dict(zip(backend.DISCIPLINES["Network Engineer"], [3, 4, 5, 5, 3])),
            "cognitive": dict(zip(backend.COGNITIVE_ORDER, [3, 4, 7, 6])),
            "difficulty": {"Easy": 6, "Medium": 10, "Hard": 4},
        }
        report = backend.build_exam_report(payload, user, {"totalItems": 20, "distribution": actual})
        self.assertEqual(report["status"], "met")
        actual["difficulty"] = {"Easy": 6, "Medium": 9, "Hard": 5}
        report = backend.build_exam_report(payload, user, {"totalItems": 20, "distribution": actual})
        self.assertEqual(report["status"], "not_met")

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_printable_tos_snapshot_and_report_access(self):
        student, cookie = self.register_student()
        user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        question_ids = [q["id"] for q in backend.imported_questions()
                        if q["domain"] in backend.DISCIPLINES["Network Engineer"]][:11]
        saved = backend.submit_exam(backend.ExamSubmission(
            title="TOS mock", scope="Network Engineer", difficulty_weights=[30, 50, 20],
            answers=[backend.AnswerIn(id=question_id) for question_id in question_ids],
        ), user)
        own = backend.exam_report(saved["id"], user)
        self.assertIsNone(own["report"])
        admin, _ = self.login_admin()
        report = backend.exam_report(saved["id"], admin["user"])["report"]
        self.assertEqual(sum(report["planned"]["domains"].values()), 11)
        self.assertEqual(sum(report["planned"]["cognitive"].values()), 11)
        self.assertEqual(sum(report["actual"]["difficulty"].values()), 11)
        self.assertIn(report["status"], {"met", "not_met"})
        self.assertEqual(backend.cohort_roster(admin["user"])[0]["mode"], "mock")
        _, admin_cookie = self.login_admin()
        self.assertEqual(html_page("admin-reports", request(admin_cookie)).status_code, 200)
        with self.assertRaises(HTTPException) as denied:
            html_page("admin-reports", request(cookie))
        self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(html_page("print-report", request(cookie)).status_code, 200)
        with self.assertRaises(HTTPException) as invalid:
            backend.submit_exam(backend.ExamSubmission(
                title="Bad scope", scope="Software Developer", difficulty_weights=[30, 50, 20],
                answers=[backend.AnswerIn(id=question_id) for question_id in question_ids],
            ), user)
        self.assertEqual(invalid.exception.status_code, 422)

        # A second student cannot retrieve someone else's performance card.
        with backend.db() as connection:
            connection.execute("""INSERT INTO users(username,email,password_hash,role,name,discipline)
                              VALUES('student02','student02@example.com','test','STUDENT',
                                     'Other Student','Network Engineer')""")
            other_id = connection.execute("SELECT id FROM users WHERE username='student02'").fetchone()[0]
        with self.assertRaises(HTTPException) as hidden:
            backend.exam_report(saved["id"], {"id": other_id, "role": "STUDENT"})
        self.assertEqual(hidden.exception.status_code, 404)

    def test_student_needs_discipline_before_saving_mock(self):
        student, _ = self.register_student()
        with self.assertRaises(HTTPException) as missing_profile:
            backend.submit_exam(backend.ExamSubmission(
                title="Network mock",
                answers=[backend.AnswerIn(id="CPE-NET-001", userAns=2)],
            ), student["user"])
        self.assertEqual(missing_profile.exception.status_code, 403)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_student_practice_records_only_selected_profile_domains(self):
        student, cookie = self.register_student()
        user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        selected = ["Networking Fundamentals", "Network Security"]
        questions = backend.imported_questions()
        answers = [backend.AnswerIn(id=next(q["id"] for q in questions if q["domain"] == domain))
                   for domain in selected]
        payload = backend.ExamSubmission(
            title="Practice Exam", mode="student_practice", selected_domains=selected,
            answers=answers)
        started = backend.start_practice_exam(backend.PracticeAttemptIn(
            question_ids=[answer.id for answer in answers], selected_domains=selected,
            time_minutes=20), user)
        payload.attempt_id = started["attemptId"]
        saved = backend.submit_exam(payload, user)
        self.assertEqual(saved["title"], "Network Engineer Practice Exam (2 domains)")
        self.assertEqual({item["name"] for item in saved["domains"]}, set(selected))
        self.assertEqual(backend.bootstrap(request(cookie))["history"][0]["mode"], "practice")
        with self.assertRaises(HTTPException) as foreign:
            backend.submit_exam(backend.ExamSubmission(
                title="Practice", mode="student_practice",
                selected_domains=[selected[0], "Memory Management"], answers=answers), user)
        self.assertEqual(foreign.exception.status_code, 422)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_practice_deadline_uses_only_answers_saved_before_expiry(self):
        student, _ = self.register_student()
        user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        questions = [item for item in backend.imported_questions(True)
                     if item["domain"] == "Networking Fundamentals" and
                     item["questionType"] == "multiple_choice"][:2]
        now = int(time.time())
        with patch.object(backend.time, "time", return_value=now):
            started = backend.start_practice_exam(backend.PracticeAttemptIn(
                question_ids=[item["id"] for item in questions],
                selected_domains=["Networking Fundamentals"], time_minutes=5), user)
            saved = backend.save_exam_answers(started["attemptId"], backend.AttemptAnswersIn(
                answers=[backend.AnswerIn(id=questions[0]["id"], userAns=questions[0]["ans"])]), user)
            self.assertTrue(saved["saved"])
        with patch.object(backend.time, "time", return_value=now + 301):
            late = backend.save_exam_answers(started["attemptId"], backend.AttemptAnswersIn(
                answers=[backend.AnswerIn(id=questions[1]["id"], userAns=questions[1]["ans"])]), user)
            self.assertTrue(late["expired"])
            result = backend.submit_timed_attempt(started["attemptId"], user)
            self.assertEqual(result["scorePct"], 50)
            self.assertEqual(result["id"], late["resultId"])
            self.assertEqual(backend.exam_attempt_status(started["attemptId"], user)["resultId"], result["id"])
            self.assertEqual(len(backend.cohort_roster({"role": "ADMIN"})), 1)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_licensure_late_submit_ignores_unsaved_answers(self):
        student, _ = self.register_student()
        user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        now = int(time.time())
        with patch.object(backend.time, "time", return_value=now):
            issued = backend.start_licensure_exam(user)
        forged = backend.ExamSubmission(
            title="Mock Licensure Exam", mode="licensure", attempt_id=issued["attemptId"],
            answers=[backend.AnswerIn(id=item["id"], userAns=0) for item in issued["questions"]])
        with patch.object(backend.time, "time", return_value=now + 3601):
            result = backend.submit_exam(forged, user)
        self.assertTrue(result["expired"])
        self.assertEqual(result["scorePct"], 0)
        self.assertEqual(result["correctItems"], 0)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_server_finalizes_closed_practice_exam_at_deadline(self):
        student, _ = self.register_student()
        user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        question = next(item for item in backend.imported_questions(True)
                        if item["domain"] == "Networking Fundamentals" and
                        item["questionType"] == "multiple_choice")
        now = int(time.time())
        with patch.object(backend.time, "time", return_value=now):
            started = backend.start_practice_exam(backend.PracticeAttemptIn(
                question_ids=[question["id"]], selected_domains=["Networking Fundamentals"],
                time_minutes=5), user)
            backend.save_exam_answers(started["attemptId"], backend.AttemptAnswersIn(
                answers=[backend.AnswerIn(id=question["id"], userAns=question["ans"])]), user)
        with patch.object(backend.time, "time", return_value=now + 301):
            self.assertEqual(backend.finalize_expired_attempts(), 1)
            self.assertEqual(backend.finalize_expired_attempts(), 0)
            self.assertEqual(backend.submit_timed_attempt(started["attemptId"], user)["scorePct"], 100)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_invalid_autosave_cannot_block_deadline_finalization(self):
        student, _ = self.register_student()
        user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        question = next(item for item in backend.imported_questions(True)
                        if item["domain"] == "Networking Fundamentals" and
                        item["questionType"] == "multiple_choice")
        now = int(time.time())
        with patch.object(backend.time, "time", return_value=now):
            started = backend.start_practice_exam(backend.PracticeAttemptIn(
                question_ids=[question["id"]], selected_domains=["Networking Fundamentals"],
                time_minutes=5), user)
            with self.assertRaises(HTTPException) as invalid:
                backend.save_exam_answers(started["attemptId"], backend.AttemptAnswersIn(
                    answers=[backend.AnswerIn(id=question["id"], userAns="invalid")]), user)
            self.assertEqual(invalid.exception.status_code, 422)
        with patch.object(backend.time, "time", return_value=now + 301):
            self.assertEqual(backend.finalize_expired_attempts(), 1)
            self.assertEqual(backend.submit_timed_attempt(started["attemptId"], user)["scorePct"], 0)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_exiting_practice_exam_prevents_deadline_result(self):
        student, _ = self.register_student()
        user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        question = next(item for item in backend.imported_questions(True)
                        if item["domain"] == "Networking Fundamentals")
        now = int(time.time())
        with patch.object(backend.time, "time", return_value=now):
            started = backend.start_practice_exam(backend.PracticeAttemptIn(
                question_ids=[question["id"]], selected_domains=["Networking Fundamentals"],
                time_minutes=5), user)
            self.assertTrue(backend.abandon_timed_attempt(started["attemptId"], user)["ok"])
        with patch.object(backend.time, "time", return_value=now + 301):
            self.assertEqual(backend.finalize_expired_attempts(), 0)
            with self.assertRaises(HTTPException) as unavailable:
                backend.submit_timed_attempt(started["attemptId"], user)
            self.assertEqual(unavailable.exception.status_code, 404)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_mock_licensure_exam_covers_registered_discipline_and_is_bound_to_student(self):
        student, cookie = self.register_student()
        backend.save_profile(backend.ProfileIn(
            name="Architecture Student", discipline="Computer Systems Architect"), student["user"])
        user = backend.current_session(request(cookie))[0]
        first = backend.start_licensure_exam(user)
        second = backend.start_licensure_exam(user)
        self.assertEqual(len(first["questions"]), 100)
        self.assertEqual(first["timeSeconds"], 3600)
        self.assertEqual(len({q["id"] for q in first["questions"]}), 100)
        domains = backend.DISCIPLINES["Computer Systems Architect"]
        self.assertEqual({q["domain"] for q in first["questions"]}, set(domains))
        self.assertEqual([sum(q["domain"] == domain for q in first["questions"])
                          for domain in domains], backend.TOS_BLUEPRINT["Computer Systems Architect"][0])
        self.assertEqual([sum(q["cognitive"] == level for q in first["questions"])
                          for level in backend.COGNITIVE_ORDER],
                         backend.TOS_BLUEPRINT["Computer Systems Architect"][1])
        for domain, domain_weight in zip(domains, backend.TOS_BLUEPRINT["Computer Systems Architect"][0]):
            for level, level_weight in zip(backend.COGNITIVE_ORDER,
                                           backend.TOS_BLUEPRINT["Computer Systems Architect"][1]):
                actual = sum(q["domain"] == domain and q["cognitive"] == level
                             for q in first["questions"])
                product = domain_weight * level_weight
                allowed = {product // 100}
                if product % 100:
                    allowed.add(product // 100 + 1)
                self.assertIn(actual, allowed)
        self.assertNotEqual({q["id"] for q in first["questions"]},
                            {q["id"] for q in second["questions"]})
        self.assertTrue(all("ans" not in q and "answerText" not in q for q in first["questions"]))
        answers = [backend.AnswerIn(id=q["id"]) for q in first["questions"]]
        payload = backend.ExamSubmission(title="Mock Licensure Exam", mode="licensure",
                                         attempt_id=first["attemptId"], answers=answers)
        with self.assertRaises(HTTPException):
            backend.submit_exam(payload, {"id": user["id"] + 100, "role": "STUDENT",
                                         "discipline": "Computer Systems Architect"})
        with self.assertRaises(HTTPException) as changed_discipline:
            backend.submit_exam(payload, {**user, "discipline": "Network Engineer"})
        self.assertEqual(changed_discipline.exception.status_code, 403)
        result = backend.submit_exam(payload, user)
        self.assertEqual(result["totalItems"], 100)
        self.assertEqual({d["name"] for d in result["domains"]}, set(domains))
        report = backend.exam_report(result["id"], {"role": "ADMIN", "id": 1})["report"]
        self.assertEqual(report["status"], "met")
        self.assertEqual(report["planned"]["joint"], report["actual"]["joint"])
        with self.assertRaises(HTTPException):
            backend.submit_exam(payload, user)
        self.assertEqual(html_page("mock-exam", request(cookie)).status_code, 200)
        _, admin_cookie = self.login_admin()
        with self.assertRaises(HTTPException) as forbidden:
            html_page("mock-exam", request(admin_cookie))
        self.assertEqual(forbidden.exception.status_code, 403)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_licensure_joint_quotas_are_feasible_for_all_six_disciplines(self):
        imported = backend.imported_questions()
        for discipline, domains in backend.DISCIPLINES.items():
            available = {(domain, level): sum(q["domain"] == domain and q["cognitive"] == level
                                              for q in imported)
                         for domain in domains for level in backend.COGNITIVE_ORDER}
            quotas = backend.licensure_cell_quotas(discipline, available)
            self.assertEqual(sum(quotas.values()), 100)
            self.assertEqual([sum(quotas[(domain, level)] for level in backend.COGNITIVE_ORDER)
                              for domain in domains], backend.TOS_BLUEPRINT[discipline][0])
            self.assertEqual([sum(quotas[(domain, level)] for domain in domains)
                              for level in backend.COGNITIVE_ORDER], backend.TOS_BLUEPRINT[discipline][1])
            for (domain, level), count in quotas.items():
                self.assertLessEqual(count, available[(domain, level)])

    def test_architect_student_only_receives_own_bank_and_cannot_take_practice(self):
        student, cookie = self.register_student()
        backend.save_profile(backend.ProfileIn(
            name="Architecture Student", discipline="Computer Systems Architect"), student["user"])
        state = backend.bootstrap(request(cookie))
        self.assertTrue(state["questions"])
        self.assertTrue(all(question["domain"] in backend.DISCIPLINES["Computer Systems Architect"]
                            for question in state["questions"]))
        with self.assertRaises(HTTPException) as practice:
            backend.practice_score(backend.ExamSubmission(
                title="Practice", answers=[backend.AnswerIn(id="CPE-ARCH-001", userAns=1)]
            ), request(cookie, method="POST"))
        self.assertEqual(practice.exception.status_code, 403)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_imported_overrides_change_visible_items_and_scoring(self):
        admin, _ = self.login_admin()
        mc = next(q for q in backend.imported_questions(True) if q["id"] == "QB-2")
        revised = backend.QuestionIn(**{key: mc[key] for key in
            ("id", "q", "opts", "ans", "answerText", "domain", "cognitive",
             "difficulty", "explanation", "questionType")})
        revised.ans = (mc["ans"] + 1) % len(mc["opts"])
        backend.edit_question("QB-2", revised, admin["user"])
        visible = next(q for q in backend.imported_questions() if q["id"] == "QB-2")
        self.assertNotIn("ans", visible)
        with backend.db() as connection:
            scored = backend.score_exam_payload(connection, backend.ExamSubmission(
                title="Changed answer", answers=[backend.AnswerIn(id="QB-2", userAns=revised.ans)]))
        self.assertEqual(scored["scorePct"], 100)

        identification = next(q for q in backend.imported_questions(True) if q["id"] == "QB-1")
        updated = backend.QuestionIn(**{key: identification[key] for key in
            ("id", "q", "opts", "ans", "answerText", "domain", "cognitive",
             "difficulty", "explanation", "questionType")})
        updated.answerText = "replacement answer"
        backend.edit_question("QB-1", updated, admin["user"])
        with backend.db() as connection:
            scored = backend.score_exam_payload(connection, backend.ExamSubmission(
                title="Changed identification", answers=[
                    backend.AnswerIn(id="QB-1", userAns="replacement answer")]))
        self.assertEqual(scored["scorePct"], 100)

    @unittest.skipUnless(backend.QUESTION_BANK_PATH.is_file(), "Team question bank not installed")
    def test_imported_question_types_are_server_graded_without_guest_history(self):
        imported = backend.imported_questions()
        self.assertEqual(len(imported), 1200)
        self.assertEqual({q["questionType"] for q in imported},
                         {"identification", "multiple_choice", "both"})
        self.assertEqual(imported[4]["id"], "QB-5")
        self.assertEqual(len(imported[4]["opts"]), 5)
        self.assertTrue(next(q for q in imported if q["id"] == "QB-151")["imageUrl"])
        guest_questions = backend.bootstrap(request())["questions"]
        for question in guest_questions:
            self.assertNotIn("ans", question)
            self.assertNotIn("answerText", question)
        result = backend.practice_score(backend.ExamSubmission(
            title="Imported practice",
            answers=[
                backend.AnswerIn(id="QB-1", userAns="local area network"),
                backend.AnswerIn(id="QB-2", userAns=3),
                backend.AnswerIn(id="QB-3", userAns="seven"),
                backend.AnswerIn(id="QB-5", userAns=4),
            ],
        ), request(method="POST"))
        self.assertEqual(result["scorePct"], 100)
        with backend.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exam_history").fetchone()[0], 0)
        wrong = backend.practice_score(backend.ExamSubmission(
            title="Wrong answer", answers=[backend.AnswerIn(id="QB-2", userAns=0)]
        ), request(method="POST"))
        self.assertEqual(wrong["scorePct"], 0)
        student, _ = self.register_student()
        student_user = backend.save_profile(backend.ProfileIn(
            name="Network Student", discipline="Network Engineer"), student["user"])["user"]
        saved = backend.submit_exam(backend.ExamSubmission(
            title="Imported mock", answers=[backend.AnswerIn(id="QB-3", userAns=0)]
        ), student_user)
        self.assertEqual(saved["scorePct"], 100)
        with backend.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exam_history").fetchone()[0], 1)

    def test_admin_can_unlock_after_three_failures(self):
        student, _ = self.register_student()
        for _ in range(3):
            with self.assertRaises(HTTPException):
                backend.login(backend.LoginIn(
                    identifier="student@example.com", password="Wrong@123",
                ), request(method="POST"), Response())
        admin, cookie = self.login_admin()
        admin_user = backend.require_user(request(cookie))
        backend.unlock(student["user"]["id"], admin_user)
        result = backend.login(backend.LoginIn(
            identifier="student01", password="Valid@123",
        ), request(method="POST"), Response())
        self.assertEqual(result["user"]["role"], "STUDENT")

    def test_local_admin_recovery_preserves_account_and_revokes_sessions(self):
        _, old_cookie = self.login_admin()
        with self.assertRaises(ValueError):
            backend.reset_admin_password_local("student01", "NewAdmin@1")
        recovered = backend.reset_admin_password_local("admin@example.com", "NewAdmin@1")
        self.assertEqual(recovered, "adminuser")
        self.assertIsNone(backend.current_session(request(old_cookie)))
        with self.assertRaises(HTTPException) as old_login:
            backend.login(backend.LoginIn(
                identifier="adminuser", password="Admin@123",
            ), request(method="POST"), Response())
        self.assertEqual(old_login.exception.status_code, 401)
        new_login = backend.login(backend.LoginIn(
            identifier="adminuser", password="NewAdmin@1",
        ), request(method="POST"), Response())
        self.assertEqual(new_login["user"]["role"], "ADMIN")


if __name__ == "__main__":
    unittest.main()
