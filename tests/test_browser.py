"""Tests for the browser launcher. No real browser is ever started."""

from __future__ import annotations

import pytest

from engine import safety
from engine.forms import browser
from engine.settings import Settings


def test_profile_lives_inside_the_git_ignored_data_folder() -> None:
    assert browser.PROFILE_DIR.parts[-2:] == ("data", "browser_profile")


def test_debugging_port_is_bound_to_localhost_only() -> None:
    assert "--remote-debugging-address=127.0.0.1" in browser.LAUNCH_ARGS
    assert browser.CDP_URL.startswith("http://127.0.0.1:")


def test_mock_mode_refuses_a_real_website_before_any_browser_starts() -> None:
    with pytest.raises(safety.SafetyError):
        browser.open_browser("https://example.com", settings=Settings(run_mode="mock"))
