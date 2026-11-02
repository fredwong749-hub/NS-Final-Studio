// NAVIA：“视频”页（#/videos?ep=all|N&state=&shot=）。全部镜头视频，每镜一格，按集顺序排（L-124）。
// 状态（只用 灰 / 琥珀呼吸 / 琥珀实心 / 绿）：出视频中 · 排队 · 待你看 · 缺首尾帧 · 失败 · 未出 · 已定稿。点开 = 右侧抽屉，播放 + 用这版 / 修改（L-123）。
// 数据：GET /api/videos/overview（后端按 vidgen 队列与历史中位时长给预计时间，前端只显示）。没有任何一种情况会出现白板：空 / 读不到都有说明和出口。
import { useCallback, useEffect, useMemo, useState } from "react";
import { Verdict } from "../Verdict";
import { useStudio } from "../../store";
import { fmtEta } from "../NavTabs.helpers";
import { SHOT_WORD, VIDEO_STATE_KIND, shotWord } from "../shotWord";
import "../navia.css";

type Row = { id: string; index: number; state: string; video_url: string | null; n: number | null; progress: number | null; queue_pos: number | null; eta: string | null; missing: string[]; candidates: number };
type Overview = {
  summary: { total: number; final: number; rendering: number; queued: number; pending_review: number; need_frames: number; todo: number; failed: number; eta_all: string | null; median_s: number };
  episodes: { ep: number; shots: Row[] }[];
};
// 状态词与圆点来自全站统一词表（v3/shotWord.ts）
const WORD: Record<string, string> = Object.fromEntries(Object.entries(VIDEO_STATE_KIND).map(([k, v]) => [k, shotWord(v, "视频")]));
const DOT: Record<string, string> = Object.fromEntries(Object.entries(VIDEO_STATE_KIND).map(([k, v]) => [k, { gray: "", breathe: "run", amber: "amber", green: "green" }[SHOT_WORD[v].dot]]));
const CHIPS: [string, string][] = [
  ["", "全部"],
  ["pending_review", "待你看"],
  ["rendering", "出视频中"],
  ["queued", "排队"],
  ["need_frames", "缺首尾帧"],
  ["todo", "未出"],
  ["final", "已定稿"],
];

const hq = () => new URLSearchParams(location.hash.split("?")[1] ?? "");
const setHq = (patch: Record<string, string | null>) => {
  const p = hq();
  for (const [k, v] of Object.entries(patch)) (v == null || v === "" ? p.delete(k) : p.set(k, v));
  history.replaceState(null, "", `#/videos${p.toString() ? `?${p}` : ""}`);
};

