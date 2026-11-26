/** Small text helpers shared by the v0 screens. */

/**
 * A short, readable form of a page address: "careers.shopee.sg/apply" for a website,
 * "saved page: sample_form.html" for a local test file. Never throws on odd input.
 */
export function shortUrl(url: string | null | undefined, max = 48): string {
  if (!url) return "";
  try {
    const u = new URL(url);
    if (u.protocol === "file:") return `saved page: ${decodeURIComponent(u.pathname.split("/").pop() ?? "")}`;
    const text = `${u.host.replace(/^www\./, "")}${u.pathname === "/" ? "" : u.pathname}`;
    return text.length > max ? `${text.slice(0, max - 1)}…` : text;
  } catch {
    return url.length > max ? `${url.slice(0, max - 1)}…` : url;
  }
}

/** True for addresses a browser tab can open from the dashboard (http/https); local files are not linked. */
export function isWebUrl(url: string | null | undefined): url is string {
  return !!url && /^https?:\/\//i.test(url);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * The engine's time stamps ("2026-11-22 10:23:34") are UTC: SQLite's datetime('now'). Show them in YOUR time:
 * "Nov 22, 18:23" in Manila (or "Nov 22" with `withTime` false). Never throws on odd input.
 */
export function dateLabel(stamp: string | null | undefined, withTime = true): string {
  if (!stamp) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(stamp);
  if (!m) return stamp;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] ?? 0), +(m[5] ?? 0), +(m[6] ?? 0)));
  const day = `${MONTHS[d.getMonth()]} ${d.getDate()}`;
  if (!withTime || m[4] === undefined) return day;
  return `${day}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** "1 time" / "3 times", "1 question" / "2 questions". */
export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}
