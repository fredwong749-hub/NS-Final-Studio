// 包一层：value 真变了这块就柔和地闪一下（第一次渲染、内容没变都不闪）。用法：<Flash value={[url, state]}>…</Flash>
import type { ReactNode } from "react";
import { useFlash } from "../v3/live";
import "./live.css";

export function Flash({ value, children, className = "", as = "div" }: { value: unknown; children: ReactNode; className?: string; as?: "div" | "span" | "li" }) {
  const on = useFlash(value);
  const Tag = as;
  return <Tag className={`${className}${on ? " live-flash" : ""}`}>{children}</Tag>;
}
