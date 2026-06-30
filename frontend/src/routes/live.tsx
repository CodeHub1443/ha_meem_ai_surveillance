import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { EventBadge } from "@/components/shared/EventBadge";
import { useCameraList } from "@/context/SettingsContext";
import { fetchLatestEvents } from "@/api/events";
import { API_BASE_URL } from "@/api/config";
import { Camera, Loader2, AlertTriangle, X } from "lucide-react";
import type { Camera as CameraType } from "@/types/surveillance";

export const Route = createFileRoute("/live")({
  component: LivePage,
  validateSearch: (s: Record<string, unknown>) => ({
    camera: typeof s.camera === "string" ? s.camera : undefined,
  }),
});

function extractIp(url: string): string {
  try {
    const m = url.match(/@([^:/\s]+)/);
    return m?.[1] ?? "";
  } catch { return ""; }
}

// ── Slot stream component ─────────────────────────────────────────────────────

function SlotStream({ camera }: { camera: CameraType }) {
  const [status, setStatus] = useState<"loading" | "ok" | "error" | "no-url">(
    camera.rtsp_url ? "loading" : "no-url"
  );
  const imgRef = useRef<HTMLImageElement>(null);
  // srcRef computed once at mount — prevents MJPEG restart on every parent re-render
  const srcRef = useRef(`${API_BASE_URL}/cameras/${camera.id}/stream?t=${Date.now()}`);

  // Reset when camera changes (component remounts via key)
  const retry = () => {
    if (!camera.rtsp_url) { setStatus("no-url"); return; }
    setStatus("loading");
    srcRef.current = `${API_BASE_URL}/cameras/${camera.id}/stream?t=${Date.now()}`;
    if (imgRef.current) imgRef.current.src = srcRef.current;
  };

  return (
    <div className="relative w-full aspect-video bg-black">
      {/* Camera ID badge — visible during loading/error/no-url; replaced by richer overlay when live */}
      {status !== "ok" && (
        <div className="absolute top-2 left-2 z-10 bg-black/50 text-white/60 text-[9px] font-mono px-1 py-0.5 rounded pointer-events-none">
          {camera.id}
        </div>
      )}
      {status === "loading" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1">
          <Loader2 className="h-6 w-6 animate-spin text-white/40" />
          <p className="text-white/25 text-[10px]">Connecting…</p>
        </div>
      )}
      {status === "error" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center px-4">
          <AlertTriangle className="h-7 w-7 text-amber-400/70" />
          <p className="text-white/50 text-xs">Stream unavailable</p>
          <button onClick={retry} className="text-[11px] text-white/40 underline mt-1">Retry</button>
        </div>
      )}
      {status === "no-url" && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center px-4">
          <Camera className="h-7 w-7 text-white/20" />
          <p className="text-white/40 text-xs">No RTSP URL configured</p>
          <p className="text-white/25 text-[10px]">Set an RTSP URL in Settings to enable this camera</p>
        </div>
      )}
      {(status === "loading" || status === "ok") && (
        <img
          ref={imgRef}
          src={srcRef.current}
          alt={camera.name}
          className={`w-full h-full object-contain ${status === "loading" ? "invisible" : ""}`}
          onLoad={() => setStatus("ok")}
          onError={() => setStatus("error")}
        />
      )}
      {status === "ok" && (
        <>
          {/* Replace the always-visible id badge with a richer name+id overlay when live */}
          <div className="absolute top-2 left-2 bg-black/60 text-white text-[11px] px-1.5 py-0.5 rounded leading-tight">
            <div>{camera.name}</div>
            <div className="text-white/50 text-[9px] font-mono">{camera.id}</div>
          </div>
          <div className="absolute top-2 right-2 flex items-center gap-1 bg-black/60 text-white text-[11px] px-1.5 py-0.5 rounded">
            <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse" />
            LIVE
          </div>
        </>
      )}
    </div>
  );
}

// ── Empty grid slot ───────────────────────────────────────────────────────────

