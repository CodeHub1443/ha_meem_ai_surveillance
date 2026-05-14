import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EventBadge } from "@/components/shared/EventBadge";
import { useCameraList } from "@/context/SettingsContext";
import { fetchLatestEvents } from "@/api/events";
import { API_BASE_URL } from "@/api/config";
import { Camera, Square, ImageOff, Loader2, AlertTriangle } from "lucide-react";
import { Link } from "@tanstack/react-router";

type SearchParams = { camera?: string };

export const Route = createFileRoute("/live")({
  component: LivePage,
  validateSearch: (s: Record<string, unknown>): SearchParams => ({
    camera: typeof s.camera === "string" ? s.camera : undefined,
  }),
});

async function checkStreamStatus(cameraId: string): Promise<{ active: boolean; reason: string }> {
  try {
    const res = await fetch(`${API_BASE_URL}/cameras/${cameraId}/stream-status`);
    if (!res.ok) return { active: false, reason: `HTTP ${res.status}` };
    return res.json() as Promise<{ active: boolean; reason: string }>;
  } catch {
    return { active: false, reason: "API server unreachable" };
  }
}

function LivePage() {
  const { t } = useTranslation();
  const cameras = useCameraList();
  const search = Route.useSearch();
  const [cameraId, setCameraId] = useState<string | undefined>(search.camera || cameras[0]?.id);
  const [isStreaming, setIsStreaming] = useState(false);
  const [imgError, setImgError] = useState(false);
  const [imgLoading, setImgLoading] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const loadTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const camera = cameras.find((c) => c.id === cameraId);
  const streamUrl = cameraId ? `${API_BASE_URL}/cameras/${cameraId}/stream` : null;

  const clearLoadTimeout = () => {
    if (loadTimeoutRef.current) {
      clearTimeout(loadTimeoutRef.current);
      loadTimeoutRef.current = null;
    }
  };

  const startStream = async () => {
    if (!cameraId) return;
    setImgError(false);
    setStatusMsg(null);
    setImgLoading(true);
    setIsStreaming(true);

    // Check whether the pipeline is actually writing frames before showing spinner
    const status = await checkStreamStatus(cameraId);
    if (!status.active) {
      setImgError(true);
      setImgLoading(false);
      setIsStreaming(false);
      setStatusMsg(`Pipeline is not running for this camera. (${status.reason})`);
      return;
    }

    // Safety timeout: if the browser connects but no frame arrives in 20s, show error
    loadTimeoutRef.current = setTimeout(() => {
      setImgError(true);
      setImgLoading(false);
      setStatusMsg("Stream connected but no frames received — pipeline may have stopped.");
    }, 20000);
  };

  const stopStream = () => {
    clearLoadTimeout();
    setIsStreaming(false);
    if (imgRef.current) imgRef.current.src = "";
    setImgLoading(false);
    setImgError(false);
    setStatusMsg(null);
  };

  // Stop stream when camera selection changes
  useEffect(() => {
    stopStream();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId]);

  const latest = useQuery({
    queryKey: ["events", "live", cameraId],
    queryFn: () => fetchLatestEvents({ camera_id: cameraId, limit: 5 }),
    enabled: !!cameraId,
    refetchInterval: 10000,
    retry: false,
  });

  return (
    <AppShell title={t("live.title")}>
      <div className="space-y-4">
        {/* Controls bar */}
        <Card className="p-4 flex items-center gap-3 flex-wrap">
          <div className="flex-1 min-w-[200px] max-w-sm">
            <Select value={cameraId} onValueChange={setCameraId}>
              <SelectTrigger><SelectValue placeholder={t("live.selectCamera")} /></SelectTrigger>
              <SelectContent>
                {cameras.map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.name} ({c.id})</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {!isStreaming ? (
            <Button onClick={startStream} disabled={!cameraId || imgLoading}>
              {imgLoading
                ? <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                : <Camera className="h-4 w-4 mr-2" />}
              {t("live.go")}
            </Button>
          ) : (
            <Button variant="destructive" onClick={stopStream}>
              <Square className="h-4 w-4 mr-2" />
              {t("live.stop")}
            </Button>
          )}
        </Card>

        {/* Video pane */}
        <Card className="p-0 overflow-hidden">
          <div className="bg-[#0F172A] aspect-video relative flex items-center justify-center">
            {/* Loading spinner */}
            {isStreaming && imgLoading && !imgError && (
              <div className="absolute inset-0 bg-black/40 flex items-center justify-center z-10">
                <Loader2 className="h-8 w-8 animate-spin text-white" />
              </div>
            )}

            {isStreaming && streamUrl && !imgError ? (
              <>
                <img
                  ref={imgRef}
                  src={streamUrl}
                  alt="live stream"
                  className="max-h-full max-w-full object-contain"
                  onLoad={() => { clearLoadTimeout(); setImgLoading(false); }}
                  onError={() => {
                    clearLoadTimeout();
                    setImgError(true);
                    setImgLoading(false);
                    setStatusMsg(t("live.streamError"));
                  }}
                />
                <div className="absolute top-3 left-3 bg-black/60 text-white text-xs px-2 py-1 rounded">
                  {camera?.name}
                </div>
                <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-black/60 text-white text-xs px-2 py-1 rounded">
                  <span className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                  LIVE
                </div>
              </>
            ) : imgError ? (
              <div className="text-center text-white/70 space-y-3 px-6 max-w-sm">
                <AlertTriangle className="h-12 w-12 mx-auto text-amber-400 opacity-80" />
                <p className="text-sm font-medium">{t("live.streamError")}</p>
                {statusMsg && (
                  <p className="text-xs text-white/50 font-mono">{statusMsg}</p>
                )}
                <Button size="sm" variant="outline" onClick={startStream}>
                  {t("common.retry")}
                </Button>
              </div>
            ) : (
              <div className="text-center text-white/60">
                <Camera className="h-16 w-16 mx-auto mb-3 opacity-40" />
                <p className="text-sm">{t("live.placeholder")}</p>
              </div>
            )}
          </div>
        </Card>

        {/* Latest events panel */}
        <Card className="p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold">{t("live.latest")}</h2>
            <Link to="/events" search={{ camera: cameraId } as never}>
              <Button variant="ghost" size="sm">{t("live.viewInEvents")}</Button>
            </Link>
          </div>
          {!latest.data?.length ? (
            <p className="text-xs text-muted-foreground py-6 text-center">{t("events.noneTitle")}</p>
          ) : (
            <div className="divide-y">
              {latest.data.map((e, i) => (
                <div key={i} className="flex items-center gap-3 py-2.5 text-sm">
                  <EventBadge type={e.event} />
                  <span className="font-medium">{e.identity || t("events.unknownPerson")}</span>
                  <span className="text-xs text-muted-foreground ml-auto">
                    {format(new Date(e.timestamp), "HH:mm:ss")}
                  </span>
                  <span className="text-xs font-mono text-muted-foreground">
                    {(e.score * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
