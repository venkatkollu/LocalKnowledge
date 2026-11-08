const NEW_CHAT_EVENT = "knowledgeos:new-chat";

let pendingNewChat = false;

export function requestNewChat(): void {
  pendingNewChat = true;
  window.dispatchEvent(new Event(NEW_CHAT_EVENT));
}

export function consumePendingNewChat(): boolean {
  const pending = pendingNewChat;
  pendingNewChat = false;
  return pending;
}

export function onNewChatRequest(handler: () => void): () => void {
  window.addEventListener(NEW_CHAT_EVENT, handler);
  return () => window.removeEventListener(NEW_CHAT_EVENT, handler);
}
