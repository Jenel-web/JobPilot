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

/** The engine's "2026-11-25 14:02:31" as "Nov 25, 14:02" (or "Nov 25" with `withTime` false). */
export function dateLabel(stamp: string | null | undefined, withTime = true): string {
  if (!stamp) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(stamp) ?? /^(\d{4})-(\d{2})-(\d{2})/.exec(stamp);
  if (!m) return stamp;
  const day = `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}`;
  return withTime && m[4] ? `${day}, ${m[4]}:${m[5]}` : day;
}

/** "1 time" / "3 times", "1 question" / "2 questions". */
export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}
