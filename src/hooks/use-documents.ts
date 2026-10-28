import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import {
  addDocumentPath,
  addGitRepository,
  cancelJob as cancelJobRequest,
  clearDocumentChunks,
  fetchChanges,
  fetchDocuments,
  fetchJob,
  fetchSyncQueue,
  indexDocument,
  removeDocument as removeDocumentRequest,
  syncDocuments,
  uploadDocuments,
} from "@/api/documents";
import type { DocumentChange, DocumentStatus, GitSourceRequest, IngestionJob, KnowledgeDocument, UploadItem } from "@/api/types";

const ATTENTION_ORDER: Record<DocumentStatus, number> = { failed: 0, changed: 1, not_indexed: 2, processing: 3, synced: 4 };

export interface DocumentsController {
  loading: boolean;
  error: string | null;
  documents: KnowledgeDocument[];
  changes: DocumentChange[];
  jobs: IngestionJob[];
  attention: KnowledgeDocument[];
  uploads: UploadItem[];
  refresh: () => void;
  syncOne: (doc: KnowledgeDocument) => void;
  indexOne: (doc: KnowledgeDocument) => void;
  syncAll: () => void;
  addFiles: (files: File[]) => void;
  addFolder: (path: string) => Promise<{ ok: boolean; message: string }>;
  addGit: (input: GitSourceRequest) => Promise<{ ok: boolean; message: string }>;
  clearUploads: () => void;
  cancelJob: (jobId: string) => void;
  clearChunks: (doc: KnowledgeDocument) => void;
  removeDocument: (doc: KnowledgeDocument) => void;
  onFiles: (files: File[]) => void;
  onFolder: (path: string) => Promise<{ ok: boolean; message: string }>;
}

