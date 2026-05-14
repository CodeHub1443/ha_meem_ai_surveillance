import { Link, useRouterState } from "@tanstack/react-router";
import { LayoutDashboard, Bell, Camera, Users, Settings, Terminal, Shield, FileBarChart2 } from "lucide-react";
import { useTranslation } from "react-i18next";

const items = [
  { to: "/dashboard", key: "nav.dashboard", icon: LayoutDashboard },
  { to: "/events", key: "nav.events", icon: Bell },
  { to: "/live", key: "nav.live", icon: Camera },
  { to: "/gallery", key: "nav.gallery", icon: Users },
  { to: "/reports", key: "nav.reports", icon: FileBarChart2 },
  { to: "/settings", key: "nav.settings", icon: Settings },
  { to: "/debug", key: "nav.debug", icon: Terminal },
] as const;

export function Sidebar() {
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <aside className="w-60 shrink-0 bg-sidebar text-sidebar-foreground flex flex-col h-screen sticky top-0">
      <div className="px-5 py-5 border-b border-white/5 flex items-center gap-2.5">
        <div className="h-9 w-9 rounded-md bg-primary/15 flex items-center justify-center">
          <Shield className="h-5 w-5 text-primary" />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">TDI</div>
          <div className="text-[10px] text-sidebar-foreground/60 uppercase tracking-wider">Surveillance</div>
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-1">
        {items.map((it) => {
          const active = pathname === it.to || (it.to !== "/dashboard" && pathname.startsWith(it.to));
          const Icon = it.icon;
          return (
            <Link
              key={it.to}
              to={it.to}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-sidebar-active text-white"
                  : "text-sidebar-foreground hover:bg-white/5 hover:text-white"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span>{t(it.key)}</span>
            </Link>
          );
        })}
      </nav>

      <div className="p-4 border-t border-white/5 text-[10px] text-sidebar-foreground/50">
        v1.0 · AI-Powered
      </div>
    </aside>
  );
}
