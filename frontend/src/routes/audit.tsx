import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { fetchAuditReport, type AuthorizedPersonAudit } from "@/api/audit";
import { useToday } from "@/hooks/useToday";
import { toast } from "sonner";
import { ClipboardCheck, Download, Printer, RefreshCw } from "lucide-react";

export const Route = createFileRoute("/audit")({
  component: AuditPage,
});

type StatusFilter = "all" | "inside" | "exited";
type SortKey = "identity" | "first_entry_time" | "status";

// ── Summary card ──────────────────────────────────────────────────────────────

function AuditSummaryCard({ title, value, subtitle, tone }: {
  title: string;
  value: number | string;
  subtitle?: string;
  tone?: "success" | "danger";
}) {
  const numClass =
    tone === "success" ? "text-success" :
    tone === "danger"  ? "text-danger"  :
    "text-foreground";
  return (
    <Card className="px-4 py-3">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className={`text-2xl font-bold tabular-nums leading-tight mt-0.5 ${numClass}`}>{value}</div>
      {subtitle && <div className="text-xs text-muted-foreground mt-0.5">{subtitle}</div>}
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function AuditPage() {
  const { t } = useTranslation();
  const today = useToday();

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sortKey, setSortKey] = useState<SortKey>("identity");
  const [sortAsc, setSortAsc] = useState(true);
  const [detail, setDetail] = useState<AuthorizedPersonAudit | null>(null);

  // since/until are left undefined so the backend computes "today" using the
  // server's local clock — the same clock the pipeline stamps events with.
  // Computing "now" in the browser would use the wrong timezone whenever the
  // browser and server clocks don't match (e.g. UTC vs local).
  const q = useQuery({
    queryKey: ["audit", "report", today],
    queryFn: () => fetchAuditReport(),
    enabled: false,
    retry: false,
  });

  const generate = () => {
    q.refetch().catch((e) => toast.error(String(e)));
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc((a) => !a);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const persons = q.data?.authorized_persons ?? [];
  const filtered = persons.filter((p) => statusFilter === "all" || p.status === statusFilter);
  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortKey] ?? "";
    const bv = b[sortKey] ?? "";
    const cmp = String(av).localeCompare(String(bv));
    return sortAsc ? cmp : -cmp;
  });

  const exportCsv = () => {
    if (!q.data) return;
    const header = ["Identity", "Entry Time", "Entry Camera", "Exit Time", "Exit Camera", "Status"];
    const rows = sorted.map((p) =>
      [p.identity, p.first_entry_time ?? "", p.first_entry_camera ?? "", p.last_exit_time ?? "", p.last_exit_camera ?? "", p.status]
        .map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")
    );
    const BOM = "﻿";
    const csv = BOM + [header.map((h) => `"${h}"`).join(","), ...rows].join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `audit_${format(new Date(), "yyyyMMdd_HHmm")}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 100);
  };

  const sortHeader = (key: SortKey, label: string) => (
    <th
      className="text-left px-4 py-2.5 font-medium cursor-pointer select-none"
      onClick={() => toggleSort(key)}
    >
      {label}{sortKey === key && (sortAsc ? " ▲" : " ▼")}
    </th>
  );

  return (
    <AppShell title={t("audit.title")}>
      <style>{`
        @media print {
          aside, header, .no-print { display: none !important; }
          main { padding: 0 !important; }
        }
      `}</style>

      {/* ── Toolbar ── */}
      <Card className="p-3 mb-4 no-print">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="text-xs text-muted-foreground">
            {q.data
              ? `${t("audit.reportGenerated")}: ${format(new Date(q.data.generated_at), "yyyy-MM-dd HH:mm:ss")}`
              : t("audit.noData")}
          </div>
          <div className="flex gap-1.5">
            <Button size="sm" className="h-7 text-xs px-3" onClick={generate} disabled={q.isFetching}>
              <RefreshCw className={`h-3 w-3 mr-1 ${q.isFetching ? "animate-spin" : ""}`} />
              {t("audit.generateReport")}
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs px-3" onClick={exportCsv} disabled={!q.data}>
              <Download className="h-3 w-3 mr-1" />{t("events.exportCsv")}
            </Button>
            <Button size="sm" variant="outline" className="h-7 text-xs px-3" onClick={() => window.print()} disabled={!q.data}>
              <Printer className="h-3 w-3 mr-1" />{t("events.print")}
            </Button>
          </div>
        </div>
      </Card>

      {!q.data && !q.isFetching && (
        <Card className="p-12 text-center">
          <ClipboardCheck className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
          <p className="text-sm font-medium">{t("audit.noData")}</p>
        </Card>
      )}

      {q.error && (
        <Card className="p-6 text-center mb-4">
          <p className="text-danger text-sm mb-3">{t("common.error")}</p>
          <Button size="sm" variant="outline" onClick={generate}>{t("common.retry")}</Button>
        </Card>
      )}

      {q.data && (
        <>
          {/* ── Summary cards ── */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
            <AuditSummaryCard
              title={t("audit.totalPersons")}
              value={q.data.summary.total_unique_persons}
            />
            <AuditSummaryCard
              title={t("audit.authorizedCount")}
              value={q.data.summary.total_unique_authorized}
              subtitle={`${t("audit.currentlyInside")}: ${q.data.summary.authorized_currently_inside}`}
              tone="success"
            />
            <AuditSummaryCard
              title={t("audit.unauthorizedCount")}
              value={q.data.summary.total_unique_unauthorized}
              subtitle={`${t("audit.currentlyInside")}: ${q.data.summary.unknown_currently_inside}`}
              tone="danger"
            />
          </div>

          {/* ── Authorized persons table ── */}
          <Card className="overflow-hidden mb-4">
            <div className="flex items-center justify-between p-3 border-b">
              <h3 className="text-sm font-semibold">{t("audit.authorizedTable")}</h3>
              <div className="flex gap-1.5 no-print">
                {(["all", "inside", "exited"] as const).map((opt) => {
                  const active = statusFilter === opt;
                  return (
                    <button
                      key={opt}
                      onClick={() => setStatusFilter(opt)}
                      className={`px-3 py-1 rounded-full text-xs font-medium border transition-colors ${
                        active ? "bg-primary text-primary-foreground border-primary" : "border-border text-muted-foreground hover:bg-muted/60"
                      }`}
                    >
                      {opt === "all" ? t("audit.allPersons") : opt === "inside" ? t("audit.insideOnly") : t("audit.exitedOnly")}
                    </button>
                  );
                })}
              </div>
            </div>

            {sorted.length === 0 ? (
              <div className="p-12 text-center">
                <p className="text-sm text-muted-foreground">{t("audit.noData")}</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-muted-foreground text-xs">
                    <tr>
                      <th className="text-left px-4 py-2.5 font-medium">#</th>
                      {sortHeader("identity", t("audit.identity"))}
                      <th className="text-left px-4 py-2.5 font-medium">{t("audit.entryTime")}</th>
                      <th className="text-left px-4 py-2.5 font-medium">{t("audit.entryCamera")}</th>
                      <th className="text-left px-4 py-2.5 font-medium">{t("audit.exitTime")}</th>
                      <th className="text-left px-4 py-2.5 font-medium">{t("audit.exitCamera")}</th>
                      {sortHeader("status", t("audit.status"))}
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {sorted.map((p, i) => (
                      <tr
                        key={p.identity}
                        className="hover:bg-primary/5 cursor-pointer"
                        onClick={() => setDetail(p)}
                      >
                        <td className="px-4 py-2 text-xs text-muted-foreground tabular-nums">{i + 1}</td>
                        <td className="px-4 py-2 text-sm font-medium">{p.identity}</td>
                        <td className="px-4 py-2 text-xs tabular-nums whitespace-nowrap">
                          {p.first_entry_time ? format(new Date(p.first_entry_time), "yyyy-MM-dd HH:mm:ss") : "—"}
                        </td>
                        <td className="px-4 py-2"><Badge variant="outline" className="text-[10px]">{p.first_entry_camera ?? "—"}</Badge></td>
                        <td className="px-4 py-2 text-xs tabular-nums whitespace-nowrap">
                          {p.last_exit_time ? format(new Date(p.last_exit_time), "yyyy-MM-dd HH:mm:ss") : "—"}
                        </td>
                        <td className="px-4 py-2"><Badge variant="outline" className="text-[10px]">{p.last_exit_camera ?? "—"}</Badge></td>
                        <td className="px-4 py-2">
                          {p.status === "inside" ? (
                            <Badge className="bg-success text-success-foreground hover:bg-success/90 text-[10px] uppercase tracking-wide">
                              {t("audit.inside")}
                            </Badge>
                          ) : (
                            <Badge variant="secondary" className="text-[10px] uppercase tracking-wide">
                              {t("audit.exited")}
                            </Badge>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* ── Unknown occupancy panel ── */}
          <Card className="p-4">
            <h3 className="text-sm font-semibold mb-3">{t("audit.unknownOccupancy")}</h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
              <AuditSummaryCard title={t("audit.netInside")} value={q.data.unknown_summary.net_inside} tone="danger" />
              <AuditSummaryCard title={t("audit.uniqueClusters")} value={q.data.unknown_summary.unique_clusters} />
              <AuditSummaryCard title={t("audit.entryCameras")} value={q.data.unknown_summary.entry_count} />
              <AuditSummaryCard title={t("audit.exitCameras")} value={q.data.unknown_summary.exit_count} />
            </div>
            <div className="flex flex-wrap gap-2 text-xs text-muted-foreground mb-3">
              {Object.entries(q.data.unknown_summary.entry_cameras).map(([cam, n]) => (
                <Badge key={cam} variant="outline" className="text-[10px]">{cam}: {n} {t("audit.entryCameras").toLowerCase()}</Badge>
              ))}
              {Object.entries(q.data.unknown_summary.exit_cameras).map(([cam, n]) => (
                <Badge key={cam} variant="outline" className="text-[10px]">{cam}: {n} {t("audit.exitCameras").toLowerCase()}</Badge>
              ))}
            </div>
            <Link to="/debug" className="text-xs text-primary hover:underline no-print">
              {t("audit.viewClustering")}
            </Link>
          </Card>
        </>
      )}

      {/* ── Sighting timeline sheet ── */}
      <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <SheetContent>
          <SheetHeader><SheetTitle>{t("audit.sightingTimeline")} — {detail?.identity}</SheetTitle></SheetHeader>
          <div className="mt-4 space-y-2">
            {detail?.all_sightings.map((s, i) => (
              <div key={i} className="flex items-center justify-between text-sm border-b pb-2">
                <span className="tabular-nums">{format(new Date(s.timestamp), "yyyy-MM-dd HH:mm:ss")}</span>
                <Badge variant="outline" className="text-[10px]">{s.camera_id}</Badge>
                <Badge className={s.direction === "entry" ? "bg-success text-success-foreground text-[10px]" : "bg-danger text-danger-foreground text-[10px]"}>
                  {s.direction}
                </Badge>
              </div>
            ))}
          </div>
        </SheetContent>
      </Sheet>
    </AppShell>
  );
}
