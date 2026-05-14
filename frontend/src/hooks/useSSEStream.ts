import { useCallback, useEffect, useRef, useState } from "react";
import type { SurveillanceEvent } from "@/types/surveillance";

export type SSEStatus = "connecting" | "connected" | "disconnected";

const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;

export function useSSEStream(url: string, autoConnect = true) {
  const [events, setEvents] = useState<SurveillanceEvent[]>([]);
  const [status, setStatus] = useState<SSEStatus>("disconnected");
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const activeRef = useRef(false); // tracks whether we *want* to be connected

  const clearRetry = () => {
    if (retryRef.current) {
      clearTimeout(retryRef.current);
      retryRef.current = null;
    }
  };

  const openConnection = useCallback(() => {
    if (esRef.current) return;
    setStatus("connecting");
    const es = new EventSource(url);
    esRef.current = es;

    es.onopen = () => {
      setStatus("connected");
      attemptRef.current = 0; // reset backoff on successful connection
    };

    es.onerror = () => {
      es.close();
      esRef.current = null;
      setStatus("disconnected");

      if (!activeRef.current) return; // user disconnected intentionally

      // Exponential backoff: 1s, 2s, 4s … capped at 30s
      const delay = Math.min(
        BACKOFF_BASE_MS * 2 ** attemptRef.current,
        BACKOFF_MAX_MS,
      );
      attemptRef.current += 1;
      retryRef.current = setTimeout(() => {
        if (activeRef.current) openConnection();
      }, delay);
    };

    es.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data) as SurveillanceEvent;
        setEvents((prev) => [data, ...prev].slice(0, 200));
      } catch {
        /* ignore keepalive comments and malformed messages */
      }
    };
  }, [url]);

  const connect = useCallback(() => {
    clearRetry();
    attemptRef.current = 0;
    activeRef.current = true;
    openConnection();
  }, [openConnection]);

  const disconnect = useCallback(() => {
    activeRef.current = false;
    clearRetry();
    esRef.current?.close();
    esRef.current = null;
    setStatus("disconnected");
  }, []);

  useEffect(() => {
    if (autoConnect) connect();
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, autoConnect]);

  const clear = useCallback(() => setEvents([]), []);

  return { events, status, connect, disconnect, clear };
}
