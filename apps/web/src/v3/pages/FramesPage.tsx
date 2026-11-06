// ASSETUX 1b：“出图”页（#/frames；顶栏“出图”指向它，旧画布入口保留）。
// 项目方 16:4x：“‘出图’那个 uiux 点不了，里面应该是全部 ep 的每一个镜头的图片管理。”
// 全部集 × 每镜首尾帧当前版；徽标只有 已定稿 / 当前 / 新（L-123 没有“不要”）；生成中 / 排队 = 呼吸灯 + 预计时间；
// 按集、状态（缺图 / 待你看 / 尽力版 / 已定稿）、人物筛选（服务端做）；点格子 = 右侧抽屉（大图 + 用这张 / 修改）。数据：/api/frames-index。
import { useCallback, useEffect, useMemo, useState } from "react";
import { Empty, LoadError, Skel } from "../../ds";
import { Verdict } from "../Verdict";
import { LoadImg } from "../../ds/LoadImg";
import { fmtClock, fmtRemain, genView, statusText } from "../GenState.helpers";
import { GenLamp } from "../GenState";
import { QueueDock } from "../QueueDock";
import "./frames.css";

type Gen = { state: string; eta_s: number | null; job_id: string | null; started_at: string | null; created_at: string | null };
type Edit = { id: string; state: string; word: string; pos: number | null; eta_at: number | null; retry: number; msg: string };
/** pending（ORPHAN-TAKE）：比当前版新、还给不了看的最新一版——等打分 / 图在传输中；没图可给时格子写这个字，不写“文件不在” */
type Pending = { n: number; word: string; why?: string };
/** fallback（L-204 D8 / L-203）：尾帧兜底生效——这一镜只给首帧，运镜交给视频模型；格子写“不用尾帧”，不算缺图、不标“新”、不写“在重出” */
type Fallback = { mode: string; word: string; why: string; at?: string | null; by?: string | null };
/** ledger（UIUX-LOOP-2 r7）：没有本机图时，活的登记表说这一格在干什么（排队 / 正在出 / 等上一步 / 没出来）——排队中的镜也要看得见 */
type Ledger = { state: string; word: string; take: number | null; why: string | null };
type Cell = { n: number | null; url: string | null; state: "none" | "current" | "final" | "fallback"; new_n: number | null; new_url: string | null; gen: Gen | null; sys_retry?: number; edit?: Edit | null; pending?: Pending | null; fallback?: Fallback | null; ledger?: Ledger | null };
type Shot = { id: string; index: number; chars: string[]; first: Cell; last: Cell; main: { kind: string; word: string } | null };
type Index = { episodes: { ep: number; shots: Shot[] }[]; counts: { shots: number; missing: number; new: number; best: number; final: number }; gen: { running: number; queued: number } };
const STATUS: [string, string][] = [
  ["", "全部"],
  ["missing", "缺图"],
  ["new", "待你看"],
  ["best", "尽力版"],
  ["final", "已定稿"],
];
const CHAR_NAME: Record<string, string> = { lin_wan: "林晚", gu_chen: "顾沉", chen_yu: "陈宇", ch_a_lan: "阿岚" };

function hashQuery(): URLSearchParams {
  const i = location.hash.indexOf("?");
  return new URLSearchParams(i >= 0 ? location.hash.slice(i + 1) : "");
}

/** 缩略图：加载失败 / 没有地址 → “文件不在 + 原因”，不出现裂图图标（项目方 16:3x：版本和片条里有好几张破图） */
export function SafeImg({ src, why = "文件不在", alt = "" }: { src: string | null; why?: string; alt?: string }) {
  if (!src)
    return (
      <div className="fp-miss" role="img" aria-label={alt || why}>
        <span>{why}</span>
      </div>
    );
  return <LoadImg src={src} alt={alt} loading="lazy" onError={() => undefined} />;
}