function useOverview(ep: string) {
  const [d, setD] = useState<Overview | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => {
    fetch(`/api/videos/overview${ep && ep !== "all" ? `?ep=${encodeURIComponent(ep)}` : ""}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status === 404 ? "后台还没更新到有“视频”接口的版本（等它自动重启后再点重试）" : `${r.status} ${r.statusText}`))))
      .then((x: Overview) => (setD(x), setErr("")))
      .catch((e: Error) => setErr(e.message));
  }, [ep]);
  useEffect(() => {
    setD(null);
    load();
    const t = window.setInterval(load, 15000);
    return () => window.clearInterval(t);
  }, [load]);
  return { d, err, load };
}

function Cell({ r, ep, onOpen }: { r: Row; ep: number; onOpen: () => void }) {
  const eta = fmtEta(r.eta);
  const right = r.state === "rendering" ? (eta ? `≈${eta}` : "") : r.state === "queued" ? (eta ? `≈${eta}` : "") : r.state === "need_frames" ? "去出图" : "";
  const word = r.state === "queued" && r.queue_pos ? `排队第 ${r.queue_pos}` : r.state === "need_frames" ? `缺${r.missing.map((m) => (m === "first" ? "首帧" : "尾帧")).join("、")}` : WORD[r.state] ?? r.state;
  return (
    <button className="vd-shot" onClick={onOpen} title={`${r.id} · ${word}${eta ? ` · 预计 ${eta}` : ""}`} data-state={r.state}>
      <div className="im">
        {r.video_url && <video src={`${r.video_url}#t=0.4`} preload="metadata" muted playsInline />}
        <span className="id">
          {ep}-{r.id.split("-")[1]}
        </span>
      </div>
      {r.state === "rendering" && r.progress != null && (
        <div className="pg">
          <i style={{ width: `${Math.round(r.progress * 100)}%` }} />
        </div>
      )}
      <div className="st">
        <span>
          <i className={`vd-dot ${DOT[r.state] ?? ""}`} />
          {word}
        </span>
        <span>{right}</span>
      </div>
    </button>
  );
}

function Drawer({ r, ep, onClose, onChanged, next }: { r: Row; ep: number; onClose: () => void; onChanged: () => void; next?: () => void }) {
  const eta = fmtEta(r.eta);
  const [chain, setChain] = useState(false);
  return (
    <aside className="vd-drawer" role="dialog" aria-label={`${r.id} 视频`}>
      <div className="row">
        <b>{r.id}</b>
        <span style={{ color: "var(--c-text-2,#aaa)" }}>{WORD[r.state]}</span>
        <span style={{ flex: 1 }} />
        <button className="v3-btn sm" onClick={onClose}>
          关闭
        </button>
      </div>
      {r.video_url ? <video key={r.video_url} src={r.video_url} controls autoPlay loop={!chain} muted playsInline onEnded={() => chain && next?.()} /> : <div className="vd-empty" style={{ margin: "20px 0" }}>{r.state === "rendering" || r.state === "queued" ? `正在排队 / 出视频${eta ? `，预计 ${eta}` : ""}` : "这一镜还没有视频"}</div>}
      <div className="row">
        {r.n != null && r.state !== "rendering" && r.state !== "queued" && (
          <span
            onClick={() => window.setTimeout(onChanged, 700)}
            onKeyDown={() => undefined}
          >
            <Verdict shot={r.id} stage="video" n={r.n} size="md" />
          </span>
        )}
        {r.state === "need_frames" && (
          <a className="v3-btn" href={`#/frames?ep=${ep}`}>
            去出图补{r.missing.map((m) => (m === "first" ? "首帧" : "尾帧")).join("、")}
          </a>
        )}
        {r.video_url && (
          <button className={`v3-btn sm${chain ? " primary" : ""}`} onClick={() => setChain(!chain)} title="播完自动播下一个有视频的镜头（按集顺序）">
            {chain ? "连播中 · 点此停止" : "从这一镜连播"}
          </button>
        )}
        <a className="v3-btn sm" href={`#ep${String(ep).padStart(2, "0")}`} title="在画布里看这一集的这一镜（一镜一行）">
          在画布里看
        </a>
      </div>
      <div style={{ fontSize: 12, color: "var(--c-text-3,#8a8a8a)" }}>候选 {r.candidates} 条 · 只有“用这版”和“修改”，没被用的自动留在历史里。</div>
    </aside>
  );
}

export default function VideosPage() {
  const [ep, setEp] = useState(hq().get("ep") ?? "all");
  const [state, setState] = useState(hq().get("state") ?? "");
  const [open, setOpen] = useState<string | null>(hq().get("shot"));
  // 顶部范围条改了 ep（hash）时跟着变
  useEffect(() => {
    const f = () => setEp(hq().get("ep") ?? "all");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  const { epNum, gotoEpisode } = useStudio();
  useEffect(() => {
    // 地址里是具体一集（ep=2）：顶部范围条的集号跟着对齐
    if (/^\d+$/.test(ep) && Number(ep) !== epNum) gotoEpisode(Number(ep));
  }, [ep]); // eslint-disable-line react-hooks/exhaustive-deps
  const { d, err, load } = useOverview(ep);
  const shown = useMemo(() => (d ? d.episodes.map((e) => ({ ...e, shots: e.shots.filter((s) => !state || s.state === state) })).filter((e) => e.shots.length) : []), [d, state]);
  const cur = open && d ? d.episodes.flatMap((e) => e.shots.map((s) => ({ s, ep: e.ep }))).find((x) => x.s.id === open) : undefined;
  const flat = useMemo(() => (d ? d.episodes.flatMap((e) => e.shots.filter((x) => !state || x.state === state).map((x) => ({ s: x, ep: e.ep }))) : []), [d, state]);
  const playNext = () => {
    const i = flat.findIndex((x) => x.s.id === open);
    const nx = flat.slice(i + 1).find((x) => x.s.video_url);
    if (nx) (setOpen(nx.s.id), setHq({ shot: nx.s.id }));
  };
  const s = d?.summary;
  const busy = (s?.rendering ?? 0) + (s?.queued ?? 0);

  return (
    <div className="vd-page">
      <div className="v3-scope" style={{ border: 0, padding: "0 0 6px" }}>
        {CHIPS.map(([k, w]) => {
          const n = !s ? null : k === "" ? s.total : (s as Record<string, number | string | null>)[k];
          return (
            <button key={k} className={`v3-scope-chip${state === k ? " on" : ""}`} onClick={() => (setState(k), setHq({ state: k }))}>
              {w}
              {typeof n === "number" ? ` ${n}` : ""}
            </button>
          );
        })}
        <span className="sp" />
        {s && <span className="v3-scope-k">{busy ? `出视频中 ${s.rendering} · 排队 ${s.queued}${s.eta_all ? ` · 全部预计 ${fmtEta(s.eta_all)} 出完` : ""}` : "现在没有视频在出"}</span>}
      </div>

      {err && !d && (
        <div className="vd-empty" role="alert">
          <b>视频状态读不到</b>
          {err}
          <br />
          <button className="v3-btn" onClick={load}>
            重试
          </button>
        </div>
      )}
      {!err && !d && <div className="vd-empty">正在读视频状态…</div>}
      {d && d.summary.total === 0 && (
        <div className="vd-empty">
          <b>{ep === "all" ? "还没有任何镜头" : `第 ${ep} 集还没有镜头`}</b>
          先到“剧本”导入分镜。
          <br />
          <a className="v3-btn" href="#/script-create">
            去剧本
          </a>
        </div>
      )}
      {d && d.summary.total > 0 && shown.length === 0 && (
        <div className="vd-empty">
          <b>
            {state === "pending_review" ? "现在没有要你看的视频" : `没有“${WORD[state] ?? state}”的镜头`}
            {busy ? `，正在出 ${s?.rendering ?? 0} 条${s?.eta_all ? `，预计 ${fmtEta(s.eta_all)}` : ""}` : ""}
          </b>
          共 {d.summary.total} 镜。
          <br />
          <button className="v3-btn" onClick={() => (setState(""), setHq({ state: "" }))}>
            看全部
          </button>
        </div>
      )}
      {shown.map((e) => {
        const all = d?.episodes.find((x) => x.ep === e.ep)?.shots ?? e.shots;
        const fin = all.filter((x) => x.state === "final").length;
        const run = all.filter((x) => x.state === "rendering").length;
        const last = all.filter((x) => x.eta).map((x) => x.eta as string).sort().pop();
        return (
          <section key={e.ep}>
            <div className="vd-eph">
              <b>第 {e.ep} 集</b>
              <span>
                {all.length} 镜 · 已定稿 {fin}
                {run ? ` · 出视频中 ${run}` : ""}
                {last ? ` · 预计 ${fmtEta(last)} 出完` : ""}
              </span>
              <a href={`#/videos?ep=${e.ep}`} style={{ marginLeft: "auto" }}>
                只看这一集
              </a>
            </div>
            <div className="vd-grid">
              {e.shots.map((r) => (
                <Cell key={r.id} r={r} ep={e.ep} onOpen={() => (setOpen(r.id), setHq({ shot: r.id }))} />
              ))}
            </div>
          </section>
        );
      })}
      {cur && <Drawer r={cur.s} ep={cur.ep} onClose={() => (setOpen(null), setHq({ shot: null }))} onChanged={load} next={playNext} />}
    </div>
  );
}
