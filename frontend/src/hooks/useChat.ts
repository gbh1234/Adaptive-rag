import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { ChatResponse, Conversation, Message } from "../types";
import { streamChat } from "../lib/api";
import { loadConversations, saveConversations } from "../lib/storage";

interface State {
  conversations: Conversation[];
  activeId: string | null;
}

type Action =
  | { type: "select"; id: string | null }
  | { type: "delete"; id: string }
  | { type: "start"; conversation: Conversation; user: Message; assistant: Message }
  | { type: "token"; conversationId: string; messageId: string; text: string }
  | { type: "complete"; conversationId: string; messageId: string; response: ChatResponse }
  | { type: "fail"; conversationId: string; messageId: string; message: string; stopped: boolean }
  | { type: "dismiss"; conversationId: string; messageId: string };

function updateConversation(
  state: State,
  id: string,
  update: (conversation: Conversation) => Conversation,
): State {
  return {
    ...state,
    conversations: state.conversations.map((item) => item.id === id ? update(item) : item),
  };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "select":
      return { ...state, activeId: action.id };
    case "delete":
      return {
        conversations: state.conversations.filter((item) => item.id !== action.id),
        activeId: state.activeId === action.id ? null : state.activeId,
      };
    case "start": {
      const existing = state.conversations.find((item) => item.id === action.conversation.id);
      const next = existing
        ? { ...existing, updatedAt: Date.now(), messages: [...existing.messages, action.user, action.assistant] }
        : { ...action.conversation, messages: [action.user, action.assistant] };
      return {
        activeId: next.id,
        conversations: [next, ...state.conversations.filter((item) => item.id !== next.id)],
      };
    }
    case "token":
      return updateConversation(state, action.conversationId, (item) => ({
        ...item,
        messages: item.messages.map((message) => message.id === action.messageId
          ? { ...message, content: message.content + action.text }
          : message),
      }));
    case "complete":
      return updateConversation(state, action.conversationId, (item) => ({
        ...item,
        sessionId: action.response.session_id,
        updatedAt: Date.now(),
        messages: item.messages.map((message) => message.id === action.messageId
          ? {
              ...message,
              content: action.response.answer,
              state: "complete",
              citations: action.response.citations,
              pendingAction: action.response.pending_action,
              strategy: action.response.strategy,
              traceId: action.response.trace_id,
              latencyMs: action.response.latency.total_ms,
            }
          : message),
      }));
    case "fail":
      return updateConversation(state, action.conversationId, (item) => ({
        ...item,
        messages: item.messages.map((message) => message.id === action.messageId
          ? {
              ...message,
              content: action.stopped ? message.content || "已停止生成。" : action.message,
              state: action.stopped ? "stopped" : "error",
            }
          : message),
      }));
    case "dismiss":
      return updateConversation(state, action.conversationId, (item) => ({
        ...item,
        messages: item.messages.map((message) => message.id === action.messageId
          ? { ...message, pendingAction: null }
          : message),
      }));
  }
}

const DEMO_USER_ID = import.meta.env.VITE_DEMO_USER_ID || "u_demo";

export function useChat() {
  const [state, dispatch] = useReducer(reducer, undefined, () => ({
    conversations: loadConversations(),
    activeId: null,
  }));
  const stateRef = useRef(state);
  stateRef.current = state;
  const requestRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => saveConversations(state.conversations), 300);
    return () => window.clearTimeout(timer);
  }, [state.conversations]);

  useEffect(() => {
    const flush = () => saveConversations(stateRef.current.conversations);
    window.addEventListener("pagehide", flush);
    return () => window.removeEventListener("pagehide", flush);
  }, []);

  useEffect(() => () => requestRef.current?.abort(), []);

  const stop = useCallback(() => requestRef.current?.abort(), []);

  const send = useCallback(async (raw: string, confirmActionId?: string) => {
    const text = raw.trim();
    if (!text || text.length > 4000 || busyRef.current) return false;
    const current = stateRef.current;
    const existing = current.conversations.find((item) => item.id === current.activeId);
    const conversation: Conversation = existing ?? {
      id: crypto.randomUUID(),
      title: text.length > 32 ? `${text.slice(0, 32)}…` : text,
      updatedAt: Date.now(),
      messages: [],
    };
    const user: Message = { id: crypto.randomUUID(), role: "user", content: text, state: "complete" };
    const assistant: Message = { id: crypto.randomUUID(), role: "assistant", content: "", state: "streaming" };
    const controller = new AbortController();
    requestRef.current = controller;
    busyRef.current = true;
    setBusy(true);
    dispatch({ type: "start", conversation, user, assistant });

    let answered = false;
    try {
      await streamChat(
        {
          message: text,
          user_id: DEMO_USER_ID,
          ...(conversation.sessionId ? { session_id: conversation.sessionId } : {}),
          ...(confirmActionId ? { confirm_action_id: confirmActionId } : {}),
        },
        (event) => {
          if (event.event === "token") {
            dispatch({ type: "token", conversationId: conversation.id, messageId: assistant.id, text: event.text });
          }
          if (event.event === "answer") {
            answered = true;
            dispatch({ type: "complete", conversationId: conversation.id, messageId: assistant.id, response: event.data });
          }
        },
        controller.signal,
      );
      if (!answered) throw new Error("连接已结束，但未收到最终回答。请重试。");
      return true;
    } catch (error) {
      const stopped = controller.signal.aborted;
      if (!answered) {
        dispatch({
          type: "fail",
          conversationId: conversation.id,
          messageId: assistant.id,
          stopped,
          message: error instanceof Error ? error.message : "请求失败，请稍后重试。",
        });
      }
      return false;
    } finally {
      requestRef.current = null;
      busyRef.current = false;
      setBusy(false);
    }
  }, []);

  const select = useCallback((id: string | null) => {
    stop();
    dispatch({ type: "select", id });
  }, [stop]);

  const remove = useCallback((id: string) => {
    if (stateRef.current.activeId === id) stop();
    dispatch({ type: "delete", id });
  }, [stop]);

  const dismissAction = useCallback((conversationId: string, messageId: string) => {
    dispatch({ type: "dismiss", conversationId, messageId });
  }, []);

  const active = state.conversations.find((item) => item.id === state.activeId) ?? null;
  return {
    conversations: state.conversations,
    active,
    busy,
    send,
    stop,
    select,
    remove,
    dismissAction,
  };
}
