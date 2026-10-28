export class ApiError extends Error {
  status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getApiBase(): string {
  const configured = (import.meta.env.VITE_KNOWLEDGEOS_API_URL as string | undefined)?.trim();
  if (configured) return configured.replace(/\/$/, "");
  return "/api";
}

function headers(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("Accept", "application/json");
  const workspace = window.localStorage.getItem("knowledgeos.workspace") || "default";
  headers.set("X-Workspace-ID", workspace);
  headers.set("X-User-ID", window.localStorage.getItem("knowledgeos.user") || "local");
  const token = window.localStorage.getItem("knowledgeos.token");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return headers;
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit & { timeoutMs?: number } = {},
): Promise<T> {
  const { timeoutMs = 30000, ...init } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${getApiBase()}${path}`, {
      ...init,
      signal: init.signal ?? controller.signal,
      headers: headers(init.headers),
    });
    const text = await response.text();
    const payload = text ? (JSON.parse(text) as unknown) : null;
    if (!response.ok) {
      const record = payload && typeof payload === "object" ? payload as Record<string, unknown> : null;
      throw new ApiError(String(record?.detail ?? `Request failed (${response.status})`), response.status);
    }
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("Request timed out");
    }
    throw new ApiError(error instanceof Error ? error.message : "Could not reach the API");
  } finally {
    window.clearTimeout(timer);
  }
}

export async function uploadRequest<T>(path: string, form: FormData, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    body: form,
    signal,
    headers: headers(),
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;
  if (!response.ok) {
    const record = payload && typeof payload === "object" ? payload as Record<string, unknown> : null;
    throw new ApiError(String(record?.detail ?? `Upload failed (${response.status})`), response.status);
  }
  return payload as T;
}
