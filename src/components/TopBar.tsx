import { PrivacyIndicator } from "@/components/PrivacyIndicator";
import { StatusDot, type Tone } from "@/components/StatusDot";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Menu } from "lucide-react";
import type { BackendHealth } from "@/hooks/use-backend-health";

export function TopBar({
  onOpenNav,
  health,
  className,
}: {
  onOpenNav: () => void;
  health: BackendHealth;
  className?: string;
}) {
  const tone: Tone = health.state === "online" ? "ok" : health.state === "offline" ? "bad" : "idle";
  const label = health.state === "online" ? "Backend online" : health.state === "offline" ? "Backend offline" : "Checking backend";

  return (
    <header
      className={cn(
        "flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card px-3 sm:px-4",
        className,
      )}
    >
      <Button
        variant="ghost"
        size="icon-sm"
        className="lg:hidden"
        onClick={onOpenNav}
        aria-label="Open navigation"
      >
        <Menu className="size-4" />
      </Button>

      <div className="term-ok hidden text-[13px] font-bold sm:block">❯_</div>

      <div className="flex min-w-0 items-center gap-2">
        <StatusDot tone={tone} />
        <span className="text-[12.5px] font-medium tracking-tight">
          {label}
        </span>
        <span className="term-dim hidden text-[11px] md:inline">
          {health.state === "online" && health.data.version ? ` · v${health.data.version}` : ""}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-3">
        <PrivacyIndicator health={health} />
      </div>
    </header>
  );
}
