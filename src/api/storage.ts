import { apiRequest } from "./client";

export interface StorageSnapshot { documents: number; originalBytes: number; chunks: number; storage: string; dataDirectory: string; }

export async function fetchStorage(): Promise<StorageSnapshot> {
  const value = await apiRequest<Record<string, unknown>>("/storage");
  return { documents: Number(value.documents ?? 0), originalBytes: Number(value.original_bytes ?? 0), chunks: Number(value.chunks ?? 0), storage: String(value.storage ?? ""), dataDirectory: String(value.data_directory ?? "") };
}