export function useDocuments(): DocumentsController {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [changes, setChanges] = useState<DocumentChange[]>([]);
  const [jobs, setJobs] = useState<IngestionJob[]>([]);
  const [uploads, setUploads] = useState<UploadItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const refresh = useCallback(() => setNonce((value) => value + 1), []);
  const timers = useRef<number[]>([]);

  const load = useCallback(async (signal: AbortSignal) => {
    setLoading(true);
    try {
      const [nextDocuments, nextChanges, nextJobs] = await Promise.all([fetchDocuments(signal), fetchChanges(signal).catch(() => []), fetchSyncQueue(signal).catch(() => [])]);
      if (signal.aborted) return;
      setDocuments(nextDocuments);
      setChanges(nextChanges);
      setJobs((current) => {
        const merged = [...nextJobs, ...current];
        return merged.filter((job, index, items) => items.findIndex((item) => item.id === job.id) === index);
      });
      setError(null);
    } catch (value) {
      if (!signal.aborted) setError(value instanceof Error ? value.message : "Could not load documents");
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, nonce]);

  useEffect(() => {
    const running = jobs.filter((job) => job.status === "queued" || job.status === "running");
    if (running.length === 0) return;
    const id = window.setInterval(() => {
      for (const job of running) {
        void fetchJob(job.id).then((updated) => {
          if (!updated) return;
          setJobs((current) => updated.status === "completed" ? current.filter((item) => item.id !== updated.id) : current.map((item) => item.id === updated.id ? updated : item));
          if (updated.status !== "running" && updated.status !== "queued") refresh();
        }).catch(() => undefined);
      }
    }, 1500);
    return () => window.clearInterval(id);
  }, [jobs, refresh]);

  useEffect(() => () => timers.current.forEach((id) => window.clearTimeout(id)), []);

  const queue = useCallback(async (promise: Promise<IngestionJob | null>, label: string) => {
    try {
      const job = await promise;
      if (job) setJobs((current) => [...current.filter((item) => item.id !== job.id), job]);
      toast(label);
      refresh();
    } catch (value) {
      toast.error(label, { description: value instanceof Error ? value.message : "Request failed" });
    }
  }, [refresh]);

  const syncOne = useCallback((doc: KnowledgeDocument) => void queue(syncDocuments(doc.id), `Sync queued for ${doc.filename}`), [queue]);
  const indexOne = useCallback((doc: KnowledgeDocument) => void queue(indexDocument(doc.id), `Index queued for ${doc.filename}`), [queue]);
  const syncAll = useCallback(() => void queue(syncDocuments(), "Sync queued"), [queue]);

  const addFiles = useCallback(async (files: File[]) => {
    if (files.length === 0) return;
    const items = files.map((file, index) => ({ id: `${file.name}-${index}-${Date.now()}`, name: file.name, sizeBytes: file.size, status: "uploading" as const }));
    setUploads(items);
    try {
      const result = await uploadDocuments(files);
      setUploads(items.map((item) => ({ ...item, status: "done" })));
      setJobs((current) => [...current, ...result.jobs]);
      toast(`Queued ${result.accepted.length} file${result.accepted.length === 1 ? "" : "s"}`);
      refresh();
    } catch (value) {
      setUploads(items.map((item) => ({ ...item, status: "failed", error: value instanceof Error ? value.message : "Upload failed" })));
      toast.error("Upload failed", { description: value instanceof Error ? value.message : "Request failed" });
    }
  }, [refresh]);

  const addFolder = useCallback(async (path: string) => {
    try {
      const result = await addDocumentPath(path);
      setJobs((current) => [...current, ...result.jobs]);
      refresh();
      return {
        ok: true,
        message: `Queued ${result.jobs.length} file${result.jobs.length === 1 ? "" : "s"} from ${path}`,
      };
    } catch (value) {
      return {
        ok: false,
        message: value instanceof Error ? value.message : "Folder ingestion failed",
      };
    }
  }, [refresh]);

  const addGit = useCallback(async (input: GitSourceRequest) => {
    try {
      const result = await addGitRepository(input);
      refresh();
      return {
        ok: true,
        message: result.files
          ? `Cloned ${result.commit?.slice(0, 8) ?? "repository"}; queued ${result.files} file${result.files === 1 ? "" : "s"}`
          : "Repository accepted",
      };
    } catch (value) {
      return {
        ok: false,
        message: value instanceof Error ? value.message : "Repository ingestion failed",
      };
    }
  }, [refresh]);

  const cancelJob = useCallback((jobId: string) => {
    const name = jobs.find((job) => job.id === jobId)?.documentName ?? "Job";
    setJobs((current) => current.filter((job) => job.id !== jobId));
    void cancelJobRequest(jobId)
      .then(() => {
        toast(`${name} cancelled`);
        refresh();
      })
      .catch((value: unknown) => {
        toast.error(`Could not cancel ${name}`, { description: value instanceof Error ? value.message : "Request failed" });
        refresh();
      });
  }, [jobs, refresh]);

  const clearChunks = useCallback((doc: KnowledgeDocument) => {
    void clearDocumentChunks(doc.id)
      .then(() => {
        setJobs((current) => current.filter((job) => job.documentId !== doc.id));
        toast(`Chunks cleared for ${doc.filename}`);
        refresh();
      })
      .catch((value: unknown) => {
        toast.error(`Could not clear chunks for ${doc.filename}`, { description: value instanceof Error ? value.message : "Request failed" });
      });
  }, [refresh]);

  const removeDocument = useCallback((doc: KnowledgeDocument) => {
    void removeDocumentRequest(doc.id)
      .then(() => {
        setJobs((current) => current.filter((job) => job.documentId !== doc.id));
        setDocuments((current) => current.filter((item) => item.id !== doc.id));
        toast(`${doc.filename} removed from knowledge base`);
        refresh();
      })
      .catch((value: unknown) => {
        toast.error(`Could not remove ${doc.filename}`, { description: value instanceof Error ? value.message : "Request failed" });
      });
  }, [refresh]);

  const onFiles = useCallback(async (files: File[]) => {
    if (files.length === 0) return;
    const items = files.map((file, index) => ({ id: `${file.name}-${index}-${Date.now()}`, name: file.name, sizeBytes: file.size, status: "uploading" as const }));
    setUploads(items);
    try {
      const result = await uploadDocuments(files);
      setUploads(items.map((item) => ({ ...item, status: "done" })));
      setJobs((current) => [...current, ...result.jobs]);
      toast(`Queued ${result.accepted.length} file${result.accepted.length === 1 ? "" : "s"}`);
      refresh();
    } catch (value) {
      setUploads(items.map((item) => ({ ...item, status: "failed", error: value instanceof Error ? value.message : "Upload failed" })));
      toast.error("Upload failed", { description: value instanceof Error ? value.message : "Request failed" });
    }
  }, [refresh]);

  const onFolder = useCallback(async (path: string) => {
    return addFolder(path);
  }, [addFolder]);

  const attention = useMemo(() => documents.filter((doc) => doc.status !== "synced" && doc.status !== "processing").sort((a, b) => ATTENTION_ORDER[a.status] - ATTENTION_ORDER[b.status]), [documents]);
  return { loading, error, documents, changes, jobs, attention, uploads, refresh, syncOne, indexOne, syncAll, addFiles, addFolder, addGit, clearUploads: useCallback(() => setUploads([]), []), cancelJob, clearChunks, removeDocument, onFiles, onFolder };
}