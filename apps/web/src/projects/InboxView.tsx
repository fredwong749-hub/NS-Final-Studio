// 「待办」：G2–G5 与「交 gpu3」授权卡片。关口之后的步骤在项目方点之前不会运行。
import { useCallback, useEffect, useState } from "react";
import { go, papi, type Card } from "./papi";

const GATE_HINT: Record<string, string> = {
  G2: "为每个角色选定身份母版（写进 assets/characters/<id>/plates/master.png）",
  G3: "gpu3 交回 v3 加强剧本后抽查对照；也可以跳过加强、用原剧本",
  GPU3: "成人首尾帧与全部视频只在 gpu3 出；批准后编排器把已就绪的集交给 gpu3",
  G4: "看第一集样片，锁定生产参数（PIPELINE_LOCKED）；锁定前只出第一集视频",
  G5: "看成片，标记发布或返工",
};

interface G2Char {
  id: string;
  name: string;
  candidates: string[];
  realism: string;
}

function G2Body({ card, choices, setChoices }: { card: Card; choices: Record<string, string>; setChoices: (c: Record<string, string>) => void }) {
  const chars = (card.detail.characters as G2Char[] | undefined) ?? [];
  return (
    <div className="ib-g2">
      {chars.map((c) => (
        <div key={c.id} className="ib-g2-char">
          <div className="ib-g2-name">
            <b>{c.name}</b> <span className="muted small">写实 {c.realism}</span>
            {choices[c.id] ? <span className="chip chip-ok">已选</span> : <span className="chip chip-warn">未选</span>}
          </div>
          <div className="ib-cands">
            {c.candidates.length === 0 && <span className="muted small">没有候选图（参考图 / candidates/）</span>}
            {c.candidates.map((f) => (
              <button key={f} className={`ib-cand${choices[c.id] === f ? " on" : ""}`} onClick={() => setChoices({ ...choices, [c.id]: f })} title={f}>
                <img src={papi.file(card.project, f)} alt="" />
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function CardView({ card, onDone }: { card: Card; onDone: () => void }) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [owner, setOwner] = useState(false); // 封板修复：关口决定须勾选“我是项目方”
  const d = card.detail;
  const act = (key: string) => {
    setBusy(true);
    setErr("");
    setOwner(false);
    papi
      .decide(card.project, card.id, key, { choices, note })
      .then(onDone, (e: Error) => setErr(e.message))
      .finally(() => setBusy(false));
  };
  return (
    <div className={`ib-card gate-${card.gate}`}>
      <div className="ib-card-head">
        <span className="ib-gate">{card.gate === "GPU3" ? "交 gpu3" : card.gate}</span>
        <b>{card.title}</b>
        <span className="chip">{card.project_name}</span>
        <span className="grow" />
        <span className="muted small">{card.opened_at}</span>
      </div>
      <div className="muted small">{GATE_HINT[card.gate]}</div>
      {card.gate === "G2" && <G2Body card={card} choices={choices} setChoices={setChoices} />}
      {card.gate === "G3" && (
        <div className="ib-detail">
          {d.v3 ? (
            <>
              <div>v3 剧本：<span className="mono">{String(d.v3)}</span></div>
              {Boolean(d.changes) && <div>对照：<a href={papi.file(card.project, String(d.changes))} target="_blank" rel="noreferrer">{String(d.changes)}</a></div>}
            </>
          ) : (
            <div className="wz-msg warn">gpu3 还没交回 v3 加强剧本（script/*v3*.md）。可以先跳过加强，用原剧本开始。</div>
          )}
          {card.last_rejected && <div className="muted small">上次退回：{card.last_rejected.decided_at}</div>}
        </div>
      )}
      {card.gate === "GPU3" && (
        <div className="ib-detail">
          <div>{String(d.note ?? "")}</div>
          <div className="badges">
            <span className={`chip ${d.adult_content ? "chip-adult" : ""}`}>成人内容 {d.adult_content ? "开" : "关"}</span>
            <span className="chip">成人镜头 {String(d.adult_shots ?? 0)}</span>
            <span className="chip chip-ok">尾帧就绪：ep{((d.episodes_ready as number[]) ?? []).join(", ep") || "—"}</span>
          </div>
        </div>
      )}
      {card.gate === "G4" && (
        <div className="ib-detail">
          样片：ep{String(d.episode ?? 1).padStart(2, "0")}（在画布或 gpu3 桥里看视频）
          {card.last_rejected && <div className="muted small">上次返工：{card.last_rejected.decided_at}</div>}
        </div>
      )}
      {card.gate === "G5" && (
        <div className="ib-detail">
          {d.final ? (
            <video className="ib-video" src={papi.file(card.project, String(d.final))} controls preload="metadata" />
          ) : (
            <span className="muted">成片文件：{String(d.final ?? "（演练模式没有真实成片）")}</span>
          )}
        </div>
      )}
      {(card.gate === "G3" || card.gate === "G4" || card.gate === "G5") && (
        <input className="ib-note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="备注（退回 / 返工原因）" />
      )}
      {err && <div className="banner">{err}</div>}
      <div className="ib-actions">
        <button className="btn ghost" onClick={() => go(`#/projects/${card.project}/board`)}>
          看板
        </button>
        <span className="grow" />
        <label className="small">
          <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} /> 我是项目方
        </label>
        {card.actions.map((a) => (
          <button key={a.key} className={`btn${a.primary ? " primary" : ""}`} disabled={busy || !owner} title={owner ? undefined : "先勾选「我是项目方」"} onClick={() => act(a.key)}>
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function InboxList({ cards, reload }: { cards: Card[]; reload: () => void }) {
  if (!cards.length) return <div className="ib-empty muted">没有待办：所有关口都已处理，其余步骤自动进行。</div>;
  return (
    <div className="ib-list">
      {cards.map((c) => (
        <CardView key={`${c.project}:${c.id}`} card={c} onDone={reload} />
      ))}
    </div>
  );
}

export function InboxView() {
  const [cards, setCards] = useState<Card[] | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    papi.inbox().then(setCards, (e: Error) => setErr(e.message));
  }, []);
  useEffect(() => {
    load();
    const t = window.setInterval(load, 15000);
    return () => window.clearInterval(t);
  }, [load]);
  return (
    <div className="pj-page">
      <div className="pj-head">
        <h2>待办</h2>
        <span className="muted">G2 人物定妆 · G3 剧本加强 · 交 gpu3 · G4 样片锁定 · G5 成片验收（G1 风格在向导里确认）</span>
      </div>
      {err && <div className="banner">{err}</div>}
      {cards ? <InboxList cards={cards} reload={load} /> : <div className="empty">加载中…</div>}
    </div>
  );
}
