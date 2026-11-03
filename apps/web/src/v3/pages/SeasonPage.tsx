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
import { breatheDelay } from "../status";
import { SeasonDrawer } from "./SeasonPeek";
import { FilmOverview } from "./FilmOverview";
import { filmOn } from "../uiStyle";
import { dotOf, statusWord, DOT_TITLE, type MainStatus } from "./seasonDot";
import { Pop } from "../widgets";
import { countKinds, hasKind, tagsTitle, type ShotStatusTags, type TagKind } from "../StatusTags.helpers";
import { NowPanel, PipelineMatrix } from "../PipelineMatrix"; // NAVFLOW-F L-146：各集进度矩阵；W5：首页“现在”四问

type SShot = { id: string; index: number; size: string | null; scene_id: string | null; scene: string | null; link: string | null; carry: string | null; cast: { name: string; presence: string }[]; switch: string[]; seconds: number | null; adult: boolean; img?: string; lens?: string | null; lens_actual?: string | null; lens_plan?: string | null; camera_move?: string | null; lighting_sources?: string[]; lighting_name?: string | null; video?: string | null; video_old?: string | null; cand_url: string | null; cand_n: number; old_script_n?: number; first_old?: boolean; last_old?: boolean; status?: ShotStatusTags };
/** UIRSI r40：板块状态（后端 ns_api/shot_status.episode_blocks；口径同镜头格标签） */
type BlockState = "stale" | "doing" | "done" | "todo";
type SBlocks = { state: BlockState; text: string; stages: { key: string; label: string; state: BlockState; counts: Record<BlockState, number>; text: string }[] };
type SEp = { number: number; title: string; scenes: string[]; shots: SShot[]; blocks?: SBlocks | null };
const BLOCK_WORD: Record<BlockState, string> = { stale: "过期", doing: "进行中", done: "已确认", todo: "未开始" };

function useSeason() {
  const [d, setD] = useState<SEp[] | null>(null);
  const [faces, setFaces] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    let wait = 60000;
    fetch("/api/season")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status === 404 ? "starting" : `HTTP ${r.status}`))))
      .then(
        (x: { episodes: SEp[]; faces?: Record<string, string> }) => alive && (setD(x.episodes), setFaces(x.faces ?? {}), setErr(null)),
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
  return { d, faces, err, retry: () => setTick((n) => n + 1) };
}

/** r43（总调度 02:2x §二）：全剧总进度——一行灰字“剧本 10/10 · 首帧 2/102 · 尾帧 0/102 · 视频 0/102 · 成片 0/10”+ 一条细的单色总进度线。
 *  数据同原 7 段条：GET /api/progress（ns_api/live.py），各集同名段 done / total 相加；实时事件来了重取。总进度 = 五段 done 之和 / total 之和。 */
type PSeg = { done: number; total: number };
type PData = { order: string[]; labels: Record<string, string>; episodes: { segs: Record<string, PSeg> }[] };
const TOT_KEYS = ["script", "first", "last", "video", "cut"];
function useTotals(): PData | null {
  const [p, setP] = useState<PData | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    fetch("/api/progress")
      .then((r) => (r.ok ? (r.json() as Promise<PData>) : null))
      .then((x) => alive && x && setP(x), () => {});
    return () => {
      alive = false;
    };
  }, [tick]);
  useLiveEvent((e) => e.type === "frame" || e.type === "lastframe" || e.type === "stage", () => setTick((n) => n + 1), 3000);
  return p;
}
function Totals({ p }: { p: PData | null }) {
  const sum = (k: string) => (p?.episodes ?? []).reduce((a, e) => ({ done: a.done + (e.segs[k]?.done ?? 0), total: a.total + (e.segs[k]?.total ?? 0) }), { done: 0, total: 0 });
  const rows = TOT_KEYS.map((k) => ({ k, label: p?.labels[k] ?? k, ...sum(k) }));
  const done = rows.reduce((a, r) => a + r.done, 0);
  const tot = rows.reduce((a, r) => a + r.total, 0);
  return (
    <div className="sea-tot" role="group" aria-label="全剧进度">
      <span className="sea-tot-t">{p ? rows.map((r) => `${r.label} ${r.done}/${r.total}`).join(" · ") : "进度读取中…"}</span>
      <span className="sea-tot-bar" title={tot ? `总进度 ${Math.round((done / tot) * 100)}%（五段完成数之和 / 总数之和）` : ""}>
        <i style={{ width: tot ? `${(done / tot) * 100}%` : 0 }} />
      </span>
    </div>
  );
}

