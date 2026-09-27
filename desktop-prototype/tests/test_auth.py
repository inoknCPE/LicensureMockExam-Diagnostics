import sys
import tempfile
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from controllers.auth_controller import AuthController  # noqa: E402
from models.database import init_db  # noqa: E402
from models.schemas import password_requirements  # noqa: E402


class AuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        database = init_db(Path(self.temporary_directory.name) / "test.db")
        self.auth = AuthController(database)
        self.admin = self.auth.create_initial_admin(
            "adminuser", "admin@example.com", "Admin@123", "Admin@123"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_password_requirements(self) -> None:
        self.assertTrue(all(password_requirements("Valid@123").values()))
        self.assertFalse(all(password_requirements("weakpass").values()))
        self.assertFalse(
            password_requirements("lower@123")["At least one uppercase letter (A-Z)"]
        )

    def test_registration_and_duplicate_username_and_email(self) -> None:
        created = self.auth.register_user(
            "reviewee1", "reviewee@example.com", "Pass@123", "Pass@123"
        )
        self.assertTrue(created.success)

        duplicate_username = self.auth.register_user(
            "REVIEWEE1", "different@example.com", "Pass@123", "Pass@123"
        )
        duplicate_email = self.auth.register_user(
            "reviewee2", "REVIEWEE@example.com", "Pass@123", "Pass@123"
        )
        self.assertFalse(duplicate_username.success)
        self.assertIn("username", duplicate_username.message.lower())
        self.assertFalse(duplicate_email.success)
        self.assertIn("email", duplicate_email.message.lower())

    def test_invalid_password_cannot_register(self) -> None:
        result = self.auth.register_user(
            "reviewee1", "reviewee@example.com", "password", "password"
        )
        self.assertFalse(result.success)

    def test_three_failures_lock_and_admin_can_unlock(self) -> None:
        self.auth.register_user(
            "reviewee1", "reviewee@example.com", "Pass@123", "Pass@123"
        )
        for _ in range(3):
            result = self.auth.login_user("reviewee1", "Wrong@123")
        self.assertIn("locked", result.message.lower())
        self.assertEqual("account_locked", result.code)

        correct_while_locked = self.auth.login_user("reviewee1", "Pass@123")
        self.assertFalse(correct_while_locked.success)

        locked = self.auth.list_locked_users(self.admin.user["id"])
        self.assertEqual(1, len(locked))
        unlocked = self.auth.unlock_user(self.admin.user["id"], locked[0][0])
        self.assertTrue(unlocked.success)
        self.assertTrue(self.auth.login_user("reviewee1", "Pass@123").success)

    def test_successful_login_resets_failed_attempt_count(self) -> None:
        self.auth.register_user(
            "reviewee1", "reviewee@example.com", "Pass@123", "Pass@123"
        )
        self.auth.login_user("reviewee1", "Wrong@123")
        self.assertTrue(self.auth.login_user("reviewee1", "Pass@123").success)
        first_new_failure = self.auth.login_user("reviewee1", "Wrong@123")
        self.assertIn("2 attempt(s) remaining", first_new_failure.message)

    def test_user_can_login_with_email(self) -> None:
        self.auth.register_user(
            "reviewee1", "reviewee@example.com", "Pass@123", "Pass@123"
        )
        result = self.auth.login_user("REVIEWEE@EXAMPLE.COM", "Pass@123")
        self.assertTrue(result.success)
        self.assertEqual("reviewee1", result.user["username"])

    def test_admin_can_approve_password_reset_and_unlock_account(self) -> None:
        self.auth.register_user(
            "reviewee1", "reviewee@example.com", "Pass@123", "Pass@123"
        )
        for _ in range(3):
            self.auth.login_user("reviewee1", "Wrong@123")

        requested = self.auth.request_password_reset(
            "reviewee@example.com", "New@123A", "New@123A"
        )
        self.assertTrue(requested.success)

        pending = self.auth.list_pending_password_resets(self.admin.user["id"])
        self.assertEqual(1, len(pending))
        approved = self.auth.review_password_reset(
            self.admin.user["id"], pending[0][0], approve=True
        )
        self.assertTrue(approved.success)
        self.assertTrue(self.auth.login_user("reviewee1", "New@123A").success)
        self.assertFalse(self.auth.login_user("reviewee1", "Pass@123").success)


if __name__ == "__main__":
    unittest.main()
