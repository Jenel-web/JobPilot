"""Where is the job? Read it from the job post text, then decide the relocation stance.

This is plain keyword matching, NOT AI: it is predictable, it is easy to test, and a wrong guess can never
invent a place. The job post text is whatever the page shows (title, location line, description).

Rules (yours, from the planning chat):
  * remote job                      -> relocation is not needed: YES
  * job in Metro Manila (commutable) -> YES, no move needed
  * anything else, or no location found -> NO (the default; it is flagged for you to check)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

LocationKind = Literal["remote", "metro_manila", "unknown"]

# Cities and areas you can commute to. Geography only: nothing personal lives in this file.
METRO_MANILA = (
    "metro manila", "metropolitan manila", "ncr", "national capital region",
    "manila", "quezon city", "makati", "taguig", "bgc", "bonifacio global city", "fort bonifacio", "pasig", "ortigas",
    "mandaluyong", "san juan", "marikina", "pasay", "paranaque", "las pinas", "muntinlupa", "alabang",
    "caloocan", "valenzuela", "malabon", "navotas", "pateros", "eastwood", "mckinley", "cubao",
)
_REMOTE = re.compile(r"\b(?:remote(?:ly)?|work[- ]from[- ]home|wfh|telecommut\w*|work from anywhere)\b", re.I)
_NOT_REMOTE = re.compile(r"\b(?:not|non|no|isn't|is not)[- ]+(?:available[- ]+)?(?:for[- ]+)?remote\b|remote (?:work )?(?:is )?not (?:available|offered|possible)", re.I)
_METRO = re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(c) for c in sorted(METRO_MANILA, key=len, reverse=True)) + r")(?![a-z])")


@dataclass(frozen=True)
class JobLocation:
    """Where the job is. ``evidence`` is the words that showed it, so you can check the guess."""

    kind: LocationKind
    evidence: str


@dataclass(frozen=True)
class Stance:
    """The relocation answer decided by code. ``reason`` is what the AI may say to the employer (so no internal talk)."""

    yes: bool
    reason: str


def _plain(text: str) -> str:
    """Lower case without accents ("Parañaque" -> "paranaque")."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def is_metro_manila(city: str) -> bool:
    """True if ``city`` is one of the Metro Manila places in :data:`METRO_MANILA`."""
    return bool(city.strip()) and _METRO.search(_plain(city)) is not None


def read_job_location(text: str = "", *, scope: str = "any", city: str = "") -> JobLocation:
    """Where the job is, from the job post ``text``; if there is none, from ``scope`` and ``city``.

    The text wins over the scope. A Metro Manila place beats the word "remote" ("Hybrid: Makati or remote").
    Nothing found means ``unknown``, and unknown is treated as "not commutable".
    """
    if text.strip():
        plain = _plain(text)
        place = _METRO.search(plain)
        if place:
            return JobLocation("metro_manila", place.group(0))
        remote = _REMOTE.search(text)
        if remote and not _NOT_REMOTE.search(text):
            return JobLocation("remote", remote.group(0))
        return JobLocation("unknown", "")
    if scope == "remote":
        return JobLocation("remote", "remote")
    if scope == "city" and is_metro_manila(city):
        return JobLocation("metro_manila", city.strip())
    return JobLocation("unknown", "")


def relocation_stance(location: JobLocation) -> Stance:
    """Yes for a remote or Metro Manila job, no for everything else (including "location not found")."""
    if location.kind == "remote":
        return Stance(True, "the job is remote, so there is no move involved")
    if location.kind == "metro_manila":
        return Stance(True, f"the job is in {location.evidence.title()}, in Metro Manila, which can be commuted to, so no move is needed")
    return Stance(False, "I am not willing to relocate, but I can commute within Metro Manila or work remotely")
