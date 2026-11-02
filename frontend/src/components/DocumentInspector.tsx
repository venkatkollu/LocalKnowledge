import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusDot } from "@/components/StatusDot";
import { DOC_STATUS } from "@/components/documents/status";
import { ChangeDiff } from "@/components/documents/ChangeNotice";
import { ChunkList } from "@/components/documents/ChunkList";
import { DocumentPreview } from "@/components/documents/DocumentPreview";
import { VersionTimeline } from "@/components/documents/VersionTimeline";
import type {
  DocumentChange,
  DocumentDetail,
  KnowledgeDocument,
} from "@/api/types";
import { fetchDocumentDetail } from "@/api/documents";
import { formatBytes, formatCount, formatDateTime } from "@/lib/format";
import { fileIconFor } from "@/lib/file-icon";
import { cn } from "@/lib/utils";
import {
  ChevronRight,
  Copy,
  FileSearch,
  MoreVertical,
  RefreshCw,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";

function MetaRow({
  label,
  value,
  mono = true,
}: {
  label: string;
  value?: string | number;
  mono?: boolean;
}) {
  if (value === undefined || value === "") return null;
  return (
    <div className="flex items-start gap-3 border-b border-border/60 py-1.5 last:border-0">
      <span className="term-dim w-28 shrink-0 text-[10.5px] tracking-wide uppercase">
        {label}
      </span>
      <span
        className={cn(
          "min-w-0 flex-1 break-words text-[11.5px] text-foreground/90",
          mono && "font-mono",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function shortHash(hash?: string): string | undefined {
  if (!hash) return undefined;
  return `SHA-256: ${hash.slice(0, 4)}…${hash.slice(-4)}`;
}

export function DocumentInspector({
  doc,
  change,
  canSync,
  onClose,
  onSync,
  onIndex,
  onCopyPath,
  className,
}: {
  doc: KnowledgeDocument | null;
  change?: DocumentChange;
  canSync: boolean;
  onClose: () => void;
  onSync: (doc: KnowledgeDocument) => void;
  onIndex: (doc: KnowledgeDocument) => void;
  onCopyPath: (doc: KnowledgeDocument) => void;
  className?: string;
}) {
  const [tab, setTab] = useState("preview");
  const [detail, setDetail] = useState<DocumentDetail | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const document = doc;

  useEffect(() => {
    if (!doc) return;
    const controller = new AbortController();
    void fetchDocumentDetail(doc.id, controller.signal)
      .then((value) => { setDetail(value); setDetailId(doc.id); })
      .catch((value) => {
        if (!controller.signal.aborted) setDetailError(value instanceof Error ? value.message : "Could not load document detail");
      });
    return () => controller.abort();
  }, [doc]);

  return (
    <section
      className={cn(
        "flex h-full min-h-0 w-full flex-col overflow-hidden bg-card",
        className,
      )}
    >
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-3">
        <FileSearch className="size-4 shrink-0 text-muted-foreground" />
        <span className="text-[11px] font-semibold tracking-[0.14em] uppercase">
          Inspector
        </span>
        <Button
          variant="ghost"
          size="icon-sm"
          className="ml-auto"
          onClick={onClose}
          aria-label="Close inspector"
        >
          <X className="size-4" />
        </Button>
      </div>

      {!document ? (
        <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
          <FileSearch className="size-6 text-muted-foreground/60" />
          <p className="mt-3 text-[12px] font-medium">No document selected</p>
          <p className="term-dim mt-1 text-[11px] leading-5">
            Pick a document from the grid to preview its text, metadata, versions
            and chunks.
          </p>
        </div>
      ) : (
        <>
          <div className="shrink-0 border-b border-border px-3 py-3">
            <div className="flex items-center gap-2">
              {(() => {
                const Icon = fileIconFor(document.filename);
                return <Icon className="size-4 shrink-0 text-muted-foreground" />;
              })()}
              <span className="truncate text-[13px] font-semibold tracking-tight">
                {document.filename}
              </span>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="ml-auto"
                    aria-label={`Actions for ${document.filename}`}
                  >
                    <MoreVertical className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-48 text-[12px]">
                  <DropdownMenuItem onClick={() => onSync(document)}>
                    <RefreshCw className="size-3.5" />
                    {document.chunks > 0 ? "Sync document" : "Index document"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => onCopyPath(document)}>
                    <Copy className="size-3.5" />
                    Copy path
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem disabled>Open in file manager</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="flex items-center gap-1.5 text-[11px] font-medium">
                <StatusDot
                  tone={DOC_STATUS[document.status].tone}
                  pulse={document.status === "processing"}
                />
                <span
                  className={cn(
                    document.status === "synced" && "text-[var(--term-ok)]",
                    document.status === "changed" && "text-[var(--term-warn)]",
                    document.status === "processing" && "text-[var(--term-info)]",
                    document.status === "failed" && "text-[var(--term-bad)]",
                    document.status === "not_indexed" && "text-muted-foreground",
                  )}
                >
                  {DOC_STATUS[document.status].label}
                </span>
              </span>
              <span className="term-dim truncate text-[10.5px]">
                {document.path}
              </span>
              <Button
                size="sm"
                variant="outline"
                className="ml-auto h-6 px-2 text-[10.5px]"
                onClick={() =>
                  document.status === "not_indexed"
                    ? onIndex(document)
                    : onSync(document)
                }
              >
                {document.status === "not_indexed" ? "Index" : "Sync"}
              </Button>
            </div>
          </div>

          <Tabs
            value={tab}
            onValueChange={setTab}
            className="min-h-0 flex-1 gap-0"
          >
            <div className="shrink-0 border-b border-border px-3 py-2">
              <TabsList className="h-8 w-full">
                <TabsTrigger value="preview" className="text-[11.5px]">
                  Preview
                </TabsTrigger>
                <TabsTrigger value="metadata" className="text-[11.5px]">
                  Metadata
                </TabsTrigger>
                <TabsTrigger value="versions" className="text-[11.5px]">
                  Versions
                </TabsTrigger>
                <TabsTrigger value="chunks" className="text-[11.5px]">
                  Chunks
                </TabsTrigger>
              </TabsList>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                  <TabsContent value="preview" className="space-y-3">
                    {change ? (
                      <ChangeDiff
                        change={change}
                        canSync={canSync}
                        onSync={() => onSync(document)}
                        onIndex={() => onIndex(document)}
                      />
                    ) : null}
                    {document.status === "processing" ? (
                      <div className="rounded-md border border-[var(--term-info)]/35 bg-[var(--term-info)]/5 px-3 py-2 text-[11px]">
                        <p className="font-medium text-[var(--term-info)]">
                          {DOC_STATUS.processing.label}
                          {document.stage ? ` · ${document.stage}` : ""}
                        </p>
                        <p className="term-dim mt-0.5 text-[10.5px]">
                          Embedding chunks —{" "}
                          {Math.round((document.progress ?? 0) * 100)}% complete.
                          The preview shows the text already on disk.
                        </p>
                      </div>
                    ) : null}
                    {detailError ? <p className="rounded-md border border-[var(--term-bad)]/40 bg-[var(--term-bad)]/10 px-3 py-2 text-[11px] text-[var(--term-bad)]">{detailError}</p> : null}
                    {!detail || detailId !== document.id ? <p className="term-dim text-[11.5px]">Loading document text…</p> : null}
                    {detail && detailId === document.id ? <DocumentPreview filename={document.filename} content={detail.content} /> : null}
                  </TabsContent>

                  <TabsContent value="metadata" className="space-y-3">
                    <div className="rounded-md border border-border bg-background px-3 py-2">
                      <MetaRow label="Filename" value={document.filename} />
                      <MetaRow
                        label="Path"
                        value={`${document.path}/${document.filename}`}
                      />
                      <MetaRow label="Size" value={formatBytes(document.sizeBytes)} />
                      <MetaRow label="Language" value={document.language} />
                      <MetaRow label="Chunks" value={formatCount(document.chunks)} />
                      <MetaRow
                        label="Current version"
                        value={document.version ? `v${document.version}` : undefined}
                      />
                      <MetaRow
                        label="Content hash"
                        value={shortHash(document.contentHash)}
                      />
                      <MetaRow
                        label="Indexed"
                        value={
                          document.indexedAt
                            ? formatDateTime(document.indexedAt)
                            : undefined
                        }
                      />
                      <MetaRow
                        label="Updated"
                        value={
                          document.updatedAt
                            ? formatDateTime(document.updatedAt)
                            : undefined
                        }
                      />
                    </div>

                    <Collapsible className="rounded-md border border-border bg-background">
                      <CollapsibleTrigger className="group flex w-full items-center gap-2 px-3 py-2 text-left">
                        <ChevronRight className="size-3.5 text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
                        <span className="text-[11.5px] font-semibold tracking-tight">
                          Pipeline details
                        </span>
                        <span className="term-dim ml-auto text-[10px]">
                          parser · chunker · embedding
                        </span>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <div className="border-t border-border px-3 py-2">
                          <MetaRow label="Parser" value={document.parser} />
                          <MetaRow label="Chunker" value={document.chunker} />
                          <MetaRow label="Embedding" value={document.embedding} />
                        </div>
                      </CollapsibleContent>
                    </Collapsible>

                    <p className="term-dim text-[10px] leading-4">
                      Parser, chunker and embedding configuration will appear
                      here when document processing is configured.
                    </p>
                  </TabsContent>

                  <TabsContent value="versions">
                    <VersionTimeline versions={detailId === document.id ? detail?.versions ?? [] : []} />
                  </TabsContent>

                  <TabsContent value="chunks">
                    <ChunkList
                      chunks={detailId === document.id ? detail?.chunks ?? [] : []}
                      total={detailId === document.id ? detail?.chunks.length ?? document.chunks : document.chunks}
                    />
                  </TabsContent>
            </div>
          </Tabs>
        </>
      )}
    </section>
  );
}
