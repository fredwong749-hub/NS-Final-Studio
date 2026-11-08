// UIUX-LOOP r3（11-06）：每集进度 / KPI 面板（全剧总览顶部）。L-205：一集 ≤ 50 分钟；L-207：一集三段 首尾帧 → 全部显卡出视频 → 合成。
// 每集一行：阶段 · 用时 / 预算（超了写超多少）· 首 / 尾 / 视频计数 · 每镜一张小图（首帧大、尾帧叠右下、视频一个点）。
// 状态全部来自 GET /api/episodes/kpi（活的 producer 登记表 + brain 快照 KPI + 每镜 takes.json 当前版），前端不猜；只给看通过的图。
// UIUX-LOOP-3 r12：每集一个“最新成片”入口（后端 cuts.latest_film：data/episodes/<run>/epNN_vN.mp4 最新一版 + 合成闸门结论，标签诚实：
// 预览版（闸门没过：缺 N 镜用占位）/ 成片（闸门通过））；“首尾对照”开关把每镜换成 首帧 | 尾帧 并排大图（L-203：首尾帧要一起看）。
import { fetchOverview, toKpi } from "./ns2";
import { useCallback, useEffect, useState } from "react";
import { thumb } from "../thumb";
import { useStudio } from "../store";
import { useLiveEvent } from "./live";
import "./kpi.css";

type CellState = "passed" | "ready" | "running" | "pending" | "failed" | "best_effort" | "fallback" | "na";
type Cell = { state: CellState; url: string | null; fallback?: { word: string; why: string } | null };
type Shot = { id: string; index: number; first: Cell; last: Cell; video: Cell };
export type Film = {
  name: string; version: number | null; url: string; at: string; duration_s: number | null;
  video_shots: number | null; placeholder_shots: number | null;
  kind: "preview" | "final" | "unknown"; kind_word: string; word: string; missing_n: number; missing: string[]; post: boolean;
};
type Ep = {
  ep: number; title: string; total: number; phase: string; phase_word: string;
  state: "assembled" | "in_budget" | "over_budget" | "not_started";
  start: string | null; elapsed_min: number | null; eta_min: number | null; over_min: number | null;
  /** L-212 #9：起点 = max(首次派单, 最近导入)（和大脑同一函数）；clock_from=import = 重新导入后从导入时刻重新计时 */
  import_at?: string | null; start_before_import?: boolean; clock_from?: "dispatch" | "import" | null;
  first_done: number; last_done: number; fallback_n: number; video_done: number; assembled: boolean; shots: Shot[];
  /** r12：最新一版整集成片（没有 = null） */
  film?: Film | null;
};
type Kpi = { run: string; at: string; budget_min: number; source: { kpi: string; snapshot_age_s: number | null; registry_age_s: number | null }; episodes: Ep[] };

const WORD: Record<CellState, string> = { passed: "已定下", ready: "排队", running: "在出", pending: "等上一步", failed: "没出来", best_effort: "尽力版", fallback: "不用尾帧", na: "—" };
const fmtMin = (m: number | null) => (m == null ? "—" : m >= 120 ? `${(m / 60).toFixed(1)} 小时` : `${Math.round(m)} 分钟`);
const age = (s: number | null) => (s == null ? "" : s < 90 ? `${s} 秒前` : `${Math.round(s / 60)} 分钟前`);

export function useEpisodeKpi() {
  const [d, setD] = useState<Kpi | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    fetchOverview()   // P5 M2：改读新 ns2 唯一总览（v3/ns2.ts toKpi）
      .then((o) => toKpi(o) as unknown as Kpi)
      .then((x) => (setD(x), setErr(null)))
      .catch((e: Error) => setErr(e.message));
  }, []);
  useEffect(() => {
    load();
    const t = window.setInterval(load, 15000);   // PLAN §2.4：轮询统一 15 秒
    return () => window.clearInterval(t);
  }, [load]);
  useLiveEvent((e) => e.type === "frame" || e.type === "lastframe" || e.type === "stage" || e.type === "video", load, 2000);
  return { d, err, load };
}

