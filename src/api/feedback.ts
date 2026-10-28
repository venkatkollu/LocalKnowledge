import { apiRequest } from "./client";

export async function sendFeedback(traceId: string, rating: 1 | -1): Promise<void> {
  await apiRequest("/feedback", {
    method: "POST",
    body: JSON.stringify({ trace_id: traceId, rating }),
    headers: { "Content-Type": "application/json" },
  });
}
