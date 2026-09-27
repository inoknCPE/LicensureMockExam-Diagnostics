import sys
from pathlib import Path
import tkinter as tk


APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from controllers.auth_controller import AuthController  # noqa: E402
from models.database import init_db  # noqa: E402
from views.auth_view import (  # noqa: E402
    AdminDashboardView,
    ForgotPasswordView,
    LoginView,
    RegistrationForm,
    UserHomeView,
)


class LicensureExamApplication:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Licensure Examination Diagnostic and Mock Testing System")
        self.root.geometry("780x760")
        self.root.minsize(720, 700)
        self.root.configure(bg="#F4F1E8")

        database = init_db(APP_DIR / "data" / "licensure_exam.db")
        self.auth = AuthController(database)
        self.current_view: tk.Frame | None = None

        if self.auth.has_admin():
            self.show_login()
        else:
            self.show_initial_admin_setup()

    def _show(self, view: tk.Frame) -> None:
        if self.current_view is not None:
            self.current_view.destroy()
        self.current_view = view
        self.current_view.pack(fill="both", expand=True)

    def show_initial_admin_setup(self) -> None:
        self._show(
            RegistrationForm(
                self.root,
                title="First-run Administrator Setup",
                subtitle=(
                    "Create the administrator who can unlock accounts after three "
                    "invalid login attempts. This screen appears only once."
                ),
                submit_text="CREATE ADMINISTRATOR",
                submit_action=self.auth.create_initial_admin,
                on_success=self.show_login,
                on_back=None,
            )
        )

    def show_login(self) -> None:
        self._show(
            LoginView(
                self.root,
                self.auth,
                self._after_login,
                self.show_register,
                self.show_forgot_password,
            )
        )

    def show_forgot_password(self, identifier: str = "", notice: str = "") -> None:
        self._show(
            ForgotPasswordView(
                self.root,
                self.auth,
                self.show_login,
                identifier=identifier,
                notice=notice,
            )
        )

    def show_register(self) -> None:
        self._show(
            RegistrationForm(
                self.root,
                title="Create Reviewee Account",
                subtitle="Register securely before starting the diagnostic examination workflow.",
                submit_text="REGISTER",
                submit_action=self.auth.register_user,
                on_success=self.show_login,
                on_back=self.show_login,
            )
        )

    def _after_login(self, user: dict) -> None:
        if user["role"] == "admin":
            self._show(AdminDashboardView(self.root, self.auth, user, self.show_login))
        else:
            self._show(UserHomeView(self.root, user, self.show_login))


if __name__ == "__main__":
    root = tk.Tk()
    LicensureExamApplication(root)
    root.mainloop()
