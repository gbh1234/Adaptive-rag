import type { Conversation, Message } from "../types";

const KEY = "adaptive-rag-web:v1";
const MAX_CONVERSATIONS = 50;
const MAX_MESSAGES = 100;

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return [];
    const value: unknown = JSON.parse(raw);
    if (!Array.isArray(value)) return [];
    return value.filter(isConversation).slice(0, MAX_CONVERSATIONS).map((item) => ({
      ...item,
      messages: item.messages.slice(-MAX_MESSAGES).map((message) => ({
        ...message,
        state: message.state === "streaming" ? "stopped" : message.state,
      })),
    }));
  } catch {
    return [];
  }
}

export function saveConversations(conversations: Conversation[]): void {
  try {
    localStorage.setItem(
      KEY,
      JSON.stringify(conversations.slice(0, MAX_CONVERSATIONS).map((item) => ({
        ...item,
        messages: item.messages.slice(-MAX_MESSAGES),
      }))),
    );
  } catch { /* Storage may be disabled or full; the current chat still works. */ }
}

function isConversation(value: unknown): value is Conversation {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === "string" && typeof item.title === "string" &&
    typeof item.updatedAt === "number" && Array.isArray(item.messages) &&
    item.messages.every(isMessage);
}

function isMessage(value: unknown): value is Message {
  if (typeof value !== "object" || value === null) return false;
  const item = value as Record<string, unknown>;
  return typeof item.id === "string" &&
    (item.role === "user" || item.role === "assistant") &&
    typeof item.content === "string" && typeof item.state === "string";
}
