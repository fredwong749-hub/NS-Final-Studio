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
  AffectedShots,
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
import { epOfShot, EXPLICIT_LABEL, flatShots, isActiveJob, laptopVideoEnabled, latestJobs, STAGE_LABEL, type Filter } from "./util";

export type View = "overview" | "episode" | "nodes" | "assets" | "import" | "people" | "ab";
export type Density = "compact" | "standard" | "detail";
export type CanvasMode = "review" | "edit";
export const VIEWS_ALL: View[] = ["overview", "episode", "nodes", "assets", "import", "people", "ab"];
/** UX6：旧整页 → 新页面（只改入口，旧组件不删；地址栏带 ?legacy=1 仍走旧页） */
export const LEGACY_REDIRECT: Partial<Record<View, string>> = {
  assets: "#/assets",
  people: "#/assets?type=people",
  import: "#/script-create?tab=import",
  ab: "#/script-create?tab=import",
  overview: "#/script-create",
  nodes: "#/script-create",
};
const legacyOn = () => false; // UIRSI 重构：旧页面已下线，?legacy=1 不再有效
function redirectLegacy(v: View) {
  const to = LEGACY_REDIRECT[v];
  if (!to) return;
  try {
    const u = new URL(location.href);
    u.searchParams.delete("view");
    history.replaceState(null, "", u.pathname + (u.search || "") + to);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } catch {
    location.hash = to;
  }
}
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
  /** 本地“已请 gpu3”标记（不是笔记本任务；gpu3 新 take 到达即消失） */
  gpu3?: boolean;
  /** 撤销本地标记（请求丢失 / 想再发一次时） */
  clear?: () => void;
}

/** 请 gpu3 重出后的本地等待标记。后端还没有 gpu3 队列查询接口（契约见 docs：GET /api/gpu3/requests），
 *  所以按“发出时 gpu3 链的签名”判断：签名变了 = 新 take 到了 → 清除；超过 GPU3_PENDING_TTL 视为过期 */
export type Gpu3Stage = "image" | "last" | "video" | "both";
export interface Gpu3Pending {
  stage: Gpu3Stage;
  at: string;
  sig: string;
}
const GPU3_PENDING_TTL = 6 * 3600 * 1000;
const GPU3_COVERS: Record<Gpu3Stage, Stage[]> = { image: ["image", "last"], last: ["last"], video: ["video"], both: ["image", "last", "video"] };
/** 只看版本号 / 版本数 / 尾帧文件戳：镜像同步改了 URL 前缀（/api/gpu3-media → /files）不算新版本 */
export const gpu3Sig = (s: ShotSummary | undefined) =>
  s
    ? [s.gpu3?.image_take, s.gpu3?.video_take, JSON.stringify(s.gpu3?.takes_count ?? {}), s.last_frame_target?.split("?v=")[1] ?? (s.last_frame_target ? "last" : "")].join("|")
    : "";
function loadGpu3Pending(): Record<string, Gpu3Pending> {
  try {
    const v = JSON.parse(localStorage.getItem("ns.gpu3Pending") || "{}") as Record<string, Gpu3Pending>;
    const now = Date.now();
    return Object.fromEntries(Object.entries(v).filter(([, p]) => p && now - new Date(p.at).getTime() < GPU3_PENDING_TTL));
  } catch {
    return {};
  }
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
  /** 第二个操作按钮（次级样式，放在主按钮左边） */
  secondary?: { label: string; onClick: () => void | Promise<void> };
  /** 取消按钮文字（默认「取消」） */
  cancelLabel?: string;
  /** 封板修复（项目方 2026-10-30）：项目方本人确认勾选框；不勾不能点主按钮（次级按钮不受限，用于“跳过成人镜”） */
  ownerCheck?: string;
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
  const m = /^ep(\d{2})(?:-S(\d+))?$/.exec(h); // W4a：S10、S11 也能深链
  if (!m) return { ep: null, shot: null };
  return { ep: Number(m[1]), shot: m[2] ? `ep${m[1]}-S${m[2]}` : null };
}

