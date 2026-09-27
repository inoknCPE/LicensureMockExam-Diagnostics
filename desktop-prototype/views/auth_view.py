import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from controllers.auth_controller import AuthController, AuthResult
from models.schemas import is_valid_email, password_requirements, username_requirements


BACKGROUND = "#F4F1E8"
CARD = "#FFFFFF"
NAVY = "#0B2239"
ORANGE = "#FF6542"
MUTED = "#52616B"
GREEN = "#168A50"
RED = "#C5392F"


class HoverTip:
    def __init__(self, widget: tk.Widget, text: str | Callable[[], str]):
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        self.tip_content: tk.Frame | None = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def _current_text(self) -> str:
        return self.text() if callable(self.text) else self.text

    def show(self, _event=None) -> None:
        if self.tip is not None:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = self.widget.winfo_rooty() - 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        self.tip_content = tk.Frame(
            self.tip,
            bg=NAVY,
            padx=10,
            pady=8,
            highlightbackground="#D1D5DB",
            highlightthickness=1,
        )
        self.tip_content.pack()
        self._render_content()

    def _render_content(self) -> None:
        if self.tip_content is None:
            return
        for child in self.tip_content.winfo_children():
            child.destroy()
        for line in self._current_text().split("\n"):
            foreground = "white"
            if line.startswith("✓"):
                foreground = "#4ADE80"
            elif line.startswith("✕"):
                foreground = "#FF6B6B"
            tk.Label(
                self.tip_content,
                text=line or " ",
                justify="left",
                anchor="w",
                bg=NAVY,
                fg=foreground,
                font=("Segoe UI", 9),
            ).pack(fill="x", anchor="w")

    def refresh(self) -> None:
        """Refresh a visible tooltip while the user is typing."""
        self._render_content()

    def hide(self, _event=None) -> None:
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None
            self.tip_content = None


def requirement_lines(title: str, requirements: dict[str, bool]) -> str:
    lines = [title]
    lines.extend(
        ("✓" if passed else "✕") + f" {requirement}"
        for requirement, passed in requirements.items()
    )
    return "\n".join(lines)


def page_header(parent: tk.Widget, title: str, subtitle: str) -> None:
    tk.Label(
        parent,
        text=title,
        font=("Segoe UI", 20, "bold"),
        bg=CARD,
        fg=NAVY,
    ).pack(anchor="w")
    tk.Label(
        parent,
        text=subtitle,
        font=("Segoe UI", 10),
        bg=CARD,
        fg=MUTED,
        wraplength=500,
        justify="left",
    ).pack(anchor="w", pady=(2, 18))


def field_label(parent: tk.Widget, text: str) -> tk.Label:
    return tk.Label(
        parent, text=text, font=("Segoe UI", 10, "bold"), bg=CARD, fg=NAVY
    )


