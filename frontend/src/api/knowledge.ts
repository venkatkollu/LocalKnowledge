import { apiRequest, ApiError, getApiBase } from "./client";
import type { ChatResponse } from "./types";

export interface HealthStatus {
  ok: boolean;
  version?: string;
  documents?: number;
  chunks?: number;
  fts5Active?: boolean;
  activeIndex?: string;
  embeddingProvider?: string;
}

function healthPayload(value: unknown): HealthStatus {
  const record = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  return {
    ok: Boolean(record.ok),
    version: typeof record.version === "string" ? record.version : undefined,
    documents: typeof record.documents === "number" ? record.documents : undefined,
    chunks: typeof record.chunks === "number" ? record.chunks : undefined,
    fts5Active: Boolean(record.fts5_active),
    activeIndex: typeof record.active_index === "string" ? record.active_index : undefined,
    embeddingProvider: typeof record.embedding_provider === "string" ? record.embedding_provider : undefined,
  };
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthStatus> {
  return healthPayload(await apiRequest<unknown>("/health", { signal, timeoutMs: 5000 }));
}

export async function askKnowledge(question: string, signal?: AbortSignal): Promise<ChatResponse> {
  const value = await apiRequest<Record<string, unknown>>("/chat", {
    method: "POST",
    body: JSON.stringify({ question }),
    headers: { "Content-Type": "application/json" },
    signal,
    timeoutMs: 60000,
  });
  return normaliseChatResponse(value);
}

export async function askKnowledgeStream(question: string, signal: AbortSignal | undefined, onToken: (text: string) => void): Promise<ChatResponse> {
  const streamHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
    "X-Workspace-ID": window.localStorage.getItem("knowledgeos.workspace") || "default",
    "X-User-ID": window.localStorage.getItem("knowledgeos.user") || "local",
  };
  const token = window.localStorage.getItem("knowledgeos.token");
  if (token) streamHeaders.Authorization = `Bearer ${token}`;
  const response = await fetch(`${getApiBase()}/chat/stream`, {
    method: "POST", body: JSON.stringify({ question, stream: true }), signal,
    headers: streamHeaders,
  });
  if (!response.ok || !response.body) throw new ApiError(`Stream failed (${response.status})`, response.status);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "message";
  let final: ChatResponse | null = null;
  const parseBlock = (block: string) => {
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    if (!data) return;
    const payload = JSON.parse(data) as Record<string, unknown>;
    if (event === "token") onToken(String(payload.text ?? ""));
    if (event === "done") final = normaliseChatResponse(payload);
    if (event === "error") throw new ApiError(String(payload.error ?? "Stream failed"));
    event = "message";
  };
  while (true) {
    const chunk = await reader.read();
    buffer += decoder.decode(chunk.value ?? new Uint8Array(), { stream: !chunk.done });
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) parseBlock(block);
    if (chunk.done) break;
  }
  if (buffer.trim()) parseBlock(buffer);
  if (!final) throw new ApiError("The stream ended before a complete answer was received");
  return final;
}

export function normaliseChatResponse(value: Record<string, unknown>): ChatResponse {
  const evidence = (value.evidence ?? {}) as Record<string, unknown>;
  const rawCitations = Array.isArray(value.citations) ? value.citations : [];
  return {
    question: String(value.question ?? ""), answer: String(value.answer ?? ""),
    evidence: {
      decision: evidence.decision as ChatResponse["evidence"]["decision"],
      queryCoverage: Number(evidence.query_coverage ?? 0) || undefined,
      evidenceAgreement: Number(evidence.evidence_agreement ?? 0) || undefined,
      supportingSources: Number(evidence.supporting_sources ?? 0) || undefined,
      citationVerification: Boolean(evidence.citation_verification),
      evidenceScore: Number(evidence.evidence_score ?? 0) || undefined,
    },
    citations: rawCitations.map((item) => {
      const citation = item as Record<string, unknown>;
      return {
        chunkId: String(citation.chunk_id), documentId: typeof citation.document_id === "string" ? citation.document_id : undefined,
        filename: String(citation.filename ?? ""), path: typeof citation.path === "string" ? citation.path : undefined,
        page: Number(citation.page ?? 0) || undefined, lineStart: Number(citation.line_start ?? 0) || undefined,
        lineEnd: Number(citation.line_end ?? 0) || undefined, version: Number(citation.version ?? 0) || undefined,
        excerpt: String(citation.excerpt ?? ""), score: Number(citation.score ?? 0) || undefined,
        verification: citation.verification as ChatResponse["citations"][number]["verification"],
      };
    }),
    retrieval: value.retrieval ? (() => {
      const retrieval = value.retrieval as Record<string, unknown>;
      return { stages: Array.isArray(retrieval.stages) ? retrieval.stages.map((stage) => {
        const item = stage as Record<string, unknown>;
        return { label: String(item.label), candidates: Number(item.candidates ?? 0) || undefined, ms: Number(item.ms ?? 0) || undefined };
      }) : [], candidates: Array.isArray(retrieval.candidates) ? retrieval.candidates.map((candidate) => {
        const item = candidate as Record<string, unknown>;
        return { chunkId: String(item.chunk_id), filename: String(item.filename ?? ""), source: item.source as NonNullable<ChatResponse["retrieval"]>["candidates"][number]["source"], cosine: Number(item.cosine ?? 0) || undefined, bm25Rank: Number(item.bm25_rank ?? 0) || undefined, rrfScore: Number(item.rrf_score ?? 0) || undefined, rerankerScore: Number(item.reranker_score ?? 0) || undefined, excerpt: typeof item.excerpt === "string" ? item.excerpt : undefined };
      }) : [], evidencePassed: Boolean(retrieval.evidence_passed) };
    })() : undefined,
    traceId: typeof value.trace_id === "string" ? value.trace_id : undefined,
    latencyMs: Number(value.latency_ms ?? 0) || undefined,
  };
}

export { ApiError };
