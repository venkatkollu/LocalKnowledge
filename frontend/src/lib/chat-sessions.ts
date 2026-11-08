import type { ChatResponse } from "@/api/types";

/** One completed question/answer pair. Streaming state is never persisted. */
export interface ChatTurn {
  id: string;
  question: string;
  response: ChatResponse;
  createdAt: number;
}

/** A persisted conversation shown in the sidebar history. */
export interface ChatSession {
  id: string;
  title: string;
  turns: ChatTurn[];
  createdAt: number;
  updatedAt: number;
}

export interface ChatSessionGroup {
  label: string;
  sessions: ChatSession[];
}

const VERSION = 1;
const MAX_TURNS = 40;
const MAX_SESSIONS = 30;
const DAY_MS = 86_400_000;

function workspace(): string {
  return (
    (typeof window !== "undefined" &&
      window.localStorage.getItem("knowledgeos.workspace")) ||
    "default"
  );
}

function sessionsKey(): string {
  return `knowledgeos.chats.${workspace()}.v1`;
}

function activeKey(): string {
  return `knowledgeos.chats.${workspace()}.active.v1`;
}

function legacyKey(): string {
  return `knowledgeos.chat.${workspace()}.v1`;
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

function isSession(value: unknown): value is ChatSession {
  if (!value || typeof value !== "object") return false;
  const session = value as Record<string, unknown>;
  return (
    typeof session.id === "string" &&
    typeof session.title === "string" &&
    typeof session.createdAt === "number" &&
    typeof session.updatedAt === "number" &&
    Array.isArray(session.turns)
  );
}

function readLegacyTurns(): ChatTurn[] {
  try {
    const raw = window.localStorage.getItem(legacyKey());
    if (!raw) return [];
    const parsed = JSON.parse(raw) as { version?: number; turns?: unknown };
    if (parsed.version !== VERSION || !Array.isArray(parsed.turns)) return [];
    return parsed.turns.filter(isTurn).slice(-MAX_TURNS);
  } catch {
    return [];
  }
}

export function createSessionId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function cleanTitle(question: string): string {
  const title = question.replace(/\s+/g, " ").trim();
  return title.length > 90 ? `${title.slice(0, 87)}…` : title;
}

export function titleForTurns(turns: ChatTurn[]): string {
  return cleanTitle(turns[0]?.question ?? "New conversation");
}

export function loadChatSessions(): ChatSession[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(sessionsKey());
    if (raw) {
      const parsed = JSON.parse(raw) as { version?: number; sessions?: unknown };
      if (parsed.version !== VERSION || !Array.isArray(parsed.sessions)) {
        return [];
      }
      return parsed.sessions
        .filter(isSession)
        .map((session) => ({
          ...session,
          turns: session.turns.filter(isTurn).slice(-MAX_TURNS),
        }))
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, MAX_SESSIONS);
    }

    const legacyTurns = readLegacyTurns();
    if (legacyTurns.length === 0) return [];
    const updatedAt = legacyTurns[legacyTurns.length - 1].createdAt;
    return [
      {
        id: createSessionId(),
        title: titleForTurns(legacyTurns),
        turns: legacyTurns,
        createdAt: legacyTurns[0].createdAt,
        updatedAt,
      },
    ];
  } catch {
    // Corrupt or unavailable storage should never block the chat.
    return [];
  }
}

export function persistChatSessions(sessions: ChatSession[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      sessionsKey(),
      JSON.stringify({
        version: VERSION,
        sessions: sessions.slice(0, MAX_SESSIONS),
      }),
    );
  } catch {
    // Quota or private mode: keep the live thread usable.
  }
}

export function loadActiveSessionId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(activeKey());
  } catch {
    return null;
  }
}

export function persistActiveSessionId(id: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (id) window.localStorage.setItem(activeKey(), id);
    else window.localStorage.removeItem(activeKey());
  } catch {
    // Nothing to do; the in-memory session remains active.
  }
}

export function groupSessionsByDate(sessions: ChatSession[]): ChatSessionGroup[] {
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate(),
  ).getTime();
  const startOfYesterday = startOfToday - DAY_MS;
  const startOfWeek = startOfToday - 6 * DAY_MS;

  const groups: ChatSessionGroup[] = [
    { label: "Today", sessions: [] },
    { label: "Yesterday", sessions: [] },
    { label: "Previous 7 days", sessions: [] },
    { label: "Older", sessions: [] },
  ];

  for (const session of sessions) {
    if (session.updatedAt >= startOfToday) groups[0].sessions.push(session);
    else if (session.updatedAt >= startOfYesterday)
      groups[1].sessions.push(session);
    else if (session.updatedAt >= startOfWeek) groups[2].sessions.push(session);
    else groups[3].sessions.push(session);
  }

  return groups.filter((group) => group.sessions.length > 0);
}