/** 场景 → 色带颜色（同一场景同一色；只用主题变量） */
const BANDS = ["var(--c-info)", "var(--c-ok)", "var(--c-warn)", "var(--c-accent)", "var(--c-busy)", "var(--c-stale)", "var(--c-adult)", "var(--c-bad)"];
const LINK_ICON: Record<string, [string, string]> = { 换场: ["┃", "换场"], 同场换机位: ["─", "同场换机位"], 接力: ["➜", "接力（上一镜的动作 / 视线直接接过来）"] };
const PRES: Record<string, [string, string]> = { 在画: ["●", "在画"], 局部: ["◐", "局部入画"], 画外: ["○", "画外（只有声音）"] };

type Seg = "none" | "cand" | "ok" | "stale" | "bad" | "busy" | "queued";
function segs(s: ShotSummary | undefined, ss: SShot): [Seg, Seg, Seg, Seg] {
  if (!s) return ["none", "none", "none", "none"];
  const st = s.stale as Record<string, unknown[]> | undefined;
  const isStale = (k: string) => !!(st?.[k] && (st[k] as unknown[]).length);
  // UIRSI r43（K-UI-048）：只有真的在跑才算“生成中”（呼吸灯）；排队中单列，静止灰色
  const busy = (k: string) => s.job != null && (s.job_stage === k || (!s.job_stage && k === "image"));
  const one = (have: boolean, k: string, cand = false): Seg => (busy(k) ? (s.job === "running" ? "busy" : "queued") : (s.bad as Record<string, unknown> | undefined)?.[k] ? "bad" : have ? (isStale(k) ? "stale" : "ok") : cand ? "cand" : "none");
  return [
    one(!!s.first_frame && !ss.first_old, "image", ss.cand_n > 0),
    one(!!s.last_frame_target && !ss.last_old, "last"), // UIRSI r40：旧剧本出的当前版本不算“有”
    one(!!s.video, "video"),
    s.review?.state === "passed" ? "ok" : s.review?.state === "rejected" ? "bad" : "none",
  ];
}

