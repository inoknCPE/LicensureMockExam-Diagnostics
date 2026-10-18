"""Localhost web app with server-enforced account roles."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from backend import current_session, initialize, router

APP_DIR = Path(__file__).resolve().parent
HTML_PAGES = {page.name for page in APP_DIR.glob("*.html")}
PAGE_ROLES = {
    "admin-dashboard.html": {"ADMIN"},
    "admin-generator.html": {"ADMIN"},
    "admin-requests.html": {"ADMIN"},
    "admin-accounts.html": {"ADMIN"},
    "admin-question-approvals.html": {"ADMIN"},
    "test-bank.html": {"ADMIN", "EXAMINER"},
    "examiner-dashboard.html": {"ADMIN", "EXAMINER"},
    "examinee-dashboard.html": {"STUDENT"},
    "exam-history.html": {"STUDENT"},
    "generator.html": {"STUDENT"},
    "request-form.html": {"STUDENT"},
    "remediation.html": {"STUDENT"},
    "profile.html": {"STUDENT", "EXAMINER", "ADMIN"},
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield

app = FastAPI(
    title="Licensure Exam Diagnostic System",
    description="Local development API for the licensure examination project.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)
app.include_router(router)


@app.get("/api/health", tags=["System"])
def health_check() -> dict[str, str]:
    """Confirm that the local backend is running."""
    return {"status": "ok", "service": "licensure-exam-local"}


@app.get("/", include_in_schema=False)
def home_page() -> FileResponse:
    return FileResponse(APP_DIR / "index.html")


@app.get("/{page_name}.html", include_in_schema=False)
def html_page(page_name: str, request: Request) -> Response:
    """Serve only known top-level HTML pages, never backend/configuration files."""
    filename = f"{page_name}.html"
    if filename not in HTML_PAGES:
        raise HTTPException(status_code=404, detail="Page not found")
    if filename in {"exam.html", "results.html"}:
        session = current_session(request)
        if session and session[0]["role"] == "EXAMINER":
            raise HTTPException(status_code=403, detail="Examiners manage questions rather than take exams.")
    allowed = PAGE_ROLES.get(filename)
    if allowed:
        session = current_session(request)
        if session is None:
            return RedirectResponse("/login.html", status_code=303)
        if session[0]["role"] not in allowed:
            raise HTTPException(status_code=403, detail="Your account cannot open this page.")
        if filename == "profile.html" and session[0]["role"] == "ADMIN":
            return RedirectResponse("/admin-dashboard.html", status_code=303)
    return FileResponse(APP_DIR / filename)


app.mount("/css", StaticFiles(directory=APP_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=APP_DIR / "js"), name="js")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=5000, reload=True)
