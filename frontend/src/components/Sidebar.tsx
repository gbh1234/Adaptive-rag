import { MessageSquare, Moon, MoreHorizontal, PanelLeftClose, Plus, Search, Sun, Trash2 } from "lucide-react";
import type { Conversation } from "../types";
import { Logo } from "./Logo";

function dateGroup(timestamp: number): string {
  const today = new Date();
  const date = new Date(timestamp);
  if (date.toDateString() === today.toDateString()) return "今天";
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "昨天";
  if (today.getTime() - timestamp < 7 * 24 * 60 * 60 * 1000) return "过去 7 天";
  return "更早";
}

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  open: boolean;
  onClose: () => void;
  onNew: () => void;
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
  onSearch: () => void;
  onTheme: () => void;
  theme: "light" | "dark";
}

export function Sidebar(props: SidebarProps) {
  const groups = new Map<string, Conversation[]>();
  for (const item of [...props.conversations].sort((a, b) => b.updatedAt - a.updatedAt)) {
    const key = dateGroup(item.updatedAt);
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }

  return <>
    {props.open && <button className="sidebar-scrim" aria-label="关闭侧栏" onClick={props.onClose} />}
    <aside className={`sidebar ${props.open ? "sidebar-open" : ""}`} aria-label="对话侧栏">
      <div className="sidebar-top">
        <button className="icon-button sidebar-toggle" aria-label="收起侧栏" title="收起侧栏" onClick={props.onClose}><PanelLeftClose size={19} /></button>
        <button className="icon-button" aria-label="新对话" title="新对话" onClick={props.onNew}><Plus size={20} /></button>
      </div>
      <div className="sidebar-actions">
        <button className="sidebar-action" onClick={props.onNew}><Logo small /><span>新对话</span></button>
        <button className="sidebar-action" onClick={props.onSearch}><Search size={19} /><span>搜索对话</span><kbd>⌘ K</kbd></button>
      </div>
      <nav className="conversation-list" aria-label="本地对话列表">
        {[...groups].map(([group, conversations]) => <div className="conversation-group" key={group}>
          <h2>{group}</h2>
          {conversations.map((item) => <div className={`conversation-row ${props.activeId === item.id ? "selected" : ""}`} key={item.id}>
            <button className="conversation-select" onClick={() => props.onSelect(item.id)} title={item.title}>
              <MessageSquare size={16} className="conversation-icon" /><span>{item.title}</span>
            </button>
            <button className="conversation-delete" title="删除对话" aria-label={`删除对话 ${item.title}`} onClick={() => props.onRemove(item.id)}><Trash2 size={15} /></button>
          </div>)}
        </div>)}
      </nav>
      <div className="sidebar-footer">
        <button className="sidebar-footer-button" onClick={props.onTheme}>
          {props.theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          <span>{props.theme === "light" ? "深色模式" : "浅色模式"}</span>
        </button>
        <div className="profile-row"><span className="profile-avatar">A</span><span><strong>Adaptive RAG</strong><small>本地演示工作台</small></span><MoreHorizontal size={18} /></div>
      </div>
    </aside>
  </>;
}
