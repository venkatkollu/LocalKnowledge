import { StatusDot } from "@/components/StatusDot";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { DOC_STATUS } from "@/components/documents/status";
import { stageLabel } from "@/lib/job-stages";
import type { JobStage, KnowledgeDocument } from "@/api/types";
import { formatBytes, formatCount, formatRelative } from "@/lib/format";
import { fileIconFor } from "@/lib/file-icon";
import { cn } from "@/lib/utils";
import { Copy, MoreVertical, RefreshCw, ScanSearch, Square, Terminal, Trash2 } from "lucide-react";
import { createElement, type KeyboardEvent, type MouseEvent } from "react";

export function DocumentCard({
  doc,
  selected,
  onOpen,
  onSync,
  onIndex,
  onCopyPath,
  onRemoveDocument,
  onClearChunks,
}: {
  doc: KnowledgeDocument;
  selected: boolean;
  onOpen: (doc: KnowledgeDocument) => void;
  onSync: (doc: KnowledgeDocument) => void;
  onIndex: (doc: KnowledgeDocument) => void;
  onCopyPath: (doc: KnowledgeDocument) => void;
  onRemoveDocument?: (doc: KnowledgeDocument) => void;
  onClearChunks?: (doc: KnowledgeDocument) => void;
}) {
  const meta = DOC_STATUS[doc.status];
  const progress = Math.round((doc.progress ?? 0) * 100);

  const stop = (event: MouseEvent) => event.stopPropagation();

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onOpen(doc);
    }
  };

  const primaryAction =
    doc.status === "changed"
      ? { label: "Sync", run: onSync }
      : doc.status === "failed"
        ? { label: "Retry", run: onSync }
        : doc.status === "not_indexed"
          ? { label: "Index", run: onIndex }
          : null;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(doc)}
      onKeyDown={onKeyDown}
      className={cn(
        "group flex cursor-pointer flex-col rounded-lg border bg-card p-3 text-left transition-colors focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none",
        selected
          ? "border-[var(--term-ok)]/60 bg-accent/30"
          : "border-border hover:border-[var(--term-ok)]/40 hover:bg-accent/20",
      )}
    >
      <div className="flex items-center gap-2">
        {createElement(fileIconFor(doc.filename), { className: "size-3.5 shrink-0 text-muted-foreground" })}
        <span className="truncate text-[12.5px] font-semibold tracking-tight">
          {doc.filename}
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="icon-sm"
              className="-mr-1 ml-auto size-6 shrink-0 opacity-60 group-hover:opacity-100"
              onClick={stop}
              aria-label={`Actions for ${doc.filename}`}
            >
              <MoreVertical className="size-3.5" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48 text-[12px]">
            <DropdownMenuItem onClick={() => onOpen(doc)}>
              <ScanSearch className="size-3.5" />
              Open in inspector
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onSync(doc)}>
              <RefreshCw className="size-3.5" />
              {doc.chunks > 0 ? "Sync document" : "Index document"}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            {onRemoveDocument || onClearChunks && doc.chunks > 0 ? (
              <>
                <DropdownMenuItem onClick={() => onRemoveDocument?.(doc)}>
                  <Trash2 className="size-3.5" />
                  Remove document
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => onClearChunks?.(doc)}>
                  <Square className="size-3.5" />
                  Clear chunks
                </DropdownMenuItem>
              </>
            ) : null}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onCopyPath(doc)}>
              <Copy className="size-3.5" />
              Copy path
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      <p className="term-dim mt-1 truncate text-[10.5px]" title={`${doc.path}/${doc.filename}`}>
        {doc.path}
      </p>

      <div className="mt-2 flex items-center gap-3 text-[11px]">
        <span className="flex items-baseline gap-1">
          <span className="font-semibold tabular-nums">
            {formatCount(doc.chunks)}
          </span>
          <span className="term-dim">
            chunk{doc.chunks === 1 ? "" : "s"}
          </span>
        </span>
        <span className="term-dim">{formatBytes(doc.sizeBytes)}</span>
        {doc.version ? (
          <span className="term-dim ml-auto">v{doc.version}</span>
        ) : null}
      </div>

      <div className="mt-2.5 border-t border-dashed border-border pt-2.5">
        <div className="flex items-center gap-1.5">
          <StatusDot
            tone={meta.tone}
            pulse={doc.status === "processing"}
          />
          <span
            className={cn(
              "text-[11px] font-medium",
              doc.status === "synced" && "text-[var(--term-ok)]",
              doc.status === "changed" && "text-[var(--term-warn)]",
              doc.status === "processing" && "text-[var(--term-info)]",
              doc.status === "failed" && "text-[var(--term-bad)]",
              doc.status === "not_indexed" && "text-muted-foreground",
            )}
          >
            {meta.label}
          </span>

          {primaryAction ? (
            <Button
              size="sm"
              variant={doc.status === "failed" ? "destructive" : "default"}
              className="ml-auto h-6 px-2 text-[10.5px]"
              onClick={(event) => {
                stop(event);
                primaryAction.run(doc);
              }}
            >
              {primaryAction.label}
            </Button>
          ) : null}
        </div>

        {doc.status === "processing" ? (
          <div className="mt-2">
            <p className="term-dim text-[10.5px]">
              {doc.stage
                ? `${stageLabel(doc.stage as JobStage)}…`
                : "Embedding chunks…"}
            </p>
            <div className="mt-1.5 flex items-center gap-2">
              <div className="h-1 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-[var(--term-info)] transition-[width] duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <span className="term-dim w-8 text-right text-[10px] tabular-nums">
                {progress}%
              </span>
            </div>
          </div>
        ) : (
          <p
            className={cn(
              "mt-1 text-[10.5px] leading-4",
              doc.status === "failed" ? "text-[var(--term-bad)]/85" : "term-dim",
            )}
          >
            {doc.status === "synced"
              ? `Indexed ${formatRelative(doc.indexedAt ?? doc.updatedAt)}`
              : doc.status === "failed"
                ? (doc.error ?? meta.hint)
                : doc.status === "changed"
                  ? `${meta.hint} · ${formatRelative(doc.updatedAt)}`
                  : meta.hint}
          </p>
        )}

        {doc.status === "not_indexed" ? (
          <p className="term-dim mt-1 flex items-center gap-1 text-[10.5px]">
            <Terminal className="size-3" />
            {formatBytes(doc.sizeBytes)} on disk · not in the index
          </p>
        ) : null}
      </div>
    </div>
  );
}
