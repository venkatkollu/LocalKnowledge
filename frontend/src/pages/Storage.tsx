import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { EmptyNote, Panel, Stat } from "@/components/system/panels";
import { useEffect, useState } from "react";
import { fetchStorage, type StorageSnapshot } from "@/api/storage";
import { formatBytes, formatCount } from "@/lib/format";

function StorageWorkspace() {
  const [snapshot, setSnapshot] = useState<StorageSnapshot | null>(null);
  useEffect(() => { void fetchStorage().then(setSnapshot).catch(() => setSnapshot(null)); }, []);
  return (
    <Workspace>
      <PageHeader
        title="Storage"
        description="Original files and indexed chunks stored by the local backend."
      />
      <PageBody>
        {snapshot ? <><div className="grid grid-cols-2 gap-2 sm:grid-cols-3"><Stat label="Documents" value={formatCount(snapshot.documents)} /><Stat label="Originals" value={formatBytes(snapshot.originalBytes)} /><Stat label="Active chunks" value={formatCount(snapshot.chunks)} /></div><Panel title="Storage adapter" description={snapshot.storage}><p className="break-all font-mono text-[11px] text-muted-foreground">{snapshot.dataDirectory}</p></Panel></> : <EmptyNote>Could not load storage statistics.</EmptyNote>}
      </PageBody>
    </Workspace>
  );
}

export default function Storage() {
  return <AppShell>{() => <StorageWorkspace />}</AppShell>;
}
