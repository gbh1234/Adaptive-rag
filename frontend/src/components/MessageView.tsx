import { useEffect, useRef, useState } from "react";
import { Check, Copy, ShieldCheck } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ActionProposal, Citation, Conversation, Message } from "../types";
import { Logo } from "./Logo";

function CitationList({ citations }: { citations: Citation[] }) {
  const unique = citations.filter((item, index, all) => all.findIndex((other) => other.chunk_id === item.chunk_id) === index);
  if (!unique.length) return null;
  return <div className="citation-list" aria-label="回答来源">
    <span className="citation-heading">来源</span>
    {unique.map((item, index) => <span className="citation" key={item.chunk_id} title={`${item.document_id} · ${item.chunk_id}`}>
      <span className="citation-index">{index + 1}</span><span>{item.title}{item.section ? ` · ${item.section}` : ""}</span>
    </span>)}
  </div>;
}

function ActionCard({ action, onConfirm, onCancel, disabled }: { action: ActionProposal; onConfirm: () => void; onCancel: () => void; disabled: boolean }) {
  return <div className="action-card">
    <div className="action-icon"><ShieldCheck size={19} /></div>
    <div className="action-content"><strong>需要你的确认</strong><p>{action.summary}</p>
      <div className="action-buttons"><button className="confirm-button" disabled={disabled} onClick={onConfirm}>确认执行</button><button className="cancel-button" disabled={disabled} onClick={onCancel}>取消</button></div>
    </div>
  </div>;
}

interface MessageViewProps {
  conversation: Conversation;
  busy: boolean;
  onConfirm: (action: ActionProposal, messageId: string) => void;
  onCancel: (messageId: string) => void;
}

export function MessageView({ conversation, busy, onConfirm, onCancel }: MessageViewProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [conversation.messages]);

  async function copy(message: Message) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedId(message.id);
      window.setTimeout(() => setCopiedId(null), 1800);
    } catch { /* Clipboard can be unavailable on insecure origins. */ }
  }

  return <div className="message-list" aria-label="对话内容">
    {conversation.messages.map((message) => message.role === "user"
      ? <div className="message user-message" key={message.id}><div className="user-bubble">{message.content}</div></div>
      : <div className="message assistant-message" key={message.id}>
          <div className="assistant-avatar"><Logo small /></div>
          <div className="assistant-body">
            {message.content ? <div className={`markdown ${message.state === "error" ? "message-error" : ""}`}><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></div> : <div className="thinking"><span /><span /><span /></div>}
            {message.state === "complete" && <>
              <CitationList citations={message.citations ?? []} />
              {message.pendingAction && <ActionCard action={message.pendingAction} disabled={busy} onConfirm={() => onConfirm(message.pendingAction!, message.id)} onCancel={() => onCancel(message.id)} />}
              <div className="message-tools"><button aria-label="复制回答" title="复制回答" onClick={() => void copy(message)}>{copiedId === message.id ? <Check size={16} /> : <Copy size={16} />}</button></div>
            </>}
            {message.state === "stopped" && <span className="message-note">生成已停止</span>}
          </div>
        </div>)}
    <div ref={endRef} />
  </div>;
}
