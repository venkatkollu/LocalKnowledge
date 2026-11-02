import { apiRequest } from "./client";

export interface ActivityEvent { id: string; kind: "document" | "sync" | "query" | "error"; title: string; detail?: string; createdAt: number; }

export async function fetchActivity(signal?: AbortSignal): Promise<ActivityEvent[]> {
  const value = await apiRequest<{ events: Record<string, unknown>[] }>("/activity", { signal });
  return (value.events ?? []).map((event) => ({ id: String(event.id), kind: event.kind as ActivityEvent["kind"], title: String(event.title), detail: typeof event.detail === "string" ? event.detail : undefined, createdAt: Number(event.created_at ?? 0) }));
}
