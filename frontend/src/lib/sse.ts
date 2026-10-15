import type { StreamEvent } from "../types";

/** Decode SSE frames even when UTF-8 characters or frame boundaries span reads. */
export class SseDecoder {
  private readonly decoder = new TextDecoder();
  private buffer = "";

  feed(bytes: Uint8Array): StreamEvent[] {
    this.buffer += this.decoder.decode(bytes, { stream: true });
    return this.drain(false);
  }

  finish(): StreamEvent[] {
    this.buffer += this.decoder.decode();
    return this.drain(true);
  }

  private drain(final: boolean): StreamEvent[] {
    if (this.buffer.length > 1_000_000) {
      throw new Error("流式响应过大");
    }
    const events: StreamEvent[] = [];
    let boundary = /\r?\n\r?\n/.exec(this.buffer);
    while (boundary !== null) {
      const frame = this.buffer.slice(0, boundary.index);
      this.buffer = this.buffer.slice(boundary.index + boundary[0].length);
      const event = parseFrame(frame);
      if (event) events.push(event);
      boundary = /\r?\n\r?\n/.exec(this.buffer);
    }
    if (final && this.buffer.trim()) {
      const event = parseFrame(this.buffer);
      if (event) events.push(event);
      this.buffer = "";
    }
    return events;
  }
}

function parseFrame(frame: string): StreamEvent | null {
  const data = frame
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data || data === "[DONE]") return null;
  try {
    const value: unknown = JSON.parse(data);
    if (typeof value !== "object" || value === null || !("event" in value)) return null;
    if (typeof value.event !== "string") return null;
    return value as StreamEvent;
  } catch {
    return null;
  }
}
