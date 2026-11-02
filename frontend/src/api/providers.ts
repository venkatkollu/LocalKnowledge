import { apiRequest } from "./client";

export interface ProviderProfile {
  id: string;
  name: string;
  kind: string;
  baseUrl: string;
  model: string;
  role: "Generation" | "Embeddings" | "Both";
  enabled: boolean;
  hasApiKey: boolean;
}

function normalise(value: Record<string, unknown>): ProviderProfile {
  return { id: String(value.id), name: String(value.name), kind: String(value.kind), baseUrl: String(value.base_url), model: String(value.model), role: value.role as ProviderProfile["role"], enabled: Boolean(value.enabled), hasApiKey: Boolean(value.has_api_key) };
}

export async function fetchProviders(signal?: AbortSignal): Promise<ProviderProfile[]> {
  const payload = await apiRequest<Record<string, unknown>[]>("/models/profiles", { signal });
  return (payload as unknown as Record<string, unknown>[]).map(normalise);
}

export async function createProvider(input: { name: string; kind: string; baseUrl: string; model: string; role: ProviderProfile["role"]; apiKey: string }): Promise<ProviderProfile> {
  const value = await apiRequest<Record<string, unknown>>("/models/profiles", { method: "POST", body: JSON.stringify({ name: input.name, kind: input.kind, base_url: input.baseUrl, model: input.model, role: input.role, api_key: input.apiKey }), headers: { "Content-Type": "application/json" } });
  return normalise(value);
}

export async function deleteProvider(id: string): Promise<void> {
  await apiRequest(`/models/profiles/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function testProvider(id: string): Promise<{ ok: boolean; detail?: string }> {
  const value = await apiRequest<Record<string, unknown>>(`/models/profiles/${encodeURIComponent(id)}/test`, { method: "POST" });
  return { ok: Boolean(value.ok), detail: typeof value.detail === "string" ? value.detail : undefined };
}
