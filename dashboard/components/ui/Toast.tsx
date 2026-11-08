"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

type ToastContextValue = { showToast: (message: string, tag?: string) => void };

const ToastContext = createContext<ToastContextValue | null>(null);

/**
 * Wrap the app once. Anything below can call `useToast().showToast("5 jobs approved")`.
 * The toast sits bottom-right and clears itself after 4 seconds (DESIGN.md).
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<{ message: string; tag?: string } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tag?: string) => {
    setToast({ message, tag });
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast(null), 4000);
  }, []);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {toast && (
        <div
          role="status"
          className="fixed bottom-6 right-6 z-50 flex h-11 min-w-[260px] items-center justify-between gap-6 rounded-card bg-jp-ink px-4 text-sm text-white"
        >
          <span>{toast.message}</span>
          {toast.tag && <span className="font-medium text-jp-brand-tint">{toast.tag}</span>}
        </div>
      )}
    </ToastContext.Provider>
  );
}

/** Returns `showToast(message, tag?)`. Must be used under <ToastProvider>. */
export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}
