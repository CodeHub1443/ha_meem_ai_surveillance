import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { toast } from "sonner";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EventBadge } from "@/components/shared/EventBadge";
import { CameraStatusDot } from "@/components/shared/CameraStatusDot";
import { fetchEvents, fetchLatestEvents, SSE_EVENTS_URL } from "@/api/events";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { useSSEStream } from "@/hooks/useSSEStream";
import { useCameraList } from "@/context/SettingsContext";
import { Activity, AlertTriangle, Camera as CameraIcon, ShieldCheck, Bell } from "lucide-react";

export const Route = createFileRoute("/dashboard")({ component: DashboardPage });

function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const cameras = useCameraList();
  const { isOnline } = useHealthCheck();

  const todayISO = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.toISOString();
  }, []);

  const todayEvents = useQuery({
    queryKey: ["events", "today", todayISO],
    queryFn: () => fetchEvents({ since: todayISO, limit: 1000 }),
    retry: false,
  });

  const latest = useQuery({
    queryKey: ["events", "latest", 10],
    queryFn: () => fetchLatestEvents({ limit: 10 }),
    refetchInterval: 15000,
    retry: false,
  });

  const sse = useSSEStream(SSE_EVENTS_URL, true);

  useEffect(() => {
    const ev = sse.events[0];
    if (!ev || ev.event !== "UNKNOWN") return;
    toast.error(t("dashboard.alertTitle"), {
      description: `${t("events.camera")}: ${ev.camera_id} — ${format(new Date(ev.timestamp), "HH:mm:ss")}`,
      action: { label: t("common.view"), onClick: () => navigate({ to: "/events" }) },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sse.events.length]);

  const events = todayEvents.data || [];
  const totalToday = events.length;
  const unauthorizedToday = events.filter((e) => e.event === "UNKNOWN").length;
  const authorizedToday = totalToday - unauthorizedToday;
  const activeCameras = cameras.filter((c) => c.active).length;

  const pieData = [
    { name: t("events.authorized"), value: authorizedToday, color: "var(--success)" },
    { name: t("events.unknown"), value: unauthorizedToday, color: "var(--danger)" },
  ];

  return (
    <AppShell title={t("dashboard.title")}>
      <div className="space-y-6">
        {/* Stat cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard icon={<Bell className="h-5 w-5" />} label={t("dashboard.totalToday")} value={totalToday} />
          <StatCard
            icon={<AlertTriangle className="h-5 w-5" />}
            label={t("dashboard.unauthorized")}
            value={unauthorizedToday}
            tone="danger"
          />
          <StatCard icon={<CameraIcon className="h-5 w-5" />} label={t("dashboard.activeCameras")} value={activeCameras} />
          <StatCard
            icon={<ShieldCheck className="h-5 w-5" />}
            label={t("dashboard.systemStatus")}
            value={isOnline ? t("common.online") : t("common.offline")}
            tone={isOnline ? "success" : "danger"}
          />
        </div>

        {/* Recent + chart */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          <Card className="lg:col-span-3 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-foreground">{t("dashboard.recentAlerts")}</h2>
              <Button variant="ghost" size="sm" onClick={() => navigate({ to: "/events" })}>
                {t("common.viewAll")}
              </Button>
            </div>
            {latest.isLoading ? (
              <SkeletonRows />
            ) : latest.error ? (
              <ErrorState onRetry={() => latest.refetch()} />
            ) : !latest.data?.length ? (
              <EmptyState title={t("events.noneTitle")} body={t("events.noneBody")} />
            ) : (
              <div className="divide-y">
                {latest.data.slice(0, 10).map((e, i) => (
                  <div key={i} className={`flex items-center gap-3 py-3 ${e.event === "UNKNOWN" ? "border-l-2 border-l-danger -ml-5 pl-5" : ""}`}>
                    <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center text-muted-foreground text-xs shrink-0">
                      {(e.identity || "?").slice(0, 2).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <EventBadge type={e.event} />
                        <span className="text-sm font-medium text-foreground">
                          {e.identity || <em className="text-muted-foreground">{t("events.unknownPerson")}</em>}
                        </span>
                        <Badge variant="outline" className="text-[10px]">{e.camera_id}</Badge>
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {format(new Date(e.timestamp), "MMM d, HH:mm:ss")} · {(e.score * 100).toFixed(1)}%
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="lg:col-span-2 p-5">
            <h2 className="text-sm font-semibold text-foreground mb-4">{t("dashboard.breakdown")}</h2>
            <div className="relative h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={pieData} dataKey="value" innerRadius={60} outerRadius={90} paddingAngle={2} stroke="none">
                    {pieData.map((d, i) => (
                      <Cell key={i} fill={d.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                <div className="text-2xl font-bold text-foreground">{totalToday}</div>
                <div className="text-xs text-muted-foreground">{t("common.today")}</div>
              </div>
            </div>
            <div className="flex justify-center gap-4 mt-3 text-xs">
              <div className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-success" /> {authorizedToday}</div>
              <div className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-danger" /> {unauthorizedToday}</div>
            </div>
          </Card>
        </div>

        {/* Camera overview */}
        <div>
          <h2 className="text-sm font-semibold text-foreground mb-3">{t("dashboard.cameraOverview")}</h2>
          {cameras.length === 0 ? (
            <Card className="p-8">
              <EmptyState title={t("dashboard.noCameras")} body="" />
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {cameras.map((c) => {
                const camEvents = events.filter((e) => e.camera_id === c.id).length;
                const masked = c.rtsp_url.replace(/:\/\/.*?@/, "://●●●●@").replace(/\d+(?=\.\d+\/)/g, "x");
                return (
                  <Card key={c.id} className="p-4">
                    <div className="flex items-start justify-between mb-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <CameraStatusDot active={c.active} />
                          <span className="font-medium text-sm text-foreground truncate">{c.name}</span>
                        </div>
                        <div className="text-[11px] text-muted-foreground mt-0.5">{c.id}</div>
                      </div>
                      <Badge variant="outline" className="text-[10px]">{camEvents} {t("nav.events")}</Badge>
                    </div>
                    <div className="text-[11px] font-mono text-muted-foreground truncate mb-3">{masked}</div>
                    <Button variant="outline" size="sm" className="w-full" onClick={() => navigate({ to: "/live", search: { camera: c.id } as never })}>
                      <Activity className="h-3.5 w-3.5 mr-2" /> {t("dashboard.viewLive")}
                    </Button>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

function StatCard({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number | string; tone?: "danger" | "success" }) {
  const accent =
    tone === "danger" ? "text-danger bg-danger/10" : tone === "success" ? "text-success bg-success/10" : "text-primary bg-primary/10";
  return (
    <Card className="p-5">
      <div className="flex items-center justify-between mb-3">
        <span className={`h-9 w-9 rounded-md flex items-center justify-center ${accent}`}>{icon}</span>
      </div>
      <div className="text-2xl font-bold text-foreground tabular-nums">{value}</div>
      <div className="text-xs text-muted-foreground mt-1">{label}</div>
    </Card>
  );
}

function SkeletonRows() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3 animate-pulse">
          <div className="h-10 w-10 rounded-full bg-muted" />
          <div className="flex-1">
            <div className="h-3 w-1/3 bg-muted rounded mb-2" />
            <div className="h-2.5 w-1/4 bg-muted rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="text-center py-8">
      <Bell className="h-10 w-10 mx-auto text-muted-foreground/40 mb-3" />
      <p className="text-sm font-medium text-foreground">{title}</p>
      {body && <p className="text-xs text-muted-foreground mt-1">{body}</p>}
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-md border border-danger/30 bg-danger/5 p-4 text-sm">
      <p className="text-danger font-medium mb-2">{t("common.error")}</p>
      <Button size="sm" variant="outline" onClick={onRetry}>{t("common.retry")}</Button>
    </div>
  );
}
