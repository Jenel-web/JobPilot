/** Words for the engine's codes, shared by Questions and Answer bank. */

import type { Kind, SavedAnswer, Scope } from "./api-types";

export const KIND_OPTIONS: Array<{ value: Kind; label: string; help: string }> = [
  { value: "fixed", label: "Fixed", help: "filled word for word" },
  { value: "open", label: "Open", help: "used as notes; the AI rewrites it for each form (flagged)" },
  { value: "protected", label: "Protected", help: "legal and eligibility; filled word for word, never touched by the AI" },
];

export const SCOPE_OPTIONS: Array<{ value: Scope; label: string }> = [
  { value: "any", label: "Any job" },
  { value: "city", label: "A specific city" },
  { value: "remote", label: "Remote" },
  { value: "abroad", label: "Abroad" },
];

/** "Any", "City · Makati", "Remote", "Abroad". */
export function scopeLabel(a: Pick<SavedAnswer, "location_scope" | "city">): string {
  switch (a.location_scope) {
    case "city":
      return `City · ${a.city || "?"}`;
    case "remote":
      return "Remote";
    case "abroad":
      return "Abroad";
    default:
      return "Any";
  }
}
