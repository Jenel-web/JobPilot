"""The on-page Fill panel (SPEC Part 2, 1b; design/screens/FillPanel.html): "Fill this page" on the job page itself.

How it works, in three parts:

1. **The panel** is drawn by a script that Playwright adds to every page of the bot's browser
   (``context.add_init_script``). It lives in a *closed* shadow DOM: the website's CSS cannot change it, and the
   website's scripts cannot see inside it.
2. **The bridge** is a function the panel calls to reach Python (``context.expose_binding``). Playwright puts that
   function on ``window``, where the website's own scripts could call it too. So:
   * the panel script runs BEFORE any website script, keeps the function in its own closure and deletes it from
     ``window``;
   * every call must carry a secret token made fresh each time the browser opens (only the panel's closure has it);
   * calls from embedded frames are refused, and the panel ignores clicks a script fakes (``event.isTrusted``).
3. **The engine** does the real work. The bridge forwards the panel's requests to the engine API on 127.0.0.1
   (``/status``, ``/jobpost``, ``POST /fill``, ``GET /fill/{id}``), the same calls the dashboard makes, so the panel
   and the dashboard give the same result. The page itself never makes an HTTP call.

Never submits: the panel only asks the engine to fill, and the filler only types into fields. The panel docks at the
top right and moves aside if it would cover a Submit / Apply / Next button.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from engine.settings import ROOT

logger = logging.getLogger(__name__)

BRIDGE_NAME = "__jobpilot_bridge"
ENGINE_URL = "http://127.0.0.1:8000"
DASHBOARD_URL = "http://localhost:3000"
TOKENS_CSS = ROOT / "design" / "tokens.css"
_JOB_ID = re.compile(r"^[0-9a-f]{1,32}$")
MAX_POST_CHARS = 200_000

ApiCall = Callable[[str, str, "dict[str, Any] | None"], "dict[str, Any]"]


# ---- talking to the engine API ---------------------------------------------------------------------------------


def http_api(method: str, path: str, body: dict[str, Any] | None = None, *, base: str = ENGINE_URL, timeout: float = 15) -> dict[str, Any]:
    """Call the engine API on 127.0.0.1 and return ``{"ok": True, "data": ...}`` or ``{"ok": False, "error": ...}``.

    Never raises: the panel shows the error in plain words instead.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        base + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed 127.0.0.1 address
            raw = response.read()
            return {"ok": True, "data": json.loads(raw) if raw else None}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, **_error_of(exc.read())}
    except (urllib.error.URLError, OSError, ValueError):
        return {"ok": False, "code": "engine_unreachable", "error": "The engine isn't running. Start it with: python -m engine.api"}


def _error_of(raw: bytes) -> dict[str, str]:
    """The engine's ``{code, detail}`` (or FastAPI's list of problems) as one plain sentence."""
    try:
        body = json.loads(raw)
    except ValueError:
        return {"code": "unknown", "error": "The engine answered with an error."}
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, list) and detail:
        return {"code": "invalid", "error": str(detail[0].get("msg", "The request was not valid.")).replace("Value error, ", "")}
    return {"code": str(body.get("code", "unknown")) if isinstance(body, dict) else "unknown", "error": str(detail or "The engine answered with an error.")}


# ---- the bridge: what the panel may ask ----------------------------------------------------------------------------


