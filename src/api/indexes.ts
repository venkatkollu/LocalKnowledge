import { apiRequest } from "./client";
import type { RagIndex } from "./types";
type IndexAction = "build" | "validate" | "evaluate" | "activate" | "rollback";

function normalise(value: Record<string, unknown>): RagIndex {
  return { id: String(value.id), state: value.state as RagIndex["state"], embedding: typeof value.embedding === "string" ? value.embedding : undefined, dimensions: Number(value.dimensions ?? 0) || undefined, revision: Number(value.revision ?? 0) || undefined, documents: Number(value.documents ?? 0), chunks: Number(value.chunks ?? 0), createdAt: Number(value.created_at ?? 0) || undefined, builtAt: Number(value.built_at ?? 0) || undefined, validated: Boolean(value.validated), evaluated: Boolean(value.evaluated), evaluationScore: Number(value.evaluation_score ?? 0) || undefined, notes: typeof value.notes === "string" ? value.notes : undefined };
}

export async function fetchIndexes(signal?: AbortSignal): Promise<RagIndex[]> {
  const payload = await apiRequest<{ indexes: Record<string, unknown>[] }>("/indexes", { signal });
  return (payload.indexes ?? []).map(normalise);
}

export async function createIndex(input: { embedding?: string; notes?: string }): Promise<RagIndex | null> {
  const payload = await apiRequest<{ index: Record<string, unknown> }>("/indexes", { method: "POST", body: JSON.stringify(input), headers: { "Content-Type": "application/json" } });
  return payload.index ? normalise(payload.index) : null;
}

export async function runIndexAction(id: string, action: IndexAction): Promise<RagIndex | null> {
  const payload = await apiRequest<{ index: Record<string, unknown> }>(`/indexes/${encodeURIComponent(id)}/${action}`, { method: "POST" });
  return payload.index ? normalise(payload.index) : null;
}
