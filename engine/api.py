"""The engine API: a small FastAPI app the dashboard and the on-page panel talk to.

Run it with ``python -m engine.api`` (it listens on 127.0.0.1:8000).

Why the guards? This API can approve a protected answer or change your answer bank, and it lives on your
PC next to a browser that visits real websites. Three layers keep other things from reaching it
(CLAUDE.md rule 11):

1. **Binding.** :func:`serve` refuses any host that is not this computer, so nothing on your network can connect.
2. **Host check.** Every request must say it is talking to ``127.0.0.1`` / ``localhost`` / ``::1``. This stops
   "DNS rebinding", where a web page tricks your browser into sending requests to a name that points at you.
3. **Origin check.** A request that changes something (POST, PUT, DELETE) and comes from a web page must come
   from the dashboard (``localhost:3000``). A random website cannot make your browser approve a wording.
   Requests with no ``Origin`` header (PowerShell, curl, tests) are not web pages, so they pass.

CORS (the browser's permission for the dashboard to read the answers) lists the same dashboard origins and nothing else.

The API never changes the run mode: only you do that, from the dashboard.
"""

from __future__ import annotations

import argparse
import threading
from collections.abc import Callable
from pathlib import Path
import sqlite3
from typing import Annotated
from urllib.parse import urlsplit

import uvicorn
from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from engine import db, learning
from engine.api_deps import get_conn, get_settings
from engine.api_models import AnswerOut, FillOut, FillStatus, Kind, UnknownOut, WordingOut
from engine.api_write import install_error_handlers, router as write_router
from engine.forms.history import list_fills
from engine.profile import ANSWERS_PATH
from engine.settings import Settings, load_settings

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_PORT = 8000
DASHBOARD_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")
CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class NotLocalError(ValueError):
    """The server was asked to listen on an address other than this computer."""


def check_local_host(host: str) -> str:
    """Return ``host`` if it means "this computer only"; otherwise refuse.

    Raises:
        NotLocalError: for ``0.0.0.0``, ``::``, an empty string, a LAN address or any other name.
    """
    if host not in LOCAL_HOSTS:
        raise NotLocalError(
            f"Refusing to listen on {host!r}: the engine API only binds to 127.0.0.1 (this computer). "
            "Anything else would let other devices on your network reach your answer bank."
        )
    return host


def _host_name(header: str) -> str:
    """The name part of a ``Host`` header: ``127.0.0.1:8000`` -> ``127.0.0.1``, ``[::1]:8000`` -> ``::1``."""
    header = header.strip().lower()
    if header.startswith("["):
        return header[1:].split("]")[0]
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


def create_app(
    settings: Settings | None = None,
    db_path: Path | str = db.DB_PATH,
    answers_path: Path = ANSWERS_PATH,
) -> FastAPI:
    """Build the app. Tests pass their own settings, temporary database and temporary answers file.

    Args:
        settings: fixed settings (tests). ``None`` re-reads ``settings.json`` on every request, so a mode you
            change in the dashboard takes effect without restarting the API.
    """
    app = FastAPI(title="JobPilot engine", docs_url=None, redoc_url=None)
    app.state.db_path = db_path
    app.state.answers_path = answers_path
    app.state.write_lock = threading.Lock()  # one change to answers.json at a time (see api_deps.get_write_lock)
    app.state.settings_source = (lambda: settings) if settings is not None else load_settings

    init = db.connect(db_path)
    try:
        db.init_db(init)  # a fresh install gets its tables; an existing database is left as it is
    finally:
        init.close()

    @app.middleware("http")
    async def local_only_guard(request: Request, call_next: Callable):  # type: ignore[no-untyped-def]
        """Refuse requests whose Host or Origin says they do not come from you, on this computer."""
        if _host_name(request.headers.get("host", "")) not in LOCAL_HOSTS:
            return JSONResponse({"detail": "Host not allowed: the engine only answers on 127.0.0.1."}, status_code=403)
        origin = request.headers.get("origin")
        if origin is not None and request.method in CHANGING_METHODS and origin not in DASHBOARD_ORIGINS:
            return JSONResponse({"detail": "Origin not allowed: only the dashboard may change things."}, status_code=403)
        return await call_next(request)

    # Added after the guard, so it is the outer layer and answers the browser's preflight questions.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(DASHBOARD_ORIGINS),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health")
    def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
        """Is the engine up, and in which run mode? (Read only: this API cannot change the mode.)"""
        return {"status": "ok", "run_mode": settings.run_mode}

    # ---- read endpoints (4.4c): look only, nothing here changes anything ----

    @app.get("/unknown")
    def unknown(conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> list[UnknownOut]:
        """Questions the bot could not answer, most-seen first. You answer them in the dashboard."""
        return [UnknownOut.from_row(r) for r in learning.open_unknowns(conn)]

    @app.get("/wordings")
    def wordings(conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> list[WordingOut]:
        """New wordings waiting for your approval, most-seen first."""
        out = []
        for row in learning.pending_wordings(conn):
            kinds = {r["kind"] for r in conn.execute("SELECT kind FROM answers WHERE question = ?", (row["matched_question"],))}
            kind: Kind = "protected" if row["protected"] or "protected" in kinds else ("open" if "open" in kinds else "fixed")
            out.append(WordingOut.from_row(row, kind))
        return out

    @app.get("/answers")
    def answers(conn: Annotated[sqlite3.Connection, Depends(get_conn)]) -> list[AnswerOut]:
        """Every saved answer with its other wordings, ordered by question, then scope and city."""
        aliases: dict[str, list[str]] = {}
        for r in conn.execute("SELECT question, alias FROM answer_aliases ORDER BY alias"):
            aliases.setdefault(r["question"], []).append(r["alias"])
        rows = conn.execute("SELECT * FROM answers ORDER BY lower(question), location_scope, city").fetchall()
        return [AnswerOut.from_row(r, aliases.get(r["question"], [])) for r in rows]

    @app.get("/fills")
    def fills(
        conn: Annotated[sqlite3.Connection, Depends(get_conn)],
        status: FillStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[FillOut]:
        """The filled pages history, newest first. ``?status=filled`` shows what still needs a decision."""
        return [FillOut.from_row(r) for r in list_fills(conn, status, limit)]

    app.include_router(write_router)  # the endpoints that change things (4.4d)
    install_error_handlers(app)
    return app


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    """Start the API. Refuses any ``host`` that is not this computer (see :func:`check_local_host`)."""
    uvicorn.run(create_app(), host=check_local_host(host), port=port, log_level="info")


def main(argv: list[str] | None = None) -> int:
    """``python -m engine.api [--host 127.0.0.1] [--port 8000]``."""
    parser = argparse.ArgumentParser(prog="python -m engine.api", description="Start the JobPilot engine API (this computer only).")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    try:
        serve(args.host, args.port)
    except NotLocalError as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
