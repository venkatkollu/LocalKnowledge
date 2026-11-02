import { apiRequest } from "./client";
import type { MetricsSnapshot } from "./types";

export async function fetchMetrics(signal?: AbortSignal): Promise<MetricsSnapshot> {
  const value = await apiRequest<Record<string, unknown>>("/metrics", { signal });
  const latency = (value.latency ?? {}) as Record<string, unknown>;
  return { latency: { p50: Number(latency.p50 ?? 0) || undefined, p95: Number(latency.p95 ?? 0) || undefined, p99: Number(latency.p99 ?? 0) || undefined }, queries: Number(value.queries ?? 0), answers: Number(value.answers ?? 0), answersWithUncertainty: Number(value.answers_with_uncertainty ?? 0), abstentions: Number(value.abstentions ?? 0), errors: Number(value.errors ?? 0), meanMs: Number(value.mean_ms ?? 0) || undefined, stages: Array.isArray(value.stages) ? value.stages as MetricsSnapshot["stages"] : [] };
}
