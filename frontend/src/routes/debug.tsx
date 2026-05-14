import { createFileRoute } from "@tanstack/react-router";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from "recharts";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TerminalLog } from "@/components/shared/TerminalLog";
import { fetchHealth, SSE_EVENTS_URL } from "@/api/events";
import { fetchPipelineStatus, fetchPipelineStats, fetchSseSubscribers, fetchLogs, fetchGalleryInfo } from "@/api/stubs";
import { useSSEStream } from "@/hooks/useSSEStream";
import { Activity, Bell, Server, Users } from "lucide-react";

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
          <DebugStat icon={<Bell className="h-5 w-5" />} label={t("debug.cachedEvents")} value={health.data?.cached_events ?? "—"} />
          <DebugStat icon={<Activity className="h-5 w-5" />} label={t("debug.pipeline")} value={pstatus.data?.running ? t("common.running") : t("common.stopped")} tone={pstatus.data?.running ? "success" : "danger"} />
          <DebugStat icon={<Users className="h-5 w-5" />} label={t("debug.sseSubs")} value={subs.data?.count ?? "—"} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <SseStreamPanel />
          <PipelinePerfPanel />
        </div>

        <LogViewer />
        <Diagnostics />
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

  useMemo(() => {
    if (stats.data?.cameras[0]) {
      const fps = stats.data.cameras[0].fps;
      setHistory((h) => [...h, { t: new Date().toLocaleTimeString().slice(3), fps }].slice(-30));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
