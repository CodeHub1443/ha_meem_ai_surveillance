import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { toast } from "sonner";
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from "recharts";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TerminalLog } from "@/components/shared/TerminalLog";
import { fetchHealth, SSE_EVENTS_URL, fetchStatsSummary, fetchClusterGroups, triggerClustering, snapshotUrl } from "@/api/events";
import type { ClusterGroup, ClusterSingleton } from "@/api/events";
import { fetchPipelineStatus, fetchPipelineStats, fetchSseSubscribers, fetchLogs, fetchGalleryInfo } from "@/api/stubs";
import { useSSEStream } from "@/hooks/useSSEStream";
import { Activity, Bell, Server, Users, GitMerge, Loader2, RefreshCw, User } from "lucide-react";

export const Route = createFileRoute("/debug")({ component: DebugPage });

function DebugPage() {
  const { t } = useTranslation();

  const health = useQuery({ queryKey: ["health-debug"], queryFn: fetchHealth, refetchInterval: 10000, retry: false });
  const pstatus = useQuery({ queryKey: ["pipeline-status"], queryFn: fetchPipelineStatus, refetchInterval: 10000 });
  const subs = useQuery({ queryKey: ["sse-subs"], queryFn: fetchSseSubscribers, refetchInterval: 10000 });

  return (
    <AppShell title={t("debug.title")}>
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <DebugStat icon={<Server className="h-5 w-5" />} label={t("debug.apiStatus")} value={health.isSuccess ? t("common.online") : t("common.offline")} tone={health.isSuccess ? "success" : "danger"} />
          <DebugStat icon={<Bell className="h-5 w-5" />} label={t("debug.cachedEvents")} value={health.data?.total_events ?? "—"} />
          <DebugStat icon={<Activity className="h-5 w-5" />} label={t("debug.pipeline")} value={pstatus.data?.running ? t("common.running") : t("common.stopped")} tone={pstatus.data?.running ? "success" : "danger"} />
          <DebugStat icon={<Users className="h-5 w-5" />} label={t("debug.sseSubs")} value={subs.data?.count ?? "—"} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SseStreamPanel />
          <PipelinePerfPanel />
        </div>

        <LogViewer />
        <Diagnostics />
        <ClusteringAnalysis />
      </div>
    </AppShell>
  );
}

function DebugStat({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string | number; tone?: "success" | "danger" }) {
  const accent = tone === "danger" ? "text-danger bg-danger/10" : tone === "success" ? "text-success bg-success/10" : "text-primary bg-primary/10";
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between">
        <span className={`h-9 w-9 rounded-md flex items-center justify-center ${accent}`}>{icon}</span>
      </div>
      <div className="mt-3 text-xl font-bold">{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </Card>
  );
}

function SseStreamPanel() {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(true);
  const [paused, setPaused] = useState(false);
  const sse = useSSEStream(SSE_EVENTS_URL, enabled);

  const lines = useMemo(
    () => sse.events.map((e) => `[${new Date(e.timestamp).toISOString()}] ${JSON.stringify(e)}`),
    [sse.events]
  );

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">{t("debug.sseStream")}</h2>
        <span className="text-xs">
          {sse.status === "connected" ? <span className="text-success">● {t("common.connected")}</span> : <span className="text-muted-foreground">○ {t("common.disconnected")}</span>}
        </span>
      </div>
      <TerminalLog lines={lines} autoScroll={!paused} height={320} />
      <div className="flex gap-2 mt-3">
        <Button size="sm" variant="outline" onClick={() => setEnabled((v) => !v)}>
          {enabled ? t("debug.disconnect") : t("debug.connect")}
        </Button>
        <Button size="sm" variant="outline" onClick={() => setPaused((p) => !p)}>{paused ? t("debug.resume") : t("debug.pause")}</Button>
        <Button size="sm" variant="outline" onClick={sse.clear}>{t("debug.clear")}</Button>
      </div>
    </Card>
  );
}

