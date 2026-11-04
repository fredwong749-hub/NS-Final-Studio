import type { ChatReply } from "./OwnerChatPanel";

export async function postChat(message: string, history: { role: string; content: string }[]): Promise<ChatReply> {
  const r = await fetch("/api/owner/chat", {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
  });
  if (!r.ok) {
    let why = `助手没回上来（HTTP ${r.status}）`;
    try { const j = await r.json(); if (j?.detail) why = String(j.detail); } catch { /* 非 JSON */ }
    throw new Error(why);
  }
  return (await r.json()) as ChatReply;
}
