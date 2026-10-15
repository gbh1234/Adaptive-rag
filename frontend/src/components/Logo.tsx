import { Sparkles } from "lucide-react";

export function Logo({ small = false }: { small?: boolean }) {
  return <span className={`brand-mark ${small ? "brand-mark-small" : ""}`} aria-hidden="true"><Sparkles size={small ? 18 : 22} strokeWidth={2.2} /></span>;
}
