// UIUX-LOOP-2 r6（11-06）：总览里的“大脑在想什么”只读小面板——BRAIN-FW / 会话内总调度最近的决定、给项目方的话、快照探针情况。
// 数据全来自 GET /api/brain/status（本机 data/brain/*），不猜、不写。全文 = data/brain/STATUS.md 原样（折叠里看）。
import { useCallback, useEffect, useState } from "react";
import "./brain.css";

type Decision = { at: string | null; kind: string | null; dry: boolean; by: string | null; reason: string; expected: string; result: string; rejected: unknown };
type Note = { at: string | null; level: "red" | "yellow" | "green"; text: string };
type Brain = {
  at: string;
  mode: { enabled: boolean; dry_run: boolean; model: string | null; interval_s: number | null; word: string };
  status_at: string | null; status_age_s: number | null;
  decisions: Decision[]; notes: Note[];
  snapshot: { at: string | null; run: string | null; age_s: number | null; probe_errors: string[]; issues_open: number; idle_lanes: string[] } | null;
  status_md: string | null; missing: string[];
};

const KIND_WORD: Record<string, string> = {
  no_action: "不动", note_to_owner: "给项目方留话", report_issue: "记卡点", restart: "重启", set_phase: "切阶段", override: "临时改表",
};
const age = (s: number | null) => (s == null ? "" : s < 90 ? `${s} 秒前` : s < 5400 ? `${Math.round(s / 60)} 分钟前` : `${(s / 3600).toFixed(1)} 小时前`);
const ICON: Record<Note["level"], string> = { red: "🔴", yellow: "🟡", green: "🟢" };

export function useBrainStatus() {
  const [d, setD] = useState<Brain | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    fetch("/api/brain/status")
      .then((r) => (r.ok ? (r.json() as Promise<Brain>) : Promise.reject(new Error(r.status === 404 ? "后台还没更新到有“大脑状态”接口的版本（重启后出现）" : `HTTP ${r.status}`))))
      .then((x) => (setD(x), setErr(null)))
      .catch((e: Error) => setErr(e.message));
  }, []);
  useEffect(() => {
    load();
    const t = window.setInterval(load, 30000);
    return () => window.clearInterval(t);
  }, [load]);
  return { d, err, load };
}

/** 全剧总览里的“大脑在想什么”面板（可折叠，记住选择；默认收起，只露一行） */
export function BrainPanel() {
  const { d, err, load } = useBrainStatus();
  const [open, setOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem("brain.open") === "1";
    } catch {
      return false;
    }
  });
  const [full, setFull] = useState(false);
  const toggle = () => {
    setOpen(!open);
    try {
      localStorage.setItem("brain.open", open ? "0" : "1");
    } catch {
      /* 存不了就只在这次有效 */
    }
  };
  const last = d?.decisions[0];
  const note = d?.notes[0];
  return (
    <section className="brain" aria-label="大脑在想什么">
      <header className="brain-h">
        <button type="button" className="brain-tg" onClick={toggle} aria-expanded={open}>
          {open ? "▾" : "▸"} 大脑在想什么
        </button>
        <span className="brain-sub">
          {d ? (
            <>
              {d.mode.word}
              {last ? ` · 最近：${KIND_WORD[last.kind ?? ""] ?? "其它动作"}${last.at ? `（${last.at.slice(5, 16)}）` : ""}` : " · 还没有决定记录"}
              {note ? ` · ${ICON[note.level]} ${note.text.slice(0, 60)}` : ""}
            </>
          ) : err ? `读不到（${err}）` : "正在读…"}
        </span>
        <span className="grow" />
        {d && (
          <small className="brain-src" title={`状态页 ${d.status_at ?? "还没生成"}${d.snapshot ? ` · 快照 ${d.snapshot.at ?? ""}` : ""}`}>
            {d.status_age_s != null ? `状态页 ${age(d.status_age_s)}` : "状态页还没生成"}
          </small>
        )}
        {err && d ? <button type="button" className="v3p-link" onClick={load}>再试</button> : null}
      </header>
      {open && d && (
        <div className="brain-body">
          {d.notes.length > 0 && (
            <div className="brain-col">
              <h4>给项目方的话</h4>
              <ul>
                {d.notes.map((n, i) => (
                  <li key={i} className={`lv-${n.level}`}>
                    {ICON[n.level]} {n.at ? <small>{n.at} </small> : null}{n.text}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="brain-col">
            <h4>最近决定</h4>
            {d.decisions.length ? (
              <ul>
                {d.decisions.map((x, i) => (
                  <li key={i} title={x.expected ? `预期：${x.expected}` : undefined}>
                    <small>{x.at?.slice(5, 16)}</small> <b title={x.kind ?? undefined}>{KIND_WORD[x.kind ?? ""] ?? "其它动作"}</b>
                    {x.dry ? <i className="brain-dry">只记不做</i> : null}
                    {x.reason ? <span> · {x.reason}</span> : null}
                    {x.result ? <span className="brain-res"> → {x.result}</span> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="brain-empty">还没有决定记录（{d.missing.includes("decisions.jsonl") ? "data/brain/decisions.jsonl 还没有" : "文件是空的"}）。</p>
            )}
          </div>
          {d.snapshot && (
            <div className="brain-col">
              <h4>大脑看到的</h4>
              <p className="brain-snap">
                快照 {age(d.snapshot.age_s) || "刚刚"}
                {d.snapshot.probe_errors.length ? <span className="brain-warn"> · 探不到：{d.snapshot.probe_errors.join("、")}</span> : " · 两台都探得到"}
                {d.snapshot.issues_open ? ` · 开着的卡点 ${d.snapshot.issues_open} 个` : " · 没有开着的卡点"}
                {d.snapshot.idle_lanes.length ? ` · 空着的卡：${d.snapshot.idle_lanes.join("、")}` : ""}
              </p>
            </div>
          )}
          <div className="brain-foot">
            <button type="button" className="v3p-link" onClick={() => setFull(!full)}>{full ? "收起全文" : "看状态页全文"}</button>
            <a className="v3p-link" href="/files/brain/STATUS.md" target="_blank" rel="noreferrer">本地打开 STATUS.md</a>
            {d.missing.length ? <small className="brain-src">还没有：{d.missing.join("、")}</small> : null}
          </div>
          {full && d.status_md ? <pre className="brain-md">{d.status_md}</pre> : null}
        </div>
      )}
    </section>
  );
}
