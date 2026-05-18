import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { format } from "date-fns";
import { SSE_EVENTS_URL } from "@/api/events";
import type { StatsSummary } from "@/api/events";
import type { SurveillanceEvent } from "@/types/surveillance";

type Listener = (event: SurveillanceEvent) => void;

interface SSEContextValue {
  /** Subscribe to raw SSE events. Returns an unsubscribe function. */
  subscribe: (cb: Listener) => () => void;
}

const SSEContext = createContext<SSEContextValue>({
  subscribe: () => () => {},
});

const BACKOFF_BASE = 1_000;
const BACKOFF_MAX = 30_000;

export function SSEProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const esRef = useRef<EventSource | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const listenersRef = useRef<Set<Listener>>(new Set());
  // Delays backoff reset until the connection has been stable for 5 s.
  const stableTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Coalesces high-frequency SSE events into one stats refetch per 2 s.
  const statsDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(() => {
    if (esRef.current) return;

    const es = new EventSource(SSE_EVENTS_URL);
    esRef.current = es;

    es.onopen = () => {
      // Only reset backoff counter after 5 s of stable connection.
      // If the server accepts TCP but immediately drops the stream (e.g., rolling
      // restart behind a proxy), onopen fires instantly and onopen → onerror
      // would permanently peg the retry delay at the minimum without this guard.
      if (stableTimerRef.current) clearTimeout(stableTimerRef.current);
      stableTimerRef.current = setTimeout(() => {
        attemptRef.current = 0;
        stableTimerRef.current = null;
      }, 5_000);
    };

    es.onmessage = (msg) => {
      let event: SurveillanceEvent;
      try {
        event = JSON.parse(msg.data) as SurveillanceEvent;
      } catch {
        return; // keepalive comment or malformed JSON — ignore
      }
      // Guard against valid JSON with wrong shape (e.g. keepalive objects).
      if (!event || typeof event.event !== "string") return;

      // ── 1. Update "recent alerts" cache directly (dashboard, no HTTP round-trip)
      queryClient.setQueryData(
        ["events", "latest", 10],
        (old: SurveillanceEvent[] | undefined) =>
          old ? [event, ...old].slice(0, 10) : [event],
      );

      // ── 2. Increment today's stat counters directly (no HTTP round-trip)
      queryClient.setQueriesData<StatsSummary>(
        { queryKey: ["stats", "today"] },
        (old) => {
          if (!old) return old;
          return {
            ...old,
            total: old.total + 1,
            authorized:
              event.event === "AUTHORIZED" ? old.authorized + 1 : old.authorized,
            unknown:
              event.event === "UNKNOWN" ? old.unknown + 1 : old.unknown,
          };
        },
      );

      // ── 3. Invalidate the paginated events list + count (refetch current page)
      void queryClient.invalidateQueries({ queryKey: ["events", "list"] });
      void queryClient.invalidateQueries({ queryKey: ["events", "count"] });

      // ── 4. Invalidate report aggregates so reports stay fresh
      void queryClient.invalidateQueries({ queryKey: ["report-stats"] });
      void queryClient.invalidateQueries({ queryKey: ["report-count"] });
      void queryClient.invalidateQueries({ queryKey: ["report-events"] });

      // ── 4b. Debounced events-page stats summary invalidation.
      // invalidateQueries bypasses staleTime and refetches immediately — at peak
      // traffic (30+ events/min) this would hammer /stats/summary once per event.
      // Coalesce into one refetch per 2 s instead.
      if (statsDebounceRef.current) clearTimeout(statsDebounceRef.current);
      statsDebounceRef.current = setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ["stats", "events-page"] });
        statsDebounceRef.current = null;
      }, 2_000);

      // ── 5. Refresh person gallery on AUTHORIZED (new snapshot + updated avg)
      if (event.event === "AUTHORIZED") {
        void queryClient.invalidateQueries({ queryKey: ["persons"] });
      }

      // ── 6. Toast alert on UNKNOWN
      if (event.event === "UNKNOWN") {
        toast.error("Unknown person detected", {
          description: `${event.camera_id} · ${format(new Date(event.timestamp), "HH:mm:ss")}`,
        });
      }

      // ── 7. Update live page event grid directly (no HTTP round-trip)
      queryClient.setQueryData(
        ["events", "live-grid"],
        (old: SurveillanceEvent[] | undefined) =>
          old ? [event, ...old].slice(0, 12) : [event],
      );

      // ── 8. Notify local subscribers (e.g. events page live-mode auto-scroll)
      listenersRef.current.forEach((cb) => cb(event));
    };

    es.onerror = () => {
      // Cancel the stable-connection timer — the connection dropped.
      if (stableTimerRef.current) {
        clearTimeout(stableTimerRef.current);
        stableTimerRef.current = null;
      }
      es.close();
      esRef.current = null;
      const delay = Math.min(
        BACKOFF_BASE * 2 ** attemptRef.current,
        BACKOFF_MAX,
      );
      attemptRef.current += 1;
      retryRef.current = setTimeout(() => connect(), delay);
    };
  }, [queryClient]);

  useEffect(() => {
    connect();
    return () => {
      if (retryRef.current) clearTimeout(retryRef.current);
      if (stableTimerRef.current) clearTimeout(stableTimerRef.current);
      if (statsDebounceRef.current) clearTimeout(statsDebounceRef.current);
      esRef.current?.close();
      esRef.current = null;
    };
  }, [connect]);

  const subscribe = useCallback((cb: Listener) => {
    listenersRef.current.add(cb);
    return () => listenersRef.current.delete(cb);
  }, []);

  return (
    <SSEContext.Provider value={{ subscribe }}>
      {children}
    </SSEContext.Provider>
  );
}

/** Subscribe to raw SSE events from the global connection. */
export function useSSEEvent(cb: Listener) {
  const { subscribe } = useContext(SSEContext);
  const cbRef = useRef(cb);
  cbRef.current = cb;

  useEffect(() => {
    return subscribe((event) => cbRef.current(event));
  }, [subscribe]);
}