function useFrames(ep: string, status: string, char: string) {
  const [d, setD] = useState<Index | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const q = useMemo(() => {
    const p = new URLSearchParams();
    if (ep) p.set("ep", ep);
    if (status) p.set("status", status);
    if (char) p.set("char", char);
    return p.toString();
  }, [ep, status, char]);
  const load = useCallback(() => {
    fetch(`/api/frames-index${q ? `?${q}` : ""}`)
      .then((r) => (r.ok ? (r.json() as Promise<Index>) : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((x) => (setD(x), setErr(null)))
      .catch((e) => setErr(String((e as Error).message ?? e)));
  }, [q]);
  useEffect(() => {
    load();
    const busy = d && (d.gen.running + d.gen.queued > 0 || d.episodes.some((e) => e.shots.some((s) => s.first.edit || s.last.edit)));
    const t = window.setInterval(load, busy ? 4000 : 20000);
    window.addEventListener("ns-frames-refresh", load);   // 提交“修改”后立刻刷新，格子马上显示“排队中”
    return () => (window.clearInterval(t), window.removeEventListener("ns-frames-refresh", load));
  }, [load, d?.gen.running, d?.gen.queued]); // eslint-disable-line react-hooks/exhaustive-deps
  return { d, err, load };
}

function GenCover({ g }: { g: Gen }) {
  const v = genView({ id: g.job_id ?? "", state: g.state, eta_s: g.eta_s, started_at: g.started_at, created_at: g.created_at }, [], Date.now());
  if (!v) return null;
  return (
    <div className={`fp-gen ${v.phase}`} role="status">
      <span className="fp-ring" aria-hidden />
      <span>
        <GenLamp phase={v.phase} /> <b>{g.state === "queued" ? "排队中" : statusText(v)}</b>
      </span>
      <span className="fp-eta">
        {fmtRemain(v.remainS, v.estimated)}
        {v.etaAt ? ` · ${fmtClock(v.etaAt)}` : ""}
      </span>
    </div>
  );
}

/** 这一格有一条“修改”在处理：原位显示排队中（灰点 + 排第 N）/ 修改中（琥珀呼吸灯 + 预计钟点）/ 打分中 / 需要你看一眼（琥珀实心） */
function EditCover({ e }: { e: Edit }) {
  const look = e.state === "needs_look";
  const run = e.state === "rendering" || e.state === "scoring";
  return (
    <div className={`fp-gen ${run ? "running" : "queued"}${look ? " look" : ""}`} role="status">
      <span className="fp-ring" aria-hidden />
      <span>
        {look ? <i className="fp-solid" aria-hidden /> : <GenLamp phase={run ? "running" : "queued"} />} <b>{e.word}</b>
      </span>
      {!look && e.eta_at ? <span className="fp-eta">预计 {fmtClock(e.eta_at * 1000)}</span> : null}
    </div>
  );
}

function CellView({ c, label, onOpen }: { c: Cell; label: string; onOpen: () => void }) {
  const show = c.new_url ?? c.url;
  if (c.state === "fallback" && c.fallback) {
    // UIUX-LOOP r2：兜底镜的尾帧格——平静的一格“不用尾帧”，悬停看原因；点开抽屉能看说明和去画布
    return (
      <div className="fp-cellw">
        <button type="button" className="fp-cell s-fallback" onClick={onOpen} title={`${label}：${c.fallback.word}\n${c.fallback.why}`}>
          <div className="fp-miss fp-fb"><span>不用尾帧</span><small>运镜交给视频模型</small></div>
        </button>
        <div className="fp-cap">{label}</div>
      </div>
    );
  }
  const badge = c.gen || c.edit ? null : c.new_n ? ["新", "a"] : c.state === "final" ? ["已定稿", "g"] : c.state === "current" ? ["当前", "g"] : null;
  // ORPHAN-TAKE：只给看通过且图已在本机的版本（“新”只在那时标）；有更新的一版还在等打分 / 传输中 → 缺图时格子写它，不写“文件不在”；
  // 有当前版时右下角小字提示“v12 等打分”，当前版照常显示
  const pend = !c.gen && !c.edit && c.pending ? c.pending : null;
  const led = c.state === "none" && !c.gen && !pend && !(c.sys_retry ?? 0) && c.ledger ? c.ledger : null;
  const missWord = c.gen ? "" : pend ? `${label}${pend.word}` : (c.sys_retry ?? 0) > 0 ? `${label}在重出` : led ? led.word : "还没出图";
  const tip = c.state === "none" && !c.gen ? (pend ? `${label}${pend.word}：${pend.why ?? ""}（v${pend.n}）` : led ? `${label}${led.word}${led.why ? `：${led.why}` : ""}` : `${label}还没出图`) : `${label}：点开看大图、用这张 / 修改${pend ? `\n另有 v${pend.n} ${pend.word}` : ""}`;
  return (
    <div className="fp-cellw">
      <button type="button" className={`fp-cell s-${c.state}`} onClick={onOpen} title={tip}>
        {c.state === "none" && !c.new_url ? <div className="fp-miss"><span>{missWord}</span></div> : <SafeImg src={show} />}
        {badge && <span className={`fp-badge ${badge[1]}`}>{badge[0]}</span>}
        {pend && (c.state !== "none" || c.new_url) && <span className="fp-pend" title={pend.why ?? ""}>v{pend.n} {pend.word}</span>}
        {c.edit ? <EditCover e={c.edit} /> : c.gen ? <GenCover g={c.gen} /> : null}
      </button>
      <div className="fp-cap">{label}</div>
    </div>
  );
}

type Log = { id: string; text: string; zh_summary: string | null; at: string; state: string; word: string; pos: number | null; eta_at: number | null; ahead: string[]; retry: number; msg: string };

/** 这一格的修改记录：你写的话、系统理解的改动、提交时间、现在的状态、预计完成、前面还有几单（哪几镜） */
function EditLog({ shot, stage }: { shot: string; stage: "first" | "last" }) {
  const [rows, setRows] = useState<Log[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch(`/api/shots/${encodeURIComponent(shot)}/frame-edits?stage=${stage}`)
        .then((r) => (r.ok ? (r.json() as Promise<{ edits: Log[] }>) : null))
        .then((x) => alive && x && setRows(x.edits))
        .catch(() => undefined);
    load();
    const t = window.setInterval(load, 4000);
    window.addEventListener("ns-frames-refresh", load);
    return () => (alive = false, window.clearInterval(t), window.removeEventListener("ns-frames-refresh", load));
  }, [shot, stage]);
  if (!rows.length) return null;
  return (
    <div className="fp-log" aria-label="修改记录">
      {rows.map((e) => (
        <div key={e.id} className={`fp-log-i s-${e.state}`}>
          <div className="fp-log-t">
            <b>{e.word}</b>
            <span>{e.at.slice(5, 16).replace("T", " ")} 提交</span>
          </div>
          <div className="fp-log-q">你写的：{e.text}</div>
          {e.zh_summary && <div className="fp-log-q">它理解的改动：{e.zh_summary}</div>}
          {e.state === "queued" && (
            <div className="fp-log-q">
              该内容已经提交，正在排队{e.pos ? `，排第 ${e.pos} 个` : ""}
              {e.eta_at ? `，预计 ${fmtClock(e.eta_at * 1000)} 前后做完` : ""}
              {e.ahead.length ? `。前面还有 ${e.ahead.length} 单：${e.ahead.join("、")}` : ""}
            </div>
          )}
          {e.state === "rendering" && <div className="fp-log-q">正在修改{e.eta_at ? `，预计 ${fmtClock(e.eta_at * 1000)} 前后做完` : ""}</div>}
          {e.state === "scoring" && <div className="fp-log-q">新版本已经出来，正在打分</div>}
          {e.state === "preparing" && <div className="fp-log-q">已记下，正在整理你的要求，马上进队列</div>}
          {e.state === "needs_look" && <div className="fp-log-q look">{e.msg}</div>}
          {e.state === "done" && <div className="fp-log-q">做好了，新版本在这一格上，点“用这张”才会设为当前</div>}
        </div>
      ))}
    </div>
  );
}

function Drawer({ shot, stage, onClose, onChanged }: { shot: Shot; stage: "first" | "last"; onClose: () => void; onChanged: () => void }) {
  const c = shot[stage];
  const n = c.new_n ?? c.n;
  const nm = stage === "first" ? "首帧" : "尾帧";
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && !document.querySelector(".vd-scrim") && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <aside className="fp-drawer" aria-label={`${shot.id} ${nm}`}>
      <header>
        <b>
          {shot.id} · {nm}
        </b>
        <button type="button" className="fp-x" onClick={onClose} aria-label="关闭">
          ×
        </button>
      </header>
      <div className="fp-big">
        <SafeImg src={c.new_url ?? c.url} why={c.state === "fallback" ? "不用尾帧" : "还没出图"} />
        {c.gen && <GenCover g={c.gen} />}
      </div>
      {c.state === "fallback" && c.fallback && (
        <p className="fp-note fp-fbnote">
          <b>{c.fallback.word}。</b>
          {c.fallback.why}
          {c.fallback.at ? ` （${c.fallback.at.slice(5, 16).replace("T", " ")} 定）` : ""}
        </p>
      )}
      <div className="fp-act" onClick={onChanged}>
        {n != null ? <Verdict shot={shot.id} stage={stage} n={n} size="md" /> : <span className="fp-note">{c.state === "fallback" ? "这一镜不出尾帧" : "还没有这一格的图"}</span>}
        <a className="fp-link" href={`#${shot.id}`}>
          在画布里打开这一镜
        </a>
        {/* NAVFLOW-F L-146：④出图的“修改”入口之一——到图像编辑器里看参考图、出几张候选、A/B 对比、写一句话修改 */}
        <a className="fp-link" href={`#/image-edit?shot=${encodeURIComponent(shot.id)}&stage=${stage}`} title="图像编辑器：参考图、出候选、并排对比、写一句话修改">
          到图像编辑器里改
        </a>
      </div>
      <EditLog shot={shot.id} stage={stage} />
      <p className="fp-note">{c.new_n ? `这是新出的一版（#${c.new_n}），点“用这张”才会设为当前。` : c.state === "final" ? "已定稿。" : c.state === "current" ? "当前版。" : ""}</p>
    </aside>
  );
}