function useStudioState() {
  const [episodes, setEpisodes] = useState<Episode[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [details, setDetails] = useState<Record<string, ShotDetail>>({});
  /** 封板修复：镜头详情加载失败的原因（检查器 / 看图显示，不再无限“加载…”） */
  const [detailErr, setDetailErr] = useState<Record<string, string>>({});
  const [epLooks, setEpLooks] = useState<Record<number, EpisodeLooks>>({});
  const [catalog, setCatalog] = useState<LookCatalog | null>(null);
  const [looksError, setLooksError] = useState<string | null>(null);

  const initial = parseHash();
  const [view, setViewState] = useState<View>(() => {
    const q = new URLSearchParams(location.search).get("view") as View | null; // ?view=overview 便于直接打开
    // UX6（A / D5）：旧资产库、人物管理、剧本导入整页 → 跳到新页面（旧代码保留，?legacy=1 仍能打开）
    if (q && LEGACY_REDIRECT[q] && !legacyOn()) {
      redirectLegacy(q);
      return "episode";
    }
    if (q && VIEWS_ALL.includes(q)) return q;
    // UXF1（审查 #51）：深链接 #epNN / #epNN-Sx 一定落在集视图，不被上次停留的页面（人物管理等）覆盖
    if (initial.ep != null) return "episode";
    const saved = loadPref<View>("ns.view", "episode", VIEWS_ALL);
    if (LEGACY_REDIRECT[saved] && !legacyOn() && !location.hash.startsWith("#/")) {
      redirectLegacy(saved);
      return "episode";
    }
    return LEGACY_REDIRECT[saved] && !legacyOn() ? "episode" : saved;
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
  /** fredw-92/W4a 画布 v3：审片（一镜一行）/ 精修（单镜三区）；?mode=edit 便于截图 */
  const [canvasMode, setCanvasModeState] = useState<CanvasMode>(() =>
    {
      const m = new URLSearchParams(location.search).get("mode"); // UXF1 #51：?mode=review 与 ?mode=edit 都认
      return m === "edit" || m === "review" ? m : loadPref<CanvasMode>("ns.canvasMode", "review", ["review", "edit"]);
    },
  );
  const setCanvasMode = useCallback((m: CanvasMode) => {
    setCanvasModeState(m);
    savePref("ns.canvasMode", m);
  }, []);
  /** v3：旧版镜头行 + 检查器（工具菜单里切换，保留全部旧功能） */
  const [classic, setClassicState] = useState<boolean>(() => new URLSearchParams(location.search).get("classic") === "1" || loadPref("ns.classic", "0", ["0", "1"]) === "1");
  const setClassic = useCallback((v: boolean) => {
    setClassicState(v);
    savePref("ns.classic", v ? "1" : "0");
  }, []);
  const [helpOpen, setHelpOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [confirmReq, setConfirmReq] = useState<ConfirmReq | null>(null);
  const [rejectFor, setRejectFor] = useState<string[] | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dirtyRef = useRef(false);
  const undoStack = useRef<UndoEntry[]>([]);
  const redoStack = useRef<UndoEntry[]>([]);
  const [clip, setClip] = useState<Clip | null>(null);
  const [gpu3Pending, setGpu3Pending] = useState<Record<string, Gpu3Pending>>(loadGpu3Pending);
  useEffect(() => {
    try {
      localStorage.setItem("ns.gpu3Pending", JSON.stringify(gpu3Pending));
    } catch {
      /* 隐私模式等 */
    }
  }, [gpu3Pending]);
  const clearGpu3Pending = useCallback((id: string) => {
    setGpu3Pending((m) => {
      if (!(id in m)) return m;
      const n = { ...m };
      delete n[id];
      return n;
    });
  }, []);

  // ---------------- 基础 ----------------
  const notify = useCallback((msg: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-4), { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 7000 : 3000);
  }, []);

  const setView = useCallback((v: View) => {
    if (LEGACY_REDIRECT[v] && !legacyOn()) {
      redirectLegacy(v);
      return;
    }
    setViewState(v);
    savePref("ns.view", v);
    // UX5（D5）：?view=… 只在首次打开时生效；切走以后从地址栏去掉，免得之后每次刷新都停在那一页
    try {
      const u = new URL(location.href);
      if (u.searchParams.get("view") && u.searchParams.get("view") !== v) {
        u.searchParams.delete("view");
        history.replaceState(null, "", u.pathname + (u.search || "") + u.hash);
      }
    } catch {
      /* 无 URL：忽略 */
    }
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
      // UX5（A2）：画布里双击人物 / 点人脸，一律去资产中心的角色详情（以前跳旧资产库 view=assets），并记下从哪一镜来
      setAssetFocus(f);
      const from = /^#ep\d+/.test(location.hash) ? location.hash.slice(1) : "";
      const q = new URLSearchParams({ char: f.character });
      if (f.lookId) q.set("look", f.lookId);
      if (from) q.set("from", from);
      location.hash = `#/assets?${q}`;
    },
    [],
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
  const liveJob = useCallback(
    (shotId: string, stage: string): LiveJob | undefined => {
      const real = live.get(`${shotId}|${stage}`);
      if (real) return real;
      const p = gpu3Pending[shotId];
      if (!p || !GPU3_COVERS[p.stage].includes(stage as Stage)) return undefined;
      const job: Job = { id: `gpu3:${shotId}:${p.stage}`, shot_id: shotId, stage: stage as Stage, seed: null, state: "queued", created_at: p.at, error: null };
      return { job, pos: 0, gpu3: true, clear: () => clearGpu3Pending(shotId) };
    },
    [live, gpu3Pending, clearGpu3Pending],
  );
  const episode = useMemo(() => episodes?.find((e) => e.number === epNum) ?? null, [episodes, epNum]);
  // T60：切到一集时它还是轻量数据 → 先换上缓存的详情（有的话），再取最新详情
  const epLoading = useRef(new Set<number>());
  useEffect(() => {
    if (!episode?.light || epLoading.current.has(episode.number)) return;
    const n = episode.number;
    const swap = (d: Episode) => setEpisodes((list) => list?.map((e) => (e.number === d.number ? d : e)) ?? list);
    const cached = detailCache.current.get(n);
    if (cached) swap(cached);
    epLoading.current.add(n);
    api.episode(n).then(
      (d) => {
        detailCache.current.set(n, d);
        swap(d);
      },
      (e: Error) => setLoadError(`第 ${n} 集加载失败：${e.message}`),
    ).finally(() => epLoading.current.delete(n));
  }, [episode]);

  // ---------------- 加载 ----------------
  // 合并并发刷新（QA30-05）：/api/episodes 约 8 MB、服务端 3–4 s；在途时不再并发再算一份（StrictMode 双挂载 / 轮询 / 改动叠加时曾 >20 s）。
  // 在途 300 ms 后才来的请求 = 期间可能有改动 → 本次结束后再刷一次；调用方 await 到的总是之后的数据。
  const epInflight = useRef<{ p: Promise<void>; t: number } | null>(null);
  const epAgain = useRef(false);
  // T60：先摘要（服务端缓存，几十 KB）+ 当前集详情（只算一集）并行；访问过的集详情缓存，切回时先显示再刷新。
  // 只有新接口不存在（404：API 未重启）时才退回旧 /api/episodes；5xx / 网络错误不退回（旧接口 8 MB 更慢），
  // 显示错误并重试（封板修复）。
  const epNumRef = useRef(epNum);
  epNumRef.current = epNum;
  const detailCache = useRef(new Map<number, Episode>());
  const fastApi = useRef<boolean | null>(null);
  const fetchEpisodes = useCallback(async (): Promise<Episode[]> => {
    const RETRY_MS = [2000, 5000];
    for (let attempt = 0; fastApi.current !== false; attempt++) {
      const n = epNumRef.current;
      try {
        const [sum, det] = await Promise.all([api.episodesSummary(), api.episode(n).catch(() => null)]);
        fastApi.current = true;
        if (det) detailCache.current.set(det.number, det);
        return sum.episodes.map((e) => (e.number === n && det ? det : e));
      } catch (e) {
        if ((e as { status?: number }).status === 404) {
          fastApi.current = false;
          break;
        }
        if (attempt >= RETRY_MS.length) throw e;
        setLoadError(`集列表加载失败，${RETRY_MS[attempt] / 1000} 秒后重试：${(e as Error).message}`);
        await new Promise((r) => setTimeout(r, RETRY_MS[attempt]));
      }
    }
    return api.episodes();
  }, []);
  const refreshEpisodes = useCallback(async () => {
    const cur = epInflight.current;
    if (cur) {
      if (Date.now() - cur.t > 300) epAgain.current = true;
      return cur.p;
    }
    const run = async () => {
      do {
        epAgain.current = false;
        try {
          setEpisodes(await fetchEpisodes());
          setLoadError(null);
        } catch (e) {
          setLoadError((e as Error).message);
        }
      } while (epAgain.current);
    };
    const p = run().finally(() => {
      epInflight.current = null;
    });
    epInflight.current = { p, t: Date.now() };
    return p;
  }, []);

  const refreshShots = useCallback(
    async (ids: string[]) => {
      const res = await Promise.allSettled(ids.map((id) => api.shot(id)));
      // 封板修复：全部失败时不换 details 引用（否则依赖 details 的 effect 会无限重拉）；失败原因记进 detailErr
      if (res.some((r) => r.status === "fulfilled"))
        setDetails((d) => {
          const next = { ...d };
          res.forEach((r) => {
            if (r.status === "fulfilled") next[r.value.summary.id] = r.value;
          });
          return next;
        });
      setDetailErr((m) => {
        let next = m;
        res.forEach((r, i) => {
          const msg = r.status === "rejected" ? String((r.reason as Error)?.message ?? r.reason) : undefined;
          if (m[ids[i]] === msg) return;
          if (next === m) next = { ...m };
          if (msg === undefined) delete next[ids[i]];
          else next[ids[i]] = msg;
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
  // UIRSI r12（W-02）：不在画布上（#/新建剧本、#/资产…）时不预取本集每镜详情（以前一开页面就多 14+ 个请求），回到画布再取
  const [onCanvas, setOnCanvas] = useState(() => !location.hash.startsWith("#/"));
  useEffect(() => {
    const on = () => setOnCanvas(!location.hash.startsWith("#/"));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    if (!epKey || !onCanvas) return;
    // UIRSI r12（W-02）：首屏只取前 4 镜详情，其余 1.8 s 后再取（浏览器每个域名同时只有 6 条连接）
    const ids = epKey.split(",");
    void refreshShots(ids.slice(0, 4));
    const later = ids.length > 4 ? window.setTimeout(() => void refreshShots(ids.slice(4)), 3000) : 0;
    const maxEp = Math.max(0, ...(episodes ?? []).map((e) => e.number)); // 末集不请求 ep61（404）
    // UIRSI r12：本集造型先取，前后两集（只在衔接提示里用）晚 2 s
    void refreshLooks([epNum]);
    const nb = window.setTimeout(() => void refreshLooks([epNum - 1, epNum + 1].filter((n) => n >= 1 && (!maxEp || n <= maxEp))), 3200);
    return () => (window.clearTimeout(later), window.clearTimeout(nb));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epKey, onCanvas]);

  // 默认选中本集第一镜
  useEffect(() => {
    if (episode && (!sel || epOfShot(sel) !== episode.number)) setSel(episode.shots[0]?.id ?? null);
  }, [episode, sel]);

  // URL hash 同步
  useEffect(() => {
    if (location.hash.startsWith("#/")) return; // W4a：#/script-create、#/models、#/assets 等页面不被镜头号覆盖
    const h = sel ?? `ep${String(epNum).padStart(2, "0")}`;
    if (location.hash !== `#${h}`) history.replaceState(null, "", `#${h}`);
    try {
      sessionStorage.setItem("ns.lastCanvas", `#${h}`); // fredw-b3：从剧本创作 / 项目页回画布时回到同一镜
    } catch {
      /* 隐私模式 */
    }
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
      // 封板修复：只回写这一步改过的字段，其余用当前值（不冲掉之后另设的尾帧等）
      const want = redo ? e.after : e.before;
      const cur = detailsRef.current[e.shotId]?.edit;
      let body = want;
      if (cur) {
        const w = want as unknown as Record<string, unknown>;
        const other = (redo ? e.before : e.after) as unknown as Record<string, unknown>;
        const merged: Record<string, unknown> = { ...cur };
        for (const k of new Set([...Object.keys(w), ...Object.keys(other)]))
          if (k !== "updated_at" && JSON.stringify(w[k] ?? null) !== JSON.stringify(other[k] ?? null)) merged[k] = w[k] ?? null;
        body = merged as unknown as ShotEdit;
      }
      const ok = await saveEdit(e.shotId, body, { quiet: true, recordUndo: false });
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
            ? `ep${String(n).padStart(2, "0")} 本集配乐已保存（英文 → 本集各镜 H3 non_diegetic_music 的默认；中文只给后期混音）`
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

  // fredw-92/W4a（项目方最新原话“成人的内容自动跳过，我们暂时不看”）：撤掉成人 / 🔴 集送 gpu3 的“我是项目方”确认；露骨红标 explicit_hold 不变

  // 规则 7：视频只在 gpu3 出。批量把「出视频」写进 gpu3 重渲队列（一条汇总提示，不逐镜弹框）
  const gpu3Video = useCallback(
    async (ids: string[]) => {
      let ok = 0;
      const bad: string[] = [];
      for (const id of ids) {
        try {
          await api.gpu3Rerender(id, "video", "");
          ok++;
          setGpu3Pending((m) => ({ ...m, [id]: { stage: "video", at: new Date().toISOString(), sig: gpu3Sig(summaryById.get(id)) } }));
        } catch (e) {
          bad.push(`${id}：${(e as Error).message}`);
        }
      }
      notify(`已请 gpu3 出视频 ${ok} 镜${bad.length ? `；失败 ${bad.length} 镜（${bad[0]}）` : "：新版本到了会出现在镜头行"}`, bad.length ? "err" : "ok");
      return ok > 0;
    },
    [notify, summaryById],
  );

  /** 请 gpu3 重出（gpu3 负责的镜头）：经桥写 gpu3 的重渲队列；last = 只重出尾帧（保留首帧） */
  const requestGpu3 = useCallback(
    (id: string, stage: Gpu3Stage, opts: { direct?: boolean } = {}) => {
      if (summaryById.get(id)?.explicit_hold) return notify(`${id}：${EXPLICIT_LABEL}，不做自动重出`, "err");
      const what = { image: "首帧（尾帧随之重编）", last: "尾帧（保留首帧）", video: "视频（保留首尾帧）", both: "首尾帧和视频" }[stage];
      const send = async () => {
        try {
          await api.gpu3Rerender(id, stage, "");
          // 本地等待标记：镜头行 / 检查器对比位 / 查看器版本条显示“已请 gpu3”，新 take 到达自动消失
          setGpu3Pending((m) => ({ ...m, [id]: { stage, at: new Date().toISOString(), sig: gpu3Sig(summaryById.get(id)) } }));
          notify(`${id} 已请 gpu3 重出${what}：新版本到了会出现在镜头行的版本条`);
          return true;
        } catch (e) {
          notify(`${id} 发给 gpu3 失败：${(e as Error).message}`, "err");
          return false;
        }
      };
      // 检查器里「保存并重出」已经看着提示词了：不再弹确认（与笔记本链一致）
      if (opts.direct) return void send();
      setConfirmReq({
        title: "请 gpu3 重出",
        lines: [
          `${id} 请 gpu3 重出${what}。`,
          "请求写进 gpu3 的重渲队列（docs/canvas.md §2），由 gpu3 系列渲染器出新 take；笔记本不出图。",
        ],
        confirmLabel: "发给 gpu3",
        onConfirm: async () => void (await send()),
      });
    },
    [notify, summaryById],
  );

  const render = useCallback(
    async (id: string, stage: Stage, seed: number | null = null) => {
      if (summaryById.get(id)?.explicit_hold) {
        notify(`${id}：${EXPLICIT_LABEL}，不做自动出图`, "err");
        return false;
      }
      if (stage === "video" && !laptopVideoEnabled()) {
        return gpu3Video([id]);
      }
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
    [notify, onJobsQueued, summaryById, gpu3Video],
  );

  const requestBatch = useCallback(
    (ids: string[], stage: Stage, onlyMissing = false) => {
      if (stage === "video" && !laptopVideoEnabled()) {
        const skipped: string[] = [];
        const run: string[] = [];
        for (const id of ids) {
          const s = summaryById.get(id);
          if (!s) continue;
          if (s.explicit_hold) skipped.push(`${id}：${EXPLICIT_LABEL}`);
          else if (!s.first_frame) skipped.push(`${id}：缺首帧`);
          else if (onlyMissing && s.video) skipped.push(`${id}：已有视频`);
          else run.push(id);
        }
        setConfirmReq({
          title: "批量出视频 · 由 gpu3 渲染",
          lines: [
            `${run.length} 镜发给 gpu3 出视频（项目规则：视频只渲染一次，全部在 gpu3；笔记本不出视频）。`,
            `镜头总时长 ${run.reduce((t, id) => t + (summaryById.get(id)?.duration?.seconds ?? 0), 0)} 秒；用各镜当前选定的首帧 / 尾帧。`,
            ...(skipped.length ? [`跳过 ${skipped.length} 镜：`, ...skipped] : []),
          ],
          confirmLabel: `发给 gpu3（${run.length} 镜）`,
          onConfirm: async () => void (run.length && (await gpu3Video(run))),
        });
        return;
      }
      const skipped: string[] = [];
      const run: string[] = [];
      for (const id of ids) {
        const s = summaryById.get(id);
        if (!s) continue;
        if (s.explicit_hold) skipped.push(`${id}：${EXPLICIT_LABEL}`);
        else if (s.owner === "gpu3") skipped.push(`${id}：gpu3 负责此镜（避免两条链），请用「请 gpu3 重出」`);
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
          // T54-B / 调研 #5：确认框写明总时长与出图位置
          `入队镜头总时长 ${run.reduce((t, id) => t + (summaryById.get(id)?.duration?.seconds ?? 0), 0)} 秒 · ${stage === "video" ? "视频" : "图片"}在本机 ComfyUI 出${stage === "video" ? "（开发者选项：本机出视频；项目规则是视频只在 gpu3 出）" : ""}`,
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
    [summaryById, notify, onJobsQueued, gpu3Video],
  );

  /** T54-B / 调研 #3：改了造型或单品后，告诉项目方影响几集几镜，并给三个选择：只更新引用 / 选中这些镜头 / 批量重出（仍走批量确认框） */
  const showAffected = useCallback(
    (r: AffectedShots, what: string) => {
      if (!r.affected_count) return notify(`${what}：不影响任何镜头`);
      const eps = new Set(r.affected_shots.map((id) => id.split("-")[0]));
      setConfirmReq({
        title: what,
        lines: [
          `影响 ${eps.size} 集 / ${r.affected_count} 镜。引用已经更新，画面要重出才会变（不会自动重渲）。`,
          r.affected_shots.slice(0, 30).join("、") + (r.affected_count > 30 ? " …" : ""),
        ],
        cancelLabel: "只更新引用",
        secondary: {
          label: "选中这些镜头",
          onClick: () => {
            setMulti(new Set(r.affected_shots));
            setView("episode");
          },
        },
        confirmLabel: `批量重出 ${r.affected_count} 镜首帧`,
        onConfirm: () => requestBatch(r.affected_shots, "image"),
      });
    },
    [notify, requestBatch, setView],
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

  // gpu3 等待标记：签名变了（新 take 到了）→ 清除并提示；超时 → 清除。等待期间每 30 s 拉一次摘要
  useEffect(() => {
    const ids = Object.keys(gpu3Pending);
    if (!ids.length || !shots.length) return;
    const now = Date.now();
    const arrived: string[] = [];
    const expired: string[] = [];
    for (const id of ids) {
      const p = gpu3Pending[id];
      const s = summaryById.get(id);
      if (!s) continue;
      if (gpu3Sig(s) !== p.sig) arrived.push(id);
      else if (now - new Date(p.at).getTime() > GPU3_PENDING_TTL) expired.push(id);
    }
    if (!arrived.length && !expired.length) return;
    setGpu3Pending((m) => {
      const n = { ...m };
      for (const id of [...arrived, ...expired]) delete n[id];
      return n;
    });
    if (arrived.length) {
      notify(`gpu3 新版本到了：${arrived.join("、")}（点版本条对比）`);
      void refreshShots(arrived.filter((id) => detailsRef.current[id]));
    }
    if (expired.length) notify(`已请 gpu3 超过 6 小时仍无新版本：${expired.join("、")}（标记已撤，可再请一次）`, "err");
  }, [gpu3Pending, shots, summaryById, notify, refreshShots]);
  const gpu3Waiting = Object.keys(gpu3Pending).length > 0;
  useEffect(() => {
    if (!gpu3Waiting) return;
    const t = setInterval(() => void refreshEpisodes(), 30000);
    return () => clearInterval(t);
  }, [gpu3Waiting, refreshEpisodes]);

  /** 检查器「重出」：已经在检查器里看着提示词了，不再弹确认，直接入队 */
  const rerender = useCallback(
    async (id: string, stage: Stage, saveFirst?: () => Promise<boolean>) => {
      if (saveFirst && !(await saveFirst())) return false;
      // gpu3 负责的镜头：保存修改后改成请 gpu3 重出（修改随请求的 edit 快照一起发过去）
      if (summaryById.get(id)?.owner === "gpu3") {
        requestGpu3(id, stage, { direct: true });
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
      if (summaryById.get(id)?.explicit_hold) return notify(`${id}：${EXPLICIT_LABEL}，不做自动出图`, "err");
      // 一镜一条链：gpu3 负责的镜头（快捷键 I/E/V 也走这里）改成请 gpu3 重出；视频一律请 gpu3（规则 7）
      if (summaryById.get(id)?.owner === "gpu3" || (stage === "video" && !laptopVideoEnabled())) return requestGpu3(id, stage);
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
      const unwatched: string[] = [];
      const noVideo: string[] = [];
      for (const id of ids) {
        const s = summaryById.get(id);
        // 审片“通过”针对视频：还没有视频的镜头不标通过（按钮说明写的就是“只对视频已完整播放过的镜头生效”）
        if (state === "passed" && s && !s.video) {
          noVideo.push(id);
          continue;
        }
        if (state === "passed" && !canPass(s)) {
          unwatched.push(id);
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
      // UIMASTER（批量通过条，项目方动作）：视频没完整看过的镜头不能通过——不只报错，直接打开串播审片停在第一镜，看完按 A 就通过（说明 + 一键解决）
      if (unwatched.length) {
        notify(`${unwatched.length} 镜视频还没完整看过，先看再通过（${unwatched.map((x) => x.replace(/^ep\d+-/, "")).join("、")}）。已为你打开串播审片，看完按 A 通过`, "err");
        if (!reviewMode) {
          select(unwatched[0]);
          setReviewMode(true);
        }
      }
      const short = (xs: string[]) => xs.map((x) => x.replace(/^ep\d+-/, "")).join("、");
      if (noVideo.length) notify(`${noVideo.length} 镜还没有视频，不能通过（${short(noVideo)}）：先在这一行点「出视频」`, "err");
      if (bad.length) {
        // 同一个原因合成一条，不逐镜重复
        const by = new Map<string, string[]>();
        for (const b of bad) { const i = b.indexOf("："); const k = i > 0 ? b.slice(i + 1) : b; by.set(k, [...(by.get(k) ?? []), i > 0 ? b.slice(0, i) : ""]); }
        for (const [why, xs] of by) notify(`${xs.length} 镜没标上（${short(xs.filter(Boolean))}）：${why}。可以再点一次`, "err");
      }
      await refreshAfter(ok.filter((id) => detailsRef.current[id]));
      return ok.length > 0;
    },
    [summaryById, canPass, notify, refreshAfter, reviewMode, select],
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
    episodes, loadError, jobs, latest, details, detailErr, epLooks, catalog, looksError,
    shots, summaryById, episode, epNum,
    // 视图
    view, setView, sel, multi, selection, setMulti, filter, setFilter,
    density, setDensity, cycleDensity, listMode, setListMode, inspectorHidden, setInspectorHidden,
    inspTab, openInspTab, assetFocus, setAssetFocus, openAssets, hlChar, setHlChar, saveEpisodeEdit,
    drawer, setDrawer, batchResults, compare, setCompare, seam, setSeam, preview, setPreview,
    viewer, setViewer, openViewer, liveJob, gpu3Pending, clearGpu3Pending,
    watched, markWatched, canPass, reviewMode, setReviewMode, canvasMode, setCanvasMode, classic, setClassic, helpOpen, setHelpOpen,
    paletteOpen, setPaletteOpen, confirmReq, setConfirmReq, rejectFor, setRejectFor, toasts, clip,
    dirtyRef,
    // 动作
    notify, refreshEpisodes, refreshShots, refreshLooks, refreshAfter, select, gotoEpisode, stepShot,
    saveEdit, undo, render, rerender, requestRender, requestGpu3, requestBatch, showAffected, requestChain, activate, setReview,
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
