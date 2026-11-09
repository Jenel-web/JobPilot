"""The bot's browser: a visible Chromium window with its OWN saved profile.

Why a separate profile (not your everyday Chrome)?
  * Your everyday profile holds every account you are logged into; the bot must
    never have access to those (spec security rule 5).
  * Chrome blocks automation on its default profile anyway.

Why a *persistent* profile?
  Cookies and logins are saved in ``data/browser_profile/`` between runs, so you
  log in to a site by hand ONCE. JobPilot never types or stores a password
  (CLAUDE.md rule 9).

How the reader reaches this window later:
  The window is started with a debugging port bound to 127.0.0.1 only. A second
  program (the reader / "Fill this page" button) can connect to the SAME window
  with ``connect_over_cdp(CDP_URL)`` and look at the page you opened.
"""

from __future__ import annotations

import logging
from pathlib import Path

from engine import safety
from engine.settings import ROOT, Settings

logger = logging.getLogger(__name__)

PROFILE_DIR: Path = ROOT / "data" / "browser_profile"
CDP_PORT = 9222
CDP_URL = f"http://127.0.0.1:{CDP_PORT}"

# 127.0.0.1 only: nothing outside this PC can reach the debugging port.
LAUNCH_ARGS = [
    f"--remote-debugging-port={CDP_PORT}",
    "--remote-debugging-address=127.0.0.1",
    "--start-maximized",
]


def open_browser(url: str | None = None, *, settings: Settings | None = None) -> None:
    """Open the bot's browser and keep it open until you close the window.

    Args:
        url: optional page to start on. You can also just type addresses into
            the window yourself; that is the normal way to use it.
        settings: override settings (tests). Defaults to ``settings.json``.

    Raises:
        safety.SafetyError: ``url`` is a real website while the run mode is ``mock``.
    """
    if url:
        safety.check("navigate", url, settings=settings)

    from playwright.sync_api import sync_playwright  # imported here: tests don't need a browser

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=False,  # visible: you log in and watch what happens
            no_viewport=True,  # use the real window size
            args=LAUNCH_ARGS,
        )
        page = context.pages[0] if context.pages else context.new_page()
        if url:
            page.goto(url)
        logger.info("Bot browser open. Close the window to stop.")
        context.wait_for_event("close", timeout=0)  # block until you close the window
