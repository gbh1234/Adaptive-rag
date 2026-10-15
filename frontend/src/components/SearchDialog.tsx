import { useEffect, useRef, useState } from "react";
import { MessageSquare, Search, X } from "lucide-react";
import type { Conversation } from "../types";

interface SearchDialogProps {
  conversations: Conversation[];
  onClose: () => void;
  onSelect: (id: string) => void;
}

export function SearchDialog({ conversations, onClose, onSelect }: SearchDialogProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);
  const filtered = conversations.filter((item) =>
    item.title.toLowerCase().includes(query.toLowerCase()) ||
    item.messages.some((message) => message.content.toLowerCase().includes(query.toLowerCase()))
  ).slice(0, 20);

  return <div className="dialog-backdrop" onMouseDown={onClose}>
    <section className="search-dialog" role="dialog" aria-modal="true" aria-label="搜索对话" onMouseDown={(event) => event.stopPropagation()}>
      <div className="search-input-row"><Search size={20} /><input ref={inputRef} value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") onClose(); if (event.key === "Enter" && filtered[0]) onSelect(filtered[0].id); }} placeholder="搜索对话" aria-label="搜索对话" /><button className="icon-button" onClick={onClose} aria-label="关闭搜索"><X size={18} /></button></div>
      <div className="search-results">
        {filtered.length ? filtered.map((item) => <button key={item.id} onClick={() => onSelect(item.id)}><MessageSquare size={17} /><span>{item.title}</span><small>{new Date(item.updatedAt).toLocaleDateString("zh-CN")}</small></button>) : <p>没有找到相关对话</p>}
      </div>
    </section>
  </div>;
}
