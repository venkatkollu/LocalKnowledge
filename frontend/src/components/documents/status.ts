import type { Tone } from "@/components/StatusDot";
import type { DocumentStatus } from "@/api/types";

export interface StatusMeta {
  /** Short label shown next to the status dot. */
  label: string;
  tone: Tone;
  /** Explains the state so the user never has to guess. */
  hint: string;
  /** Label for the state's primary action, if it has one. */
  action?: string;
}

export const DOC_STATUS: Record<DocumentStatus, StatusMeta> = {
  synced: {
    label: "Synced",
    tone: "ok",
    hint: "Indexed",
  },
  changed: {
    label: "Changes detected",
    tone: "warn",
    hint: "File modified locally",
    action: "Sync",
  },
  processing: {
    label: "Processing",
    tone: "info",
    hint: "Embedding chunks",
  },
  failed: {
    label: "Sync failed",
    tone: "bad",
    hint: "Ingestion did not complete",
    action: "Retry",
  },
  not_indexed: {
    label: "Not indexed",
    tone: "idle",
    hint: "Never indexed",
    action: "Index",
  },
};

/** Filters offered above the document grid. */
export const STATUS_FILTERS: { key: DocumentStatus | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "synced", label: "Synced" },
  { key: "changed", label: "Changed" },
  { key: "processing", label: "Processing" },
  { key: "failed", label: "Failed" },
];
