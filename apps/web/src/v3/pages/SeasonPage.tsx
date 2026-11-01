// 全剧总览 #/overview（快捷键 1）——项目方 11-01：“之前更容易看到整部剧里每一个 episode、每一个镜头之间的关系……把它拉回来，也思考一下怎样做逻辑更好。”
// 旧版（归档 OverviewGrid）功能对照（K-UI-030）：
//   每集一行 · 每镜一格                     → 保留
//   格内首帧 + 尾帧缩略                       → 保留（首帧大一点；尾帧小图叠在右下）
//   状态链（首 / 尾 / 视频 / 审）色点         → 保留，改成 4 段条：首帧 · 尾帧 · 视频 · 通过（候选 = 蓝、过期 = 黄、失败 = 红、生成中 = 动）
//   任务中 / 失败 / 改过 / 本地（成人）角标   → 保留
//   集头：集号、标题、本集造型、审 x/n        → 保留，加首帧 / 视频进度
//   点格选中、Shift/Ctrl 多选、双击进本集     → 改成：点格直达这一镜的每镜一行（画布），Ctrl/Shift 点仍是多选
//   点集头选中整集                            → 保留（集头“选中整集”）
//   过滤变暗                                  → 保留（跟画布同一过滤）
// 新增（“逻辑更好”）：景别、场景色带（同场景连成一条）、镜间衔接符号（换场 ┃ / 同场换机位 ─ / 接力 ➜ + 承接什么）、
//   集与集之间的衔接（上一集末镜 → 本集首镜）、换装点、出场人物时间线（● 在画 · ◐ 局部 · ○ 画外）。状态随画布数据实时更新。
import { useEffect, useMemo, useState, type MouseEvent } from "react";
import { useStudio } from "../../store";
import { thumb } from "../../thumb";
import { matchFilter } from "../../util";
import { Empty, Skel, LoadError } from "../../ds";
import type { ShotSummary } from "../../types";
import "./season.css";
import { LiveProgress } from "../../ds/StageProgress";
import { Flash } from "../../ds/Flash";
import { useLiveEvent } from "../live";

type SShot = { id: string; index: number; size: string | null; scene_id: string | null; scene: string | null; link: string | null; carry: string | null; cast: { name: string; presence: string }[]; switch: string[]; seconds: number | null; adult: boolean; cand_url: string | null; cand_n: number };
type SEp = { number: number; title: string; scenes: string[]; shots: SShot[] };

function useSeason() {
  const [d, setD] = useState<SEp[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    let wait = 60000;
    fetch("/api/season")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status === 404 ? "starting" : `HTTP ${r.status}`))))
      .then(
        (x: { episodes: SEp[] }) => alive && (setD(x.episodes), setErr(null)),
        (e: Error) => {
          if (!alive) return;
          setErr(e.message);
          wait = 15000; // 接口还没启用 / 暂时读不到：15 秒后自动再试
        },
      );
    // 今晚首尾帧和视频陆续出来：候选图每 60 秒刷新一次（状态本身跟画布数据实时走）
    const t = window.setTimeout(() => setTick((n) => n + 1), wait);
    return () => {
      alive = false;
      window.clearTimeout(t);
    };
  }, [tick]);
  useLiveEvent((e) => e.type === "frame" || e.type === "lastframe" || e.type === "stage", () => setTick((n) => n + 1), 1500);
  return { d, err, retry: () => setTick((n) => n + 1) };
}

/** 场景 → 色带颜色（同一场景同一色；只用主题变量） */
const BANDS = ["var(--c-info)", "var(--c-ok)", "var(--c-warn)", "var(--c-accent)", "var(--c-busy)", "var(--c-stale)", "var(--c-adult)", "var(--c-bad)"];
const LINK_ICON: Record<string, [string, string]> = { 换场: ["┃", "换场"], 同场换机位: ["─", "同场换机位"], 接力: ["➜", "接力（上一镜的动作 / 视线直接接过来）"] };
const PRES: Record<string, [string, string]> = { 在画: ["●", "在画"], 局部: ["◐", "局部入画"], 画外: ["○", "画外（只有声音）"] };

type Seg = "none" | "cand" | "ok" | "stale" | "bad" | "busy";
function segs(s: ShotSummary | undefined, ss: SShot): [Seg, Seg, Seg, Seg] {
  if (!s) return ["none", "none", "none", "none"];
  const st = s.stale as Record<string, unknown[]> | undefined;
  const isStale = (k: string) => !!(st?.[k] && (st[k] as unknown[]).length);
  const busy = (k: string) => s.job != null && (s.job_stage === k || (!s.job_stage && k === "image"));
  const one = (have: boolean, k: string, cand = false): Seg => (busy(k) ? "busy" : (s.bad as Record<string, unknown> | undefined)?.[k] ? "bad" : have ? (isStale(k) ? "stale" : "ok") : cand ? "cand" : "none");
  return [
    one(!!s.first_frame, "image", ss.cand_n > 0),
    one(!!s.last_frame_target, "last"),
    one(!!s.video, "video"),
    s.review?.state === "passed" ? "ok" : s.review?.state === "rejected" ? "bad" : "none",
  ];
}

