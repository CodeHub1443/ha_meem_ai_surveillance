import { createFileRoute } from "@tanstack/react-router";
import { useState, useRef, useEffect } from "react";
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
import { fetchEvents, fetchEventsCount, fetchStatsSummary, snapshotUrl } from "@/api/events";
import { useSSEEvent } from "@/context/SSEContext";
import { useToday } from "@/hooks/useToday";
import type { EventType, SurveillanceEvent } from "@/types/surveillance";
import { toast } from "sonner";
import { Bell, Download, Printer } from "lucide-react";
import { API_BASE_URL } from "@/api/config";

type SearchParams = { camera?: string };

export const Route = createFileRoute("/events")({
  component: EventsPage,
  validateSearch: (s: Record<string, unknown>): SearchParams => ({
    camera: typeof s.camera === "string" ? s.camera : undefined,
  }),
});

const PAGE_SIZE = 50;

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ value, label, tone }: {
  value: number | null | undefined;
  label: string;
  tone?: "success" | "danger";
}) {
  const numClass =
    tone === "success" ? "text-success" :
    tone === "danger"  ? "text-danger"  :
    "text-foreground";
  return (
    <Card className="px-4 py-3">
      <div className={`text-2xl font-bold tabular-nums leading-tight ${numClass}`}>
        {value ?? "—"}
      </div>
      <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function EventsPage() {
  const { t } = useTranslation();
  const cameras = useCameraList();
  const search = Route.useSearch();
  const today = useToday();

  const [cameraId, setCameraId]       = useState<string | undefined>(search.camera);
  const [eventType, setEventType]     = useState<EventType | "ALL">("ALL");
  const [identity, setIdentity]       = useState("");
  const [employeeId, setEmployeeId]   = useState("");
  const [designation, setDesignation] = useState("");
  const [workingArea, setWorkingArea] = useState("");
  const [startDate, setStartDate]     = useState(today);
  const [endDate, setEndDate]         = useState(today);
  const [page, setPage]               = useState(1);
  const [live, setLive]               = useState(false);
  const [detail, setDetail]           = useState<SurveillanceEvent | null>(null);
  const [snapshot, setSnapshot]       = useState<string | null>(null);

  const [appliedFilters, setAppliedFilters] = useState({
    camera_id:   undefined as string | undefined,
    event_type:  "ALL" as EventType | "ALL",
    identity:    "",
    employee_id: "",
    designation: "",
    working_area: "",
    since: `${today}T00:00:00.000Z` as string | undefined,
    until: `${today}T23:59:59.999Z` as string | undefined,
  });

  useEffect(() => {
    setStartDate(today);
    setEndDate(today);
    setAppliedFilters((prev) => ({
      ...prev,
      since: `${today}T00:00:00.000Z`,
      until: `${today}T23:59:59.999Z`,
    }));
    setPage(1);
  }, [today]);

  const liveRef = useRef(live);
  liveRef.current = live;
  useSSEEvent(() => { if (liveRef.current) setPage(1); });

  // ── Queries ────────────────────────────────────────────────────────────────

  const statsQ = useQuery({
    queryKey: ["stats", "events-page", appliedFilters.camera_id, appliedFilters.since, appliedFilters.until],
    queryFn: () => fetchStatsSummary({
      camera_id: appliedFilters.camera_id,
      since: appliedFilters.since,
      until: appliedFilters.until,
    }),
    retry: false,
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const q = useQuery({
    queryKey: ["events", "list", appliedFilters, page],
    queryFn: () =>
      fetchEvents({
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        camera_id:   appliedFilters.camera_id,
        event_type:  appliedFilters.event_type === "ALL" ? undefined : appliedFilters.event_type,
        identity:    appliedFilters.identity    || undefined,
        employee_id: appliedFilters.employee_id || undefined,
        designation: appliedFilters.designation || undefined,
        working_area: appliedFilters.working_area || undefined,
        since: appliedFilters.since,
        until: appliedFilters.until,
      }),
    retry: false,
    staleTime: 5_000,
  });

  const countQ = useQuery({
    queryKey: ["events", "count", appliedFilters],
    queryFn: () =>
      fetchEventsCount({
        camera_id:   appliedFilters.camera_id,
        event_type:  appliedFilters.event_type === "ALL" ? undefined : appliedFilters.event_type,
        identity:    appliedFilters.identity    || undefined,
        employee_id: appliedFilters.employee_id || undefined,
        designation: appliedFilters.designation || undefined,
        working_area: appliedFilters.working_area || undefined,
        since: appliedFilters.since,
        until: appliedFilters.until,
      }),
    retry: false,
    staleTime: 5_000,
  });

  const totalCount  = countQ.data ?? 0;
  const totalPages  = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const rows        = q.data ?? [];

  // ── Actions ────────────────────────────────────────────────────────────────

  const apply = () => {
    setAppliedFilters({
      camera_id:   cameraId,
      event_type:  eventType,
      identity,
      employee_id: employeeId,
      designation,
      working_area: workingArea,
      since: startDate ? new Date(startDate).toISOString() : undefined,
      until: endDate   ? `${endDate}T23:59:59.999Z`        : undefined,
    });
    setPage(1);
  };

  const reset = () => {
    setCameraId(undefined); setEventType("ALL"); setIdentity("");
    setEmployeeId(""); setDesignation(""); setWorkingArea("");
    setStartDate(today); setEndDate(today);
    setAppliedFilters({
      camera_id: undefined, event_type: "ALL", identity: "",
      employee_id: "", designation: "", working_area: "",
      since: `${today}T00:00:00.000Z`, until: `${today}T23:59:59.999Z`,
    });
    setPage(1);
  };

  // Instantly apply a type filter without touching other pending fields
  const quickTypeFilter = (type: EventType | "ALL") => {
    setEventType(type);
    setAppliedFilters((prev) => ({ ...prev, event_type: type }));
    setPage(1);
  };

  const exportCsv = async () => {
    try {
      if (totalCount > 5000) {
        toast.warning(`Export limited to 5 000 of ${totalCount} events`);
      }
      const all = await fetchEvents({
        limit: 5000,
        camera_id:   appliedFilters.camera_id,
        event_type:  appliedFilters.event_type === "ALL" ? undefined : appliedFilters.event_type,
        identity:    appliedFilters.identity    || undefined,
        employee_id: appliedFilters.employee_id || undefined,
        designation: appliedFilters.designation || undefined,
        working_area: appliedFilters.working_area || undefined,
        since: appliedFilters.since,
        until: appliedFilters.until,
      });
      const header = ["Timestamp", "Camera", "Identity", "Employee ID", "Designation", "Working Area", "Score", "Type", "Snapshot"];
      const csvRows = all.map((e) =>
        [e.timestamp, e.camera_id, e.identity ?? "", e.employee_id ?? "", e.designation ?? "",
         e.working_area ?? "", `${(e.score * 100).toFixed(1)}%`, e.event, e.snapshot ?? ""]
          .map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")
      );
      const BOM = "﻿";
      const csv = BOM + [header.map((h) => `"${h}"`).join(","), ...csvRows].join("\r\n");
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href = url;
      a.download = `events_${format(new Date(), "yyyyMMdd_HHmm")}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 100);
    } catch (e) {
      toast.error(String(e));
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <AppShell title={t("events.title")}>
      <style>{`
        @media print {
          aside, header, .no-print { display: none !important; }
          main { padding: 0 !important; }
        }
      `}</style>

      {/* ── Compact filters ── */}
      <Card className="p-3 mb-3 no-print">
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 items-end">
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("events.camera")}</label>
            <Select value={cameraId || "all"} onValueChange={(v) => setCameraId(v === "all" ? undefined : v)}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">{t("events.all")}</SelectItem>
                {cameras.map((c) => (
                  <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("events.identity")}</label>
            <Input className="h-8 text-xs" value={identity} onChange={(e) => setIdentity(e.target.value)} placeholder="Name…" />
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("events.startDate")}</label>
            <Input className="h-8 text-xs" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("events.endDate")}</label>
            <Input className="h-8 text-xs" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("events.employeeId")}</label>
            <Input className="h-8 text-xs" value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} placeholder="EMP-001…" />
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("events.designation")}</label>
            <Input className="h-8 text-xs" value={designation} onChange={(e) => setDesignation(e.target.value)} placeholder="Operator…" />
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("events.workingArea")}</label>
            <Input className="h-8 text-xs" value={workingArea} onChange={(e) => setWorkingArea(e.target.value)} placeholder="Zone…" />
          </div>
        </div>

        <div className="flex items-center justify-between mt-2.5 flex-wrap gap-2">
          <div className="flex gap-1.5 flex-wrap">
            <Button size="sm" className="h-7 text-xs px-3" onClick={apply}>{t("common.apply")}</Button>
            <Button size="sm" variant="outline" className="h-7 text-xs px-3" onClick={reset}>{t("common.reset")}</Button>
            <Button size="sm" variant="outline" className="h-7 text-xs px-3" onClick={exportCsv}>
              <Download className="h-3 w-3 mr-1" />{t("events.exportCsv")}
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs px-3" onClick={() => window.print()}>
              <Printer className="h-3 w-3 mr-1" />{t("events.print")}
            </Button>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">{t("events.liveMode")}</span>
            <Switch checked={live} onCheckedChange={setLive} />
            {live && <span className="text-[10px] text-success">● {t("events.liveIndicator")}</span>}
          </div>
        </div>
      </Card>

      {/* ── Quick type filter + Stats summary ── */}
      <div className="mb-4">
        {/* Type buttons — clicking immediately filters table */}
        <div className="flex items-center gap-2 mb-2.5">
          {(["ALL", "AUTHORIZED", "UNKNOWN"] as const).map((opt) => {
            const active = appliedFilters.event_type === opt;
            const activeClass =
              opt === "AUTHORIZED" ? "bg-success text-white border-success" :
              opt === "UNKNOWN"    ? "bg-danger text-white border-danger"    :
              "bg-primary text-primary-foreground border-primary";
            return (
              <button
                key={opt}
                onClick={() => quickTypeFilter(opt)}
                className={`px-4 py-1 rounded-full text-xs font-semibold border transition-colors ${
                  active ? activeClass : "border-border text-muted-foreground hover:bg-muted/60"
                }`}
              >
                {opt === "ALL" ? t("events.all") : opt === "AUTHORIZED" ? t("events.authorized") : t("events.unknown")}
              </button>
            );
          })}
        </div>

        {/* Stats cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard value={statsQ.data?.total}          label={t("events.statsTotal")} />
          <StatCard value={statsQ.data?.authorized}     label={t("events.authorized")}  tone="success" />
          <StatCard value={statsQ.data?.unknown}        label={t("events.unknown")}     tone="danger" />
          <StatCard value={statsQ.data?.unique_persons} label={t("events.uniquePersons")} />
        </div>
      </div>

      {/* ── Table ── */}
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
        ) : rows.length === 0 ? (
          <div className="p-12 text-center">
            <Bell className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
            <p className="text-sm font-medium">{t("events.noneTitle")}</p>
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
                  <th className="text-left px-4 py-2.5 font-medium no-print">{t("events.actions")}</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.map((e, i) => {
                  const rawSnap = snapshotUrl(e.snapshot);
                  const thumbSrc = rawSnap
                    ? rawSnap.startsWith("http") ? rawSnap : `${API_BASE_URL}/${rawSnap}`
                    : null;
                  return (
                    <tr key={`${e.timestamp}-${i}`}
                      className={`hover:bg-primary/5 ${e.event === "UNKNOWN" ? "border-l-2 border-l-danger" : ""}`}>
                      <td className="px-4 py-2 text-xs text-muted-foreground tabular-nums">
                        {(page - 1) * PAGE_SIZE + i + 1}
                      </td>
                      <td className="px-4 py-2 text-xs tabular-nums whitespace-nowrap">
                        {format(new Date(e.timestamp), "yyyy-MM-dd HH:mm:ss")}
                      </td>
                      <td className="px-4 py-2">
                        <Badge variant="outline" className="text-[10px]">{e.camera_id}</Badge>
                      </td>
                      <td className="px-4 py-2">
                        <div className="text-sm font-medium leading-tight">
                          {e.identity || <em className="text-muted-foreground font-normal">{t("events.unknown")}</em>}
                        </div>
                        {(e.employee_id || e.designation || e.working_area) && (
                          <div className="text-[10px] text-muted-foreground mt-0.5 flex flex-wrap gap-x-1.5">
                            {e.employee_id  && <span>{e.employee_id}</span>}
                            {e.designation  && <span>· {e.designation}</span>}
                            {e.working_area && <span>· {e.working_area}</span>}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2"><ScoreBar score={e.score} /></td>
                      <td className="px-4 py-2"><EventBadge type={e.event} /></td>
                      <td className="px-4 py-2">
                        {thumbSrc ? (
                          <button
                            onClick={() => setSnapshot(e.snapshot)}
                            className="h-12 w-12 rounded overflow-hidden border bg-muted hover:ring-2 hover:ring-primary transition-all block"
                          >
                            <img
                              src={thumbSrc}
                              alt="snapshot"
                              className="h-full w-full object-cover"
                              loading="lazy"
                              onError={(ev) => { (ev.target as HTMLImageElement).style.display = "none"; }}
                            />
                          </button>
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </td>
                      <td className="px-4 py-2 no-print">
                        <Button size="sm" variant="ghost" onClick={() => setDetail(e)}>
                          {t("common.details")}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {totalCount > 0 && (
          <div className="flex items-center justify-between p-3 border-t text-xs text-muted-foreground no-print">
            <span>{t("events.page")} {page} {t("events.of")} {totalPages} · {totalCount} {t("events.total")}</span>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
                {t("events.prev")}
              </Button>
              <Button size="sm" variant="outline" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>
                {t("events.next")}
              </Button>
            </div>
          </div>
        )}
      </Card>

      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent>
          <SheetHeader><SheetTitle>{t("common.details")}</SheetTitle></SheetHeader>
          <pre className="mt-4 text-xs bg-muted p-3 rounded overflow-auto">
            {JSON.stringify(detail, null, 2)}
          </pre>
        </SheetContent>
      </Sheet>

      <SnapshotModal open={!!snapshot} onOpenChange={(o) => !o && setSnapshot(null)} src={snapshot} />
    </AppShell>
  );
}