function EmptySlot({ slotNum }: { slotNum: number }) {
  return (
    <div className="w-full aspect-video bg-[#0a0f1a] flex flex-col items-center justify-center gap-2 border border-white/5 rounded">
      <Camera className="h-8 w-8 text-white/15" />
      <p className="text-white/25 text-xs">Slot {slotNum}</p>
      <p className="text-white/15 text-[10px]">Click a camera to assign</p>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

function LivePage() {
  const { t } = useTranslation();
  const cameras = useCameraList();
  const search = Route.useSearch() as { camera?: string };

  // 4-slot circular ring buffer
  const [slots, setSlots] = useState<(string | null)[]>([null, null, null, null]);
  const nextSlotRef = useRef(0);
  const didAssign = useRef(false);

  const assignCamera = (cameraId: string) => {
    setSlots((prev) => {
      if (prev.includes(cameraId)) return prev;
      // Fill first empty slot — pure updater, no ref mutation (safe under re-invocation)
      const emptyIdx = prev.indexOf(null);
      const idx = emptyIdx >= 0 ? emptyIdx : nextSlotRef.current;
      const next = [...prev];
      next[idx] = cameraId;
      return next;
    });
    // Advance ring outside the updater so it runs exactly once per call
    nextSlotRef.current = (nextSlotRef.current + 1) % 4;
  };

  // Pre-assign camera from URL param — deferred until cameras list loads
  useEffect(() => {
    if (!didAssign.current && cameras.length > 0 && search.camera) {
      if (cameras.find((c) => c.id === search.camera)) {
        assignCamera(search.camera);
        didAssign.current = true;
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameras, search.camera]);

  const clearSlot = (idx: number) => {
    setSlots((prev) => {
      const next = [...prev];
      next[idx] = null;
      return next;
    });
  };

  // Latest events for the right panel (all cameras, no filter)
  const latest = useQuery({
    queryKey: ["events", "live-grid"],
    queryFn: () => fetchLatestEvents({ limit: 12 }),
    refetchInterval: 10000,
    retry: false,
  });

  return (
    <AppShell title={t("live.title")}>
      {/* Single unified container: left panel | 2x2 grid | right panel */}
      <Card className="p-0 overflow-hidden">
        <div className="flex h-full min-h-[520px]">

          {/* ── Left: camera list ── */}
          <div className="w-48 shrink-0 border-r bg-sidebar flex flex-col">
            <div className="px-3 py-3 border-b border-white/10">
              <p className="text-xs font-semibold text-white/80 uppercase tracking-wider">Cameras</p>
              <p className="text-[10px] text-white/40 mt-0.5">Click to assign to next slot</p>
            </div>
            <nav className="flex-1 overflow-y-auto p-2 space-y-1">
              {cameras.length === 0 ? (
                <p className="text-[11px] text-white/30 px-2 py-3">No cameras configured</p>
              ) : cameras.map((cam) => {
                const ip = extractIp(cam.rtsp_url || "");
                const activeSlot = slots.indexOf(cam.id);
                return (
                  <button
                    key={cam.id}
                    onClick={() => assignCamera(cam.id)}
                    className={`w-full text-left px-2.5 py-2 rounded-md transition-colors ${
                      activeSlot >= 0
                        ? "bg-primary/20 text-white"
                        : "text-white/60 hover:bg-white/5 hover:text-white"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs font-medium truncate">{cam.name}</span>
                      {activeSlot >= 0 && (
                        <span className="text-[9px] bg-primary/30 text-primary px-1 rounded shrink-0">
                          S{activeSlot + 1}
                        </span>
                      )}
                    </div>
                    {/* Always show camera_id — critical when two cameras share the same name */}
                    <div className="text-[10px] text-white/40 mt-0.5 font-mono">{cam.id}</div>
                    {ip && <div className="text-[10px] text-white/25 font-mono">{ip}</div>}
                  </button>
                );
              })}
            </nav>
          </div>

          {/* ── Center: 2x2 MJPEG grid ── */}
          <div className="flex-1 bg-[#060b14]">
            <div className="grid grid-cols-2 grid-rows-2 h-full">
              {[0, 1, 2, 3].map((idx) => {
                const camId = slots[idx];
                const cam = cameras.find((c) => c.id === camId);
                return (
                  <div key={idx} className="relative border border-white/5">
                    {cam ? (
                      <>
                        <SlotStream key={camId} camera={cam} />
                        <button
                          onClick={() => clearSlot(idx)}
                          className="absolute top-1 right-1 z-10 bg-black/60 text-white/70 hover:text-white rounded p-0.5 opacity-0 hover:opacity-100 transition-opacity [div:hover>&]:opacity-100"
                          title="Remove"
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </>
                    ) : (
                      <EmptySlot slotNum={idx + 1} />
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── Right: latest events ── */}
          <div className="w-64 shrink-0 border-l flex flex-col">
            <div className="px-4 py-3 border-b">
              <p className="text-xs font-semibold text-foreground">{t("live.latest")}</p>
            </div>
            <div className="flex-1 overflow-y-auto divide-y">
              {!latest.data?.length ? (
                <p className="text-xs text-muted-foreground p-4 text-center">{t("events.noneTitle")}</p>
              ) : latest.data.map((e, i) => (
                <div key={i} className={`flex items-start gap-2 px-3 py-2.5 ${e.event === "UNKNOWN" ? "border-l-2 border-l-danger" : ""}`}>
                  <EventBadge type={e.event} />
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-medium text-foreground truncate">
                      {e.identity || <em className="text-muted-foreground font-normal">{t("events.unknownPerson")}</em>}
                    </p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">
                      {e.camera_id} · {format(new Date(e.timestamp), "HH:mm:ss")}
                    </p>
                    <p className="text-[10px] text-muted-foreground">
                      {(e.score * 100).toFixed(1)}%
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>

        </div>
      </Card>
    </AppShell>
  );
}
