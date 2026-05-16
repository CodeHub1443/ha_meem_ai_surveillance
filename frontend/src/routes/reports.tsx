import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { useToday } from "@/hooks/useToday";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EventBadge } from "@/components/shared/EventBadge";
import { fetchEvents, fetchEventsCount, fetchStatsSummary, triggerClustering, fetchClusterGroups, snapshotUrl } from "@/api/events";
import type { ClusterGroup, ClusterSingleton } from "@/api/events";
import { fetchPersons } from "@/api/stubs";
import { API_BASE_URL } from "@/api/config";
import { FileText, Users, Download, Printer, ShieldCheck, ScanFace } from "lucide-react";
import type { EventType } from "@/types/surveillance";

export const Route = createFileRoute("/reports")({ component: ReportsPage });

type ReportTab = "events" | "persons";

function ReportsPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<ReportTab>("events");

  return (
    <AppShell title={t("reports.title")}>
      <div className="flex gap-2 mb-6 border-b pb-3">
        <Button variant={tab === "events" ? "default" : "ghost"} size="sm" onClick={() => setTab("events")}>
          <FileText className="h-4 w-4 mr-1.5" />
          {t("reports.eventReport")}
        </Button>
        <Button variant={tab === "persons" ? "default" : "ghost"} size="sm" onClick={() => setTab("persons")}>
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
const PAGE_SIZE = 50;

function EventReportTab() {
  const { t } = useTranslation();
  const today = useToday();

  const [since, setSince] = useState(today);
  const [until, setUntil] = useState(today);
  const [camFilter, setCamFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState<"" | EventType>("");
  const [page, setPage] = useState(1);
  const [clustering, setClustering] = useState(false);
  const [distanceThreshold, setDistanceThreshold] = useState(0.45);

  const [applied, setApplied] = useState({
    since: today,
    until: today,
    camFilter,
    typeFilter,
  });

  // Roll forward at midnight
  useEffect(() => {
    setSince(today);
    setUntil(today);
    setApplied((prev) => ({ ...prev, since: today, until: today }));
    setPage(1);
  }, [today]);

  const sinceISO = applied.since ? new Date(applied.since).toISOString() : undefined;
  const untilISO = applied.until ? `${applied.until}T23:59:59.999Z` : undefined;
  const cam = applied.camFilter || undefined;
  const evType = (applied.typeFilter || undefined) as EventType | undefined;

  const statsQ = useQuery({
    queryKey: ["report-stats", applied],
    queryFn: () => fetchStatsSummary({ camera_id: cam, since: sinceISO, until: untilISO }),
  });

  const eventsQ = useQuery({
    queryKey: ["report-events", applied, page],
    queryFn: () =>
      fetchEvents({
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        camera_id: cam,
        event_type: evType,
        since: sinceISO,
        until: untilISO,
      }),
  });

  const countQ = useQuery({
    queryKey: ["report-count", applied],
    queryFn: () =>
      fetchEventsCount({ camera_id: cam, event_type: evType, since: sinceISO, until: untilISO }),
  });

  const stats = statsQ.data;
  const events = eventsQ.data ?? [];
  const totalCount = countQ.data ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const applyFilters = () => {
    setApplied({ since, until, camFilter, typeFilter });
    setPage(1);
  };

  const handleAnalyze = async () => {
    setClustering(true);
    try {
      await triggerClustering(2, distanceThreshold);
      statsQ.refetch();
    } finally {
      setClustering(false);
    }
  };

  const exportCsv = async () => {
    // Fetch all rows (no limit) for the current filters
    const all = await fetchEvents({
      limit: 5000,
      camera_id: cam,
      event_type: evType,
      since: sinceISO,
      until: untilISO,
    });
    const rows = [
      ["Timestamp", "Camera", "Identity", "Event Type", "Score", "Track ID"],
      ...all.map((e) => [
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
            <Input value={camFilter} onChange={(e) => setCamFilter(e.target.value)} placeholder="camera_01" />
          </div>
          <div className="flex gap-2">
            <Button className="flex-1" onClick={applyFilters} disabled={eventsQ.isFetching}>
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

        <div className="flex gap-2 mt-3">
          {(["", "AUTHORIZED", "UNKNOWN"] as const).map((v) => (
            <Button
              key={v || "all"}
              size="sm"
              variant={typeFilter === v ? "default" : "outline"}
              onClick={() => {
                setTypeFilter(v);
                setApplied((prev) => ({ ...prev, typeFilter: v }));
                setPage(1);
              }}
            >
              {v === "" ? t("events.all") : v === "AUTHORIZED" ? t("events.authorized") : t("events.unknown")}
            </Button>
          ))}
        </div>
      </Card>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard label={t("reports.totalEvents")} value={statsQ.isLoading ? "…" : stats?.total ?? 0} />
        <StatCard label={t("events.authorized")} value={statsQ.isLoading ? "…" : stats?.authorized ?? 0} color="success" />
        <StatCard label={t("events.unknown")} value={statsQ.isLoading ? "…" : stats?.unknown ?? 0} color="danger" />
        <StatCard label={t("reports.uniquePersons")} value={statsQ.isLoading ? "…" : stats?.unique_persons ?? 0} />
        <UniqueUnauthorizedCard
          value={statsQ.isLoading ? null : (stats?.unique_unauthorized ?? null)}
          lastClusteredAt={stats?.last_clustered_at ?? null}
          totalEmbeddings={stats?.total_unknown_embeddings ?? 0}
          clustering={clustering}
          distanceThreshold={distanceThreshold}
          onDistanceChange={setDistanceThreshold}
          onAnalyze={handleAnalyze}
          t={t}
        />
      </div>

      {/* Cluster browser — only shown after at least one clustering run */}
      {stats?.last_clustered_at && (
        <ClusterBrowser lastClusteredAt={stats.last_clustered_at} />
      )}

      {/* Events table */}
      <Card className="overflow-hidden">
        {eventsQ.isLoading ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-10 bg-muted animate-pulse rounded" />
            ))}
          </div>
        ) : events.length === 0 ? (
          <div className="text-center py-14 text-sm text-muted-foreground">{t("events.noneTitle")}</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted/40 border-b">
                <tr>
                  {[t("events.time"), t("events.camera"), t("events.identity"), t("events.type"), t("events.score"), t("events.snapshot")].map((h) => (
                    <th key={h} className="text-left px-4 py-3 font-medium text-muted-foreground text-xs uppercase tracking-wide whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y">
                {events.map((e, i) => (
                  <tr key={i} className={`hover:bg-muted/20 transition-colors ${e.event === "UNKNOWN" ? "border-l-2 border-l-danger" : ""}`}>
                    <td className="px-4 py-2.5 font-mono text-xs whitespace-nowrap text-muted-foreground">
                      {format(new Date(e.timestamp), "yyyy-MM-dd HH:mm:ss")}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge variant="outline" className="text-xs">{e.camera_id}</Badge>
                    </td>
                    <td className="px-4 py-2.5 font-medium">
                      {e.identity ?? <span className="text-muted-foreground italic">{t("events.unknownPerson")}</span>}
                    </td>
                    <td className="px-4 py-2.5"><EventBadge type={e.event} /></td>
                    <td className="px-4 py-2.5 font-mono text-xs">{(e.score * 100).toFixed(1)}%</td>
                    <td className="px-4 py-2.5">
                      {snapshotUrl(e.snapshot) ? (
                        <img src={snapshotUrl(e.snapshot)!} className="h-9 w-9 rounded object-cover border" alt="snapshot" />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {totalCount > PAGE_SIZE && (
              <div className="flex items-center justify-between px-4 py-3 border-t text-xs text-muted-foreground">
                <span>
                  {t("events.page")} {page} {t("events.of")} {totalPages} · {totalCount} {t("events.total")}
                </span>
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
          <Input placeholder={t("common.search")} value={search} onChange={(e) => setSearch(e.target.value)} className="w-48" />
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
                ? p.thumbnail_url.startsWith("http") ? p.thumbnail_url : `${API_BASE_URL}/${p.thumbnail_url}`
                : null;
              return (
                <Card key={p.id} className="p-5 text-center hover:shadow-md transition-shadow print:break-inside-avoid">
                  {thumbSrc ? (
                    <img src={thumbSrc} className="h-24 w-24 rounded-full object-cover mx-auto mb-3 border-2 border-border" alt={p.name} />
                  ) : (
                    <div className="h-24 w-24 rounded-full bg-primary/10 mx-auto mb-3 flex items-center justify-center border-2 border-border">
                      <span className="text-2xl font-bold text-primary">
                        {p.name.split(" ").map((s) => s[0]).join("").slice(0, 2).toUpperCase()}
                      </span>
                    </div>
                  )}
                  <h3 className="font-semibold text-sm leading-tight">{p.name}</h3>
                  <p className="text-xs text-muted-foreground mt-1">{p.sample_count} {t("gallery.samples")}</p>
                  {p.avg_accuracy != null && (
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {t("reports.avgAccuracy")}: <span className="font-medium text-foreground">{p.avg_accuracy}%</span>
                    </p>
                  )}
                  <div className="flex items-center justify-center gap-1 mt-2">
                    <ShieldCheck className="h-3.5 w-3.5 text-success" />
                    <span className="text-xs text-success font-medium">{t("events.authorized")}</span>
                  </div>
                </Card>
              );
            })}
          </div>
          <p className="text-xs text-muted-foreground">{t("reports.totalEnrolled", { n: persons.length })}</p>
        </>
      )}
    </div>
  );
}

/* ══════════════════════════════════════════════
   Cluster Browser
══════════════════════════════════════════════ */
function ClusterBrowser({ lastClusteredAt }: { lastClusteredAt: string }) {
  const { t } = useTranslation();

  const clusterQ = useQuery({
    queryKey: ["cluster-groups", lastClusteredAt],
    queryFn: () => fetchClusterGroups(4),
  });

  const data = clusterQ.data;

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold">{t("reports.clusterBrowser")}</h2>
        <p className="text-xs text-muted-foreground mt-0.5">{t("reports.clusterBrowserDesc")}</p>
      </div>

      {clusterQ.isLoading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-52 bg-card rounded-lg animate-pulse border" />
          ))}
        </div>
      ) : !data || (data.clusters.length === 0 && data.singletons.length === 0) ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">
          {t("reports.noClusters")}
        </Card>
      ) : (
        <>
          {data.clusters.length > 0 && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {data.clusters.map((cluster) => (
                <ClusterCard key={cluster.cluster_id} cluster={cluster} />
              ))}
            </div>
          )}

          {data.singletons.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-sm font-medium text-muted-foreground">{t("reports.singletons")}</h3>
              <div className="grid grid-cols-3 sm:grid-cols-5 md:grid-cols-7 lg:grid-cols-10 gap-3">
                {data.singletons.map((s) => (
                  <SingletonCard key={s.track_id} singleton={s} />
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ClusterCard({ cluster }: { cluster: ClusterGroup }) {
  const { t } = useTranslation();
  const placeholders = Math.max(0, 2 - cluster.snapshots.length);

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-sm truncate">
          {t("reports.clusterN", { n: cluster.cluster_id })}
        </span>
        <Badge variant="secondary" className="shrink-0 text-xs">
          {cluster.track_count} {t("reports.tracks")}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-1.5">
        {cluster.snapshots.map((snap, i) => (
          <img
            key={i}
            src={snapshotUrl(snap)!}
            className="w-full aspect-square rounded object-cover border bg-muted"
            alt={`cluster-${cluster.cluster_id}-${i}`}
          />
        ))}
        {Array.from({ length: placeholders }).map((_, i) => (
          <div key={`ph-${i}`} className="w-full aspect-square rounded bg-muted/40 border flex items-center justify-center">
            <ScanFace className="h-6 w-6 text-muted-foreground/25" />
          </div>
        ))}
      </div>

      <div className="text-xs text-muted-foreground space-y-1.5">
        <div className="flex flex-wrap gap-1">
          {cluster.cameras.map((cam) => (
            <Badge key={cam} variant="outline" className="text-xs px-1.5 py-0">{cam}</Badge>
          ))}
        </div>
        <div className="font-mono">
          {format(new Date(cluster.first_seen), "MMM d HH:mm")}
          {" – "}
          {format(new Date(cluster.last_seen), "MMM d HH:mm")}
        </div>
      </div>
    </Card>
  );
}

function SingletonCard({ singleton }: { singleton: ClusterSingleton }) {
  const { t } = useTranslation();
  const snapSrc = snapshotUrl(singleton.snapshot);

  return (
    <div className="flex flex-col items-center gap-1">
      {snapSrc ? (
        <img
          src={snapSrc}
          className="w-full aspect-square rounded object-cover border bg-muted"
          alt="singleton"
        />
      ) : (
        <div className="w-full aspect-square rounded bg-muted/40 border flex items-center justify-center">
          <ScanFace className="h-5 w-5 text-muted-foreground/25" />
        </div>
      )}
      <span className="text-xs text-muted-foreground/70 text-center leading-tight">{singleton.camera_id}</span>
      <span className="text-xs text-muted-foreground/50 text-center leading-tight">{t("reports.singleton")}</span>
    </div>
  );
}

/* ══════════════════════════════════════════════
   Shared helpers
══════════════════════════════════════════════ */
function StatCard({ label, value, color }: { label: string; value: number | string; color?: "success" | "danger" }) {
  return (
    <Card className="p-4">
      <div className={`text-2xl font-bold tabular-nums ${color === "success" ? "text-success" : color === "danger" ? "text-danger" : "text-foreground"}`}>
        {value}
      </div>
      <div className="text-xs text-muted-foreground mt-0.5">{label}</div>
    </Card>
  );
}

function UniqueUnauthorizedCard({
  value,
  lastClusteredAt,
  totalEmbeddings,
  clustering,
  distanceThreshold,
  onDistanceChange,
  onAnalyze,
  t,
}: {
  value: number | null;
  lastClusteredAt: string | null;
  totalEmbeddings: number;
  clustering: boolean;
  distanceThreshold: number;
  onDistanceChange: (v: number) => void;
  onAnalyze: () => void;
  t: (key: string) => string;
}) {
  const lastRunLabel = lastClusteredAt
    ? `${t("reports.lastAnalyzed")}: ${format(new Date(lastClusteredAt), "MMM d, HH:mm")}`
    : t("reports.neverAnalyzed");

  // cosine distance → similarity label
  const strictness =
    distanceThreshold <= 0.35 ? "Strict" :
    distanceThreshold <= 0.5  ? "Balanced" : "Loose";

  return (
    <Card className="p-4 flex flex-col justify-between gap-2">
      <div>
        <div className="text-2xl font-bold tabular-nums text-warning">
          {value === null ? "—" : value}
        </div>
        <div className="text-xs text-muted-foreground mt-0.5">{t("reports.uniqueUnauthorized")}</div>
        <div className="text-xs text-muted-foreground/70 mt-1">{lastRunLabel}</div>
        {totalEmbeddings > 0 && (
          <div className="text-xs text-muted-foreground/60 mt-0.5">
            {totalEmbeddings} embeddings stored
          </div>
        )}
      </div>

      {/* Threshold slider */}
      <div className="space-y-1">
        <div className="flex justify-between items-center">
          <span className="text-xs text-muted-foreground">Similarity</span>
          <span className="text-xs font-medium">{strictness} ({distanceThreshold.toFixed(2)})</span>
        </div>
        <input
          type="range"
          min={0.2}
          max={0.7}
          step={0.05}
          value={distanceThreshold}
          onChange={(e) => onDistanceChange(parseFloat(e.target.value))}
          disabled={clustering}
          className="w-full h-1.5 accent-primary cursor-pointer disabled:opacity-50"
          title={`Cosine distance threshold: ${distanceThreshold.toFixed(2)} (lower = stricter)`}
        />
        <div className="flex justify-between text-xs text-muted-foreground/50">
          <span>Strict</span>
          <span>Loose</span>
        </div>
      </div>

      <Button
        size="sm"
        variant="outline"
        className="w-full"
        onClick={onAnalyze}
        disabled={clustering || totalEmbeddings === 0}
        title={t("reports.analyzeHint")}
      >
        <ScanFace className="h-3.5 w-3.5 mr-1.5" />
        {clustering ? t("reports.analyzing") : t("reports.analyze")}
      </Button>
    </Card>
  );
}
