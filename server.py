"""Localhost web app with server-enforced account roles."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import (
    current_session,
    database_mode,
    finalize_expired_attempts,
    initialize,
    router,
)

APP_DIR = Path(__file__).resolve().parent
PAGES_DIR = APP_DIR / "pages"
HTML_PAGES = {page.name for page in PAGES_DIR.glob("*.html")}
PAGE_ROLES = {
    "admin-dashboard.html": {"ADMIN"},
    "admin-accounts.html": {"ADMIN"},
    "admin-question-approvals.html": {"ADMIN"},
    "admin-reports.html": {"ADMIN"},
    "print-report.html": {"STUDENT", "ADMIN"},
    "test-bank.html": {"ADMIN", "EXAMINER"},
    "examiner-question-submissions.html": {"EXAMINER"},
    "examiner-dashboard.html": {"ADMIN", "EXAMINER"},
    "examinee-dashboard.html": {"STUDENT"},
    "exam-history.html": {"STUDENT"},
    "generator.html": {"STUDENT"},
    "mock-exam.html": {"STUDENT"},
    "remediation.html": {"STUDENT"},
    "profile.html": {"STUDENT", "EXAMINER", "ADMIN"},
}


def role_landing_page(user: dict) -> str:
    if user["role"] == "ADMIN":
        return "admin-dashboard.html"
    if user["role"] == "EXAMINER":
        return "examiner-dashboard.html" if user["name"] else "profile.html"
    if user["role"] == "STUDENT":
        return "examinee-dashboard.html" if user["name"] and user["discipline"] else "profile.html"
    return "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    async def expire_exams():
        while True:
            try:
                await asyncio.to_thread(finalize_expired_attempts)
            except Exception:
                logging.exception("Could not check timed exam deadlines")
            await asyncio.sleep(10)
    task = asyncio.create_task(expire_exams())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="Licensure Exam Diagnostic System",
    description="Local development API for the licensure examination project.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.include_router(router)


@app.middleware("http")
async def prevent_stale_pages(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html") or path.startswith(("/js/", "/css/", "/api/")):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health", tags=["System"])
def health_check() -> dict[str, str]:
    """Confirm that the backend is running and report its active database."""
    return {
        "status": "ok",
        "service": "licensure-exam",
        "database": database_mode(),
    }


@app.get("/", include_in_schema=False)
def home_page() -> FileResponse:
    return FileResponse(PAGES_DIR / "index.html")


@app.get("/{page_name}.html", include_in_schema=False)
def html_page(page_name: str, request: Request) -> Response:
    """Serve only known top-level HTML pages, never backend/configuration files."""
    filename = f"{page_name}.html"
    if filename not in HTML_PAGES:
        raise HTTPException(status_code=404, detail="Page not found")
    session = None
    if filename in PAGE_ROLES or filename in {"exam.html", "results.html", "login.html"}:
        session = current_session(request)
    if filename == "login.html" and session:
        user = session[0]
        requested_page = request.query_params.get("next", "")
        if user["role"] == "STUDENT" and (not user["name"] or not user["discipline"]):
            destination = "profile.html"
        elif requested_page in PAGE_ROLES and user["role"] in PAGE_ROLES[requested_page]:
            destination = requested_page
        else:
            destination = role_landing_page(user)
        return RedirectResponse(f"/{destination}", status_code=303)
    if filename in {"exam.html", "results.html"}:
        if session and session[0]["role"] in {"ADMIN", "EXAMINER"}:
            raise HTTPException(status_code=403, detail="This role manages exams rather than taking them.")
    allowed = PAGE_ROLES.get(filename)
    if allowed:
        if session is None:
            return RedirectResponse(f"/login.html?next={filename}", status_code=303)
        if session[0]["role"] not in allowed:
            raise HTTPException(status_code=403, detail="Your account cannot open this page.")
        if filename == "profile.html" and session[0]["role"] == "ADMIN":
            return RedirectResponse("/admin-dashboard.html", status_code=303)
    return FileResponse(PAGES_DIR / filename)


app.mount("/css", StaticFiles(directory=APP_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=APP_DIR / "js"), name="js")
app.mount("/static/images", StaticFiles(directory=APP_DIR / "static" / "images"), name="question-images")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=5000, reload=True)
