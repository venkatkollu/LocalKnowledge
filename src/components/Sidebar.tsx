import { NavLink } from "react-router";

import { StatusDot, type Tone } from "@/components/StatusDot";
import { NAV_SECTIONS } from "@/lib/system";
import { cn } from "@/lib/utils";
import type { BackendHealth } from "@/hooks/use-backend-health";

interface SystemRow {
  label: string;
  value: string;
  tone: Tone;
}

function buildSystemRows(health: BackendHealth): SystemRow[] {
  const online = health.state === "online";
  const tone: Tone = online ? "ok" : health.state === "offline" ? "bad" : "idle";
  return [
    { label: "Data", value: online ? `${health.data.documents ?? 0} docs` : "Offline", tone },
    { label: "Models", value: online ? "API profiles" : "Offline", tone },
    { label: "Index", value: online ? (health.data.activeIndex ?? "No active index") : "Offline", tone },
  ];
}

export function Sidebar({
  onNavigate,
  health,
  className,
}: {
  /** Called after a nav link is followed, so the mobile drawer can close. */
  onNavigate?: () => void;
  health: BackendHealth;
  className?: string;
}) {
  const rows = buildSystemRows(health);

  return (
    <aside
      className={cn(
        "flex w-full flex-col overflow-hidden bg-sidebar text-sidebar-foreground",
        className,
      )}
    >
      <div className="flex h-14 shrink-0 items-center gap-2.5 border-b border-sidebar-border px-4">
        <div className="grid size-7 shrink-0 place-items-center rounded-md border border-[var(--term-ok)]/40 bg-[var(--term-ok)]/10 text-[13px] font-bold text-[var(--term-ok)]">
          K
        </div>
        <div className="min-w-0">
          <p className="truncate text-[13px] font-semibold leading-tight tracking-tight">
            Local KnowledgeOS
          </p>
          <p className="term-dim truncate text-[10px] leading-tight">
            {health.state === "online" ? "Backend connected" : health.state === "offline" ? "Backend unavailable" : "Connecting to backend"}
          </p>
        </div>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title} className="mb-3 last:mb-0">
            <p className="term-dim px-2 pb-1.5 text-[10px] font-medium tracking-[0.14em] uppercase">
              {section.title}
            </p>
            <ul className="space-y-0.5">
              {section.items.map((item) => {
                const Icon = item.icon;
                const shipped = Boolean(item.to);

                if (!shipped) {
                  return (
                    <li key={item.label}>
                      <button
                        type="button"
                        disabled
                        title={`Planned for ${item.ships}`}
                        className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[12.5px] text-muted-foreground/70"
                      >
                        <Icon className="size-3.5 shrink-0" />
                        <span className="truncate">{item.label}</span>
                        <span className="term-dim ml-auto text-[9px] tracking-wider uppercase">
                          {item.ships}
                        </span>
                      </button>
                    </li>
                  );
                }

                return (
                  <li key={item.label}>
                    <NavLink
                      to={item.to!}
                      end={item.to === "/"}
                      onClick={onNavigate}
                      className={({ isActive }) =>
                        cn(
                          "group flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-[12.5px] transition-colors",
                          isActive
                            ? "bg-sidebar-accent font-medium text-sidebar-accent-foreground"
                            : "text-muted-foreground hover:bg-sidebar-accent/50 hover:text-foreground",
                        )
                      }
                    >
                      {({ isActive }) => (
                        <>
                          <Icon className="size-3.5 shrink-0" />
                          <span className="truncate">{item.label}</span>
                          <span
                            className={cn(
                              "ml-auto text-[10px]",
                              isActive ? "text-[var(--term-ok)]" : "term-dim",
                            )}
                          >
                            ▸
                          </span>
                        </>
                      )}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="shrink-0 border-t border-sidebar-border px-4 py-3">
        <p className="term-dim pb-2 text-[10px] font-medium tracking-[0.14em] uppercase">
          Local system
        </p>
        <ul className="space-y-1.5">
          {rows.map((row) => (
            <li key={row.label} className="flex items-center gap-2 text-[11px]">
              <StatusDot
                tone={row.tone}
              />
              <span className="text-muted-foreground">{row.label}</span>
              <span className="term-dim ml-auto truncate">{row.value}</span>
            </li>
          ))}
        </ul>

      </div>
    </aside>
  );
}
