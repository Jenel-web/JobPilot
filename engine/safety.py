"""Safety: ``check()`` before every action, and the action log.

CLAUDE.md rules 5-7: before each navigate, fill, upload, submit or send the
engine calls ``check()``; every action is written to ``action_log``.

In v0 this is deliberately small:
  * ``submit`` and ``send`` are ALWAYS refused (the form filler never clicks Submit).
  * In ``mock`` mode, real web addresses are refused (only saved fixture pages).
The kill switch, blocklist and daily caps arrive in v1/v2.
"""

from __future__ import annotations

import sqlite3

from engine.settings import RUN_MODES, Settings, load_settings

ACTION_KINDS = ("navigate", "read", "fill", "upload", "screenshot", "submit", "send", "error")
FORBIDDEN_IN_V0 = ("submit", "send")


class SafetyError(Exception):
    """Raised when an action is not allowed. Callers log it and skip that action."""


def check(kind: str, target: str = "", *, settings: Settings | None = None) -> None:
    """Raise :class:`SafetyError` unless this action is allowed right now.

    Args:
        kind: one of ``ACTION_KINDS``.
        target: the address or field the action is about.
        settings: override settings (tests). Defaults to ``settings.json``.
    """
    settings = settings or load_settings()
    if kind not in ACTION_KINDS:
        raise SafetyError(f"Unknown action kind: {kind!r}")
    if settings.run_mode not in RUN_MODES:
        raise SafetyError(f"Unknown run mode: {settings.run_mode!r}")
    if kind in FORBIDDEN_IN_V0:
        raise SafetyError(f"'{kind}' is never done automatically in v0: you submit yourself")
    if settings.run_mode == "mock" and kind == "navigate" and target.lower().startswith(("http://", "https://")):
        raise SafetyError("Mock mode only opens saved fixture pages, not real websites")
    if settings.run_mode == "mock" and kind in ("fill", "upload") and target.lower().startswith(("http://", "https://")):
        raise SafetyError("Mock mode only fills saved fixture pages, not real websites (set run_mode to dry_run to try a real page)")


def log_action(
    conn: sqlite3.Connection,
    kind: str,
    target: str = "",
    details: str = "",
    *,
    fill_id: int | None = None,
    screenshot_path: str | None = None,
) -> int:
    """Write one row to ``action_log`` and return its id.

    Never put phone, address, email or passwords in ``details``.
    """
    with conn:
        cursor = conn.execute(
            "INSERT INTO action_log (kind, target, details, screenshot_path, fill_id) VALUES (?, ?, ?, ?, ?)",
            (kind, target, details, screenshot_path, fill_id),
        )
    return int(cursor.lastrowid or 0)
