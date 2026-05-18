import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { format } from "date-fns";
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from "recharts";
import { AppShell } from "@/components/layout/AppShell";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EventBadge } from "@/components/shared/EventBadge";
import { fetchLatestEvents, fetchStatsSummary } from "@/api/events";
import { useHealthCheck } from "@/hooks/useHealthCheck";
import { useToday } from "@/hooks/useToday";
import { useCameraList } from "@/context/SettingsContext";
import { AlertTriangle, Camera as CameraIcon, ShieldCheck, Bell } from "lucide-react";

export const Route = createFileRoute("/dashboard")({ component: DashboardPage });

function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const cameras = useCameraList();
  const { isOnline } = useHealthCheck();

  const today = useToday(); // re-triggers at midnight — never stale past 00:00

  const todayStats = useQuery({
    queryKey: ["stats", "today", today],
    queryFn: () => fetchStatsSummary({ since: `${today}T00:00:00.000Z` }),
    refetchInterval: 30_000,
    staleTime: 30_000,
    retry: false,
  });

  const latest = useQuery({
    queryKey: ["events", "latest", 10],
    queryFn: () => fetchLatestEvents({ limit: 10 }),
    refetchInterval: 15_000,
    staleTime: 15_000,
    retry: false,
  });

  const totalToday = todayStats.data?.total ?? 0;
  const unauthorizedToday = todayStats.data?.unknown ?? 0;
  const authorizedToday = todayStats.data?.authorized ?? 0;
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
