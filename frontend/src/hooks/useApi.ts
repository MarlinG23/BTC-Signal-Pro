/**
 * Generic API fetch hook with loading, error, and retry state.
 *
 * Usage:
 *   const { data, loading, error, refetch } = useApi<Signal[]>("/api/signals/latest");
 */

import { useCallback, useEffect, useRef, useState } from "react";

interface UseApiReturn<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

const API_BASE =
  import.meta.env.VITE_API_URL || "";

async function fetchWithRetry<T>(
  url: string,
  retries = 3,
  delayMs = 1000
): Promise<T> {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      const res = await fetch(`${API_BASE}${url}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      return (await res.json()) as T;
    } catch (err) {
      if (attempt === retries) throw err;
      await new Promise((r) => setTimeout(r, delayMs * attempt));
    }
  }
  throw new Error("Max retries exceeded");
}

export function useApi<T>(
  endpoint: string,
  refreshIntervalMs = 0
): UseApiReturn<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const mountedRef = useRef(true);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;

    const load = async () => {
      if (!mountedRef.current) return;
      setLoading(true);
      setError(null);
      try {
        const result = await fetchWithRetry<T>(endpoint);
        if (mountedRef.current) {
          setData(result);
        }
      } catch (err) {
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : "Unknown error");
        }
      } finally {
        if (mountedRef.current) {
          setLoading(false);
        }
      }
    };

    load();

    if (refreshIntervalMs > 0) {
      interval = setInterval(load, refreshIntervalMs);
    }

    return () => {
      if (interval) clearInterval(interval);
    };
  }, [endpoint, tick, refreshIntervalMs]);

  return { data, loading, error, refetch };
}
