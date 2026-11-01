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
import { MainTag, TagCounts, TagLegend } from "../StatusTags";
import { countKinds, hasKind, tagsTitle, type ShotStatusTags, type TagKind } from "../StatusTags.helpers";

type SShot = { id: string; index: number; size: string | null; scene_id: string | null; scene: string | null; link: string | null; carry: string | null; cast: { name: string; presence: string }[]; switch: string[]; seconds: number | null; adult: boolean; cand_url: string | null; cand_n: number; old_script_n?: number; first_old?: boolean; last_old?: boolean; status?: ShotStatusTags };
/** UIRSI r40：板块状态（后端 ns_api/shot_status.episode_blocks；口径同镜头格标签） */
type BlockState = "stale" | "doing" | "done" | "todo";
type SBlocks = { state: BlockState; text: string; stages: { key: string; label: string; state: BlockState; counts: Record<BlockState, number>; text: string }[] };
type SEp = { number: number; title: string; scenes: string[]; shots: SShot[]; blocks?: SBlocks | null };
const BLOCK_WORD: Record<BlockState, string> = { stale: "过期", doing: "进行中", done: "已确认", todo: "未开始" };

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
    one(!!s.first_frame && !ss.first_old, "image", ss.cand_n > 0),
    one(!!s.last_frame_target && !ss.last_old, "last"), // UIRSI r40：旧剧本出的当前版本不算“有”
    one(!!s.video, "video"),
    s.review?.state === "passed" ? "ok" : s.review?.state === "rejected" ? "bad" : "none",
  ];
}

