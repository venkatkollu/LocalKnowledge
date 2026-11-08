import type { Citation, VerificationStatus } from "@/api/types";

/** Human-readable location for a retrieved chunk. */
export function citationLocation(citation: Citation): string {
  const parts: string[] = [];

  if (citation.page !== undefined) {
    parts.push(`Page ${citation.page}`);
  }
  if (citation.lineStart !== undefined) {
    const end = citation.lineEnd ?? citation.lineStart;
    parts.push(
      end === citation.lineStart
        ? `Line ${citation.lineStart}`
        : `Lines ${citation.lineStart}–${end}`,
    );
  }
  if (citation.section) parts.push(citation.section);
  if (citation.symbol) parts.push(citation.symbol);
  if (citation.path && parts.length === 0) parts.push(citation.path);

  return parts.join(" · ") || "Retrieved passage";
}

export interface VerificationStyle {
  label: string;
  className: string;
  dotClassName: string;
}

const VERIFICATION: Record<VerificationStatus, VerificationStyle> = {
  verified: {
    label: "Verified",
    className: "text-muted-foreground",
    dotClassName: "bg-[var(--term-ok)]",
  },
  partial: {
    label: "Partial",
    className: "text-muted-foreground",
    dotClassName: "bg-[var(--term-warn)]",
  },
  unverified: {
    label: "Unverified",
    className: "text-muted-foreground",
    dotClassName: "bg-muted-foreground",
  },
};

export function verificationStyle(
  status?: VerificationStatus,
): VerificationStyle | null {
  return status ? VERIFICATION[status] : null;
}

export function formatLatency(milliseconds?: number): string | null {
  if (!milliseconds || milliseconds <= 0) return null;
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  return `${(milliseconds / 1000).toFixed(1)} s`;
}
