import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  createSessionId,
  loadActiveSessionId,
  loadChatSessions,
  persistActiveSessionId,
  persistChatSessions,
  titleForTurns,
  type ChatSession,
  type ChatTurn,
} from "@/lib/chat-sessions";

interface ChatSessionsValue {
  sessions: ChatSession[];
  activeId: string | null;
  activeSession: ChatSession | null;
  /** Increments every time "New chat" is pressed, even from a draft. */
  newChatNonce: number;
  startNewChat: () => void;
  openSession: (id: string) => void;
  saveSession: (turns: ChatTurn[]) => ChatSession;
  deleteSession: (id: string) => void;
}

const ChatSessionsContext = createContext<ChatSessionsValue | null>(null);

export function ChatSessionsProvider({ children }: { children: ReactNode }) {
  const [sessions, setSessions] = useState<ChatSession[]>(loadChatSessions);
  const [activeId, setActiveId] = useState<string | null>(loadActiveSessionId);
  const [newChatNonce, setNewChatNonce] = useState(0);

  useEffect(() => {
    persistChatSessions(sessions);
  }, [sessions]);

  useEffect(() => {
    persistActiveSessionId(activeId);
  }, [activeId]);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeId) ?? null,
    [sessions, activeId],
  );

  const startNewChat = useCallback(() => {
    setActiveId(null);
    setNewChatNonce((value) => value + 1);
  }, []);

  const openSession = useCallback((id: string) => {
    setActiveId(id);
  }, []);

  const saveSession = useCallback(
    (turns: ChatTurn[]): ChatSession => {
      const now = Date.now();
      const id = activeId ?? createSessionId();
      const existing = sessions.find((session) => session.id === id);
      const session: ChatSession = {
        id,
        title: titleForTurns(turns),
        turns: turns.slice(-40),
        createdAt: existing?.createdAt ?? now,
        updatedAt: now,
      };
      setSessions((current) =>
        [session, ...current.filter((item) => item.id !== id)]
          .sort((a, b) => b.updatedAt - a.updatedAt)
          .slice(0, 30),
      );
      setActiveId(id);
      return session;
    },
    [activeId, sessions],
  );

  const deleteSession = useCallback((id: string) => {
    setSessions((current) => current.filter((session) => session.id !== id));
    setActiveId((current) => (current === id ? null : current));
  }, []);

  const value = useMemo<ChatSessionsValue>(
    () => ({
      sessions,
      activeId,
      activeSession,
      newChatNonce,
      startNewChat,
      openSession,
      saveSession,
      deleteSession,
    }),
    [
      sessions,
      activeId,
      activeSession,
      newChatNonce,
      startNewChat,
      openSession,
      saveSession,
      deleteSession,
    ],
  );

  return (
    <ChatSessionsContext.Provider value={value}>
      {children}
    </ChatSessionsContext.Provider>
  );
}

export function useChatSessions(): ChatSessionsValue {
  const value = useContext(ChatSessionsContext);
  if (!value) {
    throw new Error("useChatSessions must be used inside ChatSessionsProvider");
  }
  return value;
}
