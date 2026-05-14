import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format, subDays, endOfDay } from "date-fns";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EventBadge } from "@/components/shared/EventBadge";
import { fetchEvents } from "@/api/events";
import { fetchPersons } from "@/api/stubs";
import { snapshotUrl } from "@/api/events";
import { API_BASE_URL } from "@/api/config";
import {
  FileText,
  Users,
  Download,
  Printer,
  ShieldCheck,
} from "lucide-react";
import type { EventType } from "@/types/surveillance";

export const Route = createFileRoute("/reports")({ component: ReportsPage });

type ReportTab = "events" | "persons";

function ReportsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<ReportTab>("events");

  return (
    <AppShell title={t("reports.title")}>
      {/* Tab switcher */}
      <div className="flex gap-2 mb-6 border-b pb-3">
        <Button
          variant={tab === "events" ? "default" : "ghost"}
          size="sm"
          onClick={() => setTab("events")}
        >
          <FileText className="h-4 w-4 mr-1.5" />
          {t("reports.eventReport")}
        </Button>
        <Button
          variant={tab === "persons" ? "default" : "ghost"}
          size="sm"
          onClick={() => setTab("persons")}
        >
          <Users className="h-4 w-4 mr-1.5" />
          {t("reports.enrolledPersons")}
        </Button>
      </div>

      {tab === "events" ? <EventReportTab /> : <EnrolledPersonsTab />}
    </AppShell>
  );
}