export default function SeasonPage() {
  const st = useStudio();
  const { d, err, retry } = useSeason();
  const [people, setPeople] = useState(true);
  const byId = useMemo(() => {
    const m = new Map<string, ShotSummary>();
    for (const e of st.episodes ?? []) for (const s of e.shots) m.set(s.id, s);
    return m;
  }, [st.episodes]);
  // 主要人物（全季出场镜数排序，前 5 位）做时间线
  const leads = useMemo(() => {
    const c = new Map<string, number>();
    for (const e of d ?? []) for (const s of e.shots) for (const x of s.cast) if (x.name) c.set(x.name, (c.get(x.name) ?? 0) + 1);
    return [...c.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([n]) => n);
  }, [d]);
  const bandOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const e of d ?? []) for (const s of e.shots) if (s.scene_id && !m.has(s.scene_id)) m.set(s.scene_id, BANDS[m.size % BANDS.length]);
    return m;
  }, [d]);
  if (err && !d)
    return (
      <div className="v3p-page">
        {err === "starting" ? (
          <Empty icon="▦" title="全剧总览正在启用，约 1 分钟" sub="不用操作，好了这里会自己出来（每 15 秒自动再试）。" />
        ) : (
          <LoadError what="全剧总览" err={err} retry={retry} />
        )}
      </div>
    );
  if (!d) return <div className="v3p-page"><Skel h={480} /></div>;
  const all = d.flatMap((e) => e.shots);
  const cnt = (f: (s: ShotSummary) => boolean) => all.filter((x) => { const s = byId.get(x.id); return s ? f(s) : false; }).length;
  const total = all.length;
  const go = (ev: MouseEvent, id: string) => {
    if (ev.shiftKey || ev.ctrlKey || ev.metaKey) return st.select(id, { shift: ev.shiftKey, ctrl: ev.ctrlKey || ev.metaKey });
    location.hash = `#${id}`; // 直达这一镜的每镜一行（画布）
  };
  return (
    <div className="v3p-page sea-page">
      <header className="v3p-head sea-head">
        <h1>全剧总览</h1>
        <span className="v3p-muted">
          {d.length} 集 · {total} 镜 · 首帧 {cnt((s) => !!s.first_frame)}/{total} · 尾帧 {cnt((s) => !!s.last_frame_target)}/{total} · 视频 {cnt((s) => !!s.video)}/{total} · 通过 {cnt((s) => s.review?.state === "passed")}/{total}
          {all.some((x) => x.cand_n > 0) ? ` · 有候选待挑 ${all.filter((x) => x.cand_n > 0 && !byId.get(x.id)?.first_frame).length}` : ""}
        </span>
        <span className="grow" />
        <label className="sea-tog">
          <input type="checkbox" checked={people} onChange={(e) => setPeople(e.target.checked)} /> 人物时间线
        </label>
      </header>
      <LiveProgress run={null} title="全剧进度" />
      <div className="sea-legend" aria-label="图例">
        <span><i className="sea-seg s-ok" />有了</span>
        <span><i className="sea-seg s-cand" />有候选待挑</span>
        <span><i className="sea-seg s-busy" />生成中</span>
        <span><i className="sea-seg s-stale" />过期</span>
        <span><i className="sea-seg s-bad" />坏图 / 打回</span>
        <span className="sea-lg-sep">每格下方四段：首帧 · 尾帧 · 视频 · 通过</span>
        <span>┃ 换场</span>
        <span>─ 同场换机位</span>
        <span>➜ 接力</span>
        <span>● 在画 ◐ 局部 ○ 画外{people && leads.length ? `（每格最下一行依次是：${leads.join(" · ")}）` : ""}</span>
        <span className="sea-sw">换装</span>
      </div>
      <div className="sea-grid">
        {d.map((e, ei) => {
          const prev = ei > 0 ? d[ei - 1] : null;
          const first = e.shots[0];
          const lastPrev = prev?.shots[prev.shots.length - 1];
          const sums = e.shots.map((x) => byId.get(x.id));
          const nFF = sums.filter((s) => s?.first_frame).length;
          const nV = sums.filter((s) => s?.video).length;
          const nP = sums.filter((s) => s?.review?.state === "passed").length;
          const secs = e.shots.reduce((a, s) => a + (s.seconds ?? 0), 0);
          const cur = st.epNum === e.number;
          return (
            <section key={e.number} className={`sea-ep${cur ? " cur" : ""}`} aria-label={`第 ${e.number} 集`}>
              <div className="sea-eph">
                <a href={`#ep${String(e.number).padStart(2, "0")}`} className="sea-epn" title="打开这一集（画布）">
                  第 {e.number} 集
                </a>
                <b className="sea-ept" title={e.title}>{e.title}</b>
                <span className="sea-epm">{e.shots.length} 镜 · {Math.round(secs)} 秒</span>
                <span className="sea-epm">首帧 {nFF}/{e.shots.length} · 视频 {nV} · 过 {nP}</span>
                <span className="sea-epm sea-scn" title={e.scenes.join("、")}>{e.scenes.join(" · ")}</span>
                {lastPrev && first && (
                  <span className="sea-epm sea-xep" title={`上一集末镜 S${lastPrev.index}（${lastPrev.scene ?? "?"}）→ 本集 S1（${first.scene ?? "?"}）：${first.link ?? "未写"}${first.carry ? `，承接 ${first.carry}` : ""}`}>
                    承上集：{first.scene_id && first.scene_id === lastPrev.scene_id ? "同场景" : "换场"}
                  </span>
                )}
                <span className="sea-epbar"><LiveProgress run={null} episode={e.number} compact /></span>
                <button type="button" className="v3p-link sea-selall" onClick={() => st.setMulti(new Set(e.shots.map((s) => s.id)))} title="选中整集（之后可在画布批量出图 / 审片）">
                  选中整集
                </button>
              </div>
              <ol className="sea-row">
                {e.shots.map((x, i) => {
                  const s = byId.get(x.id);
                  const sg = segs(s, x);
                  const img = s?.first_frame ?? x.cand_url;
                  const lk = x.link ? LINK_ICON[x.link] : null;
                  const sameScene = i > 0 && e.shots[i - 1].scene_id === x.scene_id;
                  const dim = s ? !matchFilter(st.filter, s, st.latest.get(s.id)) : false;
                  return (
                    <Flash as="li" key={x.id} value={[img, sg, x.cand_n]} className={`sea-cell${st.sel === x.id ? " sel" : ""}${st.multi.has(x.id) ? " multi" : ""}${dim ? " dim" : ""}`}>
                      {i > 0 && (
                        <span className={`sea-link${lk ? "" : " none"}${sameScene ? "" : " cut"}`} title={`${x.link ? (lk?.[1] ?? x.link) : "衔接没写"}${x.carry ? `：承接 ${x.carry}` : ""}`}>
                          {lk?.[0] ?? (sameScene ? "─" : "┃")}
                        </span>
                      )}
                      <button type="button" className="sea-card" onClick={(ev) => go(ev, x.id)} title={`${x.id} · ${x.size ?? ""} · ${x.scene ?? ""} · ${x.seconds ?? "?"} 秒\n${s?.img_summary ?? ""}\n点：打开这一镜（每镜一行）；Ctrl / Shift 点：多选`}>
                        <span className="sea-band" style={{ background: x.scene_id ? bandOf.get(x.scene_id) : undefined }} title={x.scene ?? "场景未标"} />
                        <span className={`sea-pic${img ? "" : " none"}`} data-zoom-label={`${x.id.split("-")[1]} · ${s?.first_frame ? `首帧 #${s.first_frame_take ?? "?"}` : x.cand_n ? "首帧候选" : "首帧"}`}>
                          {img ? <img key={img} className="live-img" src={thumb(img, 120) ?? img} alt="" loading="lazy" decoding="async" draggable={false} /> : <span>未出</span>}
                          {s?.last_frame_target && <img className="sea-last" src={thumb(s.last_frame_target, 120) ?? s.last_frame_target} alt="" loading="lazy" />}
                          <b className="sea-no">S{x.index}</b>
                          {!s?.first_frame && x.cand_n > 0 && <span className="sea-cand" title={`有 ${x.cand_n} 张合格的首帧候选，还没选定用哪张`}>{x.cand_n} 张候选</span>}
                          {s?.job && <span className="sea-busy">生成中</span>}
                          {x.adult && <span className="sea-adult" title="成人镜头：只在本机生成">本地</span>}
                        </span>
                        <span className="sea-segs" aria-label="首帧 · 尾帧 · 视频 · 通过">
                          {sg.map((g, k) => (
                            <i key={k} className={`sea-seg s-${g}`} />
                          ))}
                        </span>
                        <span className="sea-meta">
                          {x.size ?? "—"}
                          {x.seconds ? ` · ${x.seconds}s` : ""}
                        </span>
                        {x.switch.length > 0 && <span className="sea-sw" title={`从这一镜起换装：${x.switch.join("、")}`}>换装 {x.switch.join("、")}</span>}
                        {people && (
                          <span className="sea-cast">
                            {leads.map((n) => {
                              const c = x.cast.find((y) => y.name === n);
                              const p = c ? PRES[c.presence] ?? ["●", c.presence] : null;
                              return (
                                <i key={n} className={p ? "on" : ""} title={p ? `${n}：${p[1]}` : `${n}：不在这一镜`}>
                                  {p ? p[0] : "·"}
                                </i>
                              );
                            })}
                          </span>
                        )}
                      </button>
                    </Flash>
                  );
                })}
              </ol>
            </section>
          );
        })}
      </div>
    </div>
  );
}
