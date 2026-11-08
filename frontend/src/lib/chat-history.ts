import type { ChatResponse } from "@/api/types";

/** One completed question/answer pair. Streaming state is never persisted. */
export interface ChatTurn {
  id: string;
  question: string;
  response: ChatResponse;
  createdAt: number;
}

const VERSION = 1;
const MAX_TURNS = 40;

function storageKey(): string {
  const workspace =
    window.localStorage.getItem("knowledgeos.workspace") || "default";
  return `knowledgeos.chat.${workspace}.v1`;
}

function isTurn(value: unknown): value is ChatTurn {
  if (!value || typeof value !== "object") return false;
  const turn = value as Record<string, unknown>;
  const response = turn.response as Record<string, unknown> | undefined;
  const evidence = response?.evidence as Record<string, unknown> | undefined;
  return (
    typeof turn.id === "string" &&
    typeof turn.question === "string" &&
    typeof turn.createdAt === "number" &&
    Boolean(response) &&
    typeof response?.answer === "string" &&
    Array.isArray(response?.citations) &&
    typeof evidence?.decision === "string"
  );
}

export function loadChatTurns(): ChatTurn[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(storageKey());
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { version?: number; turns?: unknown };
    if (parsed.version !== VERSION || !Array.isArray(parsed.turns)) return [];
    return parsed.turns.filter(isTurn).slice(-MAX_TURNS);
  } catch {
    // Corrupt or unavailable storage should never block the chat.
    return [];
  }
}

export function saveChatTurns(turns: ChatTurn[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      storageKey(),
      JSON.stringify({ version: VERSION, turns: turns.slice(-MAX_TURNS) }),
    );
  } catch {
    // Quota or private mode: keep the live thread usable.
  }
}

export function clearChatTurns(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(storageKey());
  } catch {
    // Nothing to do; the in-memory thread is cleared by the caller.
  }
}
