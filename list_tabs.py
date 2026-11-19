"""Throwaway helper: list the tabs open in the bot's browser, so you know what to type after --tab.
Prints only addresses and titles, never page text. Delete when done (don't commit it).

Usage:  python list_tabs.py
"""

from playwright.sync_api import sync_playwright

from engine.forms.reader import connect_to_bot_browser

with sync_playwright() as p:
    browser = connect_to_bot_browser(p)
    pages = [pg for ctx in browser.contexts for pg in ctx.pages]
    print(f"{len(pages)} tab(s) open in the bot's browser:\n")
    for number, page in enumerate(pages):
        try:
            showing = page.evaluate("document.visibilityState") == "visible"
        except Exception:  # noqa: BLE001 - a tab that is still loading
            showing = False
        print(f"[{number}] {'<- YOU ARE LOOKING AT THIS ONE' if showing else ''}")
        print(f"    address: {page.url}")
        print(f"    title  : {page.title()[:80]}\n")