class PanelBridge:
    """Answers the panel's calls. Anything without the token, from a frame, or not on the list is refused.

    The page can only ask for four things, and can only send three fill choices. The page to fill is ALWAYS the
    page the panel sits on (taken from Playwright, not from the page), so a page cannot ask to fill another tab.
    """

    REFUSED = {"ok": False, "code": "refused", "error": "Refused."}

    def __init__(self, token: str, api: ApiCall = http_api) -> None:
        self._token = token
        self._api = api

    def __call__(self, source: dict[str, Any], payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or not hmac.compare_digest(str(payload.get("token", "")), self._token):
            logger.warning("Fill panel: refused a call without the right token")
            return self.REFUSED
        page, frame = source.get("page"), source.get("frame")
        if page is None or frame is None or frame != page.main_frame:
            logger.warning("Fill panel: refused a call from an embedded frame")
            return self.REFUSED
        action, data = payload.get("action"), payload.get("data") or {}
        if not isinstance(data, dict):
            return self.REFUSED
        if action == "status":
            return self._api("GET", "/status", None)
        if action == "jobpost":
            return self._api("GET", "/jobpost", None)
        if action == "job":
            job_id = str(data.get("job_id", ""))
            return self._api("GET", f"/fill/{job_id}", None) if _JOB_ID.match(job_id) else self.REFUSED
        if action == "fill":
            return self._api("POST", "/fill", fill_body(data, page.url))
        return self.REFUSED


def fill_body(data: dict[str, Any], page_url: str) -> dict[str, Any]:
    """The ``POST /fill`` body from the panel's choices: only ``post_text``, ``post_tab_url`` or ``no_resume``.

    ``tab`` is set to the panel's own page by Python; anything else the page sends is dropped.
    """
    body: dict[str, Any] = {"tab": page_url}
    if data.get("no_resume") is True:
        body["no_resume"] = True
    elif isinstance(data.get("post_text"), str) and data["post_text"].strip():
        body["post_text"] = data["post_text"][:MAX_POST_CHARS]
    elif isinstance(data.get("post_tab_url"), str) and data["post_tab_url"]:
        body["post_tab_url"] = data["post_tab_url"][:2000]
    return body


# ---- the panel script -------------------------------------------------------------------------------------------------


def token_vars() -> str:
    """The light-theme ``--jp-*`` variables from design/tokens.css (the single source of truth for values)."""
    css = TOKENS_CSS.read_text(encoding="utf-8")
    root = css[css.index(":root {"): css.index("}", css.index(":root {"))]
    return " ".join(m.group(0) for m in re.finditer(r"--jp-[\w-]+:\s*[^;]+;", root))


def panel_script(token: str, *, shadow_mode: str = "closed", dashboard_url: str = DASHBOARD_URL) -> str:
    """The script added to every page. ``shadow_mode="open"`` is for tests only (so they can look inside)."""
    if shadow_mode not in ("closed", "open"):
        raise ValueError("shadow_mode must be 'closed' or 'open'")
    return (
        _PANEL_JS.replace("__BRIDGE__", json.dumps(BRIDGE_NAME))
        .replace("__TOKEN__", json.dumps(token))
        .replace("__SHADOW__", json.dumps(shadow_mode))
        .replace("__VARS__", json.dumps(token_vars()))
        .replace("__DASHBOARD__", json.dumps(dashboard_url))
    )


def install_panel(context: Any, token: str, *, api: ApiCall = http_api, shadow_mode: str = "closed") -> None:
    """Add the bridge and the panel to every page of ``context`` (and to the pages already open).

    The bridge is added FIRST, so it exists when the panel script runs and hides it.
    """
    context.expose_binding(BRIDGE_NAME, PanelBridge(token, api))
    script = panel_script(token, shadow_mode=shadow_mode)
    context.add_init_script(script)
    for page in context.pages:
        try:
            page.evaluate(script)
        except Exception:  # noqa: BLE001 - a page that is still loading gets the init script anyway
            pass


_PANEL_JS = r"""
(() => {
  const BRIDGE = __BRIDGE__;
  let call = null;
  try { call = window[BRIDGE]; } catch (e) {}
  try { delete window[BRIDGE]; } catch (e) {}
  try { if (window[BRIDGE] !== undefined) Object.defineProperty(window, BRIDGE, {value: undefined, configurable: true}); } catch (e) {}
  if (typeof call !== 'function' || window.top !== window) return;  // only the top page shows the panel

  const TOKEN = __TOKEN__, SHADOW = __SHADOW__, VARS = __VARS__, DASHBOARD = __DASHBOARD__;
  const ask = (action, data) => Promise.resolve(call({token: TOKEN, action, data: data || {}}))
    .catch(() => ({ok: false, error: 'JobPilot lost its link to this window. Reload the page.'}));
  const S = {open: false, userMoved: false, mode: '', view: 'loading', post: null, tabs: [], picked: '', pasted: '',
             fromChange: false, result: null, error: '', started: 0, jobId: ''};
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const MODES = {mock: ['MOCK', 'm-mock'], dry_run: ['DRY RUN', 'm-dry'], live: ['LIVE', 'm-live']};
  const FLAG = '<svg viewBox="0 0 16 16"><path d="M8 1.5 15 14H1z"/></svg>';
  let host = null, root = null, timer = null, ticker = null;

  const CSS = `:host{all:initial;${VARS}}
  *{box-sizing:border-box;font-family:var(--jp-font-sans);}
  .panel{width:320px;background:var(--jp-surface);color:var(--jp-ink);border:1px solid var(--jp-line);border-radius:var(--jp-radius-card);box-shadow:var(--jp-shadow-overlay);font-size:14px;display:flex;flex-direction:column}
  .p-head{display:flex;align-items:center;gap:8px;height:44px;padding:0 8px 0 14px;border-bottom:1px solid var(--jp-line-soft)}
  .name{font-size:14px;font-weight:600}
  .mode{display:inline-flex;align-items:center;height:22px;padding:0 8px;border-radius:var(--jp-radius-control);font-size:12px;font-weight:600;letter-spacing:.02em}
  .m-mock{background:var(--jp-muted-bg);color:var(--jp-ink-2)} .m-dry{background:var(--jp-status-queued-bg);color:var(--jp-status-queued)} .m-live{background:var(--jp-danger);color:#fff}
  .grip{margin-left:auto;color:var(--jp-line-strong);letter-spacing:2px;font-size:12px;cursor:grab;user-select:none;padding:4px}
  .iconbtn{width:28px;height:28px;border:0;background:transparent;border-radius:var(--jp-radius-control);display:inline-flex;align-items:center;justify-content:center;color:var(--jp-ink-2);cursor:pointer;font-size:16px}
  .p-body{padding:14px;display:flex;flex-direction:column;gap:12px}
  .job{display:flex;flex-direction:column;gap:2px;font-size:13px}
  .k{color:var(--jp-ink-2);font-weight:500;font-size:13px}
  .row{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
  .v{font-weight:500;line-height:1.35}
  .muted{color:var(--jp-ink-2);font-weight:400}
  .link{font-size:14px;font-weight:500;color:var(--jp-brand);white-space:nowrap;background:none;border:0;padding:0;cursor:pointer;text-decoration:none}
  .btn{display:inline-flex;align-items:center;justify-content:center;height:36px;padding:0 16px;border-radius:var(--jp-radius-control);font-size:14px;font-weight:500;border:1px solid var(--jp-line-strong);background:var(--jp-surface);color:var(--jp-ink);cursor:pointer}
  .btn.primary{background:var(--jp-brand);border-color:var(--jp-brand);color:#fff;font-weight:600}
  .btn:disabled{opacity:.45;cursor:default}
  .block{width:100%}
  .note{font-size:13px;color:var(--jp-ink-2);line-height:1.45;margin:0}
  .status{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--jp-ink-2);margin:0}
  .spin{width:14px;height:14px;border-radius:50%;border:2px solid var(--jp-line);border-top-color:var(--jp-brand);animation:sp .9s linear infinite;flex:0 0 14px}
  @keyframes sp{to{transform:rotate(360deg)}}
  .result{display:flex;flex-direction:column;gap:6px;padding:12px;border-radius:var(--jp-radius-control);background:var(--jp-brand-tint)}
  .big{font-size:14px;font-weight:600;color:var(--jp-brand)}
  .flag{display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:500;color:var(--jp-amber-text)}
  .flag svg{width:14px;height:14px;fill:var(--jp-amber);flex:0 0 14px}
  .chips{display:flex;flex-wrap:wrap;gap:6px}
  .chip{display:inline-flex;align-items:center;height:24px;padding:0 10px;border-radius:999px;background:var(--jp-status-new-bg);color:var(--jp-status-new);font-size:13px;font-weight:500}
  .banner{padding:10px 12px;border-radius:var(--jp-radius-control);background:var(--jp-amber-bg);border:1px solid var(--jp-amber-border);color:var(--jp-amber-text);font-size:13px;line-height:1.45}
  .tabs{display:flex;flex-direction:column;gap:6px}
  .tabrow{display:flex;flex-direction:column;gap:1px;padding:8px 10px;border:1px solid var(--jp-line);border-radius:var(--jp-radius-control);font-size:13px;background:var(--jp-surface);text-align:left;cursor:pointer;color:var(--jp-ink)}
  .tabrow.on{border-color:var(--jp-brand);background:var(--jp-brand-tint)}
  .tabrow b{font-weight:600;line-height:1.3} .tabrow span{color:var(--jp-ink-2);font-size:12px}
  textarea{width:100%;min-height:54px;border:1px dashed var(--jp-line-strong);border-radius:var(--jp-radius-control);padding:8px 10px;font-size:13px;color:var(--jp-ink);background:var(--jp-ground);resize:vertical}
  .actions{display:flex;align-items:center;justify-content:space-between;gap:8px}
  .tab{width:36px;padding:12px 0;display:flex;flex-direction:column;align-items:center;gap:8px;background:var(--jp-surface);border:1px solid var(--jp-line);border-right:0;border-radius:var(--jp-radius-card) 0 0 var(--jp-radius-card);box-shadow:var(--jp-shadow-overlay);cursor:pointer;color:var(--jp-brand);font-size:13px;font-weight:600}
  .tab .dot{width:8px;height:8px;border-radius:50%;background:var(--jp-status-submitted)}
  .tab .lbl{writing-mode:vertical-rl}`;

  // ---- what the page looks like: an application form? (by code, no AI) ----
  const looksLikeForm = () => [...document.querySelectorAll('input, select, textarea')].filter(e =>
    !['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes((e.type || '').toLowerCase()) && e.getClientRects().length > 0).length >= 3;

  // ---- never cover the site's Submit / Apply / Next button ----
  const SUBMITS = 'button, input[type=submit], input[type=button], [role=button]';
  const isSubmitLike = e => (e.type || '').toLowerCase() === 'submit' || /\b(submit|apply|send|next|continue)\b/i.test(e.innerText || e.value || '');
  const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  const avoidSubmit = () => {
    if (!host || !S.open || S.userMoved) return;
    host.style.left = 'auto'; host.style.right = '16px';
    const box = host.getBoundingClientRect();
    const hit = [...document.querySelectorAll(SUBMITS)].some(e => isSubmitLike(e) && e.getClientRects().length && overlaps(box, e.getBoundingClientRect()));
    if (hit) { host.style.right = 'auto'; host.style.left = '16px'; }
  };

  // ---- drawing ----
  const head = () => {
    const m = MODES[S.mode];
    return `<div class="p-head"><span class="name">JobPilot</span>${m ? `<span class="mode ${m[1]}">${m[0]}</span>` : ''}
      <span class="grip" data-drag title="Drag">&#8942;&#8942;</span><button class="iconbtn" data-act="min" aria-label="Collapse">&#8211;</button></div>`;
  };
  const jobBlock = (title, withChange) => {
    const text = S.view === 'loading' ? '<span class="muted">Checking this page…</span>'
      : S.choiceLabel ? esc(S.choiceLabel) : S.post ? esc(S.post.label) : '<span class="muted">Found when you press Fill</span>';
    return `<div class="job"><span class="k">${title}</span><div class="row"><span class="v">${text}</span>${withChange ? '<button class="link" data-act="change">Change</button>' : ''}</div></div>`;
  };
  const views = {
    loading: () => `${jobBlock('Job post', false)}<button class="btn primary block" disabled>Fill this page</button>`,
    ready: () => `${jobBlock('Job post', true)}<button class="btn primary block" data-act="fill">Fill this page</button>
      <p class="note">Nothing is submitted. You review the form and click Submit yourself.</p>`,
    filling: () => `${jobBlock('Job post', false)}<p class="status"><span class="spin"></span>Filling… <span data-secs>${Math.round((Date.now() - S.started) / 1000)}</span> s</p>
      <button class="btn primary block" disabled>Filling…</button><p class="note">Don't type in the form until it is done.</p>`,
    done: () => {
      const r = S.result || {}, q = (r.unknown_ids || []).length;
      return `<div class="result"><span class="big">Done. Review the form, then submit it yourself.</span>
        <div class="chips"><span class="chip">${r.filled || 0} filled</span>${q ? `<span class="chip">${q} new question${q > 1 ? 's' : ''}</span>` : ''}
        <span class="chip">${r.resume_id ? 'Resume ' + esc(r.resume_id) : 'No resume'}</span></div>
        ${r.flagged ? `<span class="flag">${FLAG}${r.flagged} flagged (guessed or needs you). Highlighted in amber on the page.</span>` : ''}</div>
        ${(r.messages || []).map(m => `<p class="note">${esc(m)}</p>`).join('')}
        ${jobBlock('Job post used', true)}
        <div class="actions"><button class="btn" data-act="fill">Fill this page again</button><a class="link" href="${esc(DASHBOARD)}" target="_blank" rel="noreferrer">Open dashboard</a></div>`;
    },
    picker: () => `${S.fromChange ? '<span class="k">Choose the job post for this page</span>'
        : '<div class="banner"><b>Job post not found.</b> I can\'t pick a resume without it, so none will be uploaded until you choose one.</div>'}
      <span class="k">Pick the tab with the job post</span>
      <div class="tabs">${S.tabs.length ? S.tabs.map(t => `<button class="tabrow${t.url === S.picked ? ' on' : ''}" data-act="pick" data-url="${esc(t.url)}"><b>${esc(t.title || '(untitled tab)')}</b><span>${esc(t.url.replace(/^https?:\/\//, '').slice(0, 60))}</span></button>`).join('')
        : '<span class="note">No other tabs are open.</span>'}</div>
      <span class="k">Or paste the job post text:</span><textarea data-field="paste" placeholder="Paste here…">${esc(S.pasted)}</textarea>
      <button class="btn primary block" data-act="use" ${S.picked || S.pasted.trim() ? '' : 'disabled'}>Use this job post and fill</button>
      <button class="btn block" data-act="noresume">Fill without resume</button>
      ${S.fromChange ? '<button class="link" data-act="cancel">Cancel</button>' : ''}`,
    error: () => `<div class="banner">${esc(S.error)}</div><button class="btn block" data-act="retry">Try again</button>`,
  };

  const render = () => {
    clearInterval(ticker);
    // Same top z-index as the filler's amber highlights: the LAST element wins, so the panel moves itself last.
    if (host.nextElementSibling) document.documentElement.appendChild(host);
    if (!S.open) {
      root.innerHTML = `<style>${CSS}</style><button class="tab" data-act="open" aria-label="Open JobPilot"><span class="dot"></span><span class="lbl">JobPilot</span></button>`;
      host.style.top = '40%'; host.style.left = 'auto'; host.style.right = '0';
      return;
    }
    root.innerHTML = `<style>${CSS}</style><div class="panel" role="dialog" aria-label="JobPilot">${head()}<div class="p-body">${views[S.view]()}</div></div>`;
    if (!S.userMoved) { host.style.top = '56px'; }
    avoidSubmit();
    if (S.view === 'filling') ticker = setInterval(() => {
      const el = root.querySelector('[data-secs]'); if (el) el.textContent = Math.round((Date.now() - S.started) / 1000);
    }, 1000);
  };

  // ---- talking to JobPilot (through the bridge) ----
  const fail = msg => { S.view = 'error'; S.error = msg || 'Something went wrong.'; render(); };
  const load = async () => {
    S.view = 'loading'; render();
    const st = await ask('status');
    if (!st.ok) return fail(st.error);
    S.mode = st.data.run_mode;
    if (st.data.fill_running && st.data.fill_job_id) { S.jobId = st.data.fill_job_id; S.view = 'filling'; S.started = Date.now(); render(); return poll(); }
    const jp = await ask('jobpost');
    if (jp.ok) { S.post = jp.data.post; S.tabs = jp.data.tabs || []; S.view = jp.data.post ? 'ready' : 'picker'; S.fromChange = false; }
    else { S.post = null; S.view = 'ready'; }
    render();
  };
  const poll = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const r = await ask('job', {job_id: S.jobId});
      if (!r.ok) return fail(r.error);
      if (r.data.status === 'running') return poll();
      if (r.data.status === 'done') { S.result = r.data.result; if (S.result && S.result.post) { S.post = S.result.post; S.choiceLabel = ''; } S.view = 'done'; return render(); }
      fail(r.data.error || 'The fill stopped. Check the page: nothing was submitted.');
    }, 1500);
  };
  const fill = async (body, label) => {
    S.choiceLabel = label || ''; S.view = 'filling'; S.started = Date.now(); S.error = ''; render();
    const r = await ask('fill', body || {});
    if (!r.ok) return fail(r.error);
    S.jobId = r.data.job_id; poll();
  };

  const ACTS = {
    open: () => { S.open = true; render(); load(); },
    min: () => { S.open = false; S.touched = true; render(); },
    fill: () => fill({}, S.choiceLabel),
    change: () => { S.view = 'picker'; S.fromChange = true; render(); },
    cancel: () => { S.view = S.result ? 'done' : 'ready'; render(); },
    pick: t => { S.picked = t.getAttribute('data-url'); S.pasted = ''; render(); },
    use: () => {
      if (S.pasted.trim()) return fill({post_text: S.pasted}, 'Text you pasted');
      const tab = S.tabs.find(t => t.url === S.picked);
      if (tab) fill({post_tab_url: tab.url}, (tab.title || tab.url) + ' (tab you picked)');
    },
    noresume: () => fill({no_resume: true}, 'None · no resume uploaded'),
    retry: () => load(),
  };

  const start = () => {
    if (document.documentElement.querySelector(':scope > jobpilot-panel')) return;  // already drawn on this page
    host = document.createElement('jobpilot-panel');
    host.style.cssText = 'position:fixed;top:56px;right:16px;z-index:2147483647;display:block';
    root = host.attachShadow({mode: SHADOW});
    document.documentElement.appendChild(host);
    root.addEventListener('click', e => {
      if (!e.isTrusted) return;  // a click a script faked is ignored: only YOUR clicks count
      const t = e.target.closest('[data-act]');
      if (t && !t.disabled && ACTS[t.getAttribute('data-act')]) ACTS[t.getAttribute('data-act')](t);
    });
    root.addEventListener('input', e => {
      if (e.target.matches && e.target.matches('textarea[data-field=paste]')) {
        S.pasted = e.target.value; if (S.pasted.trim()) S.picked = '';
        const use = root.querySelector('[data-act=use]'); if (use) use.disabled = !(S.picked || S.pasted.trim());
        root.querySelectorAll('.tabrow.on').forEach(x => x.classList.remove('on'));
      }
    });
    root.addEventListener('mousedown', e => {  // drag the panel aside by its grip
      if (!e.isTrusted || !e.target.closest('[data-drag]')) return;
      const box = host.getBoundingClientRect(), dx = e.clientX - box.left, dy = e.clientY - box.top;
      const move = m => { S.userMoved = true; host.style.right = 'auto'; host.style.left = Math.max(0, m.clientX - dx) + 'px'; host.style.top = Math.max(0, m.clientY - dy) + 'px'; };
      const up = () => { window.removeEventListener('mousemove', move, true); window.removeEventListener('mouseup', up, true); };
      window.addEventListener('mousemove', move, true); window.addEventListener('mouseup', up, true);
      e.preventDefault();
    });
    window.addEventListener('resize', avoidSubmit);
    window.addEventListener('scroll', avoidSubmit, {passive: true});
    S.open = looksLikeForm();
    render();
    if (S.open) load();
    else [1500, 4000].forEach(ms => setTimeout(() => {  // forms drawn late by the site's own scripts
      if (!S.open && !S.touched && looksLikeForm()) { S.open = true; render(); load(); }
    }, ms));
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})()
"""
