import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { StatusDot } from "@/components/StatusDot";
import type { BackendHealth } from "@/hooks/use-backend-health";

export function PrivacyIndicator({ health }: { health: BackendHealth }) {
  const online = health.state === "online";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 rounded-md border-border px-2 font-mono text-[11px] font-medium tracking-wide"
        >
          <StatusDot tone={online ? "ok" : health.state === "offline" ? "bad" : "idle"} />
          STATUS
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-80 rounded-lg p-0 font-mono text-xs"
      >
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <span className="term-ok">●</span>
          <span className="font-semibold tracking-wide">SERVICES</span>
          <span className="term-dim ml-auto">{online ? "connected" : health.state}</span>
        </div>
        <div className="px-3 py-3 leading-5 text-muted-foreground">
          {online ? "Workspace API is connected. Provider credentials remain encrypted on the backend." : "The workspace API is not reachable yet."}
        </div>
      </PopoverContent>
    </Popover>
  );
}
