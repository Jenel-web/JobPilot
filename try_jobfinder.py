"""Throwaway check for the job post finder. Read-only. Delete this file when you're done (don't commit it).

Usage:
    python try_jobfinder.py                 # the tab you are looking at
    python try_jobfinder.py docs.google     # the first tab whose address contains this text (e.g. the form)
"""

import sys

from playwright.sync_api import sync_playwright

from engine.forms import jobfinder
from engine.forms.reader import connect_to_bot_browser, find_current_page

wanted = sys.argv[1] if len(sys.argv) > 1 else ""

with sync_playwright() as p:
    browser = connect_to_bot_browser(p)
    if wanted:
        pages = [pg for ctx in browser.contexts for pg in ctx.pages if wanted in pg.url]
        if not pages:
            raise SystemExit(f"No open tab has {wanted!r} in its address.")
        page = pages[0]
    else:
        page = find_current_page(browser)

    result = jobfinder.find_job_post(page)
    print("FORM PAGE:", page.url)
    chrome_opener = jobfinder.opener_of(page)
    print("OPENER   :", chrome_opener.url[:100] if chrome_opener else None, "(Playwright says:", page.opener(), ")")
    for tab in page.context.pages:
        t = jobfinder.tab_text(tab)
        print(f"  tab {tab.url[:70]!r}: words={len(t.split())} headings={jobfinder.count_headings(t)} "
              f"repeated_share={jobfinder.repeated_line_share(t):.2f} post={jobfinder.looks_like_job_post(t)}")
    print("FOUND    :", result.post.label if result.post else "NOT FOUND (you would be asked)")
    if result.post:
        text = result.post.text
        print("SOURCE   :", result.post.source, "|", result.post.tab_url)
        print("WORDS    :", len(text.split()), "| HEADINGS:", jobfinder.count_headings(text))
        print("HEADING LINES THAT MATCHED:")
        for line in text.splitlines():
            clean = line.strip(" \t:-•*#").lower()
            if clean and len(clean) <= jobfinder.MAX_HEADING_CHARS and any(h.fullmatch(clean) for h in jobfinder._HEADINGS):
                print("   -", line.strip())
    print("TABS     :", [(t.index, t.title[:30], t.url[:60]) for t in result.tabs])
