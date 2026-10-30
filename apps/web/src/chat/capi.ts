// T58 剧本创作对话框：后端 /api/script-chat（services/api/ns_api/script_chat.py）
export type Issue = { rule_id: string; level: string; detail: string };
export type ShotCheck = { id: string; index: number; duration: number | null; ok: boolean; issues: Issue[]; repair: string };
export type EpCheck = {
  number: number; title: string; blocking: number; warnings: number; issues: Issue[]; repair: string; shots: ShotCheck[];
};
export type Validation = { at: string; episodes: EpCheck[]; blocking: number; warnings: number; draft: string; error?: string };
export type Msg = {
  role: "user" | "assistant"; content: string; at?: string; reasoning?: string; episodes?: number[];
  usage?: { prompt_tokens?: number; completion_tokens?: number } | null; finish?: string; partial?: boolean;
  seconds?: number; model?: string; episode?: number;
};
export type Session = {
  id: string; title: string; created_at: string; independent?: boolean; messages: Msg[];
  episodes: Record<string, string>; validation: Validation | null;
};
export type SessionRow = {
  id: string; title: string; created_at: string; updated_at: string; messages: number; episodes: number[]; blocking: number | null;
};
export type ChatConfig = {
  provider: string; model: string; base_url: string; has_key: boolean; temperature: number; max_tokens: number;
  parts: { name: string; path: string; chars: number }[];
};

import { detailText } from "../api";

const B = "/api/script-chat";

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let m = `${r.status}`;
    try { const d = (await r.json()).detail; if (d) m = detailText(d); } catch { /* 非 JSON */ }
    throw new Error(m);
  }
  return r.json();
}

export const capi = {
  config: () => j<ChatConfig>(`${B}/config`),
  system: () => j<{ text: string }>(`${B}/system`),
  sessions: () => j<SessionRow[]>(`${B}/sessions`),
  create: (title?: string) =>
    j<Session>(`${B}/sessions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) }),
  session: (id: string) => j<Session>(`${B}/sessions/${id}`),
  repair: (id: string) => j<{ text: string }>(`${B}/sessions/${id}/repair`),
  validate: (id: string) => j<Validation | null>(`${B}/sessions/${id}/validate`, { method: "POST" }),
};

export type StreamEvent =
  | { t: "start"; model: string }
  | { t: "reasoning" | "content" | "warn" | "progress"; d: string }
  | { t: "saved"; episodes: number[] }
  | { t: "validating" }
  | { t: "done"; episodes: number[]; validation: Validation | null }
  | { t: "error"; d: string };

/** POST 一条消息，逐个回调 SSE 事件；signal 可中止（已收到的部分后端会存档） */
export async function chatStream(id: string, content: string, on: (e: StreamEvent) => void, signal: AbortSignal, extra?: Record<string, unknown>) {
  // extra：v1 剧本创作页带 llm（⚙ 覆盖，api_v1_contract §B）；对话框不传
  const r = await fetch(`${B}/sessions/${id}/chat`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...extra, content }), signal,
  });
  if (!r.ok || !r.body) {
    let m = `${r.status}`;
    try { const d = (await r.json()).detail; if (d) m = detailText(d); } catch { /* 非 JSON */ }
    throw new Error(m);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      for (const line of block.split("\n"))
        if (line.startsWith("data: ")) on(JSON.parse(line.slice(6)));
    }
  }
}
