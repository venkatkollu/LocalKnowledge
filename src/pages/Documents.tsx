import { AppShell } from "@/components/AppShell";
import { DocumentGrid } from "@/components/documents/DocumentGrid";
import { AddSourceDialog } from "@/components/documents/AddSourceDialog";
import { NeedsAttention } from "@/components/documents/ChangeNotice";
import { SyncProgress } from "@/components/documents/SyncProgress";
import { STATUS_FILTERS } from "@/components/documents/status";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { DocumentStatus, KnowledgeDocument } from "@/api/types";
import { useDocuments } from "@/hooks/use-documents";
import { formatCount } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  FileStack,
  FolderOpen,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

type Filter = DocumentStatus | "all";

function DocumentsWorkspace() {
  const docs = useDocuments();
  const addFiles = docs.addFiles;

  // Initialized from ?q= so other screens can deep-link into a filtered view.
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [draggingFiles, setDraggingFiles] = useState(false);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return docs.documents.filter((doc) => {
      if (filter !== "all" && doc.status !== filter) return false;
      if (!needle) return true;
      return (
        doc.filename.toLowerCase().includes(needle) ||
        doc.path.toLowerCase().includes(needle)
      );
    });
  }, [docs.documents, filter, search]);

  const totalChunks = useMemo(
    () => docs.documents.reduce((total, doc) => total + doc.chunks, 0),
    [docs.documents],
  );

  const open = (doc: KnowledgeDocument) => {
    setSelectedId(doc.id);
  };

  const copyPath = (doc: KnowledgeDocument) => {
    const full = `${doc.path}/${doc.filename}`;
    void navigator.clipboard
      ?.writeText(full)
      .then(() => toast("Path copied", { description: full }))
      .catch(() => toast.error("Could not copy the path"));
  };

  /* Window-wide drag & drop → uploads start immediately and the dialog opens. */
  useEffect(() => {
    const onDragEnter = (event: DragEvent) => {
      if (event.dataTransfer?.types?.includes("Files")) setDraggingFiles(true);
    };
    const onDragOver = (event: DragEvent) => {
      if (event.dataTransfer?.types?.includes("Files")) event.preventDefault();
    };
    const onDragLeave = (event: DragEvent) => {
      if (event.relatedTarget === null) setDraggingFiles(false);
    };
    const onDrop = (event: DragEvent) => {
      const files = Array.from(event.dataTransfer?.files ?? []);
      setDraggingFiles(false);
      if (files.length === 0) return;
      event.preventDefault();
      setAddOpen(true);
      void addFiles(files);
    };

    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [addFiles]);

  return (
    <>
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="shrink-0 border-b border-border px-4 py-3">
          <div className="mx-auto w-full max-w-5xl space-y-3">
            <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
              <div className="min-w-0">
                <h1 className="text-[15px] font-bold tracking-tight">
                  Documents
                </h1>
                <p className="term-dim mt-0.5 text-[11px]">
                  {formatCount(docs.documents.length)} documents ·{" "}
                  {formatCount(totalChunks)} chunks
                  {docs.attention.length
                    ? ` · ${docs.attention.length} need attention`
                    : ""}
                </p>
              </div>

              <div className="ml-auto flex flex-wrap items-center gap-1.5">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-[11px]"
                  onClick={() => setAddOpen(true)}
                >
                  <Upload className="size-3.5" />
                  Add files
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-[11px]"
                  onClick={() => setAddOpen(true)}
                >
                  <FolderOpen className="size-3.5" />
                  Add folder
                </Button>
                <Button
                  size="sm"
                  className="h-7 text-[11px]"
                  onClick={docs.syncAll}
                >
                  <RefreshCw className="size-3.5" />
                  Sync all
                </Button>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <div className="relative min-w-[180px] flex-1">
                <Search className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Filter by name or path"
                  className="h-7 pl-7 text-[11px]"
                />
              </div>
              <div className="flex flex-wrap gap-1">
                {STATUS_FILTERS.map((item) => (
                  <Button
                    key={item.key}
                    size="sm"
                    variant={filter === item.key ? "default" : "outline"}
                    className={cn("h-7 px-2 text-[10.5px]", filter !== item.key && "text-muted-foreground")}
                    onClick={() => setFilter(item.key)}
                  >
                    {item.label}
                  </Button>
                ))}
              </div>
            </div>
          </div>
        </header>

        {draggingFiles ? (
          <div className="pointer-events-none fixed inset-3 z-50 flex items-center justify-center rounded-xl border-2 border-dashed border-[var(--term-info)] bg-background/85">
            <p className="rounded-md border border-border bg-card px-4 py-2 text-[12px] font-semibold shadow-sm">
              Drop files to add them to the knowledge base
            </p>
          </div>
        ) : null}

        <div className="term-grid min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <div className="mx-auto w-full max-w-5xl space-y-3">
            <NeedsAttention
              attention={docs.attention}
              changes={docs.changes}
              onSync={docs.syncOne}
              onIndex={docs.indexOne}
              onOpen={open}
            />

            <SyncProgress jobs={docs.jobs} onCancel={docs.cancelJob} />

            {docs.loading ? (
              <div className="flex items-center gap-2 py-6 text-[12px] text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" />
                Loading documents…
              </div>
            ) : docs.error ? (
              <div className="rounded-lg border border-[var(--term-bad)]/40 bg-[var(--term-bad)]/10 px-3 py-3">
                <p className="text-[12px] font-semibold text-[var(--term-bad)]">
                  Could not load documents
                </p>
                <p className="term-dim mt-1 text-[11.5px]">{docs.error}</p>
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-2 h-7 text-[11px]"
                  onClick={docs.refresh}
                >
                  Retry
                </Button>
              </div>
            ) : (
              <DocumentGrid
                documents={visible}
                selectedId={selectedId}
                onOpen={open}
                onSync={docs.syncOne}
                onIndex={docs.indexOne}
                onCopyPath={copyPath}
                onRemoveDocument={docs.removeDocument}
                onClearChunks={docs.clearChunks}
                empty={
                  <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-card px-6 py-12 text-center">
                    <FileStack className="size-6 text-muted-foreground/60" />
                    <p className="mt-3 text-[12.5px] font-semibold tracking-tight">
                      {docs.documents.length === 0
                        ? "No documents yet"
                        : "No documents match this view"}
                    </p>
                    <p className="term-dim mt-1 max-w-sm text-[11px] leading-5">
                      {docs.documents.length === 0
                        ? "Add files or index a local folder to start building your knowledge base."
                        : "Try a different filter or search term."}
                    </p>
                    {docs.documents.length === 0 ? (
                      <Button
                        size="sm"
                        className="mt-3 h-7 text-[11px]"
                        onClick={() => setAddOpen(true)}
                      >
                        <Plus className="size-3.5" />
                        Add files
                      </Button>
                    ) : null}
                  </div>
                }
              />
            )}
          </div>
        </div>
      </main>

      <AddSourceDialog
        open={addOpen}
        onOpenChange={(open) => {
          setAddOpen(open);
          if (!open) docs.clearUploads();
        }}
        uploads={docs.uploads}
        onFiles={(files) => void addFiles(files)}
        onFolder={docs.addFolder}
        onGit={docs.addGit}
      />
    </>
  );
}

export default function Documents() {
  return (
    <AppShell>
      {() => <DocumentsWorkspace />}
    </AppShell>
  );
}