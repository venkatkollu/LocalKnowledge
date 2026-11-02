import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { EmptyNote, Panel } from "@/components/system/panels";
import { useEffect, useState } from "react";
import { apiRequest } from "@/api/client";

function SettingsWorkspace() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { void apiRequest<Record<string, unknown>>("/config").then(setConfig).catch(() => setConfig(null)); }, []);
  return (
    <Workspace>
      <PageHeader
        title="Settings"
        description="Workspace limits and connected provider metadata. Secrets stay server-side."
      />
      <PageBody maxWidth="max-w-4xl">
        {config ? <Panel title="Runtime configuration" description="Read-only values reported by the backend"><pre className="overflow-x-auto rounded-md border border-border bg-background p-3 text-[11px] leading-5">{JSON.stringify(config, null, 2)}</pre></Panel> : <EmptyNote>Could not load runtime configuration.</EmptyNote>}
      </PageBody>
    </Workspace>
  );
}

export default function Settings() {
  return <AppShell>{() => <SettingsWorkspace />}</AppShell>;
}
