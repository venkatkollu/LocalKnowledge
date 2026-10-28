import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { EmptyNote, Panel, Stat } from "@/components/system/panels";
import { useDocuments } from "@/hooks/use-documents";
import { useTelemetry } from "@/hooks/use-telemetry";
import { formatCount, formatMs } from "@/lib/format";

export default function Dashboard() {
  const documents = useDocuments();
  const telemetry = useTelemetry();
  return (
    <AppShell>
      {() => (
        <Workspace>
          <PageHeader
            title="Dashboard"
            description="Workspace overview"
          />
          <PageBody>
            {documents.error && documents.documents.length === 0 ? <EmptyNote>{documents.error}</EmptyNote> : (
              <>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Stat label="Documents" value={formatCount(documents.documents.length)} />
                  <Stat label="Indexed chunks" value={formatCount(documents.documents.reduce((sum, doc) => sum + doc.chunks, 0))} />
                  <Stat label="Queries" value={formatCount(telemetry.metrics?.queries)} />
                  <Stat label="p95 latency" value={formatMs(telemetry.metrics?.latency.p95)} />
                </div>
                <Panel title="Workspace status" description="Live counts from the local KnowledgeOS API">
                  {documents.loading && documents.documents.length === 0 ? <EmptyNote>Loading workspace…</EmptyNote> : <p className="text-[11.5px] text-muted-foreground">{documents.attention.length ? `${documents.attention.length} document${documents.attention.length === 1 ? "" : "s"} need attention.` : "All tracked documents are synchronized."}</p>}
                </Panel>
              </>
            )}
          </PageBody>
        </Workspace>
      )}
    </AppShell>
  );
}
