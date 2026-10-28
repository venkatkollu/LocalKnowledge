import { Button } from "@/components/ui/button";
import type {
  DocumentChange,
  KnowledgeDocument,
} from "@/api/types";
import { formatCount, formatRelative } from "@/lib/format";
import { fileIconFor } from "@/lib/file-icon";
import { ArrowRight, GitCompareArrows } from "lucide-react";
import { motion } from "framer-motion";

/** Compact list of documents that need attention (changed / failed / new). */
export function NeedsAttention({
  attention,
  changes,
  onSync,
  onIndex,
  onOpen,
}: {
  attention: KnowledgeDocument[];
  changes: DocumentChange[];
  onSync: (doc: KnowledgeDocument) => void;
  onIndex: (doc: KnowledgeDocument) => void;
  onOpen: (doc: KnowledgeDocument) => void;
}) {
  if (attention.length === 0) return null;
  const changeByDoc = new Map(changes.map((change) => [change.documentId, change]));

  return (
    <motion.section
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-lg border border-[var(--term-warn)]/35 bg-[var(--term-warn)]/10 p-3"
    >
      <div className="flex items-center gap-2">
        <GitCompareArrows className="size-3.5 shrink-0 text-[var(--term-warn)]" />
        <p className="text-[12px] font-semibold tracking-tight">
          {attention.length} document{attention.length === 1 ? "" : "s"} need
          {attention.length === 1 ? "s" : ""} attention
        </p>
      </div>

      <ul className="mt-2.5 divide-y divide-[var(--term-warn)]/20 rounded-md border border-[var(--term-warn)]/25 bg-card">
        {attention.map((doc) => {
          const Icon = fileIconFor(doc.filename);
          const change = changeByDoc.get(doc.id);
          return (
            <li
              key={doc.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2"
            >
              <button
                type="button"
                onClick={() => onOpen(doc)}
                className="flex min-w-0 items-center gap-2 text-left"
              >
                <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="truncate text-[12px] font-medium">
                  {doc.filename}
                </span>
              </button>

              <span className="term-dim text-[10.5px]">
                {doc.status === "changed"
                  ? change
                    ? `Changed ${formatRelative(change.changedAt)} · ${change.previousChunks} → ${change.currentChunks} chunks`
                    : `Changed ${formatRelative(doc.updatedAt)}`
                  : doc.status === "failed"
                    ? "Sync failed"
                    : "Not indexed"}
              </span>

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
        })}
      </ul>
    </motion.section>
  );
}

/** Previous/current comparison for a single document, shown in the inspector. */
export function ChangeDiff({
  change,
  onSync,
  onIndex,
  canSync,
}: {
  change: DocumentChange;
  onSync: () => void;
  onIndex: () => void;
  canSync: boolean;
  }) {
  const delta = change.currentChunks - change.previousChunks;
  return (
    <div className="rounded-lg border border-[var(--term-warn)]/35 bg-[var(--term-warn)]/10 p-3">
      <p className="text-[12px] font-semibold tracking-tight">Changes detected</p>
      <p className="term-dim mt-0.5 text-[11px]">
        {change.filename} was modified locally
      </p>

      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <div className="rounded-md border border-border bg-card px-3 py-2">
          <p className="term-dim text-[10px] tracking-[0.1em] uppercase">
            Previous version
          </p>
          <p className="mt-1 text-[13px] font-semibold tabular-nums">
            {formatCount(change.previousChunks)} chunks
          </p>
          {change.previousVersion ? (
            <p className="term-dim text-[10px]">v{change.previousVersion}</p>
          ) : null}
        </div>
        <div className="rounded-md border border-border bg-card px-3 py-2">
          <p className="term-dim text-[10px] tracking-[0.1em] uppercase">
            Current version
          </p>
          <p className="mt-1 flex items-baseline gap-1.5 text-[13px] font-semibold tabular-nums">
            {formatCount(change.currentChunks)} chunks
            {delta !== 0 ? (
              <span
                className={
                  delta > 0 ? "term-ok text-[10.5px]" : "term-warn text-[10.5px]"
                }
              >
                {delta > 0 ? `+${delta}` : delta}
              </span>
            ) : null}
          </p>
          {change.currentVersion ? (
            <p className="term-dim text-[10px]">v{change.currentVersion}</p>
          ) : null}
        </div>
      </div>

      {change.reused !== undefined ? (
        <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px]">
          <span className="term-dim">
            {formatCount(change.currentChunks)} chunks
          </span>
          <span className="text-[var(--term-ok)]">
            {formatCount(change.reused)} reused
          </span>
          <span className="text-[var(--term-info)]">
            {formatCount(change.newlyEmbedded ?? 0)} newly embedded
          </span>
        </p>
      ) : null}

      <p className="term-dim mt-2 flex items-center gap-1 text-[10px]">
        <ArrowRight className="size-3" />
        Change was detected by SHA-256, not by re-indexing everything.
      </p>

      <Button
        size="sm"
        className="mt-2.5 h-7 w-full text-[11px]"
        disabled={!canSync}
        onClick={canSync ? onSync : onIndex}
      >
        Sync document
      </Button>
    </div>
  );
}
