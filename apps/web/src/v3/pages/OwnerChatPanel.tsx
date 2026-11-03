// W30 · PLAN_OWNER_CHAT 分期 2：#/queue 顶部常驻的项目方助手（只读）。
// 后端 POST /api/owner/chat {message, history[]} → {reply, need, proposed_actions[]}；GET /api/owner/chat/digest → {sentence}。
// 本期动作不执行：proposed_actions 画成灰色、不可点的按钮，标“下一期”。挂法：OwnerQueuePage 顶部 <OwnerChatPanel />（由 A-G3 加那一行）。
import { useCallback, useEffect, useRef, useState, type CSSProperties, type FormEvent } from "react";

export type ChatAction = { tool: string; args: Record<string, unknown>; label: string; executable: boolean; phase?: string };
export type ChatReply = { reply: string; need: string; proposed_actions: ChatAction[]; error?: string };
type Msg = { role: "user" | "assistant"; content: string; need?: string; actions?: ChatAction[]; error?: string };

const S: Record<string, CSSProperties> = {
  box: { border: "1px solid var(--oq-line2, rgba(255,255,255,.16))", borderRadius: 6, margin: "16px 0 6px", padding: "10px 12px", background: "rgba(255,255,255,.015)" },
  head: { display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: "var(--oq-t2, rgba(233,230,224,.62))", flexWrap: "wrap" },
  digest: { color: "var(--oq-t1, #e9e6e0)", fontSize: 14 },
  flow: { maxHeight: 280, overflowY: "auto", margin: "8px 0", display: "flex", flexDirection: "column", gap: 8 },
  me: { alignSelf: "flex-end", maxWidth: "85%", background: "rgba(255,255,255,.06)", padding: "6px 10px", borderRadius: 6, fontSize: 13.5, whiteSpace: "pre-wrap" },
  bot: { alignSelf: "flex-start", maxWidth: "92%", fontSize: 13.5, whiteSpace: "pre-wrap", lineHeight: 1.5 },
  need: { fontWeight: 600, marginBottom: 2 },
  err: { color: "var(--c-warn, #d6a23a)", fontSize: 12 },
  acts: { display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6 },
  act: { opacity: 0.45, cursor: "not-allowed", border: "1px solid var(--oq-line2, rgba(255,255,255,.16))", background: "transparent", borderRadius: 4, padding: "3px 8px", fontSize: 12 },
  form: { display: "flex", gap: 8 },
  input: { flex: 1, minWidth: 0, background: "var(--oq-base, #030303)", color: "inherit", border: "1px solid var(--oq-line2, rgba(255,255,255,.16))", borderRadius: 4, padding: "6px 8px", fontSize: 14 },
  send: { border: "1px solid var(--oq-line2, rgba(255,255,255,.16))", background: "transparent", borderRadius: 4, padding: "6px 14px", cursor: "pointer" },
};

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

export default function OwnerChatPanel() {
  const [digest, setDigest] = useState<string>("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const flow = useRef<HTMLDivElement>(null);

  const loadDigest = useCallback(async () => {
    try {
      const r = await fetch("/api/owner/chat/digest", { credentials: "same-origin" });
      if (r.ok) setDigest(String((await r.json())?.sentence || ""));
    } catch { /* 汇总读不到不挡对话 */ }
  }, []);

  useEffect(() => { void loadDigest(); const t = window.setInterval(() => void loadDigest(), 60_000); return () => window.clearInterval(t); }, [loadDigest]);
  useEffect(() => { flow.current?.scrollTo({ top: flow.current.scrollHeight }); }, [msgs, busy]);

  const send = async (e?: FormEvent) => {
    e?.preventDefault();
    const m = text.trim();
    if (!m || busy) return;
    const history = msgs.map((x) => ({ role: x.role, content: x.role === "assistant" ? [x.need, x.content].filter(Boolean).join("\n") : x.content }));
    setMsgs((xs) => [...xs, { role: "user", content: m }]);
    setText("");
    setBusy(true);
    try {
      const r = await postChat(m, history);
      setMsgs((xs) => [...xs, { role: "assistant", content: r.reply, need: r.need, actions: r.proposed_actions || [], error: r.error }]);
    } catch (err) {
      setMsgs((xs) => [...xs, { role: "assistant", content: "", error: (err as Error).message }]);
    } finally {
      setBusy(false);
      void loadDigest();
    }
  };

  return (
    <section style={S.box} aria-label="项目方助手">
      <div style={S.head}>
        <span>助手</span>
        <span style={S.digest}>{digest || "正在读你的待办…"}</span>
      </div>
      {(msgs.length > 0 || busy) && (
        <div style={S.flow} ref={flow}>
          {msgs.map((x, i) => x.role === "user" ? (
            <div key={i} style={S.me}>{x.content}</div>
          ) : (
            <div key={i} style={S.bot}>
              {x.need && <div style={S.need}>{x.need}</div>}
              {x.content && x.content !== x.need && <div>{x.content}</div>}
              {x.error && <div style={S.err}>{x.error}</div>}
              {!!x.actions?.length && (
                <div style={S.acts}>
                  {x.actions.map((a, j) => (
                    <button key={j} type="button" disabled style={S.act} title="下一期接通：现在请在下面的卡片上点">
                      {a.label}（下一期）
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
          {busy && <div style={S.bot}>想一下…</div>}
        </div>
      )}
      <form style={{ ...S.form, marginTop: msgs.length ? 0 : 8 }} onSubmit={send}>
        <input style={S.input} value={text} onChange={(e) => setText(e.target.value)} placeholder="问：现在要我做什么？/ 这张为什么推荐 2 号？" maxLength={4000} disabled={busy} />
        <button type="submit" style={S.send} disabled={busy || !text.trim()}>问</button>
      </form>
    </section>
  );
}
