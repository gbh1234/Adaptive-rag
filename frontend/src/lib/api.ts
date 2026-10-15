import type { ChatRequest, StreamEvent } from "../types";
import { SseDecoder } from "./sse";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export async function checkHealth(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/health`, { signal });
    return response.ok;
  } catch {
    return false;
  }
}

export async function streamChat(
  payload: ChatRequest,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/v1/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    let message = `请求失败（HTTP ${response.status}）`;
    try {
      const error: unknown = await response.json();
      if (typeof error === "object" && error !== null && "message" in error) {
        message = String(error.message);
      }
    } catch { /* Use the HTTP status when no JSON error body is available. */ }
    throw new Error(message);
  }
  if (!response.body) throw new Error("浏览器不支持流式响应");

  const reader = response.body.getReader();
  const decoder = new SseDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of decoder.feed(value)) onEvent(event);
    }
    for (const event of decoder.finish()) onEvent(event);
  } finally {
    reader.releaseLock();
  }
}
