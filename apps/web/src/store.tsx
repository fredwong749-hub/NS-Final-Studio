import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "./api";
import type {
  BatchResult,
  Episode,
  EpisodeLooks,
  Job,
  LookCatalog,
  ReviewState,
  ShotDetail,
  ShotEdit,
  ShotSummary,
  Stage,
} from "./types";
import { epOfShot, flatShots, isActiveJob, latestJobs, STAGE_LABEL, type Filter } from "./util";

export type View = "overview" | "episode" | "nodes" | "assets";
export type Density = "compact" | "standard" | "detail";
export const VIEWS_ALL: View[] = ["overview", "episode", "nodes", "assets"];
/** 资产页定位：从镜头卡点脸图跳过来时带上角色和造型 */
export interface AssetFocus {
  character: string;
  lookId?: string | null;
  itemId?: string | null;
}
/** 检查器页签（规范 §3.3） */
export type InspectorTab = "script" | "first" | "last" | "video" | "people" | "takes" | "review" | "boost";
export type DrawerTab = "jobs" | "batch" | "compare" | "seam";
/** 全屏看图：pair = 首帧|尾帧并排；ab = 同一阶段两个版本对比 */
export type FrameStage = "image" | "last";
export interface ViewerState {
  shotId: string;
  stage: FrameStage;
  mode: "pair" | "ab";
  /** ab 模式下的 B（默认 = 最新的非当前版本） */
  b?: number | null;
}
/** 某镜某阶段正在进行的任务（行内进度 / 检查器对比位） */
export interface LiveJob {
  job: Job;
  /** 排队位置（1 起）；运行中为 0 */
  pos: number;
}

export interface Toast {
  id: number;
  msg: string;
  kind: "ok" | "err";
}

export interface ConfirmReq {
  title: string;
  lines: string[];
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void | Promise<void>;
}

interface Preview {
  shotId: string;
  stage: Stage;
  n: number;
}
interface Compare {
  shotId: string;
  stage: Stage;
  a: number;
  b: number;
}
interface UndoEntry {
  shotId: string;
  before: ShotEdit;
  after: ShotEdit;
}

/** 可复制粘贴的编辑字段（规范 C8：运镜、表情、负面词、种子） */
export const PASTE_FIELDS = ["camera", "expression", "image_negative", "image_seed", "video_seed"] as const;
type Clip = Pick<ShotEdit, (typeof PASTE_FIELDS)[number]>;

function loadPref<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && allowed.includes(v) ? v : fallback;
  } catch {
    return fallback;
  }
}
function savePref(key: string, v: string) {
  try {
    localStorage.setItem(key, v);
  } catch {
    /* 隐私模式等 */
  }
}

function parseHash(): { ep: number | null; shot: string | null } {
  const h = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const m = /^ep(\d{2})(?:-S(\d))?$/.exec(h);
  if (!m) return { ep: null, shot: null };
  return { ep: Number(m[1]), shot: m[2] ? `ep${m[1]}-S${m[2]}` : null };
}

