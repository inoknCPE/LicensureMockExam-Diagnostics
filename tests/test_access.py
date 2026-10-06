"""Direct backend tests; no HTTP test client dependency is required."""

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from fastapi import Response
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import backend  # noqa: E402
from server import html_page  # noqa: E402


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
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        backend.DB_PATH = Path(self.temp.name) / "test.sqlite3"
        backend.initialize()
        backend.create_initial_admin("adminuser", "admin@example.com", "Admin@123")

    def tearDown(self):
        self.temp.cleanup()

    def register_student(self):
        response = Response()
        result = backend.register(backend.RegisterIn(
            username="student01", email="student@example.com",
            password="Valid@123", confirm_password="Valid@123",
        ), request(method="POST"), response)
        cookie = response.headers["set-cookie"].split(";", 1)[0]
        return result, cookie

    def login_admin(self):
        response = Response()
        result = backend.login(backend.LoginIn(
            identifier="admin@example.com", password="Admin@123",
        ), request(method="POST"), response)
        return result, response.headers["set-cookie"].split(";", 1)[0]

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
        with backend.db() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM exam_history").fetchone()[0], 0)

    def test_registration_and_server_role_guard(self):
        student, cookie = self.register_student()
        self.assertEqual(student["user"]["role"], "STUDENT")
        self.assertEqual(backend.current_session(request(cookie))[0]["role"], "STUDENT")
        with self.assertRaises(HTTPException) as error:
            html_page("admin-dashboard", request(cookie))
        self.assertEqual(error.exception.status_code, 403)
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

    def test_admin_can_grant_examiner_and_examiner_can_add_questions(self):
        student, _ = self.register_student()
        admin, cookie = self.login_admin()
        admin_user = backend.require_user(request(cookie))
        with self.assertRaises(HTTPException):
            backend.role_required("ADMIN")(user=student["user"])
        backend.change_role(
            student["user"]["id"], backend.RoleIn(role="EXAMINER"), admin_user)
        response = Response()
        examiner = backend.login(backend.LoginIn(
            identifier="student01", password="Valid@123",
        ), request(method="POST"), response)
        self.assertEqual(examiner["user"]["role"], "EXAMINER")
        backend.add_question(backend.QuestionIn(
            q="What does DNS resolve?",
            opts=["Names", "Voltages", "Threads", "Files"], ans=0,
            domain="Networking Fundamentals", cognitive="Understand",
            difficulty="Easy",
        ), examiner["user"])
        with self.assertRaises(HTTPException):
            backend.role_required("ADMIN")(user=examiner["user"])

    def test_student_mock_score_is_saved_by_server(self):
        student, _ = self.register_student()
        result = backend.submit_exam(backend.ExamSubmission(
            title="Network mock",
            answers=[backend.AnswerIn(id="CPE-NET-001", userAns=2)],
        ), student["user"])
        self.assertEqual(result["scorePct"], 100)
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


if __name__ == "__main__":
    unittest.main()
