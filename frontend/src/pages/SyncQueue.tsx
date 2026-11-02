import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { Callout, EmptyNote, Panel } from "@/components/system/panels";
import { SyncProgress } from "@/components/documents/SyncProgress";
import { DOC_STATUS } from "@/components/documents/status";
import { StatusDot } from "@/components/StatusDot";
import { Button } from "@/components/ui/button";
import type { DocumentStatus, KnowledgeDocument } from "@/api/types";
import { useDocuments } from "@/hooks/use-documents";
import { formatCount, formatRelative } from "@/lib/format";
import { fileIconFor } from "@/lib/file-icon";
import { createElement } from "react";
import { CheckCircle2, RefreshCw } from "lucide-react";

const GROUPS: { status: DocumentStatus; title: string; description: string }[] = [
  {
    status: "changed",
    title: "Changed locally",
    description: "SHA-256 detected a difference — the index is behind the file",
  },
  {
    status: "not_indexed",
    title: "Not indexed",
    description: "Present on disk but never parsed or embedded",
  },
  {
    status: "failed",
    title: "Failed",
    description: "Ingestion did not complete; the stage is preserved for retry",
  },
];

function reason(doc: KnowledgeDocument): string {
  if (doc.status === "failed") return doc.error ?? "Ingestion failed";
  if (doc.status === "changed") {
    return `Changed ${formatRelative(doc.updatedAt)}`;
  }
  return `On disk · ${formatCount(doc.chunks)} chunks indexed`;
}

function SyncRow({
  doc,
  onSync,
  onIndex,
}: {
  doc: KnowledgeDocument;
  onSync: (doc: KnowledgeDocument) => void;
  onIndex: (doc: KnowledgeDocument) => void;
}) {
  const meta = DOC_STATUS[doc.status];

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
      {createElement(fileIconFor(doc.filename), { className: "size-3.5 shrink-0 text-muted-foreground" })}
      <span className="truncate text-[12px] font-medium">{doc.filename}</span>
      <StatusDot tone={meta.tone} />
      <span className="term-dim text-[10.5px]">{reason(doc)}</span>
      <Button
        size="sm"
        variant={doc.status === "failed" ? "destructive" : "outline"}
        className="ml-auto h-6 px-2 text-[10.5px]"
        onClick={() =>
          doc.status === "not_indexed" ? onIndex(doc) : onSync(doc)
        }
      >
        {doc.status === "failed"
          ? "Retry"
          : doc.status === "not_indexed"
            ? "Index"
            : "Sync"}
      </Button>
    </li>
  );
}

function SyncQueueWorkspace() {
  const docs = useDocuments();
  const pending = docs.attention;

  return (
    <Workspace>
      <PageHeader
        title="Sync Queue"
        description="Everything the index is behind on, with the exact next step for each document."
      >
        <Button
          size="sm"
          className="h-7 text-[11px]"
          onClick={docs.syncAll}
          disabled={pending.length === 0}
        >
          <RefreshCw className="size-3.5" />
          Sync all
        </Button>
      </PageHeader>

      <PageBody>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px]">
          {pending.length === 0 ? (
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <CheckCircle2 className="size-3.5" />
              No documents in the queue
            </span>
          ) : (
            <>
              <span className="font-medium">
                {pending.length} document{pending.length === 1 ? "" : "s"} need
                {pending.length === 1 ? "s" : ""} attention
              </span>
              <span className="term-dim ml-auto">
                {formatCount(docs.documents.length)} documents tracked
              </span>
            </>
          )}
        </div>

        <SyncProgress jobs={docs.jobs} />

        {GROUPS.map((group) => {
          const rows = pending.filter((doc) => doc.status === group.status);
          if (rows.length === 0) return null;
          return (
            <Panel
              key={group.status}
              title={group.title}
              description={group.description}
            >
              <ul className="divide-y divide-border rounded-md border border-border bg-background">
                {rows.map((doc) => (
                  <SyncRow
                    key={doc.id}
                    doc={doc}
                    onSync={docs.syncOne}
                    onIndex={docs.indexOne}
                  />
                ))}
              </ul>
            </Panel>
          );
        })}

        {pending.length === 0 ? (
          <Panel>
            <EmptyNote>
              There are no documents or jobs to display.
            </EmptyNote>
          </Panel>
        ) : (
          <Callout tone="info" title="Incremental by default">
            Sync re-parses and re-chunks only the files whose content hash
            changed, and re-embeds only the chunks whose pipeline fingerprint no
            longer matches. Everything else is reused.
          </Callout>
        )}

      </PageBody>
    </Workspace>
  );
}

export default function SyncQueue() {
  return (
    <AppShell>
      {() => <SyncQueueWorkspace />}
    </AppShell>
  );
}