function Budget({ e, budget }: { e: Ep; budget: number }) {
  if (e.state === "not_started") return <span className="kpi-bud muted">还没开始</span>;
  const pct = e.elapsed_min == null ? 0 : Math.min(100, (e.elapsed_min / budget) * 100);
  const over = e.state === "over_budget";
  return (
    <span className={`kpi-bud s-${e.state}`} title={`起点 ${e.start ?? "未知"}（JST，${e.clock_from === "import" ? "本版剧本导入时刻" : "两台里最早派单"}）· 预算 ${budget} 分钟（L-205）${e.eta_min != null ? ` · 按已定视频比例外推还要 ${fmtMin(e.eta_min)}` : ""}`}>
      <i className="kpi-bar"><b style={{ width: `${pct}%` }} /></i>
      <span>
        {e.state === "assembled" ? `用时 ${fmtMin(e.elapsed_min)} · 已合成` : over ? `用时 ${fmtMin(e.elapsed_min)} · 超预算 ${fmtMin(e.over_min)}` : `用时 ${fmtMin(e.elapsed_min)} / ${budget} 分钟`}
        {e.clock_from === "import" ? <small className="kpi-note">（从本版剧本导入算起）</small> : null}
      </span>
    </span>
  );
}

function ShotTile({ s, ep }: { s: Shot; ep: number }) {
  const f = s.first.url ? thumb(s.first.url, 120) ?? s.first.url : null;
  const l = s.last.url ? thumb(s.last.url, 120) ?? s.last.url : null;
  const tip = `${s.id}\n首帧：${WORD[s.first.state]}\n尾帧：${s.last.state === "fallback" ? `不用尾帧（${s.last.fallback?.word ?? ""}）` : WORD[s.last.state]}\n视频：${WORD[s.video.state]}${s.video.state === "passed" && !s.video.url ? "（定下了，片子还没拉到本机）" : ""}\n点开：这一镜的画布`;
  return (
    <a className="kpi-shot" href={`#${s.id}`} title={tip} data-ep={ep}>
      <span className={`kpi-pic s-${s.first.state}`}>
        {f ? <img src={f} alt="" loading="lazy" decoding="async" /> : <span className="kpi-nopic">{s.first.state === "running" ? "在出" : s.first.state === "ready" ? "排队" : "首帧"}</span>}
        {l ? <img className="kpi-last" src={l} alt="" loading="lazy" /> : s.last.state === "fallback" ? <i className="kpi-last fb" title="不用尾帧">—</i> : null}
        <b className="kpi-no">S{s.index}</b>
      </span>
      <span className="kpi-dots" aria-label="首帧 · 尾帧 · 视频">
        <i className={`d s-${s.first.state}`} />
        <i className={`d s-${s.last.state}`} />
        <i className={`d s-${s.video.state}${s.video.state === "running" ? " is-rendering" : ""}`} />
      </span>
    </a>
  );
}

