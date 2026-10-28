import { apiRequest, uploadRequest } from "./client";
import type { DocumentChange, DocumentDetail, GitSourceRequest, IngestionJob, KnowledgeDocument } from "./types";

function normaliseDocument(value: Record<string, unknown>): KnowledgeDocument {
  const path = String(value.path ?? "");
  return {
    id: String(value.id), filename: String(value.filename), path,
    extension: String(value.extension ?? ""), language: String(value.language ?? "Document"),
    sizeBytes: Number(value.size_bytes ?? 0), chunks: Number(value.chunks ?? 0),
    status: value.status as KnowledgeDocument["status"], updatedAt: Number(value.updated_at ?? 0) || undefined,
    indexedAt: Number(value.indexed_at ?? 0) || undefined, version: Number(value.version ?? 0) || undefined,
    contentHash: typeof value.content_hash === "string" ? value.content_hash : undefined,
    parser: typeof value.parser === "string" ? value.parser : undefined,
    chunker: typeof value.chunker === "string" ? value.chunker : undefined,
    embedding: typeof value.embedding === "string" ? value.embedding : undefined,
    error: typeof value.error === "string" ? value.error : undefined,
    progress: typeof value.progress === "number" ? value.progress : undefined,
    stage: typeof value.stage === "string" ? value.stage : undefined,
  };
}

function normaliseJob(value: Record<string, unknown>): IngestionJob {
  return { id: String(value.id), documentId: typeof value.document_id === "string" ? value.document_id : undefined, documentName: typeof value.document_name === "string" ? value.document_name : undefined, stage: value.stage as IngestionJob["stage"], status: value.status as IngestionJob["status"], progress: Number(value.progress ?? 0), error: typeof value.error === "string" ? value.error : undefined };
}

export async function fetchDocuments(signal?: AbortSignal): Promise<KnowledgeDocument[]> {
  const payload = await apiRequest<{ documents: Record<string, unknown>[] }>("/documents", { signal });
  return (payload.documents ?? []).map(normaliseDocument);
}

export async function fetchChanges(signal?: AbortSignal): Promise<DocumentChange[]> {
  const payload = await apiRequest<{ changes: Record<string, unknown>[] }>("/changes/latest", { signal });
  return (payload.changes ?? []).map((value) => ({ documentId: String(value.document_id), filename: String(value.filename), path: String(value.path ?? ""), changedAt: Number(value.changed_at ?? 0), previousVersion: Number(value.previous_version ?? 0) || undefined, currentVersion: Number(value.current_version ?? 0) || undefined, previousChunks: Number(value.previous_chunks ?? 0), currentChunks: Number(value.current_chunks ?? 0), reused: Number(value.reused ?? 0) || undefined, newlyEmbedded: Number(value.newly_embedded ?? 0) || undefined }));
}

export async function fetchDocumentDetail(id: string, signal?: AbortSignal): Promise<DocumentDetail> {
  const value = await apiRequest<Record<string, unknown>>(`/documents/${encodeURIComponent(id)}`, { signal });
  const document = normaliseDocument(value.document as Record<string, unknown>);
  const versions = Array.isArray(value.versions) ? value.versions.map((item) => {
    const row = item as Record<string, unknown>;
    return {
      version: Number(row.version ?? 0), chunks: Number(row.chunks ?? 0),
      createdAt: Number(row.created_at ?? 0), current: Boolean(row.current),
      contentHash: typeof row.content_hash === "string" ? row.content_hash : undefined,
      reused: Number(row.reused ?? 0) || undefined,
      newlyEmbedded: Number(row.newly_embedded ?? 0) || undefined,
      note: typeof row.note === "string" ? row.note : undefined,
    };
  }) : [];
  const chunks = Array.isArray(value.chunks) ? value.chunks.map((item) => {
    const row = item as Record<string, unknown>;
    return {
      id: String(row.id), index: Number(row.index ?? 0),
      lineStart: Number(row.line_start ?? 0), lineEnd: Number(row.line_end ?? 0),
      section: typeof row.section === "string" ? row.section : undefined,
      symbol: typeof row.symbol === "string" ? row.symbol : undefined,
      tokens: Number(row.tokens ?? 0) || undefined, excerpt: String(row.excerpt ?? ""),
    };
  }) : [];
  return { document, content: String(value.content ?? ""), versions, chunks };
}

export async function uploadDocuments(files: File[], signal?: AbortSignal): Promise<{ jobs: IngestionJob[]; accepted: string[] }> {
  const form = new FormData();
  for (const file of files) form.append("files", file, file.name);
  const payload = await uploadRequest<{ jobs: Record<string, unknown>[]; accepted: string[] }>("/documents", form, signal);
  return { jobs: (payload.jobs ?? []).map(normaliseJob), accepted: payload.accepted ?? [] };
}

export async function syncDocuments(documentId?: string): Promise<IngestionJob | null> {
  const payload = await apiRequest<Record<string, unknown>>("/documents/sync", { method: "POST", body: JSON.stringify({ document_id: documentId }), headers: { "Content-Type": "application/json" } });
  return payload.job ? normaliseJob(payload.job as Record<string, unknown>) : null;
}

export async function indexDocument(documentId: string): Promise<IngestionJob | null> {
  const payload = await apiRequest<Record<string, unknown>>("/documents/index", { method: "POST", body: JSON.stringify({ document_id: documentId }), headers: { "Content-Type": "application/json" } });
  return payload.job ? normaliseJob(payload.job as Record<string, unknown>) : null;
}

export async function fetchJob(id: string, signal?: AbortSignal): Promise<IngestionJob | null> {
  const payload = await apiRequest<Record<string, unknown>>(`/jobs/${encodeURIComponent(id)}`, { signal });
  return normaliseJob(payload);
}

export async function fetchSyncQueue(signal?: AbortSignal): Promise<IngestionJob[]> {
  const payload = await apiRequest<{ jobs: Record<string, unknown>[] }>("/sync", { signal });
  return (payload.jobs ?? []).map(normaliseJob).filter((job) => job.status !== "completed" && job.status !== "cancelled");
}

export async function addDocumentPath(path: string): Promise<{ jobs: IngestionJob[]; accepted: string[] }> {
  const payload = await apiRequest<{ jobs?: Record<string, unknown>[]; accepted?: string[] }>("/documents", {
    method: "POST",
    body: JSON.stringify({ path }),
    headers: { "Content-Type": "application/json" },
  });
  return { jobs: (payload.jobs ?? []).map(normaliseJob), accepted: payload.accepted ?? [] };
}

export async function addGitRepository(request: GitSourceRequest): Promise<{ accepted: boolean; files?: number; commit?: string }> {
  return apiRequest("/repositories/git", { method: "POST", body: JSON.stringify(request), headers: { "Content-Type": "application/json" } });
}

export async function cancelJob(jobId: string): Promise<{ accepted: boolean; job_id: string }> {
  return apiRequest<{ accepted: boolean; job_id: string }>(`/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
}

export async function clearDocumentChunks(documentId: string): Promise<{ accepted: boolean; document_id: string; removed_chunks: number }> {
  return apiRequest<{ accepted: boolean; document_id: string; removed_chunks: number }>(`/documents/${encodeURIComponent(documentId)}/chunks`, { method: "DELETE" });
}

export async function removeDocument(documentId: string): Promise<{ accepted: boolean; document_id: string }> {
  return apiRequest<{ accepted: boolean; document_id: string }>(`/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}