function useStudioState() {
  const [episodes, setEpisodes] = useState<Episode[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [details, setDetails] = useState<Record<string, ShotDetail>>({});
  const [epLooks, setEpLooks] = useState<Record<number, EpisodeLooks>>({});
  const [catalog, setCatalog] = useState<LookCatalog | null>(null);
  const [looksError, setLooksError] = useState<string | null>(null);

  const initial = parseHash();
  const [view, setViewState] = useState<View>(() => {
    const q = new URLSearchParams(location.search).get("view") as View | null; // ?view=overview 便于直接打开
    return q && VIEWS_ALL.includes(q) ? q : loadPref<View>("ns.view", "episode", VIEWS_ALL);
  });
  const [density, setDensityState] = useState<Density>(() => {
    const q = new URLSearchParams(location.search).get("density") as Density | null;
    return q && ["compact", "standard", "detail"].includes(q) ? q : loadPref<Density>("ns.density", "standard", ["compact", "standard", "detail"]);
  });
  const [listMode, setListModeState] = useState<boolean>(() => new URLSearchParams(location.search).get("list") === "1" || loadPref("ns.list", "0", ["0", "1"]) === "1");
  const [inspectorHidden, setInspectorHiddenState] = useState<boolean>(() => loadPref("ns.inspHidden", "0", ["0", "1"]) === "1");
  const [inspTab, setInspTab] = useState<InspectorTab>(() => {
    const q = new URLSearchParams(location.search).get("tab") as InspectorTab | null;
    const t = q ?? loadPref<InspectorTab>("ns.inspTab", "first", ["script", "first", "last", "video", "people", "takes", "review", "boost"]);
    return t === "takes" ? "first" : t; // v3：版本并入首帧 / 尾帧 / 视频页签
  });
  const [assetFocus, setAssetFocus] = useState<AssetFocus | null>(() => {
    const c = new URLSearchParams(location.search).get("char");
    return c ? { character: c } : null;
  });
  const [hlChar, setHlChar] = useState<string | null>(null);
  const [epNum, setEpNum] = useState<number>(initial.ep ?? 1);
  const [sel, setSel] = useState<string | null>(initial.shot);
  const [multi, setMulti] = useState<Set<string>>(new Set());
  const anchor = useRef<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const [drawer, setDrawer] = useState<{ open: boolean; tab: DrawerTab }>({ open: false, tab: "jobs" });
  const [batchResults, setBatchResults] = useState<{ stage: Stage; at: string; results: BatchResult[] } | null>(null);
  const [compare, setCompare] = useState<Compare | null>(null);
  const [seam, setSeam] = useState<{ from: string; to: string } | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [viewer, setViewer] = useState<ViewerState | null>(() => {
    const v = new URLSearchParams(location.search).get("viewer"); // ?viewer=ep01-S1:image:ab 便于截图
    if (!v) return null;
    const [shotId, stage, mode] = v.split(":");
    return { shotId, stage: stage === "last" ? "last" : "image", mode: mode === "ab" ? "ab" : "pair" };
  });
  const [watched, setWatched] = useState<Set<string>>(new Set());
  const [reviewMode, setReviewMode] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [confirmReq, setConfirmReq] = useState<ConfirmReq | null>(null);
  const [rejectFor, setRejectFor] = useState<string[] | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dirtyRef = useRef(false);
  const undoStack = useRef<UndoEntry[]>([]);
  const redoStack = useRef<UndoEntry[]>([]);
  const [clip, setClip] = useState<Clip | null>(null);

  // ---------------- 基础 ----------------
  const notify = useCallback((msg: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-4), { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 7000 : 3000);
  }, []);

  const setView = useCallback((v: View) => {
    setViewState(v);
    savePref("ns.view", v);
  }, []);
  const setDensity = useCallback((d: Density) => {
    setDensityState(d);
    savePref("ns.density", d);
  }, []);
  const cycleDensity = useCallback(() => {
    setDensityState((d) => {
      const n: Density = d === "compact" ? "standard" : d === "standard" ? "detail" : "compact";
      savePref("ns.density", n);
      return n;
    });
  }, []);
  const setListMode = useCallback((v: boolean) => {
    setListModeState(v);
    savePref("ns.list", v ? "1" : "0");
  }, []);
  const setInspectorHidden = useCallback((v: boolean) => {
    setInspectorHiddenState(v);
    savePref("ns.inspHidden", v ? "1" : "0");
  }, []);
  const openInspTab = useCallback((tab: InspectorTab, field?: string) => {
    setInspTab(tab);
    savePref("ns.inspTab", tab);
    setInspectorHiddenState(false);
    if (field)
      setTimeout(() => {
        const el = document.querySelector<HTMLElement>(`[data-field="${field}"]`);
        el?.scrollIntoView({ block: "center" });
        el?.focus();
      }, 60);
  }, []);
  const openAssets = useCallback(
    (f: AssetFocus) => {
      setAssetFocus(f);
      setView("assets");
    },
    [setView],
  );

  const shots = useMemo(() => (episodes ? flatShots(episodes) : []), [episodes]);
  const summaryById = useMemo(() => new Map(shots.map((s) => [s.id, s])), [shots]);
  const latest = useMemo(() => latestJobs(jobs), [jobs]);
  /** shotId|stage → 进行中的任务 + 排队位置 */
  const live = useMemo(() => {
    const m = new Map<string, LiveJob>();
    const queued = jobs.filter((j) => j.state === "queued").sort((a, b) => a.created_at.localeCompare(b.created_at));
    for (const j of jobs) {
      if (j.state !== "queued" && j.state !== "running") continue;
      const k = `${j.shot_id}|${j.stage}`;
      if (m.has(k)) continue;
      m.set(k, { job: j, pos: j.state === "running" ? 0 : queued.findIndex((q) => q.id === j.id) + 1 });
    }
    return m;
  }, [jobs]);
  const liveJob = useCallback((shotId: string, stage: string) => live.get(`${shotId}|${stage}`), [live]);
  const episode = useMemo(() => episodes?.find((e) => e.number === epNum) ?? null, [episodes, epNum]);

  // ---------------- 加载 ----------------
  const refreshEpisodes = useCallback(async () => {
    try {
      setEpisodes(await api.episodes());
      setLoadError(null);
    } catch (e) {
      setLoadError((e as Error).message);
    }
  }, []);

  const refreshShots = useCallback(
    async (ids: string[]) => {
      const res = await Promise.allSettled(ids.map((id) => api.shot(id)));
      setDetails((d) => {
        const next = { ...d };
        res.forEach((r) => {
          if (r.status === "fulfilled") next[r.value.summary.id] = r.value;
        });
        return next;
      });
    },
    [],
  );

  const refreshLooks = useCallback(async (nums: number[]) => {
    const res = await Promise.allSettled(nums.filter((n) => n >= 1).map((n) => api.looks.episode(n)));
    const got = res.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
    const failed = res.find((r): r is PromiseRejectedResult => r.status === "rejected");
    setEpLooks((m) => {
      const next = { ...m };
      for (const v of got) next[v.episode] = v;
      return next;
    });
    // 越界集号（如 ep61）会 404，只有全部失败才算接口不可用
    setLooksError(got.length || !failed ? null : (failed.reason as Error).message);
  }, []);

  /** 改动后刷新：全部摘要 + 指定镜头详情 */
  const refreshAfter = useCallback(
    async (ids: string[]) => {
      await Promise.all([refreshEpisodes(), ids.length ? refreshShots(ids) : null]);
    },
    [refreshEpisodes, refreshShots],
  );

  useEffect(() => {
    void refreshEpisodes();
    api.jobs().then(setJobs, () => undefined);
    api.looks.catalog().then(setCatalog, (e: Error) => setLooksError(e.message));
  }, [refreshEpisodes]);

  // 当前集：加载 6 镜详情 + 本集和上一集造型
  const epShotIds = useMemo(() => episode?.shots.map((s) => s.id) ?? [], [episode]);
  const epKey = epShotIds.join(",");
  useEffect(() => {
    if (!epKey) return;
    void refreshShots(epKey.split(","));
    void refreshLooks([epNum - 1, epNum, epNum + 1]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epKey]);

  // 默认选中本集第一镜
  useEffect(() => {
    if (episode && (!sel || epOfShot(sel) !== episode.number)) setSel(episode.shots[0]?.id ?? null);
  }, [episode, sel]);

  // URL hash 同步
  useEffect(() => {
    const h = sel ?? `ep${String(epNum).padStart(2, "0")}`;
    if (location.hash !== `#${h}`) history.replaceState(null, "", `#${h}`);
  }, [sel, epNum]);
  useEffect(() => {
    const on = () => {
      const p = parseHash();
      if (p.ep) setEpNum(p.ep);
      if (p.shot) setSel(p.shot);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  // ---------------- 任务轮询：有排队/运行中的任务时每 3 s，否则 15 s ----------------
  const jobsRef = useRef<Job[]>([]);
  const detailsRef = useRef(details);
  detailsRef.current = details;
  const anyBusy = jobs.some(isActiveJob) || shots.some((s) => s.job);
  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const next = await api.jobs();
        if (stop) return;
        const prev = new Map(jobsRef.current.map((j) => [j.id, j.state]));
        const changed = new Set<string>();
        for (const j of next) if (prev.get(j.id) !== j.state) changed.add(j.shot_id);
        jobsRef.current = next;
        setJobs(next);
        if (changed.size) {
          for (const j of next)
            if (changed.has(j.shot_id) && prev.has(j.id) && j.state === "failed")
              notify(`${j.shot_id} ${STAGE_LABEL[j.stage]}渲染失败`, "err");
          await refreshAfter([...changed].filter((id) => detailsRef.current[id]));
        }
      } catch {
        /* 后端暂时不可达：下次再试 */
      }
    };
    const t = setInterval(tick, anyBusy ? 3000 : 15000);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, [anyBusy, refreshAfter, notify]);

  const onJobsQueued = useCallback(
    (js: Job[]) => {
      setJobs((cur) => {
        const next = [...js, ...cur];
        jobsRef.current = next;
        return next;
      });
      void refreshEpisodes();
    },
    [refreshEpisodes],
  );

  // ---------------- 选择 / 导航 ----------------
  const confirmDiscard = useCallback(() => {
    if (!dirtyRef.current) return true;
    if (!window.confirm("当前镜头有未保存的修改，放弃修改？")) return false;
    dirtyRef.current = false;
    return true;
  }, []);

  const select = useCallback(
    (id: string, mods?: { shift?: boolean; ctrl?: boolean }) => {
      if (mods?.ctrl) {
        setMulti((m) => {
          const n = new Set(m);
          if (n.size === 0 && sel) n.add(sel);
          if (n.has(id)) n.delete(id);
          else n.add(id);
          return n;
        });
        anchor.current = id;
        return;
      }
      if (mods?.shift && anchor.current) {
        const order = shots.map((s) => s.id);
        const a = order.indexOf(anchor.current);
        const b = order.indexOf(id);
        if (a >= 0 && b >= 0) {
          const [lo, hi] = a < b ? [a, b] : [b, a];
          setMulti(new Set(order.slice(lo, hi + 1)));
          return;
        }
      }
      if (id !== sel && !confirmDiscard()) return;
      anchor.current = id;
      setMulti(new Set());
      setSel(id);
      setPreview(null);
      setEpNum(epOfShot(id));
    },
    [sel, shots, confirmDiscard],
  );

  const gotoEpisode = useCallback(
    (n: number) => {
      if (!episodes?.some((e) => e.number === n)) return;
      if (!confirmDiscard()) return;
      setEpNum(n);
      setSel(null);
      setMulti(new Set());
      setPreview(null);
    },
    [episodes, confirmDiscard],
  );

  const stepShot = useCallback(
    (d: 1 | -1) => {
      const order = shots.map((s) => s.id);
      const i = sel ? order.indexOf(sel) : -1;
      const j = Math.min(order.length - 1, Math.max(0, i + d));
      if (order[j]) select(order[j]);
    },
    [shots, sel, select],
  );

  const selection = useMemo(() => (multi.size ? [...multi] : sel ? [sel] : []), [multi, sel]);

  // ---------------- 写入 ----------------
  const saveEdit = useCallback(
    async (id: string, edit: ShotEdit, opts: { quiet?: boolean; recordUndo?: boolean } = {}) => {
      const before = detailsRef.current[id]?.edit;
      try {
        const after = await api.saveEdit(id, edit);
        if (before && opts.recordUndo !== false) {
          undoStack.current.push({ shotId: id, before, after });
          if (undoStack.current.length > 100) undoStack.current.shift();
          redoStack.current = [];
        }
        if (!opts.quiet) notify(`${id} 已保存`);
        await refreshAfter([id]);
        return true;
      } catch (e) {
        notify(`${id} 保存失败：${(e as Error).message}`, "err");
        return false;
      }
    },
    [notify, refreshAfter],
  );

  const undo = useCallback(
    async (redo = false) => {
      const from = redo ? redoStack.current : undoStack.current;
      const to = redo ? undoStack.current : redoStack.current;
      const e = from.pop();
      if (!e) return notify(redo ? "没有可重做的修改" : "没有可撤销的修改");
      // 撤销 = 把旧值再写一次，同样经过后端校验
      const ok = await saveEdit(e.shotId, redo ? e.after : e.before, { quiet: true, recordUndo: false });
      if (ok) {
        to.push(e);
        notify(`${redo ? "已重做" : "已撤销"} ${e.shotId} 的修改`);
      } else from.push(e);
    },
    [notify, saveEdit],
  );

  const saveEpisodeEdit = useCallback(
    async (n: number, body: { boost_first?: string | null; boost_last?: string | null; music?: string | null }) => {
      try {
        await api.saveEpisodeEdit(n, body);
        notify(
          "music" in body
            ? `ep${String(n).padStart(2, "0")} 本集背景音乐已保存（后期混音用，不影响画面和 H3 声音）`
            : `ep${String(n).padStart(2, "0")} 本集导演加强已保存（作用于本集全部镜头，旧版本标为过期）`,
        );
        await refreshEpisodes();
        return true;
      } catch (e) {
        notify(`本集加强保存失败：${(e as Error).message}`, "err");
        return false;
      }
    },
    [notify, refreshEpisodes],
  );

  const render = useCallback(
    async (id: string, stage: Stage, seed: number | null = null) => {
      try {
        const job = await api.render(id, stage, seed);
        onJobsQueued([job]);
        notify(`${id} ${STAGE_LABEL[stage]}已加入队列（任务 ${job.id}）`);
        return true;
      } catch (e) {
        notify(`${id} 提交失败：${(e as Error).message}`, "err");
        return false;
      }
    },
    [notify, onJobsQueued],
  );

  const requestBatch = useCallback(
    (ids: string[], stage: Stage, onlyMissing = false) => {
      const skipped: string[] = [];
      const run: string[] = [];
      for (const id of ids) {
        const s = summaryById.get(id);
        if (!s) continue;
        if (s.owner === "gpu3") skipped.push(`${id}：gpu3 负责此镜（避免两条链），请用「请 gpu3 重出」`);
        else if (s.job) skipped.push(`${id}：已有任务在${s.job === "running" ? "渲染" : "排队"}`);
        else if ((stage === "video" || stage === "last") && !s.first_frame) skipped.push(`${id}：缺首帧`);
        else if (stage === "last" && !s.last_supported) skipped.push(`${id}：尾帧生成尚未上线`);
        else if (onlyMissing && (stage === "image" ? s.first_frame : stage === "last" ? s.last_frame_take != null : s.video))
          skipped.push(`${id}：已有${STAGE_LABEL[stage]}`);
        else run.push(id);
      }
      setConfirmReq({
        title: `批量渲染${STAGE_LABEL[stage]}`,
        lines: [
          `选中 ${ids.length} 镜，将入队 ${run.length} 个任务（GPU 串行执行）。`,
          ...(skipped.length ? [`跳过 ${skipped.length} 镜：`, ...skipped] : []),
        ],
        confirmLabel: `入队 ${run.length} 个任务`,
        onConfirm: async () => {
          if (!run.length) return;
          try {
            const results = await api.renderBatch(run, stage, onlyMissing);
            setBatchResults({ stage, at: new Date().toISOString(), results });
            setDrawer({ open: true, tab: "batch" });
            onJobsQueued(results.flatMap((r) => (r.ok && r.job ? [r.job] : [])));
            const bad = results.filter((r) => !r.ok).length;
            notify(`已入队 ${results.length - bad} 个${bad ? `，失败 ${bad} 个` : ""}`, bad ? "err" : "ok");
          } catch (e) {
            notify(`批量提交失败：${(e as Error).message}`, "err");
          }
        },
      });
    },
    [summaryById, notify, onJobsQueued],
  );

  /** 沿链重渲：本镜尾帧锁定下一镜首帧时，先出下一镜首帧，再出本镜视频 */
  const requestChain = useCallback(
    (id: string) => {
      const d = detailsRef.current[id];
      if (!d) return;
      const steps: [string, Stage][] = [];
      if (d.edit.last_frame === "next" && d.next_shot) steps.push([d.next_shot, "image"]);
      steps.push([id, "video"]);
      setConfirmReq({
        title: "沿链重渲",
        lines: [
          "按依赖顺序入队：",
          ...steps.map(([s, st], i) => `${i + 1}. ${s} ${STAGE_LABEL[st]}`),
          ...(d.edit.last_frame === "next" ? [] : ["（本镜未设置「尾帧 = 下一镜首帧」，只重渲本镜视频）"]),
        ],
        confirmLabel: "入队",
        onConfirm: async () => {
          for (const [s, st] of steps) if (!(await render(s, st))) break;
        },
      });
    },
    [render],
  );

  /** 请 gpu3 重出（gpu3 负责的镜头）：经桥写 gpu3 的重渲队列；last = 只重出尾帧（保留首帧） */
  const requestGpu3 = useCallback(
    (id: string, stage: "image" | "last" | "video" | "both") => {
      const what = { image: "首帧（尾帧随之重编）", last: "尾帧（保留首帧）", video: "视频（保留首尾帧）", both: "首尾帧和视频" }[stage];
      setConfirmReq({
        title: "请 gpu3 重出",
        lines: [`${id} 请 gpu3 重出${what}。`, "请求写进 gpu3 的重渲队列（docs/canvas.md §2），由 gpu3 系列渲染器出新 take；笔记本不出图。"],
        confirmLabel: "发给 gpu3",
        onConfirm: async () => {
          try {
            await api.gpu3Rerender(id, stage);
            notify(`${id} 已请 gpu3 重出${what}`);
          } catch (e) {
            notify(`${id} 发给 gpu3 失败：${(e as Error).message}`, "err");
          }
        },
      });
    },
    [notify],
  );

  /** 检查器「重出」：已经在检查器里看着提示词了，不再弹确认，直接入队 */
  const rerender = useCallback(
    async (id: string, stage: Stage, saveFirst?: () => Promise<boolean>) => {
      if (saveFirst && !(await saveFirst())) return false;
      // gpu3 负责的镜头：保存修改后改成请 gpu3 重出（修改随请求的 edit 快照一起发过去）
      if (summaryById.get(id)?.owner === "gpu3") {
        requestGpu3(id, stage);
        return true;
      }
      return render(id, stage);
    },
    [render, summaryById, requestGpu3],
  );

  const openViewer = useCallback(
    (shotId: string, stage: FrameStage, mode: "pair" | "ab" = "pair", b?: number | null) => {
      setViewer({ shotId, stage, mode, b });
      if (!detailsRef.current[shotId]) void refreshShots([shotId]);
    },
    [refreshShots],
  );

  const requestRender = useCallback(
    (id: string, stage: Stage) => {
      // 一镜一条链：gpu3 负责的镜头（快捷键 I/E/V 也走这里）改成请 gpu3 重出
      if (summaryById.get(id)?.owner === "gpu3") return requestGpu3(id, stage);
      setConfirmReq({
        title: `渲染${STAGE_LABEL[stage]}`,
        lines: [`${id} 重新渲染${STAGE_LABEL[stage]}，使用已保存的修改。`],
        confirmLabel: "入队",
        onConfirm: () => void render(id, stage),
      });
    },
    [render, summaryById, requestGpu3],
  );

  const activate = useCallback(
    async (id: string, stage: Stage, n: number) => {
      try {
        await api.activate(id, stage, n);
        notify(`${id} ${STAGE_LABEL[stage]} #${n} 已设为当前（审核回到未审）`);
        setPreview(null);
        await refreshAfter([id]);
      } catch (e) {
        notify(`切换失败：${(e as Error).message}`, "err");
      }
    },
    [notify, refreshAfter],
  );

  const markWatched = useCallback((url: string) => {
    setWatched((w) => (w.has(url) ? w : new Set(w).add(url)));
  }, []);

  /** 通过前必须完整看过当前视频（规范 B11）；没有视频时按首帧审核 */
  const canPass = useCallback((s: ShotSummary | undefined) => !!s && (!s.video || watched.has(s.video)), [watched]);

  const setReview = useCallback(
    async (ids: string[], state: ReviewState, reason = "") => {
      const ok: string[] = [];
      const bad: string[] = [];
      for (const id of ids) {
        const s = summaryById.get(id);
        if (state === "passed" && !canPass(s)) {
          bad.push(`${id}：视频未完整播放`);
          continue;
        }
        try {
          await api.review(id, state, reason);
          ok.push(id);
        } catch (e) {
          bad.push(`${id}：${(e as Error).message}`);
        }
      }
      const label = { passed: "通过", rejected: "打回", unreviewed: "未审" }[state];
      if (ok.length) notify(ids.length === 1 ? `${ok[0]} 已标为${label}` : `${ok.length} 镜已标为${label}`);
      if (bad.length) notify(`未能标记：${bad.join("；")}`, "err");
      await refreshAfter(ok.filter((id) => detailsRef.current[id]));
      return ok.length > 0;
    },
    [summaryById, canPass, notify, refreshAfter],
  );

  const copyEdit = useCallback(() => {
    const d = sel ? detailsRef.current[sel] : undefined;
    if (!d) return;
    const c = Object.fromEntries(PASTE_FIELDS.map((k) => [k, d.edit[k]])) as Clip;
    setClip(c);
    notify(`已复制 ${sel} 的运镜 / 表情 / 负面词 / 种子`);
  }, [sel, notify]);

  const pasteEdit = useCallback(
    (fields: (typeof PASTE_FIELDS)[number][]) => {
      if (!clip) return notify("剪贴板是空的，先 Ctrl+C 复制一个镜头的编辑");
      const targets = selection.filter((id) => id !== undefined);
      setConfirmReq({
        title: "粘贴编辑",
        lines: [`把 ${fields.join("、")} 粘贴到 ${targets.length} 镜：${targets.join("、")}`],
        confirmLabel: "粘贴",
        onConfirm: async () => {
          let n = 0;
          for (const id of targets) {
            const d = detailsRef.current[id] ?? (await api.shot(id).catch(() => undefined));
            if (!d) continue;
            const edit = { ...d.edit };
            for (const k of fields) (edit as Record<string, unknown>)[k] = clip[k];
            if (await saveEdit(id, edit, { quiet: true })) n++;
          }
          notify(`已粘贴到 ${n}/${targets.length} 镜`);
        },
      });
    },
    [clip, selection, notify, saveEdit],
  );

  return {
    // 数据
    episodes, loadError, jobs, latest, details, epLooks, catalog, looksError,
    shots, summaryById, episode, epNum,
    // 视图
    view, setView, sel, multi, selection, setMulti, filter, setFilter,
    density, setDensity, cycleDensity, listMode, setListMode, inspectorHidden, setInspectorHidden,
    inspTab, openInspTab, assetFocus, setAssetFocus, openAssets, hlChar, setHlChar, saveEpisodeEdit,
    drawer, setDrawer, batchResults, compare, setCompare, seam, setSeam, preview, setPreview,
    viewer, setViewer, openViewer, liveJob,
    watched, markWatched, canPass, reviewMode, setReviewMode, helpOpen, setHelpOpen,
    paletteOpen, setPaletteOpen, confirmReq, setConfirmReq, rejectFor, setRejectFor, toasts, clip,
    dirtyRef,
    // 动作
    notify, refreshEpisodes, refreshShots, refreshLooks, refreshAfter, select, gotoEpisode, stepShot,
    saveEdit, undo, render, rerender, requestRender, requestGpu3, requestBatch, requestChain, activate, setReview,
    copyEdit, pasteEdit, onJobsQueued,
  };
}

export type Studio = ReturnType<typeof useStudioState>;
const Ctx = createContext<Studio | null>(null);

export function StudioProvider({ children }: { children: ReactNode }) {
  const s = useStudioState();
  return <Ctx.Provider value={s}>{children}</Ctx.Provider>;
}

export function useStudio(): Studio {
  const s = useContext(Ctx);
  if (!s) throw new Error("useStudio 必须在 StudioProvider 里使用");
  return s;
}
