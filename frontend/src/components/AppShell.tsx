import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { useState, type ReactNode } from "react";
import { useBackendHealth } from "@/hooks/use-backend-health";

/**
 * Shared desktop-style shell: top bar, navigation rail and the responsive
 * navigation drawer. Pages render their own main column and inspector through
 * the render-prop `children` so each section owns its workspace.
 */
export function AppShell({
  children,
}: {
  children: () => ReactNode;
}) {
  const [navOpen, setNavOpen] = useState(false);
  const health = useBackendHealth();

  return (
    <div className="flex h-[100dvh] flex-col overflow-hidden bg-background text-foreground">
      <TopBar
        onOpenNav={() => setNavOpen(true)}
        health={health}
      />

      <div className="flex min-h-0 flex-1">
        <Sidebar
          health={health}
          className="hidden w-64 shrink-0 border-r border-sidebar-border lg:flex"
        />
        {children()}
      </div>

      <Sheet open={navOpen} onOpenChange={setNavOpen}>
        <SheetContent side="left" className="w-72 border-sidebar-border p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">
            Local KnowledgeOS sections
          </SheetDescription>
          <Sidebar
            health={health}
            onNavigate={() => setNavOpen(false)}
          />
        </SheetContent>
      </Sheet>
    </div>
  );
}