class LoginView(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        auth: AuthController,
        on_login: Callable[[dict], None],
        on_register: Callable[[], None],
        on_forgot_password: Callable[[str, str], None],
    ):
        super().__init__(parent, bg=BACKGROUND)
        self.auth = auth
        self.on_login = on_login
        self.on_forgot_password = on_forgot_password
        self.identifier = tk.StringVar()
        self.password = tk.StringVar()
        self.show_password = tk.BooleanVar(value=False)

        card = tk.Frame(self, bg=CARD, padx=42, pady=36, highlightthickness=1)
        card.configure(highlightbackground="#DED9CE")
        card.place(relx=0.5, rely=0.5, anchor="center", width=500, height=540)

        page_header(
            card,
            "Licensure Exam System",
            "Sign in to continue to the diagnostic and mock testing application.",
        )

        field_label(card, "Username or email").pack(anchor="w")
        username_entry = ttk.Entry(card, textvariable=self.identifier, font=("Segoe UI", 11))
        username_entry.pack(fill="x", ipady=7, pady=(4, 14))

        field_label(card, "Password").pack(anchor="w")
        self.password_entry = ttk.Entry(
            card, textvariable=self.password, show="•", font=("Segoe UI", 11)
        )
        self.password_entry.pack(fill="x", ipady=7, pady=(4, 7))
        ttk.Checkbutton(
            card,
            text="Show password",
            variable=self.show_password,
            command=self._toggle_password,
        ).pack(anchor="w", pady=(0, 18))

        self.login_message = tk.Label(
            card,
            text="",
            bg=CARD,
            fg=RED,
            font=("Segoe UI", 9),
            wraplength=410,
            justify="left",
        )
        self.login_message.pack(fill="x", pady=(0, 8))

        self.login_button = tk.Button(
            card,
            text="LOGIN",
            command=self._login,
            state="disabled",
            bg="#757575",
            disabledforeground="#E5E7EB",
            fg="white",
            activebackground="#107340",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self.login_button.pack(fill="x", ipady=9)
        tk.Button(
            card,
            text="Forgot password?",
            command=lambda: on_forgot_password(self.identifier.get().strip(), ""),
            bg=CARD,
            fg="#1769AA",
            activebackground=CARD,
            relief="flat",
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
        ).pack(pady=(10, 0))
        tk.Button(
            card,
            text="Create a new account",
            command=on_register,
            bg=CARD,
            fg="#1769AA",
            activebackground=CARD,
            relief="flat",
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
        ).pack(pady=(5, 0))

        username_entry.focus_set()
        username_entry.bind("<Return>", lambda _event: self.password_entry.focus_set())
        self.password_entry.bind("<Return>", lambda _event: self._login())
        self.identifier.trace_add("write", self._update_login_state)
        self.password.trace_add("write", self._update_login_state)
        self._update_login_state()

    def _toggle_password(self) -> None:
        self.password_entry.configure(show="" if self.show_password.get() else "•")

    def _update_login_state(self, *_args) -> None:
        # Existing accounts may have been created under an earlier policy.
        # Password-strength rules belong to registration/password changes;
        # login only requires credentials to be present for verification.
        ready = bool(self.identifier.get().strip()) and bool(self.password.get())
        self.login_button.configure(
            state="normal" if ready else "disabled",
            bg=GREEN if ready else "#757575",
        )
        self.login_message.configure(text="")

    def _login(self) -> None:
        if self.login_button.cget("state") == "disabled":
            return
        result = self.auth.login_user(self.identifier.get(), self.password.get())
        if result.success and result.user:
            self.on_login(result.user)
        else:
            identifier = self.identifier.get().strip()
            self.password.set("")
            if result.code == "account_locked":
                self.on_forgot_password(identifier, result.message)
            else:
                self.login_message.configure(text=result.message)


class ForgotPasswordView(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        auth: AuthController,
        on_back: Callable[[], None],
        identifier: str = "",
        notice: str = "",
    ):
        super().__init__(parent, bg=BACKGROUND)
        self.auth = auth
        self.identifier = tk.StringVar(value=identifier)
        self.new_password = tk.StringVar()
        self.confirm_password = tk.StringVar()
        self.show_password = tk.BooleanVar(value=False)

        card = tk.Frame(self, bg=CARD, padx=38, pady=30, highlightthickness=1)
        card.configure(highlightbackground="#DED9CE")
        card.place(relx=0.5, rely=0.5, anchor="center", width=560, height=610)
        page_header(
            card,
            "Forgot Password",
            "Submit a new password for administrator review. Your password changes only after approval.",
        )

        if notice:
            tk.Label(
                card,
                text=notice,
                bg="#FFF7ED",
                fg="#9A3412",
                font=("Segoe UI", 9),
                wraplength=470,
                justify="left",
                padx=10,
                pady=8,
            ).pack(fill="x", pady=(0, 12))

        field_label(card, "Username or email").pack(anchor="w")
        ttk.Entry(card, textvariable=self.identifier, font=("Segoe UI", 11)).pack(
            fill="x", ipady=6, pady=(4, 12)
        )

        password_row = tk.Frame(card, bg=CARD)
        password_row.pack(fill="x")
        field_label(password_row, "New password").pack(side="left")
        help_icon = tk.Label(
            password_row,
            text="?",
            bg=ORANGE,
            fg="white",
            width=2,
            font=("Segoe UI", 9, "bold"),
            cursor="question_arrow",
        )
        help_icon.pack(side="left", padx=7)
        self.password_tip = HoverTip(help_icon, self._password_tip_text)

        self.password_entry = ttk.Entry(
            card, textvariable=self.new_password, show="•", font=("Segoe UI", 11)
        )
        self.password_entry.pack(fill="x", ipady=6, pady=(4, 12))

        field_label(card, "Confirm new password").pack(anchor="w")
        self.confirm_entry = ttk.Entry(
            card, textvariable=self.confirm_password, show="•", font=("Segoe UI", 11)
        )
        self.confirm_entry.pack(fill="x", ipady=6, pady=(4, 7))

        ttk.Checkbutton(
            card,
            text="Show passwords",
            variable=self.show_password,
            command=self._toggle_password,
        ).pack(anchor="w", pady=(7, 12))

        self.form_message = tk.Label(
            card,
            text="",
            bg=CARD,
            fg=RED,
            font=("Segoe UI", 9),
            wraplength=470,
            justify="left",
        )
        self.form_message.pack(fill="x", pady=(0, 8))

        self.submit_button = tk.Button(
            card,
            text="SUBMIT FOR ADMIN REVIEW",
            command=self._submit,
            state="disabled",
            bg="#757575",
            disabledforeground="#E5E7EB",
            fg="white",
            activebackground="#107340",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self.submit_button.pack(fill="x", ipady=8)
        tk.Button(
            card,
            text="Back to login",
            command=on_back,
            bg=CARD,
            fg="#1769AA",
            activebackground=CARD,
            relief="flat",
            font=("Segoe UI", 10, "underline"),
            cursor="hand2",
        ).pack(pady=(8, 0))

        self.identifier.trace_add("write", self._update_state)
        self.new_password.trace_add("write", self._update_state)
        self.confirm_password.trace_add("write", self._update_state)
        self._update_state()

    def _toggle_password(self) -> None:
        marker = "" if self.show_password.get() else "•"
        self.password_entry.configure(show=marker)
        self.confirm_entry.configure(show=marker)

    def _password_tip_text(self) -> str:
        requirements = password_requirements(self.new_password.get())
        requirements["Passwords match"] = bool(self.new_password.get()) and (
            self.new_password.get() == self.confirm_password.get()
        )
        return requirement_lines("New password requirements:", requirements)

    def _update_state(self, *_args) -> None:
        checks = password_requirements(self.new_password.get())
        passwords_match = bool(self.new_password.get()) and (
            self.new_password.get() == self.confirm_password.get()
        )
        ready = (
            bool(self.identifier.get().strip())
            and all(checks.values())
            and passwords_match
        )
        self.submit_button.configure(
            state="normal" if ready else "disabled",
            bg=GREEN if ready else "#757575",
        )
        self.form_message.configure(text="", fg=RED)
        self.password_tip.refresh()

    def _submit(self) -> None:
        result = self.auth.request_password_reset(
            self.identifier.get(),
            self.new_password.get(),
            self.confirm_password.get(),
        )
        if result.success:
            self.new_password.set("")
            self.confirm_password.set("")
            self.form_message.configure(text=result.message, fg=GREEN)
        else:
            self.form_message.configure(text=result.message, fg=RED)


class RegistrationForm(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        title: str,
        subtitle: str,
        submit_text: str,
        submit_action: Callable[[str, str, str, str], AuthResult],
        on_success: Callable[[], None],
        on_back: Callable[[], None] | None,
    ):
        super().__init__(parent, bg=BACKGROUND)
        self.submit_action = submit_action
        self.on_success = on_success
        self.username = tk.StringVar()
        self.email = tk.StringVar()
        self.password = tk.StringVar()
        self.confirm_password = tk.StringVar()
        self.show_password = tk.BooleanVar(value=False)

        card = tk.Frame(self, bg=CARD, padx=38, pady=28, highlightthickness=1)
        card.configure(highlightbackground="#DED9CE")
        card.place(relx=0.5, rely=0.5, anchor="center", width=560, height=680)
        page_header(card, title, subtitle)

        username_row = tk.Frame(card, bg=CARD)
        username_row.pack(fill="x")
        field_label(username_row, "Username").pack(side="left")
        username_help_icon = tk.Label(
            username_row,
            text="?",
            bg=ORANGE,
            fg="white",
            width=2,
            font=("Segoe UI", 9, "bold"),
            cursor="question_arrow",
        )
        username_help_icon.pack(side="left", padx=7)
        self.username_tip = HoverTip(username_help_icon, self._username_tip_text)
        ttk.Entry(card, textvariable=self.username, font=("Segoe UI", 11)).pack(
            fill="x", ipady=6, pady=(4, 12)
        )

        field_label(card, "Email address").pack(anchor="w")
        ttk.Entry(card, textvariable=self.email, font=("Segoe UI", 11)).pack(
            fill="x", ipady=6, pady=(4, 12)
        )

        password_row = tk.Frame(card, bg=CARD)
        password_row.pack(fill="x")
        field_label(password_row, "Password").pack(side="left")
        help_icon = tk.Label(
            password_row,
            text="?",
            bg=ORANGE,
            fg="white",
            width=2,
            font=("Segoe UI", 9, "bold"),
            cursor="question_arrow",
        )
        help_icon.pack(side="left", padx=7)
        self.password_tip = HoverTip(help_icon, self._password_tip_text)

        self.password_entry = ttk.Entry(
            card, textvariable=self.password, show="•", font=("Segoe UI", 11)
        )
        self.password_entry.pack(fill="x", ipady=6, pady=(4, 12))

        field_label(card, "Confirm password").pack(anchor="w")
        self.confirm_entry = ttk.Entry(
            card, textvariable=self.confirm_password, show="•", font=("Segoe UI", 11)
        )
        self.confirm_entry.pack(fill="x", ipady=6, pady=(4, 7))

        ttk.Checkbutton(
            card,
            text="Show passwords",
            variable=self.show_password,
            command=self._toggle_password,
        ).pack(anchor="w", pady=(7, 12))

        self.form_message = tk.Label(
            card,
            text="",
            bg=CARD,
            fg=RED,
            font=("Segoe UI", 9),
            wraplength=470,
            justify="left",
        )
        self.form_message.pack(fill="x", pady=(0, 8))

        self.submit_button = tk.Button(
            card,
            text=submit_text,
            command=self._submit,
            state="disabled",
            bg="#757575",
            disabledforeground="#E5E7EB",
            fg="white",
            activebackground="#107340",
            activeforeground="white",
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self.submit_button.pack(fill="x", ipady=8)
        if on_back:
            tk.Button(
                card,
                text="Back to login",
                command=on_back,
                bg=CARD,
                fg="#1769AA",
                activebackground=CARD,
                relief="flat",
                font=("Segoe UI", 10, "underline"),
                cursor="hand2",
            ).pack(pady=(8, 0))

        self.username.trace_add("write", self._update_requirements)
        self.email.trace_add("write", self._update_requirements)
        self.password.trace_add("write", self._update_requirements)
        self.confirm_password.trace_add("write", self._update_requirements)
        self._update_requirements()

    def _toggle_password(self) -> None:
        marker = "" if self.show_password.get() else "•"
        self.password_entry.configure(show=marker)
        self.confirm_entry.configure(show=marker)

    def _username_tip_text(self) -> str:
        return requirement_lines(
            "Username requirements:", username_requirements(self.username.get())
        )

    def _password_tip_text(self) -> str:
        requirements = password_requirements(self.password.get())
        passwords_match = bool(self.password.get()) and (
            self.password.get() == self.confirm_password.get()
        )
        requirements["Passwords match"] = passwords_match
        return (
            requirement_lines("Password requirements:", requirements)
            + "\n\nThree invalid attempts lock the account."
        )

    def _update_requirements(self, *_args) -> None:
        username_ok = all(username_requirements(self.username.get()).values())
        email_ok = is_valid_email(self.email.get())
        checks = password_requirements(self.password.get())
        passwords_match = bool(self.password.get()) and (
            self.password.get() == self.confirm_password.get()
        )
        ready = username_ok and email_ok and all(checks.values()) and passwords_match
        self.submit_button.configure(
            state="normal" if ready else "disabled",
            bg=GREEN if ready else "#757575",
        )
        self.form_message.configure(text="")
        self.username_tip.refresh()
        self.password_tip.refresh()

    def _submit(self) -> None:
        result = self.submit_action(
            self.username.get(),
            self.email.get(),
            self.password.get(),
            self.confirm_password.get(),
        )
        if result.success:
            messagebox.showinfo("Success", result.message, parent=self)
            self.on_success()
        else:
            self.form_message.configure(text=result.message)


class UserHomeView(tk.Frame):
    def __init__(self, parent: tk.Widget, user: dict, on_logout: Callable[[], None]):
        super().__init__(parent, bg=BACKGROUND)
        card = tk.Frame(self, bg=CARD, padx=45, pady=40, highlightthickness=1)
        card.configure(highlightbackground="#DED9CE")
        card.place(relx=0.5, rely=0.5, anchor="center", width=620, height=380)
        page_header(
            card,
            f"Welcome, {user['username']}!",
            "Authentication is complete. The examination modules will be added in the next milestones.",
        )
        steps = (
            "1   Reviewee Enrollment",
            "2   TOS Configuration",
            "3   Question Bank Tagging",
            "4   Dynamic Exam Generation",
        )
        for step in steps:
            tk.Label(
                card,
                text=step,
                bg="#F8FAFC",
                fg=NAVY,
                font=("Segoe UI", 10, "bold"),
                anchor="w",
                padx=12,
                pady=7,
            ).pack(fill="x", pady=2)
        tk.Button(
            card,
            text="LOG OUT",
            command=on_logout,
            bg=NAVY,
            fg="white",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="e", pady=(18, 0), ipadx=15, ipady=5)


class AdminDashboardView(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        auth: AuthController,
        administrator: dict,
        on_logout: Callable[[], None],
    ):
        super().__init__(parent, bg=BACKGROUND)
        self.auth = auth
        self.administrator = administrator

        card = tk.Frame(self, bg=CARD, padx=35, pady=30, highlightthickness=1)
        card.configure(highlightbackground="#DED9CE")
        card.pack(fill="both", expand=True, padx=45, pady=35)
        page_header(
            card,
            "Administrator Dashboard",
            "Manage locked accounts and review requested password changes.",
        )

        notebook = ttk.Notebook(card)
        notebook.pack(fill="both", expand=True)

        locked_tab = tk.Frame(notebook, bg=CARD, padx=12, pady=12)
        reset_tab = tk.Frame(notebook, bg=CARD, padx=12, pady=12)
        notebook.add(locked_tab, text="Locked Accounts")
        notebook.add(reset_tab, text="Password Reset Requests")

        locked_table = tk.Frame(locked_tab, bg=CARD)
        locked_table.pack(fill="both", expand=True)
        locked_columns = ("id", "username", "email", "role")
        self.locked_tree = ttk.Treeview(
            locked_table, columns=locked_columns, show="headings"
        )
        for name, width in (
            ("id", 55),
            ("username", 150),
            ("email", 230),
            ("role", 75),
        ):
            self.locked_tree.heading(name, text=name.replace("_", " ").title())
            self.locked_tree.column(
                name, width=width, anchor="center" if name in ("id", "role") else "w"
            )
        locked_scrollbar = ttk.Scrollbar(
            locked_table, orient="vertical", command=self.locked_tree.yview
        )
        self.locked_tree.configure(yscrollcommand=locked_scrollbar.set)
        self.locked_tree.pack(side="left", fill="both", expand=True)
        locked_scrollbar.pack(side="right", fill="y")

        locked_buttons = tk.Frame(locked_tab, bg=CARD)
        locked_buttons.pack(fill="x", pady=(12, 0))
        tk.Button(
            locked_buttons,
            text="Unlock selected account",
            command=self._unlock,
            bg=GREEN,
            fg="white",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", ipadx=12, ipady=6)
        self.locked_status = tk.Label(
            locked_buttons, bg=CARD, fg=MUTED, font=("Segoe UI", 9)
        )
        self.locked_status.pack(side="left", padx=12)

        reset_table = tk.Frame(reset_tab, bg=CARD)
        reset_table.pack(fill="both", expand=True)
        reset_columns = ("id", "username", "email", "account", "requested")
        self.reset_tree = ttk.Treeview(
            reset_table, columns=reset_columns, show="headings"
        )
        for name, heading, width in (
            ("id", "Request ID", 75),
            ("username", "Username", 125),
            ("email", "Email", 185),
            ("account", "Account", 75),
            ("requested", "Requested", 140),
        ):
            self.reset_tree.heading(name, text=heading)
            self.reset_tree.column(
                name,
                width=width,
                anchor="center" if name in ("id", "account", "requested") else "w",
            )
        reset_scrollbar = ttk.Scrollbar(
            reset_table, orient="vertical", command=self.reset_tree.yview
        )
        self.reset_tree.configure(yscrollcommand=reset_scrollbar.set)
        self.reset_tree.pack(side="left", fill="both", expand=True)
        reset_scrollbar.pack(side="right", fill="y")

        reset_buttons = tk.Frame(reset_tab, bg=CARD)
        reset_buttons.pack(fill="x", pady=(12, 0))
        tk.Button(
            reset_buttons,
            text="Approve selected",
            command=lambda: self._review_reset(True),
            bg=GREEN,
            fg="white",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", ipadx=10, ipady=6)
        tk.Button(
            reset_buttons,
            text="Reject selected",
            command=lambda: self._review_reset(False),
            bg="#B42318",
            fg="white",
            relief="flat",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left", padx=8, ipadx=10, ipady=6)
        self.reset_status = tk.Label(
            reset_buttons, bg=CARD, fg=MUTED, font=("Segoe UI", 9)
        )
        self.reset_status.pack(side="left", padx=6)

        footer = tk.Frame(card, bg=CARD)
        footer.pack(fill="x", pady=(14, 0))
        tk.Button(
            footer,
            text="Refresh all",
            command=self.refresh,
            bg="#1769AA",
            fg="white",
            relief="flat",
        ).pack(side="left", ipadx=12, ipady=6)
        tk.Button(
            footer,
            text="Log out",
            command=on_logout,
            bg=NAVY,
            fg="white",
            relief="flat",
        ).pack(side="right", ipadx=12, ipady=6)
        self.refresh()

    def refresh(self) -> None:
        for item in self.locked_tree.get_children():
            self.locked_tree.delete(item)
        locked_rows = self.auth.list_locked_users(self.administrator["id"])
        for row in locked_rows:
            self.locked_tree.insert("", "end", values=row)
        self.locked_status.configure(
            text=(
                "No locked accounts."
                if not locked_rows
                else f"{len(locked_rows)} locked account(s)."
            )
        )

        for item in self.reset_tree.get_children():
            self.reset_tree.delete(item)
        reset_rows = self.auth.list_pending_password_resets(
            self.administrator["id"]
        )
        for row in reset_rows:
            self.reset_tree.insert("", "end", values=row)
        self.reset_status.configure(
            text=(
                "No pending requests."
                if not reset_rows
                else f"{len(reset_rows)} pending request(s)."
            )
        )

    def _unlock(self) -> None:
        selected = self.locked_tree.selection()
        if not selected:
            messagebox.showwarning(
                "Select an account", "Select a locked account first.", parent=self
            )
            return
        user_id = int(self.locked_tree.item(selected[0], "values")[0])
        result = self.auth.unlock_user(self.administrator["id"], user_id)
        if result.success:
            messagebox.showinfo("Account unlocked", result.message, parent=self)
            self.refresh()
        else:
            messagebox.showerror("Unlock failed", result.message, parent=self)

    def _review_reset(self, approve: bool) -> None:
        selected = self.reset_tree.selection()
        if not selected:
            messagebox.showwarning(
                "Select a request", "Select a password-reset request first.", parent=self
            )
            return
        values = self.reset_tree.item(selected[0], "values")
        request_id = int(values[0])
        username = values[1]
        action = "approve" if approve else "reject"
        if not messagebox.askyesno(
            "Confirm review",
            f"Do you want to {action} the password-reset request for '{username}'?",
            parent=self,
        ):
            return
        result = self.auth.review_password_reset(
            self.administrator["id"], request_id, approve
        )
        if result.success:
            messagebox.showinfo("Request reviewed", result.message, parent=self)
            self.refresh()
        else:
            messagebox.showerror("Review failed", result.message, parent=self)
