"use client";

import { Banner } from "@/components/ui/Banner";
import { useEngine } from "./EngineProvider";

/** Red banner on every v0 screen while the engine does not answer. One fix button, as DESIGN.md asks. */
export function EngineDownBanner() {
  const { error, refresh } = useEngine();
  if (!error || error.code !== "engine_unreachable") return null;
  return <Banner tone="danger" message={error.message} actionLabel="Check again" onAction={refresh} />;
}
