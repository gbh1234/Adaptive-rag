import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MessageView } from "./MessageView";
import type { Conversation } from "../types";

describe("answer presentation", () => {
  it("shows the answer and source without internal timing or route metadata", () => {
    const conversation: Conversation = {
      id: "chat-1",
      title: "退货政策",
      updatedAt: 0,
      messages: [{
        id: "answer-1",
        role: "assistant",
        state: "complete",
        content: "根据退货规则，质量问题可以申请售后。",
        strategy: "multi",
        latencyMs: 4200,
        citations: [{ chunk_id: "chunk-1", document_id: "policy-1", title: "退货规则", section: null }],
      }],
    };
    const html = renderToStaticMarkup(
      <MessageView conversation={conversation} busy={false} onConfirm={() => {}} onCancel={() => {}} />,
    );
    expect(html).toContain("质量问题可以申请售后");
    expect(html).toContain("退货规则");
    expect(html).not.toContain("多跳检索");
    expect(html).not.toContain("4.2 秒");
  });
});
