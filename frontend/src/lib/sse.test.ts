import { describe, expect, it } from "vitest";
import { SseDecoder } from "./sse";

describe("SseDecoder", () => {
  it("reassembles split UTF-8 and frame boundaries", () => {
    const decoder = new SseDecoder();
    const bytes = new TextEncoder().encode('data: {"event":"token","text":"你好"}\n\ndata: {"event":"done","trace_id":"t"}\n\n');
    const cut = bytes.indexOf(0xe5) + 1;
    expect(decoder.feed(bytes.slice(0, cut))).toEqual([]);
    expect(decoder.feed(bytes.slice(cut, bytes.length - 1))).toEqual([
      { event: "token", text: "你好" },
    ]);
    expect(decoder.feed(bytes.slice(bytes.length - 1))).toEqual([
      { event: "done", trace_id: "t" },
    ]);
  });

  it("handles CRLF, comments and an unterminated final frame", () => {
    const decoder = new SseDecoder();
    expect(decoder.feed(new TextEncoder().encode(': ping\r\ndata: {"event":"started","trace_id":"x"}\r\n\r\n'))).toEqual([
      { event: "started", trace_id: "x" },
    ]);
    decoder.feed(new TextEncoder().encode('data: {"event":"done","trace_id":"x"}'));
    expect(decoder.finish()).toEqual([{ event: "done", trace_id: "x" }]);
  });
});
