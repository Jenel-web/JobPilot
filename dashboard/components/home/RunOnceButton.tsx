"use client";

import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";

/** "Run once now": in the mock it only shows a toast. The real one will call the engine API. */
export function RunOnceButton() {
  const { showToast } = useToast();
  return <Button onClick={() => showToast("Mock run started. Nothing is searched or sent.")}>Run once now</Button>;
}
