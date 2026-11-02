import { AppShell } from "@/components/AppShell";
import { PageBody, PageHeader, Workspace } from "@/components/system/layout";
import { Callout, EmptyNote, Panel, Stat } from "@/components/system/panels";
import { DOC_STATUS } from "@/components/documents/status";
import { StatusDot } from "@/components/StatusDot";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { KnowledgeDocument } from "@/api/types";
import { useDocuments } from "@/hooks/use-documents";
import { formatBytes, formatCount, formatRelative } from "@/lib/format";
import { fileIconFor } from "@/lib/file-icon";
import { cn } from "@/lib/utils";
import { ChevronRight, FolderOpen, Loader2, RefreshCw } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router";

interface Collection {
  path: string;
  name: string;
  documents: KnowledgeDocument[];
  chunks: number;
  sizeBytes: number;
  pending: number;
  updatedAt?: number;
}

function buildCollections(documents: KnowledgeDocument[]): Collection[] {
  const map = new Map<string, KnowledgeDocument[]>();
  for (const doc of documents) {
    const key = doc.path || "~";
    const bucket = map.get(key);
    if (bucket) bucket.push(doc);
    else map.set(key, [doc]);
  }

  return [...map.entries()]
    .map(([path, items]) => ({
      path,
      name: path.split("/").filter(Boolean).pop() ?? path,
      documents: items,
      chunks: items.reduce((total, doc) => total + doc.chunks, 0),
      sizeBytes: items.reduce((total, doc) => total + doc.sizeBytes, 0),
      pending: items.filter(
        (doc) => doc.status !== "synced" && doc.status !== "processing",
      ).length,
      updatedAt: items.reduce<number | undefined>((latest, doc) => {
        if (!doc.updatedAt) return latest;
        return latest === undefined ? doc.updatedAt : Math.max(latest, doc.updatedAt);
      }, undefined),
    }))
    .sort((a, b) => b.chunks - a.chunks);
}

function CollectionsWorkspace() {
  const docs = useDocuments();
  const collections = useMemo(
    () => buildCollections(docs.documents),
    [docs.documents],
  );

  const totalPending = collections.reduce(
    (total, collection) => total + collection.pending,
    0,
  );

  return (
    <Workspace>
      <PageHeader
        title="Collections"
        description="Your corpus grouped by the folder each document came from."
      />

      <PageBody>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Collections" value={String(collections.length)} />
          <Stat label="Documents" value={formatCount(docs.documents.length)} />
          <Stat
            label="Chunks"
            value={formatCount(
              docs.documents.reduce((total, doc) => total + doc.chunks, 0),
            )}
          />
          <Stat
            label="Needs sync"
            value={String(totalPending)}
            tone={totalPending ? "warn" : "ok"}
          />
        </div>

        <Callout tone="info" title="Derived from document paths">
          This API surface exposes documents, not a collections resource. The
          grouping below is computed from each document's path, so it always
          matches what is actually on disk — nothing is stored twice.
        </Callout>

        {docs.loading ? (
          <div className="flex items-center gap-2 py-6 text-[12px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Loading documents…
          </div>
        ) : collections.length === 0 ? (
          <Panel>
            <EmptyNote>
              No documents yet. Add files or point the ingester at a folder and
              the collections will appear here.
            </EmptyNote>
          </Panel>
        ) : (
          collections.map((collection) => (
            <Collapsible
              key={collection.path}
              className="rounded-lg border border-border bg-card"
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5">
                <FolderOpen className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="text-[12.5px] font-semibold tracking-tight">
                  {collection.name}
                </span>
                {collection.pending > 0 ? (
                  <span className="flex items-center gap-1.5 text-[10.5px] text-[var(--term-warn)]">
                    <StatusDot tone="warn" />
                    {collection.pending} to sync
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5 text-[10.5px] text-[var(--term-ok)]">
                    <StatusDot tone="ok" />
                    in sync
                  </span>
                )}

                <div className="ml-auto flex items-center gap-1.5">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-6 px-2 text-[10.5px]"
                    disabled={collection.pending === 0}
                    onClick={() =>
                      collection.documents
                        .filter(
                          (doc) =>
                            doc.status !== "synced" && doc.status !== "processing",
                        )
                        .forEach((doc) =>
                          doc.status === "not_indexed"
                            ? docs.indexOne(doc)
                            : docs.syncOne(doc),
                        )
                    }
                  >
                    <RefreshCw className="size-3" />
                    Sync
                  </Button>
                  <CollapsibleTrigger asChild>
                    <Button size="sm" variant="ghost" className="h-6 px-2 text-[10.5px]">
                      <ChevronRight className="size-3.5" />
                      Files
                    </Button>
                  </CollapsibleTrigger>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-3 py-2 text-[10.5px]">
                <span className="term-dim truncate font-mono">{collection.path}</span>
                <span className="term-dim ml-auto tabular-nums">
                  {formatCount(collection.documents.length)} docs ·{" "}
                  {formatCount(collection.chunks)} chunks ·{" "}
                  {formatBytes(collection.sizeBytes)}
                </span>
                {collection.updatedAt ? (
                  <span className="term-dim">
                    updated {formatRelative(collection.updatedAt)}
                  </span>
                ) : null}
              </div>

              <CollapsibleContent>
                <ul className="divide-y divide-border border-t border-border">
                  {collection.documents.map((doc) => {
                    const Icon = fileIconFor(doc.filename);
                    const meta = DOC_STATUS[doc.status];
                    return (
                      <li
                        key={doc.id}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5"
                      >
                        <Icon className="size-3 shrink-0 text-muted-foreground" />
                        <span className="truncate text-[11px]">{doc.filename}</span>
                        <span
                          className={cn(
                            "flex items-center gap-1.5 text-[10px]",
                            meta.tone === "ok" && "text-[var(--term-ok)]",
                            meta.tone === "warn" && "text-[var(--term-warn)]",
                            meta.tone === "bad" && "text-[var(--term-bad)]",
                            meta.tone === "info" && "text-[var(--term-info)]",
                            meta.tone === "idle" && "term-dim",
                          )}
                        >
                          <StatusDot tone={meta.tone} />
                          {meta.label}
                        </span>
                        <span className="term-dim ml-auto tabular-nums">
                          {formatCount(doc.chunks)} chunks
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <div className="border-t border-border px-3 py-2">
                  <Link
                    to={`/documents?q=${encodeURIComponent(collection.name)}`}
                    className="text-[10.5px] font-medium text-[var(--term-ok)] hover:underline"
                  >
                    [ Open in Documents ]
                  </Link>
                </div>
              </CollapsibleContent>
            </Collapsible>
          ))
        )}
      </PageBody>
    </Workspace>
  );
}

export default function Collections() {
  return (
    <AppShell>
      {() => <CollectionsWorkspace />}
    </AppShell>
  );
}
