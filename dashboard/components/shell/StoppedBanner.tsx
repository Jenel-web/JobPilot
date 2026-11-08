"use client";

import { Banner } from "@/components/ui/Banner";
import { useShell } from "./ShellProvider";

/** Red banner across every screen after STOP: "Stopped by you at 3:12 PM. Nothing will run." */
export function StoppedBanner() {
  const { stopped, stoppedAt, resume } = useShell();
  if (!stopped) return null;
  return (
    <Banner
      tone="danger"
      message={`Stopped by you at ${stoppedAt}. Nothing will run.`}
      actionLabel="Resume"
      onAction={resume}
    />
  );
}
