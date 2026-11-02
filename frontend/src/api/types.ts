/** Data models used by the Local KnowledgeOS interface. */

export type AnswerDecision = "answer" | "answer_with_uncertainty" | "abstain";

export type VerificationStatus = "verified" | "partial" | "unverified";

/** A single piece of retrieved, cited evidence. */
export interface Citation {
  chunkId: string;
  documentId?: string;
  filename: string;
  path?: string;
  /** Heading or section title the chunk came from. */
  section?: string;
  /** 1-based PDF page, when the source is a PDF. */
  page?: number;
  /** 1-based, inclusive line range for text and code sources. */
  lineStart?: number;
  lineEnd?: number;
  /** Python/JS symbol the chunk is anchored to, when known. */
  symbol?: string;
  /** Document version at retrieval time. */
  version?: number;
  excerpt: string;
  /** Reranker / retrieval score, kept for the debug drawer. */
  score?: number;
  verification?: VerificationStatus;
}

/** Evidence quality values shown alongside an answer. */
export interface EvidenceQuality {
  decision: AnswerDecision;
  /** 0–1, share of the question the evidence covers. */
  queryCoverage?: number;
  /** 0–1, agreement between supporting sources. */
  evidenceAgreement?: number;
  supportingSources?: number;
  citationVerification?: boolean;
  /** 0–1, the combined heuristic score. */
  evidenceScore?: number;
}

/** Per-stage retrieval counts for the "Debug retrieval" drawer. */
export interface RetrievalStage {
  label: string;
  /** Candidates produced or surviving at this stage. */
  candidates?: number;
  /** Milliseconds spent in this stage. */
  ms?: number;
}

export interface RetrievalCandidate {
  chunkId: string;
  filename: string;
  source: "dense" | "bm25" | "both";
  cosine?: number;
  bm25Rank?: number;
  rrfScore?: number;
  rerankerScore?: number;
  excerpt?: string;
}

export interface RetrievalTrace {
  stages: RetrievalStage[];
  candidates: RetrievalCandidate[];
  evidencePassed: boolean;
}

export interface ChatResponse {
  question: string;
  answer: string;
  evidence: EvidenceQuality;
  citations: Citation[];
  retrieval?: RetrievalTrace;
/** Optional trace id for this query. */
  traceId?: string;
  /** Wall-clock latency of the request in milliseconds. */
  latencyMs?: number;
}

export interface ChatRequest {
  question: string;
  /** Optional retrieval overrides. */
  topK?: number;
  stream?: boolean;
}

/* ------------------------------------------------------------------ *
 * Documents
 * ------------------------------------------------------------------ */

/**
 * Synchronisation state of a document. The UI never leaves the user guessing:
 * each state has a distinct label, colour and action.
 */
export type DocumentStatus =
  | "synced"
  | "changed"
  | "processing"
  | "failed"
  | "not_indexed";

export interface KnowledgeDocument {
  id: string;
  filename: string;
  /** Directory portion, shown under the filename. */
  path: string;
  extension: string;
  language: string;
  sizeBytes: number;
  chunks: number;
  status: DocumentStatus;
  /** Epoch milliseconds. */
  updatedAt?: number;
  indexedAt?: number;
  version?: number;
  /** SHA-256 content hash used for change detection. */
  contentHash?: string;
  /** Parser / chunker / embedding identity recorded at index time. */
  parser?: string;
  chunker?: string;
  embedding?: string;
  /** Human failure reason when status is `failed`. */
  error?: string;
  /** 0–1 progress while status is `processing`. */
  progress?: number;
  /** Current ingestion stage while status is `processing`. */
  stage?: string;
}

/** A point in the document's own version history (not the RAG index version). */
export interface DocumentVersion {
  version: number;
  chunks: number;
  /** Epoch milliseconds. */
  createdAt: number;
  current: boolean;
  contentHash?: string;
  /** Embeddings reused from the compatible previous pipeline fingerprint. */
  reused?: number;
  /** Chunks newly embedded in this version. */
  newlyEmbedded?: number;
  note?: string;
}

export interface DocumentChunk {
  id: string;
  index: number;
  lineStart: number;
  lineEnd: number;
  section?: string;
  symbol?: string;
  tokens?: number;
  excerpt: string;
}

/** Details associated with a document. */
export interface DocumentDetail {
  document: KnowledgeDocument;
  content: string;
  versions: DocumentVersion[];
  chunks: DocumentChunk[];
}

/** A change associated with a document. */
export interface DocumentChange {
  documentId: string;
  filename: string;
  path: string;
  /** Epoch milliseconds. */
  changedAt: number;
  previousVersion?: number;
  currentVersion?: number;
  previousChunks: number;
  currentChunks: number;
  /** Chunks whose embeddings were reused from the compatible pipeline. */
  reused?: number;
  /** Chunks newly embedded for this change. */
  newlyEmbedded?: number;
}

/* ------------------------------------------------------------------ *
 * Ingestion jobs
 * ------------------------------------------------------------------ */

/** Document processing stages, in order. */
export type JobStage =
  | "parsing"
  | "structure"
  | "chunking"
  | "contextualizing"
  | "embedding"
  | "indexing"
  | "validating"
  | "completed"
  | "failed";

export type JobStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export interface IngestionJob {
  id: string;
  documentId?: string;
  documentName?: string;
  stage: JobStage;
  status: JobStatus;
  /** 0–1. */
  progress: number;
  error?: string;
}

/** Repository source configuration. */
export interface GitSourceRequest {
  url: string;
  branch?: string;
}

/** One file inside an upload batch. */
export interface UploadItem {
  id: string;
  name: string;
  sizeBytes: number;
  status: "queued" | "uploading" | "done" | "failed";
  error?: string;
}

/* ------------------------------------------------------------------ *
 * Telemetry, indexes and configuration
 * ------------------------------------------------------------------ */

export interface LatencyPercentiles {
  p50?: number;
  p95?: number;
  p99?: number;
}

/** One stage of the query pipeline with its measured cost. */
export interface StageMetric {
  label: string;
  ms?: number;
}

/** Query performance metrics. */
export interface MetricsSnapshot {
  latency: LatencyPercentiles;
  queries?: number;
  answers?: number;
  answersWithUncertainty?: number;
  abstentions?: number;
  errors?: number;
  /** Mean latency across completed queries, when reported. */
  meanMs?: number;
  stages: StageMetric[];
}

/** Lifecycle states of a RAG index build. */
export type IndexState = "building" | "ready" | "active" | "retired";

/** State of an index build. */
export interface RagIndex {
  id: string;
  state: IndexState;
  embedding?: string;
  dimensions?: number;
  revision?: number;
  documents?: number;
  chunks?: number;
  createdAt?: number;
  builtAt?: number;
  validated?: boolean;
  evaluated?: boolean;
  evaluationScore?: number;
  notes?: string;
}

/** A read-only configuration value surfaced in Settings. */
export interface ConfigEntry {
  label: string;
  value: string;
  hint?: string;
  /** Advanced values are grouped behind a disclosure. */
  advanced?: boolean;
}
