"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export type Poll<T> = {
  data: T | undefined;
  error: ApiError | null;
  /** True only until the first answer (success or error) arrives. */
  loading: boolean;
  /** Ask again now (after a change), without waiting for the next tick. */
  reload: () => Promise<void>;
};

/**
 * Ask the engine for something now, then again every `intervalMs` (0 = only once, plus `reload()`).
 *
 * Why polling? The engine changes things the dashboard did not do itself (a fill adds unknown questions,
 * the bot's browser moves to another page). Asking every few seconds is the simplest way to stay current,
 * and it needs no extra library. The last good `data` is kept while a later request fails, so a short
 * hiccup does not blank the screen.
 */
export function usePoll<T>(fetcher: () => Promise<T>, intervalMs = 0): Poll<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher; // always call the newest fetcher without restarting the timer
  }, [fetcher]);

  const reload = useCallback(async () => {
    try {
      const value = await fetcherRef.current();
      setData(value);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
    if (!intervalMs) return;
    const id = setInterval(() => void reload(), intervalMs);
    return () => clearInterval(id);
  }, [reload, intervalMs]);

  return { data, error, loading, reload };
}