export default function SeasonPage() {
  const st = useStudio();
  const { d, faces, err, retry } = useSeason();
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
  // UIRSI r43（总调度 02:1x）：每镜可展开看参考图和过程小图（同一时间展开一镜，面板在本集这一排下面）
  const [peek, setPeek] = useState<string | null>(null);
  const prog = useTotals();
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
  // W5 UIUX：“现在”四问和进度矩阵不依赖每镜数据（/api/season 慢 / 读不到时照样先出来）
  if (err && !d)
    return (
      <div className="v3p-page">
        <NowPanel />
        <PipelineMatrix />
        {err === "starting" ? (
          <Empty icon="▦" title="全剧总览正在启用，约 1 分钟" sub="不用操作，好了这里会自己出来（每 15 秒自动再试）。" />
        ) : (
          <LoadError what="全剧总览" err={err} retry={retry} />
        )}
      </div>
    );
  if (!d)
    return (
      <div className="v3p-page">
        <NowPanel />
        <PipelineMatrix />
        <p className="v3p-muted">每镜的图正在读（通常十几秒）…</p>
        <Skel h={320} />
      </div>
    );
  const all = d.flatMap((e) => e.shots);
  const cnt = (f: (s: ShotSummary) => boolean) => all.filter((x) => { const s = byId.get(x.id); return s ? f(s) : false; }).length;
  const total = all.length;
  // r43（总调度 02:2x §四）：单击 = 右侧详情抽屉（不跳页）；双击 = 进画布这一镜；Ctrl / Shift 点 = 多选（照旧）
  const go = (ev: MouseEvent, id: string) => {
    if (ev.shiftKey || ev.ctrlKey || ev.metaKey) return st.select(id, { shift: ev.shiftKey, ctrl: ev.ctrlKey || ev.metaKey });
    setPeek(id);
  };
  const goCanvas = (id: string) => (setPeek(null), (location.hash = `#${id}`)); // 直达这一镜的每镜一行（画布）
  const nFilter = (blockF ? 1 : 0) + (tagF ? 1 : 0);
  const peekShot = peek ? all.find((x) => x.id === peek) : undefined;
  return (
    <div className={`v3p-page sea-page slide${detail ? "" : " simple"}`}>{/* r45 · L-113：正片 B（深色桌面 + 灰纸框，v3/slide.css），不管“显示细节”开不开都生效；胶卷条已隔离 */}
      <header className="v3p-head sea-head">
        <h1>全剧总览</h1>
        <span className="v3p-muted">
          {d.length} 集 · {total} 镜{!detail ? null : <> · 首帧 {cnt((s) => !!s.first_frame)}/{total} · 尾帧 {cnt((s) => !!s.last_frame_target)}/{total} · 视频 {cnt((s) => !!s.video)}/{total} · 通过 {cnt((s) => s.review?.state === "passed")}/{total}
          {all.some((x) => x.cand_n > 0) ? ` · 有候选待挑 ${all.filter((x) => x.cand_n > 0 && !byId.get(x.id)?.first_frame).length}` : ""}</>}
        </span>
        <span className="grow" />
        {/* r43（总调度 02:2x §二）：板块胶囊、9 个状态胶囊、显示细节都收进“筛选 ▾”（功能保留，只是收起） */}
        <Pop label={<>筛选{nFilter ? ` · ${nFilter}` : ""} ▾</>} btnClass="v3-btn sea-filter-btn" align="right" title="按板块 / 状态筛选；显示细节；人物时间线">
          {() => (
            <div className="sea-filter-pop">
            <label className="sea-tog" title="每镜的景别 · 时长 · 候选数 · 四段进度 · 人物时间线 · 换装 · 各色数量 · 各阶段">
              <input type="checkbox" checked={detail} onChange={(e) => setDetail(e.target.checked)} /> 显示细节
            </label>
            {(
              <label className="sea-tog" hidden={!detail}>
                <input type="checkbox" checked={people} onChange={(e) => setPeople(e.target.checked)} /> 人物时间线
              </label>
            )}
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
            <div className="sea-legend sea-filters">
              <TagLegend counts={countKinds(d.flatMap((e) => e.shots.map((x) => x.status)))} on={tagF?.ep == null ? tagF?.k ?? null : null} onPick={(k) => setTagF(k ? { ep: null, k } : null)} />
            </div>
          )}
              {nFilter > 0 && (
                <button type="button" className="v3p-link" onClick={() => (setBlockF(null), setTagF(null))}>
                  清除筛选
                </button>
              )}
            </div>
          )}
        </Pop>
      </header>
      {/* NAVFLOW-F 11-03（项目方 L-146）：总览顶部 = 各集进度矩阵（每行一集 × 六步，✓ ● ⚠ ·；状态来自后端 sop_gate，点格子跳对应页面和集）。
          下面每镜一格的胶片总览原样保留 */}
      <NowPanel />
      <PipelineMatrix />
      {/* r43（§二）：总进度改成一行灰字 + 一条细的单色总进度线；原 7 段彩色条在“显示细节”里 */}
      {detail ? <LiveProgress run={null} title="全剧进度" /> : <Totals p={prog} />}
      <div className="sea-legend" aria-label="图例">
        <span><i className="sea-seg s-ok" />有了</span>
        <span><i className="sea-seg s-cand" />有候选待挑</span>
        <span><i className="sea-seg s-busy" />生成中</span>
        <span><i className="sea-seg s-queued" />排队中</span>
        <span><i className="sea-seg s-stale" />过期</span>
        <span><i className="sea-seg s-bad" />坏图 / 待修改</span>
        <span className="sea-lg-sep">每格下方四段：首帧 · 尾帧 · 视频 · 通过</span>
        <span>┃ 换场</span>
        <span>─ 同场换机位</span>
        <span>➜ 接力</span>
        <span>● 在画 ◐ 局部 ○ 画外{people && leads.length ? `（每格最下一行依次是：${leads.join(" · ")}）` : ""}</span>
        <span className="sea-sw">换装</span>
      </div>
      {/* r46 · L-114：电影胶片 A（开关 html.ui-film）——每集一条片；单击 = 详情抽屉、双击 = 进画布、Ctrl / Shift = 多选、悬停放大 */}
      {filmOn() && (
        <FilmOverview
          eps={d.filter((e) => !blockF || e.blocks?.state === blockF).map((e) => ({
            number: e.number,
            title: e.title,
            // r46 亲审：一个圆点 + 一行短字（如“3 镜要重出”），详细原因放悬停
            state: (() => {
              const need = e.shots.filter((x) => dotOf(x.status as MainStatus) === "need").length;
              const redo = e.shots.filter((x) => (x.status as MainStatus | undefined)?.main5 === "doing" || (x.status as MainStatus | undefined)?.main5 === "stale").length;
              return need ? `${need} 镜要你看` : redo ? `${redo} 镜要重出` : e.blocks?.state === "done" ? "已确认" : `首帧 ${e.shots.filter((x) => byId.get(x.id)?.first_frame && !x.first_old).length}/${e.shots.length}`;
            })(),
            stateTip: `${e.blocks?.text ?? ""}
首帧 ${e.shots.filter((x) => byId.get(x.id)?.first_frame && !x.first_old).length}/${e.shots.length}`,
            stateDot: e.shots.some((x) => dotOf(x.status as MainStatus) === "need") ? "need" : e.blocks?.state === "done" ? "ok" : null,
            shots: e.shots.filter((x) => !tagF || (tagF.ep != null && tagF.ep !== e.number) || hasKind(x.status, tagF.k)).map((x) => ({
              id: x.id,
              index: x.index,
              img: (x.first_old ? null : byId.get(x.id)?.first_frame) ?? x.cand_url,
              cap: `EP${String(e.number).padStart(2, "0")} · S${String(x.index).padStart(2, "0")} · ${x.size ?? "景别未标"} · ${x.seconds ?? "?"}s · ${x.lens ?? ""}`,
              dot: dotOf(x.status as MainStatus),
              // r46（项目方 11:3x）：每帧下面的镜头细节——接口有的用真值（src: api），没有的用 mock（src: mock，前端灰色斜体“示意”）
              size: { v: x.size, src: "api" as const },
              secs: { v: x.seconds ? `${x.seconds}s` : null, src: "api" as const },
              lens: { v: x.lens ?? null, src: "api" as const },
              light: x.lighting_name || x.lighting_sources?.length ? { v: x.lighting_name ?? x.lighting_sources![0].slice(0, 14), src: "api" as const } : { v: "夜景主光 + 轮廓光", src: "mock" as const },
              move: x.camera_move ? { v: x.camera_move.replace(/^[a-z ]+/i, "").trim() || x.camera_move, src: "api" as const } : { v: "固定机位", src: "mock" as const },
              faces: x.cast.filter((c) => c.presence !== "画外").map((c) => ({ name: c.name, url: faces[c.name] ?? null })),
              video: x.video ?? null,
              videoOld: x.video_old ?? null,
              hasLast: !!byId.get(x.id)?.last_frame_target, // FILMUI r4：片窗角“已有尾帧”图标
              // 演示悬停播放（地址栏 ?mock=1 才有）：本机还没有同步到任何当前剧本的视频，用一段示意视频，帧角标“示意视频”
              videoMock: null, // r6（项目方 12:4x“只看最新状态”）：去掉 ?mock=1 示意视频
              // r6：出图中 → 片窗右上角琥珀呼吸灯；悬停说明用后端 live 状态（status.running / step / why），不编数据
              dotTip: (x.status as MainStatus | undefined)?.running ? `出图中 · ${({ first: "首帧", last: "尾帧", video: "视频" } as Record<string, string>)[(x.status as MainStatus).step ?? ""] ?? (x.status as MainStatus).step ?? ""}${(x.status as MainStatus).why ? " · " + (x.status as MainStatus).why : ""}` : null,
            })),
          }))}
          onOpen={(id) => setPeek(id)}
          onCanvas={(id) => goCanvas(id)}
          onMulti={(id, ev) => st.select(id, { shift: ev.shiftKey, ctrl: ev.ctrlKey || ev.metaKey })}
        />
      )}
      <div className="sea-grid" hidden={filmOn()} style={filmOn() ? { display: "none" } : undefined}>
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
                {(() => {
                  const nNeed = e.shots.filter((x) => dotOf(x.status as MainStatus) === "need").length;
                  return nNeed ? (
                    <span className="sea-need" title={`这一集有 ${nNeed} 镜需要你看（没过检查或尽力版待接受）`}>
                      <i className="sea-dot d-need" />
                      {nNeed}
                    </span>
                  ) : null;
                })()}
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
                      <button type="button" className={`sea-card k-${x.status?.main ?? "none"}`} onClick={(ev) => go(ev, x.id)} onDoubleClick={() => goCanvas(x.id)} title={`${x.id} · ${x.size ?? ""} · ${x.scene ?? ""} · ${x.seconds ?? "?"} 秒${x.cand_n ? ` · ${x.cand_n} 张候选` : ""}${x.adult ? " · 成人镜头（只在本机生成）" : ""}\n${tagsTitle(x.status)}\n${s?.img_summary ?? ""}\n${statusWord(x.status as MainStatus)}${(x.status as MainStatus | undefined)?.why ? `：${(x.status as MainStatus).why}` : ""}
单击：右侧看详情；双击：进画布这一镜；Ctrl / Shift 点：多选`}>
                        {/* r45 胶卷（项目方 04:3x：“改成像胶卷那种模式吧，就像传统胶卷那样”）：片框上边码 S1 · 景别 · 时长，下边码 镜头参数 · 场景，片框下一排身份脸 */}
                        <span className="film-edge top">{`S${x.index} · ${x.size ?? "景别未标"} · ${x.seconds ? `${x.seconds}s` : "?"}`}</span>
                        <span className="sea-band" style={{ background: x.scene_id ? bandOf.get(x.scene_id) : undefined }} title={x.scene ?? "场景未标"} />
                        <span className={`sea-pic${img ? "" : " none"}`} style={breatheDelay(x.id)} data-zoom-label={`${x.id.split("-")[1]} · ${s?.first_frame ? `首帧 #${s.first_frame_take ?? "?"}` : x.cand_n ? "首帧候选" : "首帧"}`}>
                          {img ? <img key={img} className="live-img" src={thumb(img, 120) ?? img} alt="" loading="lazy" decoding="async" draggable={false} /> : <span title={x.old_script_n ? `有 ${x.old_script_n} 张是剧本更新前出的旧图，不再作候选（在这一镜的“旧图”里能看）` : undefined}>{"未曝光"}<small className="film-why">{s?.job === "running" || (x.status as MainStatus | undefined)?.running ? "正在出" : s?.job === "queued" || (x.status as MainStatus | undefined)?.main5 === "doing" ? "排队中" : x.old_script_n || x.first_old ? "剧本已更新" : "未开始"}</small></span>}
                          {(() => { const dt = dotOf(x.status as MainStatus); return dt ? <i className={`sea-dot d-${dt}${dt === "run" ? " is-rendering" : ""}`} title={DOT_TITLE[dt]} /> : null; })()}
                          {lastImg && <img className="sea-last" src={thumb(lastImg, 120) ?? lastImg} alt="" loading="lazy" />}
                          <b className="sea-no">S{x.index}</b>
                          <span className="sea-hover" aria-hidden>查看详情</span>
                          <MainTag st={x.status} size="xs" />
                          {(!s?.first_frame || x.first_old) && x.cand_n > 0 && <span className="sea-cand" title={`有 ${x.cand_n} 张合格的首帧候选，还没选定用哪张`}>{x.cand_n} 张候选</span>}
                          {s?.job === "running" && <span className="sea-busy">生成中</span>}
                          {s?.job === "queued" && <span className="sea-busy is-queued">排队中</span>}
                          {x.adult && <span className="sea-adult" title="成人镜头：只在本机生成">本地</span>}
                        </span>
                        <span className="sea-segs" style={breatheDelay(x.id)} aria-label="首帧 · 尾帧 · 视频 · 通过">
                          {sg.map((g, k) => (
                            <i key={k} className={`sea-seg s-${g}`} />
                          ))}
                        </span>
                        <span className="film-edge bot" title={`镜头（D-LENS：实拍取本版出图提示词，计划取作业）：${x.lens ?? "读取中"}`}>{[x.lens ?? "…", x.scene].filter(Boolean).join(" · ")}</span>
                        <span className="film-cast" title={x.cast.map((c) => `${c.name}（${c.presence}）`).join("、") || "这一镜没有人物"}>
                          {x.cast.filter((c) => c.presence !== "画外").map((c) => (faces[c.name] ? <img key={c.name} src={thumb(faces[c.name], 64) ?? faces[c.name]} alt={c.name} title={c.name} loading="lazy" /> : <i key={c.name} title={c.name}>{c.name.slice(0, 1)}</i>))}
                        </span>
                        {/* r43（项目方 02:4x：“缺乏很多细节，比如人物什么的……信息也不够”）：图下固定 3 行——人物 / 景别 · 时长 · 场景 / 一句话内容 + 阶段 */}
                        <span className="sea-info">
                          <span className="sea-i1" title={x.cast.map((c) => `${c.name}（${c.presence}）`).join("、") || "这一镜没有人物"}>
                            {x.cast.filter((c) => c.presence !== "画外").map((c) => (
                              <span key={c.name} className="sea-who">
                                {faces[c.name] ? <img src={thumb(faces[c.name], 64) ?? faces[c.name]} alt="" loading="lazy" /> : <i>{c.name.slice(0, 1)}</i>}
                                {c.name}
                              </span>
                            ))}
                            {!x.cast.some((c) => c.presence !== "画外") && <span className="sea-who none">{x.cast.length ? `画外：${x.cast.map((c) => c.name).join("、")}` : "无人物"}</span>}
                          </span>
                          <span className="sea-i2">{[x.size, x.seconds ? `${x.seconds}s` : null, x.scene].filter(Boolean).join(" · ")}</span>
                          <span className="sea-i3">
                            <span className="sea-txt" title={x.img || ""}>{x.img ? (x.img.length > 20 ? `${x.img.slice(0, 20)}…` : x.img) : "—"}</span>
                            <span className="sea-stage">{s?.video ? "视频 已出" : s?.last_frame_target && !x.last_old ? "尾帧 已出" : s?.first_frame && !x.first_old ? "首帧 已定" : x.cand_n ? `首帧 · 候选 ${x.cand_n}` : ""}</span>
                          </span>
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
      {peek && (
        <SeasonDrawer shot={peek} sum={byId.get(peek)} status={peekShot?.status as MainStatus | undefined}
          meta={[peekShot?.scene, peekShot?.size, peekShot?.seconds ? `${peekShot.seconds} 秒` : null].filter(Boolean).join(" · ")} onClose={() => setPeek(null)} />
      )}
    </div>
  );
}