export default function FramesPage() {
  const q0 = hashQuery();
  const [ep, setEp] = useState(q0.get("ep") ?? "");
  const [status, setStatus] = useState(q0.get("status") ?? "");
  const [char, setChar] = useState(q0.get("char") ?? "");
  const [open, setOpen] = useState<Record<number, boolean>>({});
  const [peek, setPeek] = useState<{ id: string; stage: "first" | "last" } | null>(q0.get("shot") ? { id: q0.get("shot") as string, stage: "first" } : null); // NAVIA：深链接 &shot=ep02-S3 直接开抽屉
  const { d, err, load } = useFrames(ep, status, char);
  useEffect(() => {
    // 筛选写回地址栏（可分享）；不触发新的路由
    const p = new URLSearchParams();
    if (ep) p.set("ep", ep);
    if (status) p.set("status", status);
    if (char) p.set("char", char);
    const s = p.toString();
    history.replaceState(null, "", `#/frames${s ? `?${s}` : ""}`);
  }, [ep, status, char]);
  // NAVIA：集范围由顶部范围条管（地址里的 ep=all|N），这一页不再自带集下拉
  useEffect(() => {
    const f = () => {
      const e = hashQuery().get("ep");
      setEp(!e || e === "all" ? "" : e);
    };
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  const [allChars, setAllChars] = useState<string[]>([]);
  useEffect(() => {
    if (!d || ep || status || char) return;
    setAllChars([...new Set(d.episodes.flatMap((e) => e.shots.flatMap((s) => s.chars)))]);
  }, [d, ep, status, char]);
  if (err && !d) return <div className="v3p-page"><LoadError what="出图" err={err} retry={load} /></div>;
  if (!d) return <div className="v3p-page"><Skel h={480} /></div>;
  const shot = peek ? d.episodes.flatMap((e) => e.shots).find((s) => s.id === peek.id) : undefined;
  const filtered = !!(ep || status || char);
  return (
    <div className="v3p-page fp-page">
      <header className="v3p-head fp-head">
        <h1>出图</h1>
        <label>
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="按状态">
            {STATUS.map(([k, t]) => (
              <option key={k} value={k}>
                {k ? `状态：${t}` : "全部状态"}
              </option>
            ))}
          </select>
        </label>
        <label>
          <select value={char} onChange={(e) => setChar(e.target.value)} aria-label="按人物">
            <option value="">全部人物</option>
            {allChars.map((c) => (
              <option key={c} value={c}>
                {CHAR_NAME[c] ?? c}
              </option>
            ))}
          </select>
        </label>
        <span className="v3p-muted">
          {d.counts.shots} 镜 · 缺图 {d.counts.missing} · 待你看 {d.counts.new} · 已定稿 {d.counts.final}
        </span>
        <span className="grow" />
        {d.gen.running + d.gen.queued > 0 && (
          <span className="fp-sum" role="status">
            <GenLamp phase="running" /> {d.gen.running} 在生成{d.gen.queued ? ` · ${d.gen.queued} 排队` : ""}
          </span>
        )}
      </header>
      {!d.episodes.length &&
        (status || char ? (
          <Empty icon="○" title="没有符合的镜头" sub="换个筛选条件，或者选“全部”。" />
        ) : (
          <Empty
            icon="○"
            title={ep && ep !== "all" ? `第 ${ep} 集还没有镜头` : "这部剧还没有镜头"}
            sub={`${ep && ep !== "all" ? "这一集" : "剧本"}的分镜导入后，系统会自动出首帧和尾帧，出来就显示在这里，不用你操作。现在可以去看剧本写到哪了。`}
            action={<a className="v3-btn" href={`#/script-create${ep && ep !== "all" ? `?ep=${ep}` : ""}`}>去看剧本</a>}
          />
        ))}
      {d.episodes.map((e, i) => {
        const shut = open[e.ep] === undefined ? i >= 1 && !filtered : !open[e.ep];
        return (
          <section key={e.ep} className="fp-ep">
            <button type="button" className="fp-eph" aria-expanded={!shut} onClick={() => setOpen((o) => ({ ...o, [e.ep]: shut }))}>
              <b>第 {e.ep} 集</b>
              <span className="v3p-muted">
                {e.shots.length} 镜 · 缺图 {e.shots.filter((s) => s.first.state === "none" || s.last.state === "none").length} · 待你看 {e.shots.filter((s) => s.first.new_n || s.last.new_n).length}
              </span>
              <span className="fp-chev">{shut ? "▸" : "▾"}</span>
            </button>
            {!shut && (
              <div className="fp-grid">
                {e.shots.map((s) => (
                  <div key={s.id} className="fp-shot">
                    <CellView c={s.first} label={`S${s.index} 首帧`} onOpen={() => setPeek({ id: s.id, stage: "first" })} />
                    <CellView c={s.last} label={`S${s.index} 尾帧`} onOpen={() => setPeek({ id: s.id, stage: "last" })} />
                  </div>
                ))}
              </div>
            )}
          </section>
        );
      })}
      <QueueDock />
      {shot && peek && <Drawer shot={shot} stage={peek.stage} onClose={() => setPeek(null)} onChanged={() => window.setTimeout(load, 600)} />}
    </div>
  );
}
