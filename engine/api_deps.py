"""Things every API endpoint can ask for (FastAPI "dependencies"): settings, a database connection, the write lock.

They live in their own module so ``engine/api.py`` and the route modules can both use them without importing each other.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from fastapi import Request

from engine import db
from engine.settings import Settings


def get_settings(request: Request) -> Settings:
    """The settings for this request."""
    return request.app.state.settings_source()


def get_conn(request: Request) -> Iterator:  # type: ignore[type-arg]
    """One database connection per request, closed afterwards. Never shared between requests."""
    conn = db.connect(request.app.state.db_path, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


def get_answers_path(request: Request) -> Path:
    """The ``answers.json`` this app edits (tests point it at a temporary file)."""
    return request.app.state.answers_path


def get_write_lock(request: Request) -> Iterator[None]:
    """Hold the write lock for the whole request.

    Changing ``answers.json`` is read, change, write. Two requests doing that at the same moment could each
    read the old file and the second write would silently erase the first change. One writer at a time
    prevents that. (Reads do not take the lock.)
    """
    with request.app.state.write_lock:
        yield