function PipelinePerfPanel() {
  const { t } = useTranslation();
  const stats = useQuery({ queryKey: ["pipeline-stats"], queryFn: fetchPipelineStats, refetchInterval: 3000 });
  const [history, setHistory] = useState<{ t: string; fps: number }[]>([]);

  useEffect(() => {
    if (stats.data?.cameras[0]) {
      const fps = stats.data.cameras[0].fps;
      setHistory((h) => [...h, { t: new Date().toLocaleTimeString().slice(3), fps }].slice(-30));
    }
  }, [stats.data]);

  return (
    <Card className="p-4">
      <h2 className="text-sm font-semibold mb-3">{t("debug.perf")}</h2>
      <div className="overflow-x-auto mb-3">
        <table className="w-full text-xs">
          <thead className="text-muted-foreground"><tr>
            <th className="text-left py-1.5 font-medium">{t("events.camera")}</th>
            <th className="text-left py-1.5 font-medium">{t("debug.fps")}</th>
            <th className="text-left py-1.5 font-medium">{t("debug.tracks")}</th>
            <th className="text-left py-1.5 font-medium">{t("debug.decisions")}</th>
            <th className="text-left py-1.5 font-medium">{t("debug.status")}</th>
          </tr></thead>
          <tbody>
            {stats.data?.cameras.map((c) => (
              <tr key={c.id} className="border-t">
                <td className="py-1.5 font-mono">{c.id}</td>
                <td className="py-1.5 tabular-nums">{c.fps.toFixed(1)}</td>
                <td className="py-1.5 tabular-nums">{c.active_tracks}</td>
                <td className="py-1.5 tabular-nums">{c.decisions_per_min}</td>
                <td className="py-1.5"><Badge className="bg-success text-success-foreground text-[10px]">{c.status}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="h-32">
        {/* TODO: real data comes from /api/debug/pipeline-stats */}
        <ResponsiveContainer>
          <LineChart data={history}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis dataKey="t" tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} />
            <YAxis tick={{ fontSize: 10, fill: "var(--muted-foreground)" }} />
            <Tooltip />
            <Line type="monotone" dataKey="fps" stroke="var(--primary)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function LogViewer() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<"events" | "bot" | "system">("events");
  const logs = useQuery({ queryKey: ["logs", tab], queryFn: () => fetchLogs(tab) });

  const download = () => {
    const text = (logs.data?.lines || []).join("\n");
    const blob = new Blob([text], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `${tab}_log.txt`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card className="p-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold">{t("debug.logViewer")}</h2>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => logs.refetch()}>{t("common.retry")}</Button>
          <Button size="sm" variant="outline" onClick={download}>{t("debug.downloadLog")}</Button>
        </div>
      </div>
      <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
        <TabsList>
          <TabsTrigger value="events">Events</TabsTrigger>
          <TabsTrigger value="bot">Bot</TabsTrigger>
          <TabsTrigger value="system">System</TabsTrigger>
        </TabsList>
        <TabsContent value={tab} className="mt-3">
          <TerminalLog lines={logs.data?.lines || []} showLineNumbers height={260} />
        </TabsContent>
      </Tabs>
    </Card>
  );
}

function Diagnostics() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const info = useQuery({ queryKey: ["gallery-info"], queryFn: fetchGalleryInfo, enabled: open });
  const health = useQuery({ queryKey: ["health-raw"], queryFn: fetchHealth, enabled: open, retry: false });

  return (
    <Card className="p-4">
      <button onClick={() => setOpen(!open)} className="text-sm font-semibold text-primary">
        {t("debug.diagnostics")} {open ? "▾" : "▸"}
      </button>
      {open && (
        <div className="mt-4 space-y-4 text-sm">
          <div>
            <h3 className="font-medium mb-2">{t("debug.galleryInfo")}</h3>
            <div className="bg-muted p-3 rounded text-xs font-mono space-y-1">
              <div>persons: {info.data?.person_count ?? "—"}</div>
              <div>embeddings: {info.data?.embedding_count ?? "—"}</div>
              <div>last built: {info.data?.last_built ?? "—"}</div>
            </div>
          </div>
          <div>
            <h3 className="font-medium mb-2">{t("debug.rawHealth")}</h3>
            <pre className="bg-muted p-3 rounded text-xs overflow-auto">
              {health.data ? JSON.stringify(health.data, null, 2) : (health.error ? "(unreachable)" : "...")}
            </pre>
          </div>
        </div>
      )}
    </Card>
  );
}

// ── Clustering Analysis ───────────────────────────────────────────────────────

function ClusteringAnalysis() {
  const qc = useQueryClient();
  const [minSize, setMinSize] = useState(2);
  const [threshold, setThreshold] = useState(0.45);
  const [lastResult, setLastResult] = useState<{
    n_clusters: number; n_noise: number; n_embeddings: number; n_tracks: number; unique_unauthorized: number;
  } | null>(null);

  const stats = useQuery({ queryKey: ["stats-summary-debug"], queryFn: () => fetchStatsSummary(), refetchInterval: 30000 });
  const groups = useQuery({ queryKey: ["cluster-groups"], queryFn: () => fetchClusterGroups(4) });

  const { t } = useTranslation();

  const clusterMut = useMutation({
    mutationFn: () => triggerClustering(minSize, threshold),
    onSuccess: (data) => {
      setLastResult(data);
      toast.success(t("debug.clusteringComplete", { clusters: data.n_clusters, noise: data.n_noise }));
      void qc.invalidateQueries({ queryKey: ["cluster-groups"] });
      void qc.invalidateQueries({ queryKey: ["stats-summary-debug"] });
    },
    onError: (e) => toast.error(String(e)),
  });

  const s = stats.data;

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 mb-4">
        <GitMerge className="h-4 w-4 text-primary" />
        <h2 className="text-sm font-semibold">{t("debug.clustering")}</h2>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
        <div className="bg-muted/50 rounded-md p-3 text-center">
          <div className="text-xl font-bold">{s?.unique_unauthorized ?? "—"}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">{t("debug.uniqueUnknowns")}</div>
        </div>
        <div className="bg-muted/50 rounded-md p-3 text-center">
          <div className="text-xl font-bold">{s?.total_unknown_embeddings ?? "—"}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">{t("debug.embeddingsStored")}</div>
        </div>
        <div className="bg-muted/50 rounded-md p-3 text-center">
          <div className="text-xl font-bold">{groups.data?.clusters.length ?? "—"}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">{t("debug.clusterCount")}</div>
        </div>
        <div className="bg-muted/50 rounded-md p-3 text-center">
          <div className="text-xl font-bold">{groups.data?.singletons.length ?? "—"}</div>
          <div className="text-[11px] text-muted-foreground mt-0.5">{t("debug.singletonCount")}</div>
        </div>
      </div>

      {/* Controls */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mb-4">
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium">{t("debug.minClusterSize")}</span>
            <span className="text-xs tabular-nums text-muted-foreground">{minSize}</span>
          </div>
          <Slider
            min={2} max={10} step={1}
            value={[minSize]}
            onValueChange={([v]) => setMinSize(v)}
            className="w-full"
          />
          <p className="text-[10px] text-muted-foreground mt-1">{t("debug.minTracksHint")}</p>
        </div>
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-medium">{t("debug.distanceThreshold")}</span>
            <span className="text-xs tabular-nums text-muted-foreground">{threshold.toFixed(2)}</span>
          </div>
          <Slider
            min={0.2} max={0.8} step={0.01}
            value={[threshold]}
            onValueChange={([v]) => setThreshold(v)}
            className="w-full"
          />
          <p className="text-[10px] text-muted-foreground mt-1">{t("debug.linkageCutoffHint")}</p>
        </div>
      </div>

      <div className="flex items-center gap-3 mb-5">
        <Button onClick={() => clusterMut.mutate()} disabled={clusterMut.isPending} size="sm">
          {clusterMut.isPending ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : <GitMerge className="h-3.5 w-3.5 mr-1.5" />}
          {t("debug.runClustering")}
        </Button>
        <Button variant="outline" size="sm" onClick={() => { void groups.refetch(); void stats.refetch(); }}>
          <RefreshCw className="h-3.5 w-3.5 mr-1.5" />{t("debug.refresh")}
        </Button>
        {lastResult && (
          <span className="text-xs text-muted-foreground">
            {t("debug.lastRunSummary", { clusters: lastResult.n_clusters, tracks: lastResult.n_tracks, embeddings: lastResult.n_embeddings })}
          </span>
        )}
        {s?.last_clustered_at && (
          <span className="text-xs text-muted-foreground ml-auto">
            {t("debug.clusteredAt", { timestamp: format(new Date(s.last_clustered_at), "yyyy-MM-dd HH:mm") })}
          </span>
        )}
      </div>

      {/* Results */}
      {groups.isLoading ? (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : (!groups.data?.clusters.length && !groups.data?.singletons.length) ? (
        <p className="text-sm text-muted-foreground text-center py-8">
          {t("debug.noClustersYet")}
        </p>
      ) : (
        <div className="space-y-5">
          {(groups.data?.clusters.length ?? 0) > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                {t("debug.clusterHeader", { n: groups.data!.clusters.length })}
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {groups.data!.clusters.map((c) => (
                  <ClusterCard key={c.cluster_id} cluster={c} />
                ))}
              </div>
            </div>
          )}
          {(groups.data?.singletons.length ?? 0) > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                {t("debug.singletonsHeader", { n: groups.data!.singletons.length })}
              </h3>
              <div className="flex flex-wrap gap-3">
                {groups.data!.singletons.map((s) => (
                  <SingletonCard key={s.track_id} singleton={s} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function ClusterCard({ cluster }: { cluster: ClusterGroup }) {
  const { t } = useTranslation();
  const imgs = cluster.snapshots.filter(Boolean);
  return (
    <div className="border rounded-md p-3 bg-muted/20 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold">{t("debug.clusterCard", { n: cluster.cluster_id })}</span>
        <Badge variant="secondary" className="text-[10px] h-4 px-1.5">{t("debug.trackCount", { n: cluster.track_count })}</Badge>
      </div>
      <div className="flex gap-1.5 flex-wrap">
        {imgs.length ? imgs.map((url, i) => (
          <img
            key={i}
            src={snapshotUrl(url) ?? url}
            alt={`Cluster ${cluster.cluster_id} snap ${i + 1}`}
            className="h-14 w-14 rounded object-cover border"
            loading="lazy"
          />
        )) : (
          <div className="h-14 w-14 rounded bg-muted flex items-center justify-center">
            <User className="h-5 w-5 text-muted-foreground/40" />
          </div>
        )}
      </div>
      <div className="text-[10px] text-muted-foreground space-y-0.5">
        <div>{t("debug.cameras")}: {cluster.cameras.join(", ") || "—"}</div>
        <div>{t("debug.first")}: {format(new Date(cluster.first_seen), "MM-dd HH:mm")}</div>
        <div>{t("debug.last")}: {format(new Date(cluster.last_seen), "MM-dd HH:mm")}</div>
      </div>
    </div>
  );
}

function SingletonCard({ singleton }: { singleton: ClusterSingleton }) {
  const imgUrl = snapshotUrl(singleton.snapshot);
  return (
    <div className="border rounded-md p-2 bg-muted/20 flex flex-col items-center gap-1.5 w-[80px]">
      {imgUrl ? (
        <img src={imgUrl} alt={`Track ${singleton.track_id}`} className="h-12 w-12 rounded object-cover border" />
      ) : (
        <div className="h-12 w-12 rounded bg-muted flex items-center justify-center">
          <User className="h-4 w-4 text-muted-foreground/40" />
        </div>
      )}
      <div className="text-center">
        <div className="text-[10px] font-mono text-muted-foreground">#{singleton.track_id}</div>
        <div className="text-[9px] text-muted-foreground/70">{singleton.camera_id}</div>
      </div>
    </div>
  );
}
