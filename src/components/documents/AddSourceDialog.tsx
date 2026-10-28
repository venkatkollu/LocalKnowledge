import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SUPPORTED_EXTENSIONS } from "@/lib/file-kind";
import type { UploadItem } from "@/api/types";
import { cn } from "@/lib/utils";
import { Check, FolderOpen, GitBranch, Loader2, Upload, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

function UploadRow({ item }: { item: UploadItem }) {
  return (
    <li className="flex items-center gap-2 text-[11px]">
      {item.status === "done" ? (
        <Check className="size-3.5 shrink-0 text-[var(--term-ok)]" />
      ) : item.status === "failed" ? (
        <X className="size-3.5 shrink-0 text-[var(--term-bad)]" />
      ) : item.status === "uploading" ? (
        <Loader2 className="size-3.5 shrink-0 animate-spin text-[var(--term-info)]" />
      ) : (
        <span className="inline-block size-2.5 shrink-0 rounded-full border border-border" />
      )}
      <span
        className={cn(
          "truncate",
          item.status === "failed" ? "text-[var(--term-bad)]" : "text-foreground/90",
        )}
      >
        {item.name}
      </span>
      <span className="term-dim ml-auto shrink-0">
        {item.error ?? `${Math.max(1, Math.round(item.sizeBytes / 1024))} KB`}
      </span>
    </li>
  );
}

export function AddSourceDialog({
  open,
  onOpenChange,
  uploads,
  onFiles,
  onFolder,
  onGit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  uploads: UploadItem[];
  onFiles: (files: File[]) => void;
  onFolder: (path: string) => Promise<{ ok: boolean; message: string }>;
  onGit: (input: { url: string; branch?: string }) => Promise<{
    ok: boolean;
    message: string;
  }>;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [folderPath, setFolderPath] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [repoRef, setRepoRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; message: string } | null>(null);

  const handleFiles = (files: File[]) => {
    if (files.length === 0) return;
    onFiles(files);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    handleFiles(Array.from(event.dataTransfer.files));
  };

  const shortExtensions = SUPPORTED_EXTENSIONS.filter((ext) =>
    ["pdf", "md", "txt", "py", "js", "ts", "json", "yaml", "csv", "sql", "go", "rs"].includes(
      ext,
    ),
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto font-mono sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="text-[15px] tracking-tight">
            Add source
          </DialogTitle>
          <DialogDescription className="text-[11.5px]">
            Upload files, index a local folder, or submit a repository source.
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="files">
          <TabsList className="w-full">
            <TabsTrigger value="files" className="text-[11.5px]">
              <Upload className="size-3.5" />
              Files
            </TabsTrigger>
            <TabsTrigger value="folder" className="text-[11.5px]">
              <FolderOpen className="size-3.5" />
              Folder
            </TabsTrigger>
            <TabsTrigger value="git" className="text-[11.5px]">
              <GitBranch className="size-3.5" />
              Git repository
            </TabsTrigger>
          </TabsList>

          <TabsContent value="files" className="space-y-3">
            <div
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              className={cn(
                "flex flex-col items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center transition-colors",
                dragging
                  ? "border-[var(--term-ok)] bg-accent/40"
                  : "border-border bg-card",
              )}
            >
              <Upload className="size-5 text-muted-foreground" />
              <p className="mt-2.5 text-[12.5px] font-semibold tracking-tight">
                {dragging ? "Drop files here" : "Drop files here"}
              </p>
              <p className="term-dim mt-1 text-[11px] leading-5">
                Upload documents to your local knowledge base
              </p>
              <p className="term-dim mt-2 text-[10.5px]">
                {shortExtensions.map((ext) => ext.toUpperCase()).join(" • ")} …
              </p>
              <input
                ref={inputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(event) => {
                  handleFiles(Array.from(event.target.files ?? []));
                  event.target.value = "";
                }}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="mt-3 h-7 text-[11px]"
                onClick={() => inputRef.current?.click()}
              >
                Browse files
              </Button>
            </div>

            {uploads.length > 0 ? (
              <div className="rounded-md border border-border bg-card px-3 py-2">
                <p className="term-dim pb-1.5 text-[10px] tracking-[0.12em] uppercase">
                  {uploads.every((item) => item.status === "done")
                    ? "Uploaded"
                    : "Uploading"}
                </p>
                <ul className="space-y-1">
                  {uploads.map((item) => (
                    <UploadRow key={item.id} item={item} />
                  ))}
                </ul>
                <p className="term-dim mt-2 border-t border-dashed border-border pt-2 text-[10px] leading-4">
                  Files are hashed for idempotency and queued for background ingestion.
                </p>
              </div>
            ) : null}
          </TabsContent>

          <TabsContent value="folder" className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="folder-path" className="text-[11.5px]">
                Folder path
              </Label>
              <Input
                id="folder-path"
                value={folderPath}
                onChange={(event) => setFolderPath(event.target.value)}
                placeholder="~/Projects/LocalKnowledgeOS/docs"
                className="h-8 font-mono text-[12px]"
              />
              <p className="term-dim text-[10.5px] leading-4">
                Every supported file under the path is ingested incrementally.
                Unchanged files are skipped by SHA-256.
              </p>
            </div>
            <Button
              size="sm"
              className="h-8 text-[11.5px]"
              disabled={!folderPath.trim() || busy}
              onClick={async () => {
                setBusy(true);
                setNotice(await onFolder(folderPath.trim()));
                setBusy(false);
              }}
            >
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : null}
              Index folder
            </Button>
            {notice ? (
              <p
                className={cn(
                  "text-[10.5px] leading-4",
                  notice.ok ? "text-[var(--term-ok)]" : "text-[var(--term-warn)]",
                )}
              >
                {notice.message}
              </p>
            ) : null}
          </TabsContent>

          <TabsContent value="git" className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="repo-url" className="text-[11.5px]">
                Repository URL
              </Label>
              <Input
                id="repo-url"
                value={repoUrl}
                onChange={(event) => setRepoUrl(event.target.value)}
                placeholder="https://github.com/…"
                className="h-8 font-mono text-[12px]"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="repo-ref" className="text-[11.5px]">
                Branch / commit
              </Label>
              <Input
                id="repo-ref"
                value={repoRef}
                onChange={(event) => setRepoRef(event.target.value)}
                placeholder="main"
                className="h-8 font-mono text-[12px]"
              />
            </div>
            <Button
              size="sm"
              className="h-8 text-[11.5px]"
              disabled={!repoUrl.trim() || busy}
              onClick={async () => {
                setBusy(true);
                setNotice(
                  await onGit({
                    url: repoUrl.trim(),
                    branch: repoRef.trim() || undefined,
                  }),
                );
                setBusy(false);
              }}
            >
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : null}
              Add repository
            </Button>
            <p className="term-dim text-[10px] leading-4">
              Repository ingestion is accepted when the repository worker is enabled on the backend.
            </p>
            {notice ? (
              <p
                className={cn(
                  "text-[10.5px] leading-4",
                  notice.ok ? "text-[var(--term-ok)]" : "text-[var(--term-warn)]",
                )}
              >
                {notice.message}
              </p>
            ) : null}
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