/** r12：首帧 | 尾帧 并排大图（L-203 项目方要把首尾帧放一起判断衔接）；只显示通过的版本，点开进画布，没有任何接受 / 驳回按钮 */
function PairTile({ s }: { s: Shot }) {
  const f = s.first.url ? thumb(s.first.url, 240) ?? s.first.url : null;
  const l = s.last.url ? thumb(s.last.url, 240) ?? s.last.url : null;
  const lastWord = s.last.state === "fallback" ? `不用尾帧（${s.last.fallback?.word ?? "运镜交给视频模型"}）` : WORD[s.last.state];
  return (
    <a className="kpi-pair" href={`#${s.id}`} title={`${s.id}\n首帧：${WORD[s.first.state]}\n尾帧：${lastWord}\n视频：${WORD[s.video.state]}\n点开：这一镜的画布`}>
      <span className="kpi-pair-no">S{s.index}</span>
      <span className={`kpi-pair-pic s-${s.first.state}`}>{f ? <img src={f} alt="" loading="lazy" decoding="async" /> : <span className="kpi-nopic">{WORD[s.first.state]}</span>}<small>首</small></span>
      <span className={`kpi-pair-pic s-${s.last.state}`}>{l ? <img src={l} alt="" loading="lazy" decoding="async" /> : <span className="kpi-nopic">{s.last.state === "fallback" ? "不用尾帧" : WORD[s.last.state]}</span>}<small>尾</small></span>
      <i className={`d s-${s.video.state}${s.video.state === "running" ? " is-rendering" : ""}`} title={`视频：${WORD[s.video.state]}`} />
    </a>
  );
}

const fmtSec = (s: number | null | undefined) => (s == null ? "" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);

/** r12：每集“最新成片”——写明是预览版还是成片、合成闸门结论、几镜占位；点开成片页（本集），“播放”直接开文件 */
function FilmLink({ ep, film, onOpen }: { ep: number; film: Film | null | undefined; onOpen: (ep: number) => void }) {
  if (!film) return <span className="kpi-film none" title="这一集还没有合成过整集">最新成片：还没有</span>;
  const tip = `${film.name} · ${film.at.replace("T", " ")} JST\n${film.kind_word} · ${film.word}${film.missing.length ? `（${film.missing.join("、")}）` : ""}${film.post ? "\n已调色 / 加音效" : ""}\n真视频 ${film.video_shots ?? 0} 镜 · 占位 ${film.placeholder_shots ?? 0} 镜 · ${fmtSec(film.duration_s)}\n点开：成片页（本集全部版本、两版对比）`;
  return (
    <span className={`kpi-film k-${film.kind}`} title={tip}>
      <a href="#/cut" onClick={(ev) => { ev.preventDefault(); onOpen(ep); }}>
        最新成片 {film.version != null ? `v${film.version}` : film.name} · {film.kind_word}
      </a>
      <small className={film.kind === "final" ? "ok" : film.kind === "unknown" ? "muted" : "warn"}>{film.word}</small>
      <small className="muted">{film.at.slice(5, 16).replace("T", " ")}</small>
      <a href={film.url} target="_blank" rel="noreferrer" title="直接播放这个文件（新开一页）">播放</a>
    </span>
  );
}

