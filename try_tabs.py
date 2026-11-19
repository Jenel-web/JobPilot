"""Throwaway diagnostic: what does the browser know about every open tab? Read-only. Delete when done.

Usage:  python try_tabs.py
"""

from playwright.sync_api import sync_playwright

from engine.forms import jobfinder
from engine.forms.reader import connect_to_bot_browser

with sync_playwright() as p:
    browser = connect_to_bot_browser(p)
    print("CONTEXTS:", len(browser.contexts))
    for c, ctx in enumerate(browser.contexts):
        print(f"\n== context {c}: {len(ctx.pages)} tab(s)")
        # Chrome's own record of who opened whom (works even when Playwright's opener() says None).
        openers: dict[str, str] = {}
        if ctx.pages:
            try:
                session = ctx.new_cdp_session(ctx.pages[0])
                for t in session.send("Target.getTargets")["targetInfos"]:
                    if t.get("type") == "page":
                        openers[t["targetId"]] = t.get("openerId", "")
            except Exception as exc:  # noqa: BLE001 - diagnostic only
                print("  (could not read Chrome's target list:", exc, ")")
        for i, page in enumerate(ctx.pages):
            text = jobfinder.tab_text(page)
            try:
                referrer = page.evaluate("document.referrer")
            except Exception:  # noqa: BLE001
                referrer = "?"
            print(f"\n[{i}] {page.url[:110]}")
            print("    title    :", page.title()[:80])
            print("    opener() :", page.opener().url[:80] if page.opener() else None)
            print("    referrer :", referrer[:110] or "(empty)")
            print("    words    :", len(text.split()), "| headings:", jobfinder.count_headings(text),
                  "| looks like a post:", jobfinder.looks_like_job_post(text))
            lowered = text.lower()
            for needle in ("egoist", "apply on employer", "responsibilit", "qualification"):
                at = lowered.find(needle)
                if at >= 0:
                    print(f"    has {needle!r}: ...{text[max(0, at - 40):at + 60]!r}")
    print("\n(Chrome opener ids, any tab with a value was opened by another tab):", {k[:6]: v[:6] for k, v in openers.items()})
