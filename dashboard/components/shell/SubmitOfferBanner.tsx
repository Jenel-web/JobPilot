"use client";

import { useState } from "react";
import { Banner } from "@/components/ui/Banner";
import { useToast } from "@/components/ui/Toast";
import { markFill } from "@/lib/api";
import { useEngine } from "./EngineProvider";

/**
 * Passive submit detection (engine/forms/submitwatch.py): after a fill, the engine watches the tab read-only and
 * may offer "Looks submitted. Mark it?". This banner shows that offer on every screen. JobPilot never marks a page
 * itself: only this button (or the Filled pages buttons) does. Not submitted? Mark it Abandoned in Filled pages.
 */
export function SubmitOfferBanner() {
  const { status, refresh } = useEngine();
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const offer = status?.submit_offer;
  if (!offer) return null;

  const message = offer.strong
    ? `Looks submitted: ${offer.title}. ${offer.reason} Mark it as submitted?`
    : `${offer.title}: ${offer.reason} Did you submit it? If not, mark it Abandoned in Filled pages.`;

  return (
    <Banner
      tone="amber"
      message={message}
      actionLabel={busy ? "Marking…" : "Mark as submitted"}
      onAction={async () => {
        if (busy) return;
        setBusy(true);
        try {
          await markFill(offer.fill_id, "submitted");
          showToast(`${offer.title} marked as submitted`);
        } catch (e) {
          showToast(e instanceof Error ? e.message : String(e));
        } finally {
          setBusy(false);
          refresh();
        }
      }}
    />
  );
}
