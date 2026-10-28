import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { createIndex, fetchIndexes, runIndexAction as executeIndexAction } from "@/api/indexes";
import { fetchMetrics } from "@/api/metrics";
import type { MetricsSnapshot, RagIndex } from "@/api/types";

export type IndexAction = "build" | "validate" | "evaluate" | "activate" | "rollback" | "create";

export interface TelemetryController {
  loading: boolean;
  error: string | null;
  metrics: MetricsSnapshot | null;
  indexes: RagIndex[];
  refresh: () => void;
  busy: string | null;
  runIndexAction: (id: string, action: IndexAction) => void;
}

export function useTelemetry(): TelemetryController {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [indexes, setIndexes] = useState<RagIndex[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const refresh = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([fetchMetrics(controller.signal), fetchIndexes(controller.signal)])
      .then(([nextMetrics, nextIndexes]) => {
        if (controller.signal.aborted) return;
        setMetrics(nextMetrics);
        setIndexes(nextIndexes);
        setError(null);
      })
      .catch((value) => {
        if (!controller.signal.aborted) setError(value instanceof Error ? value.message : "Could not load telemetry");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [nonce]);

  const runIndexAction = useCallback((id: string, action: IndexAction) => {
    setBusy(id || "create");
    const request = action === "create" ? createIndex({}) : executeIndexAction(id, action);
    request.then((index) => {
      if (index) setIndexes((current) => action === "create" ? [index, ...current] : current.map((item) => item.id === index.id ? index : item));
      toast(`${action[0].toUpperCase()}${action.slice(1)} requested`);
    }).catch((value) => toast.error("Index action failed", { description: value instanceof Error ? value.message : "Request failed" })).finally(() => setBusy(null));
  }, []);

  return { loading, error, metrics, indexes, refresh, busy, runIndexAction };
}