/* ══════════════════════════════════════════════
   Tab 1 — Event Report
══════════════════════════════════════════════ */
function EventReportTab() {
  const { t } = useTranslation();

  const [since, setSince] = useState(format(subDays(new Date(), 7), "yyyy-MM-dd"));
  const [until, setUntil] = useState(format(new Date(), "yyyy-MM-dd"));
  const [camFilter, setCamFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState<"" | EventType>("");

  // Applied state — only updated when user clicks Apply
  const [applied, setApplied] = useState({ since, until, camFilter, typeFilter });

  const eventsQ = useQuery({
    queryKey: ["report-events", applied],
    queryFn: () =>
      fetchEvents({
        limit: 1000,
        camera_id: applied.camFilter || undefined,
        event_type: (applied.typeFilter || undefined) as EventType | undefined,
        since: applied.since ? new Date(applied.since).toISOString() : undefined,
      }),
  });

  const allEvents = eventsQ.data ?? [];

  // Client-side "until" filter (backend only has "since")
  const events = applied.until
    ? allEvents.filter((e) => new Date(e.timestamp) <= endOfDay(new Date(applied.until)))
    : allEvents;

  const authorized = events.filter((e) => e.event === "AUTHORIZED").length;
  const unknown = events.filter((e) => e.event === "UNKNOWN").length;
  const uniquePersons = new Set(
    events.filter((e) => e.identity).map((e) => e.identity),
  ).size;

  const exportCsv = () => {
    const rows = [
      ["Timestamp", "Camera", "Identity", "Event Type", "Score", "Track ID"],
      ...events.map((e) => [
        e.timestamp,
        e.camera_id,
        e.identity ?? "Unknown",
        e.event,
        `${(e.score * 100).toFixed(1)}%`,
        String(e.track_id),
      ]),
    ];
    const csv = rows.map((r) => r.map((c) => `"${c}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `tdi_event_report_${format(new Date(), "yyyyMMdd_HHmm")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <Card className="p-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 items-end">
          <div>
            <Label className="text-xs mb-1 block">{t("events.startDate")}</Label>
            <Input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
          </div>
          <div>
            <Label className="text-xs mb-1 block">{t("events.endDate")}</Label>
            <Input type="date" value={until} onChange={(e) => setUntil(e.target.value)} />
          </div>
          <div>
            <Label className="text-xs mb-1 block">{t("events.camera")}</Label>
            <Input
              value={camFilter}
              onChange={(e) => setCamFilter(e.target.value)}
              placeholder="camera_01"
            />
          </div>
          <div className="flex gap-2">
            <Button
              className="flex-1"
              onClick={() => setApplied({ since, until, camFilter, typeFilter })}
              disabled={eventsQ.isFetching}
            >
              {t("common.apply")}
            </Button>
            <Button variant="outline" onClick={exportCsv} title={t("events.exportCsv")}>
              <Download className="h-4 w-4" />
            </Button>
            <Button variant="outline" onClick={() => window.print()} title={t("reports.print")}>
              <Printer className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Event-type quick filter */}
        <div className="flex gap-2 mt-3">
          {(["", "AUTHORIZED", "UNKNOWN"] as const).map((v) => (
            <Button
              key={v || "all"}
              size="sm"
              variant={typeFilter === v ? "default" : "outline"}
              onClick={() => {
                setTypeFilter(v);
                setApplied((prev) => ({ ...prev, typeFilter: v }));
              }}
            >
              {v === "" ? t("events.all") : v === "AUTHORIZED" ? t("events.authorized") : t("events.unknown")}
            </Button>
          ))}
        </div>
      </Card>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label={t("reports.totalEvents")} value={events.length} />
        <StatCard label={t("events.authorized")} value={authorized} color="success" />
        <StatCard label={t("events.unknown")} value={unknown} color="danger" />
        <StatCard label={t("reports.uniquePersons")} value={uniquePersons} />
      </div>

      {/* Events table */}
      <Card className="overflow-hidden">
        {eventsQ.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-10 bg-muted animate-pulse rounded" />
            ))}
          </div>
        ) : events.length === 0 ? (
          <div className="text-center py-14 text-sm text-muted-foreground">
            {t("events.noneTitle")}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 border-b">
                <tr>
                  {[
                    t("events.time"),
                    t("events.camera"),
                    t("events.identity"),
                    t("events.type"),
                    t("events.score"),
                    t("events.snapshot"),
                  ].map((h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {events.slice(0, 200).map((e, i) => (
                  <tr
                    key={i}
                    className={`hover:bg-muted/20 transition-colors ${
                      e.event === "UNKNOWN" ? "border-l-2 border-l-danger" : ""
                    }`}
                  >
                    <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap text-muted-foreground">
                      {format(new Date(e.timestamp), "yyyy-MM-dd HH:mm:ss")}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge variant="outline" className="text-xs">
                        {e.camera_id}
                      </Badge>
                    </td>
                    <td className="px-4 py-2.5 font-medium">
                      {e.identity ?? (
                        <span className="text-muted-foreground italic">
                          {t("events.unknownPerson")}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <EventBadge type={e.event} />
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs">
                      {(e.score * 100).toFixed(1)}%
                    </td>
                    <td className="px-4 py-2.5">
                      {snapshotUrl(e.snapshot) ? (
                        <img
                          src={snapshotUrl(e.snapshot)!}
                          className="h-9 w-9 rounded object-cover border"
                          alt="snapshot"
                        />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {events.length > 200 && (
              <p className="text-xs text-center text-muted-foreground py-3 border-t">
                {t("reports.showingFirst", { n: 200 })} —{" "}
                <button
                  className="text-primary underline underline-offset-2"
                  onClick={exportCsv}
                >
                  {t("reports.downloadAll")}
                </button>
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

/* ══════════════════════════════════════════════
   Tab 2 — Enrolled Persons Directory
══════════════════════════════════════════════ */
function EnrolledPersonsTab() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");

  const personsQ = useQuery({ queryKey: ["persons"], queryFn: fetchPersons });
  const persons = (personsQ.data ?? []).filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold">{t("reports.enrolledPersons")}</h2>
          <p className="text-xs text-muted-foreground mt-0.5">{t("reports.enrolledDesc")}</p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            placeholder={t("common.search")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-48"
          />
          <Button variant="outline" size="sm" onClick={() => window.print()}>
            <Printer className="h-4 w-4 mr-1.5" />
            {t("reports.print")}
          </Button>
        </div>
      </div>

      {personsQ.isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-52 bg-card rounded-lg animate-pulse border" />
          ))}
        </div>
      ) : persons.length === 0 ? (
        <Card className="p-14 text-center">
          <Users className="h-12 w-12 mx-auto text-muted-foreground/30 mb-3" />
          <p className="text-sm text-muted-foreground">{t("gallery.noPersons")}</p>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
            {persons.map((p) => {
              const thumbSrc = p.thumbnail_url
                ? p.thumbnail_url.startsWith("http")
                  ? p.thumbnail_url
                  : `${API_BASE_URL}/${p.thumbnail_url}`
                : null;

              return (
                <Card
                  key={p.id}
                  className="p-5 text-center hover:shadow-md transition-shadow print:break-inside-avoid"
                >
                  {thumbSrc ? (
                    <img
                      src={thumbSrc}
                      className="h-24 w-24 rounded-full object-cover mx-auto mb-3 border-2 border-border"
                      alt={p.name}
                    />
                  ) : (
                    <div className="h-24 w-24 rounded-full bg-primary/10 mx-auto mb-3 flex items-center justify-center border-2 border-border">
                      <span className="text-2xl font-bold text-primary">
                        {p.name
                          .split(" ")
                          .map((s) => s[0])
                          .join("")
                          .slice(0, 2)
                          .toUpperCase()}
                      </span>
                    </div>
                  )}
                  <h3 className="font-semibold text-sm leading-tight">{p.name}</h3>
                  <p className="text-xs text-muted-foreground mt-1">
                    {p.sample_count} {t("gallery.samples")}
                  </p>
                  {p.avg_accuracy != null && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {t("reports.avgAccuracy")}: <span className="font-medium text-foreground">{p.avg_accuracy}%</span>
                    </p>
                  )}
                  <div className="flex items-center justify-center gap-1 mt-2">
                    <ShieldCheck className="h-3.5 w-3.5 text-success" />
                    <span className="text-xs text-success font-medium">
                      {t("events.authorized")}
                    </span>
                  </div>
                </Card>
              );
            })}
          </div>

          <p className="text-xs text-muted-foreground">
            {t("reports.totalEnrolled", { n: persons.length })}
          </p>
        </>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════
   Shared helpers
══════════════════════════════════════════════ */
function StatCard({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color?: "success" | "danger";
}) {
  return (
    <Card className="p-4">
      <div
        className={`text-2xl font-bold tabular-nums ${
          color === "success"
            ? "text-success"
            : color === "danger"
              ? "text-danger"
              : "text-foreground"
        }`}
      >
        {value}
      </div>
      <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
    </Card>
  );
}