export default function SeasonPage() {
  const st = useStudio();
  const { d, err, retry } = useSeason();
  const [people, setPeople] = useState(true);
  // UIRSI r40：按状态筛（ep = null 表示全剧，数字 = 只筛这一集）
  const [tagF, setTagF] = useState<{ ep: number | null; k: TagKind } | null>(null);
  // UIRSI r40（项目方 00:3x：“哪个板块已经确认,哪个板块正在进行中,哪个板块是过期的”）：只看过期 / 进行中的集
  const [blockF, setBlockF] = useState<BlockState | null>(null);
  // UIRSI r41（项目方 00:5x：“现在 UI/UX 的设计有点丑,数据有点太多了”）：默认简洁——每镜一张大图 + 状态色 + 镜号 + 一个状态词；
  // 景别 / 时长 / 候选数 / 四段进度 / 人物时间线 / 各色数量收进“显示细节”（记住选择）和每集的“细节 ▸”
  const [detail, setDetailRaw] = useState<boolean>(() => {
    try {
      return localStorage.getItem("sea.detail") === "1";
    } catch {
      return false;
    }
  });
  const setDetail = (v: boolean) => {
    setDetailRaw(v);
    try {
      localStorage.setItem("sea.detail", v ? "1" : "0");
    } catch {
      /* 存不了就只在这次有效 */
    }
  };
  const [openEp, setOpenEp] = useState<Set<number>>(new Set());
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
    <div className={`v3p-page sea-page${detail ? "" : " simple"}`}>
      <header className="v3p-head sea-head">
        <h1>全剧总览</h1>
        <span className="v3p-muted">
          {d.length} 集 · {total} 镜 · 首帧 {cnt((s) => !!s.first_frame)}/{total} · 尾帧 {cnt((s) => !!s.last_frame_target)}/{total} · 视频 {cnt((s) => !!s.video)}/{total} · 通过 {cnt((s) => s.review?.state === "passed")}/{total}
          {all.some((x) => x.cand_n > 0) ? ` · 有候选待挑 ${all.filter((x) => x.cand_n > 0 && !byId.get(x.id)?.first_frame).length}` : ""}
        </span>
        <span className="grow" />
        <label className="sea-tog" title="每镜的景别 · 时长 · 候选数 · 四段进度 · 人物时间线 · 换装 · 各色数量 · 各阶段">
          <input type="checkbox" checked={detail} onChange={(e) => setDetail(e.target.checked)} /> 显示细节
        </label>
        {detail && (
          <label className="sea-tog">
            <input type="checkbox" checked={people} onChange={(e) => setPeople(e.target.checked)} /> 人物时间线
          </label>
        )}
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
      {/* UIRSI r40（项目方：“哪些是重置的,过期的,就给它用不同的颜色 label 一下”）：每格左下角一个彩色主标签（最严重的那个，悬停看全部）；点颜色只看这类 */}
      {d && (
        <div className="sea-legend blk-bar" role="group" aria-label="板块状态筛选">
          <span className="blk-lg-t">板块</span>
          {(["stale", "doing", "done", "todo"] as BlockState[]).map((k) => {
            const n = d.filter((e) => e.blocks?.state === k).length;
            return (
              <button key={k} type="button" className={`blk-chip b-${k}${blockF === k ? " on" : ""}`} onClick={() => setBlockF(blockF === k ? null : k)} aria-pressed={blockF === k}
                title={`${BLOCK_WORD[k]}：${k === "stale" ? "剧本或作业变了、旧剧本版本，需要重出" : k === "doing" ? "有在出、排队、待补判的" : k === "done" ? "全部通过、已设为当前 / 已定稿" : "还没开始"}；点一下只看这 ${n} 集，再点取消`}>
                {BLOCK_WORD[k]} <em>{n} 集</em>
              </button>
            );
          })}
        </div>
      )}
      {d && (
        <div className="sea-legend">
          <TagLegend counts={countKinds(d.flatMap((e) => e.shots.map((x) => x.status)))} on={tagF?.ep == null ? tagF?.k ?? null : null} onPick={(k) => setTagF(k ? { ep: null, k } : null)} />
        </div>
      )}
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
            <section key={e.number} className={`sea-ep${cur ? " cur" : ""}${e.blocks ? ` blk b-${e.blocks.state}` : ""}${openEp.has(e.number) ? " open" : ""}`} aria-label={`第 ${e.number} 集`} hidden={!!blockF && e.blocks?.state !== blockF}>
              <div className="sea-eph">
                {e.blocks && (
                  <span className={`blk-badge b-${e.blocks.state}`} title={e.blocks.text}>
                    {BLOCK_WORD[e.blocks.state]}
                  </span>
                )}
                <a href={`#ep${String(e.number).padStart(2, "0")}`} className="sea-epn" title="打开这一集（画布）">
                  第 {e.number} 集
                </a>
                <b className="sea-ept" title={e.title}>{e.title}</b>
                <span className="sea-epm">{e.shots.length} 镜 · {Math.round(secs)} 秒</span>
                <span className="sea-epm sea-prog" title={`首帧 ${nFF}/${e.shots.length} · 视频 ${nV} · 通过 ${nP}`}>
                  {detail ? `首帧 ${nFF}/${e.shots.length} · 视频 ${nV} · 过 ${nP}` : nV ? `视频 ${nV}/${e.shots.length}` : `首帧 ${nFF}/${e.shots.length}`}
                </span>
                {!detail && (
                  <button type="button" className="sea-more" aria-expanded={openEp.has(e.number)} onClick={() => setOpenEp((o) => { const n = new Set(o); if (n.has(e.number)) n.delete(e.number); else n.add(e.number); return n; })}
                    title="展开本集的各色数量、各阶段、场景、进度条">
                    细节 {openEp.has(e.number) ? "▾" : "▸"}
                  </button>
                )}
                <TagCounts counts={countKinds(e.shots.map((x) => x.status))} on={tagF?.ep === e.number ? tagF.k : null} onPick={(k) => setTagF(k ? { ep: e.number, k } : null)} />
                <span className="sea-epm sea-scn" title={e.scenes.join("、")}>{e.scenes.join(" · ")}</span>
                {lastPrev && first && (
                  <span className="sea-epm sea-xep" title={`上一集末镜 S${lastPrev.index}（${lastPrev.scene ?? "?"}）→ 本集 S1（${first.scene ?? "?"}）：${first.link ?? "未写"}${first.carry ? `，承接 ${first.carry}` : ""}`}>
                    承上集：{first.scene_id && first.scene_id === lastPrev.scene_id ? "同场景" : "换场"}
                  </span>
                )}
                {e.blocks && (
                  <span className="blk-stages" aria-label="各阶段状态">
                    {e.blocks.stages.map((g) => (
                      <span key={g.key} className={`blk-stage b-${g.state}`} title={g.text}>
                        {g.label}
                      </span>
                    ))}
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
                  // UIRSI r40：当前版本是旧剧本出的 → 不显示（剧本 23:21 重导后镜头重新编号，旧图对不上新镜头）
                  const img = (x.first_old ? null : s?.first_frame) ?? x.cand_url;
                  const lastImg = x.last_old ? null : s?.last_frame_target;
                  const lk = x.link ? LINK_ICON[x.link] : null;
                  const sameScene = i > 0 && e.shots[i - 1].scene_id === x.scene_id;
                  const dim = s ? !matchFilter(st.filter, s, st.latest.get(s.id)) : false;
                  const tagDim = !!tagF && (tagF.ep == null || tagF.ep === e.number) && !hasKind(x.status, tagF.k);
                  return (
                    <Flash as="li" key={x.id} value={[img, sg, x.cand_n]} className={`sea-cell${st.sel === x.id ? " sel" : ""}${st.multi.has(x.id) ? " multi" : ""}${dim ? " dim" : ""}${tagDim ? " stag-dim" : ""}`}>
                      {i > 0 && (
                        <span className={`sea-link${lk ? "" : " none"}${sameScene ? "" : " cut"}`} title={`${x.link ? (lk?.[1] ?? x.link) : "衔接没写"}${x.carry ? `：承接 ${x.carry}` : ""}`}>
                          {lk?.[0] ?? (sameScene ? "─" : "┃")}
                        </span>
                      )}
                      <button type="button" className={`sea-card k-${x.status?.main ?? "none"}`} onClick={(ev) => go(ev, x.id)} title={`${x.id} · ${x.size ?? ""} · ${x.scene ?? ""} · ${x.seconds ?? "?"} 秒${x.cand_n ? ` · ${x.cand_n} 张候选` : ""}${x.adult ? " · 成人镜头（只在本机生成）" : ""}\n${tagsTitle(x.status)}\n${s?.img_summary ?? ""}\n点：打开这一镜（每镜一行）；Ctrl / Shift 点：多选`}>
                        <span className="sea-band" style={{ background: x.scene_id ? bandOf.get(x.scene_id) : undefined }} title={x.scene ?? "场景未标"} />
                        <span className={`sea-pic${img ? "" : " none"}`} data-zoom-label={`${x.id.split("-")[1]} · ${s?.first_frame ? `首帧 #${s.first_frame_take ?? "?"}` : x.cand_n ? "首帧候选" : "首帧"}`}>
                          {img ? <img key={img} className="live-img" src={thumb(img, 120) ?? img} alt="" loading="lazy" decoding="async" draggable={false} /> : <span title={x.old_script_n ? `有 ${x.old_script_n} 张是剧本更新前出的旧图，不再作候选（在这一镜的“旧图”里能看）` : undefined}>{x.old_script_n || x.first_old ? <>未出<br />（剧本已更新）</> : "未出"}</span>}
                          {lastImg && <img className="sea-last" src={thumb(lastImg, 120) ?? lastImg} alt="" loading="lazy" />}
                          <b className="sea-no">S{x.index}</b>
                          <MainTag st={x.status} size="xs" />
                          {(!s?.first_frame || x.first_old) && x.cand_n > 0 && <span className="sea-cand" title={`有 ${x.cand_n} 张合格的首帧候选，还没选定用哪张`}>{x.cand_n} 张候选</span>}
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
