"use client";

import { useEffect, useRef } from "react";
import { Button } from "./Button";

/**
 * Centred dialog for risky actions. The body lists exactly what will happen.
 * Cancel has the default focus and the risky button is red (DESIGN.md
 * principle 5). Escape or a click on the dim background also cancels.
 */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "danger",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  children: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** "danger" = red confirm button (STOP, Live). "primary" = green (Submit approved). */
  tone?: "danger" | "primary";
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-jp-ink/30"
      onClick={onCancel}
      role="presentation"
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="flex w-[440px] max-w-[calc(100vw-32px)] flex-col gap-3 rounded-card border border-jp-line bg-jp-surface p-5 shadow-overlay"
      >
        <div className="text-[18px] font-semibold">{title}</div>
        <div className="text-sm leading-normal text-jp-ink-2">{children}</div>
        <div className="mt-1.5 flex justify-end gap-2.5">
          <button
            ref={cancelRef}
            type="button"
            onClick={onCancel}
            className="inline-flex h-9 items-center rounded-control border border-jp-line-strong bg-jp-surface px-4 text-sm font-medium text-jp-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-jp-brand"
          >
            {cancelLabel}
          </button>
          <Button variant={tone === "danger" ? "danger" : "primary"} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