/** 全剧总览顶部的每集进度 / KPI 面板（可折叠，记住选择） */
export function EpisodeKpiPanel() {
  const { d, err, load } = useEpisodeKpi();
  const st = useStudio();
  const openCut = (ep: number) => {
    st.gotoEpisode(ep);
    location.hash = "#/cut";
  };
  const [pairs, setPairs] = useState<Record<number, boolean>>(() => {
    try {
      return JSON.parse(localStorage.getItem("kpi.pairs") || "{}") as Record<number, boolean>;
    } catch {
      return {};
    }
  });
  const togglePair = (ep: number) => {
    const next = { ...pairs, [ep]: !pairs[ep] };
    setPairs(next);
    try {
      localStorage.setItem("kpi.pairs", JSON.stringify(next));
    } catch {
      /* 存不了就只在这次有效 */
    }
  };
  const [open, setOpen] = useState<boolean>(() => {
    try {
      return localStorage.getItem("kpi.open") !== "0";
    } catch {
      return true;
    }
  });
  const toggle = () => {
    setOpen(!open);
    try {
      localStorage.setItem("kpi.open", open ? "0" : "1");
    } catch {
      /* 存不了就只在这次有效 */
    }
  };
  const live = d?.episodes.filter((e) => e.state !== "not_started") ?? [];
  return (
    <section className="kpi" aria-label="每集进度">
      <header className="kpi-h">
        <button type="button" className="kpi-tg" onClick={toggle} aria-expanded={open}>
          {open ? "▾" : "▸"} 每集进度
        </button>
        <span className="kpi-sub">
          {d ? `一集预算 ${d.budget_min} 分钟 · 三段：出首尾帧 → 全部显卡出视频 → 合成` : err ? `读不到（${err}）` : "正在读…"}
        </span>
        <span className="grow" />
        {d && (
          <small className="kpi-src" title={`登记表 ${age(d.source.registry_age_s) || "未知"}同步；KPI 计时来自${d.source.kpi === "brain" ? `大脑快照（${age(d.source.snapshot_age_s)}）` : "本机日志（只有一台的起点）"}`}>
            {d.at.slice(11, 16)} JST{d.source.kpi !== "brain" ? " · 计时只有一台" : ""}
          </small>
        )}
        {err && d ? <button type="button" className="v3p-link" onClick={load}>再试</button> : null}
      </header>
      {open && d && !live.length && <p className="kpi-empty">还没有哪一集开始出图。</p>}
      {open &&
        d &&
        live.map((e) => (
          <div key={e.ep} className={`kpi-ep ph-${e.phase}`}>
            <div className="kpi-row">
              <a className="kpi-epn" href={`#ep${String(e.ep).padStart(2, "0")}`} title="打开这一集（画布）">第 {e.ep} 集</a>
              <b className="kpi-title">{e.title}</b>
              <span className={`kpi-phase ph-${e.phase}`} title="L-207：一集严格三段，首尾帧全部定下后 6 张卡一起出视频">{e.phase_word}</span>
              <Budget e={e} budget={d.budget_min} />
              <span className="kpi-cnt" title={`首帧已定 ${e.first_done}/${e.total} · 尾帧已定 ${e.last_done}/${e.total}${e.fallback_n ? `（另 ${e.fallback_n} 镜不用尾帧）` : ""} · 视频已定 ${e.video_done}/${e.total}`}>
                首 {e.first_done}/{e.total} · 尾 {e.last_done + e.fallback_n}/{e.total}{e.fallback_n ? <small>（{e.fallback_n} 镜不用尾帧）</small> : null} · 视频 {e.video_done}/{e.total}
              </span>
              <FilmLink ep={e.ep} film={e.film} onOpen={openCut} />
              <span className="grow" />
              <button type="button" className={`v3p-link kpi-pairtg${pairs[e.ep] ? " on" : ""}`} onClick={() => togglePair(e.ep)} aria-pressed={!!pairs[e.ep]} title="每镜 首帧 | 尾帧 并排放大，一起看衔接">
                {pairs[e.ep] ? "收起首尾对照" : "首尾对照"}
              </button>
              <a className="v3p-link" href={`#/frames?ep=${e.ep}`}>出图</a>
              <a className="v3p-link" href={`#/videos?ep=${e.ep}`}>视频</a>
            </div>
            {pairs[e.ep] ? (
              <div className="kpi-pairs" aria-label="首尾帧对照">
                {e.shots.map((s) => (
                  <PairTile key={s.id} s={s} />
                ))}
              </div>
            ) : (
              <div className="kpi-strip">
                {e.shots.map((s) => (
                  <ShotTile key={s.id} s={s} ep={e.ep} />
                ))}
              </div>
            )}
          </div>
        ))}
      {open && (
        <p className="kpi-legend" aria-hidden>
          <span><i className="d s-passed" />已定下</span>
          <span><i className="d s-running is-rendering" />在出</span>
          <span><i className="d s-ready" />排队</span>
          <span><i className="d s-best_effort" />尽力版</span>
          <span><i className="d s-fallback" />不用尾帧</span>
          <span><i className="d s-failed" />没出来</span>
          <span className="muted">每镜三个点：首帧 · 尾帧 · 视频；小图只显示通过的版本</span>
        </p>
      )}
    </section>
  );
}
