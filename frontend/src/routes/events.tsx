import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EventBadge } from "@/components/shared/EventBadge";
import { ScoreBar } from "@/components/shared/ScoreBar";
import { SnapshotModal } from "@/components/shared/SnapshotModal";
import { useCameraList } from "@/context/SettingsContext";
import { fetchEvents, SSE_EVENTS_URL } from "@/api/events";
import { useSSEStream } from "@/hooks/useSSEStream";
import type { EventType, SurveillanceEvent } from "@/types/surveillance";
import { Bell, Download } from "lucide-react";

type SearchParams = { camera?: string };

export const Route = createFileRoute("/events")({
  component: EventsPage,
  validateSearch: (s: Record<string, unknown>): SearchParams => ({
    camera: typeof s.camera === "string" ? s.camera : undefined,
  }),
});

const PAGE_SIZE = 50;

function EventsPage() {
  const { t } = useTranslation();
  const cameras = useCameraList();
  const search = Route.useSearch();

  const [cameraId, setCameraId] = useState<string | undefined>(search.camera);
  const [eventType, setEventType] = useState<EventType | "ALL">("ALL");
  const [identity, setIdentity] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [page, setPage] = useState(1);
  const [live, setLive] = useState(false);
  const [extra, setExtra] = useState<SurveillanceEvent[]>([]);
  const [detail, setDetail] = useState<SurveillanceEvent | null>(null);
  const [snapshot, setSnapshot] = useState<string | null>(null);

  const [appliedFilters, setAppliedFilters] = useState({
    camera_id: cameraId,
    event_type: eventType,
    since: undefined as string | undefined,
    until: undefined as string | undefined,
  });

  const sse = useSSEStream(SSE_EVENTS_URL, live);
  useEffect(() => {
    if (live && sse.events.length) {
      setExtra((prev) => [sse.events[0], ...prev].slice(0, 200));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sse.events.length]);

  const q = useQuery({
    queryKey: ["events", "list", appliedFilters],
    queryFn: () =>
      fetchEvents({
        limit: 500,
        camera_id: appliedFilters.camera_id,
        event_type: appliedFilters.event_type === "ALL" ? undefined : appliedFilters.event_type,
        since: appliedFilters.since,
      }),
    refetchInterval: 20000,
    retry: false,
  });

  const merged = useMemo(() => {
    const base = q.data || [];
    const all = [...extra, ...base];
    return all.filter((e) => {
      if (identity && !(e.identity || "").toLowerCase().includes(identity.toLowerCase())) return false;
      if (appliedFilters.until && new Date(e.timestamp) > new Date(appliedFilters.until)) return false;
      return true;
    });
  }, [q.data, extra, identity, appliedFilters.until]);

  const totalPages = Math.max(1, Math.ceil(merged.length / PAGE_SIZE));
  const pageRows = merged.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const apply = () => {
    setAppliedFilters({
      camera_id: cameraId,
      event_type: eventType,
      since: startDate ? new Date(startDate).toISOString() : undefined,
      until: endDate ? new Date(endDate).toISOString() : undefined,
    });
    setPage(1);
  };

  const reset = () => {
    setCameraId(undefined); setEventType("ALL"); setIdentity(""); setStartDate(""); setEndDate("");
    setAppliedFilters({ camera_id: undefined, event_type: "ALL", since: undefined, until: undefined });
    setPage(1);
  };

  const exportCsv = () => {
    const header = ["timestamp", "camera_id", "track_id", "identity", "score", "event", "snapshot"];
    const rows = merged.map((e) =>
      [e.timestamp, e.camera_id, e.track_id, e.identity ?? "", e.score, e.event, e.snapshot ?? ""].join(",")
    );
    const csv = [header.join(","), ...rows].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `events_${Date.now()}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <AppShell title={t("events.title")}>
      <Card className="p-4 mb-4">
        <div className="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
          <div className="md:col-span-2">
            <label className="text-xs font-medium text-muted-foreground mb-1 block">{t("events.camera")}</label>
            <Select value={cameraId || "all"} onValueChange={(v) => setCameraId(v === "all" ? undefined : v)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("events.all")}</SelectItem>
                {cameras.map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.name} ({c.id})</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">{t("events.type")}</label>
            <div className="inline-flex rounded-md border bg-card overflow-hidden text-xs h-9 w-full">
              {(["ALL", "AUTHORIZED", "UNKNOWN"] as const).map((opt) => (
                <button
                  key={opt}
                  onClick={() => setEventType(opt)}
                  className={`flex-1 transition-colors ${eventType === opt ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                >
                  {opt === "ALL" ? t("events.all") : opt === "AUTHORIZED" ? t("events.authorized") : t("events.unknown")}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">{t("events.identity")}</label>
            <Input value={identity} onChange={(e) => setIdentity(e.target.value)} placeholder="John..." />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">{t("events.startDate")}</label>
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1 block">{t("events.endDate")}</label>
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
        </div>
        <div className="flex items-center justify-between mt-4 flex-wrap gap-3">
          <div className="flex gap-2">
            <Button onClick={apply}>{t("common.apply")}</Button>
            <Button variant="outline" onClick={reset}>{t("common.reset")}</Button>
            <Button variant="outline" onClick={exportCsv}><Download className="h-4 w-4 mr-1.5" />{t("events.exportCsv")}</Button>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{t("events.liveMode")}</span>
            <Switch checked={live} onCheckedChange={setLive} />
            {live && (
              <span className="text-[10px] text-muted-foreground">
                {sse.status === "connected" ? "● live" : "○"}
              </span>
            )}
          </div>
        </div>
      </Card>

      <Card className="overflow-hidden">
        {q.isLoading ? (
          <div className="p-6 space-y-3">
            {Array.from({ length: 8 }).map((_, i) => <div key={i} className="h-8 bg-muted rounded animate-pulse" />)}
          </div>
        ) : q.error ? (
          <div className="p-6 text-center">
            <p className="text-danger text-sm mb-3">{t("common.error")}</p>
            <Button size="sm" variant="outline" onClick={() => q.refetch()}>{t("common.retry")}</Button>
          </div>
        ) : merged.length === 0 ? (
          <div className="p-12 text-center">
            <Bell className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm font-medium text-foreground">{t("events.noneTitle")}</p>
            <p className="text-xs text-muted-foreground mt-1">{t("events.noneBody")}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-muted-foreground text-xs">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium">#</th>
                  <th className="text-left px-4 py-2.5 font-medium">{t("events.time")}</th>
                  <th className="text-left px-4 py-2.5 font-medium">{t("events.camera")}</th>
                  <th className="text-left px-4 py-2.5 font-medium">{t("events.identity")}</th>
                  <th className="text-left px-4 py-2.5 font-medium">{t("events.score")}</th>
                  <th className="text-left px-4 py-2.5 font-medium">{t("events.type")}</th>
                  <th className="text-left px-4 py-2.5 font-medium">{t("events.snapshot")}</th>
                  <th className="text-left px-4 py-2.5 font-medium">{t("events.actions")}</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {pageRows.map((e, i) => {
                  const isNew = extra.includes(e);
                  return (
                    <tr key={`${e.timestamp}-${i}`} className={`hover:bg-primary/5 ${e.event === "UNKNOWN" ? "border-l-2 border-l-danger" : ""} ${isNew ? "flash-row" : ""}`}>
                      <td className="px-4 py-2 text-xs text-muted-foreground tabular-nums">{(page - 1) * PAGE_SIZE + i + 1}</td>
                      <td className="px-4 py-2 text-xs tabular-nums">{format(new Date(e.timestamp), "yyyy-MM-dd HH:mm:ss")}</td>
                      <td className="px-4 py-2"><Badge variant="outline" className="text-[10px]">{e.camera_id}</Badge></td>
                      <td className="px-4 py-2">{e.identity || <em className="text-muted-foreground">{t("events.unknown")}</em>}</td>
                      <td className="px-4 py-2"><ScoreBar score={e.score} /></td>
                      <td className="px-4 py-2"><EventBadge type={e.event} /></td>
                      <td className="px-4 py-2">
                        {e.snapshot ? (
                          <button onClick={() => setSnapshot(e.snapshot)} className="h-10 w-10 rounded bg-muted overflow-hidden hover:ring-2 hover:ring-primary">
                            <span className="text-[10px] text-muted-foreground flex items-center justify-center h-full">img</span>
                          </button>
                        ) : <span className="text-muted-foreground">—</span>}
                      </td>
                      <td className="px-4 py-2">
                        <Button size="sm" variant="ghost" onClick={() => setDetail(e)}>{t("common.details")}</Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {merged.length > 0 && (
          <div className="flex items-center justify-between p-3 border-t text-xs text-muted-foreground">
            <span>{t("events.page")} {page} {t("events.of")} {totalPages} · {merged.length}</span>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>{t("events.prev")}</Button>
              <Button size="sm" variant="outline" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>{t("events.next")}</Button>
            </div>
          </div>
        )}
      </Card>

      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent>
          <SheetHeader><SheetTitle>{t("common.details")}</SheetTitle></SheetHeader>
          <pre className="mt-4 text-xs bg-muted p-3 rounded overflow-auto">{JSON.stringify(detail, null, 2)}</pre>
        </SheetContent>
      </Sheet>

      <SnapshotModal open={!!snapshot} onOpenChange={(o) => !o && setSnapshot(null)} src={snapshot} />
    </AppShell>
  );
}
