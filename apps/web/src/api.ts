import type {
  AssetCatalog,
  CharacterAssets,
  EpisodeEdit,
  GenerateRequest,
  ImportReport,
  ItemImage,
  Look,
  ShotRefs,
  BatchResult,
  Episode,
  AffectedShots,
  EpisodeLooks,
  Job,
  LookCatalog,
  LookPatch,
  Review,
  ReviewState,
  ShotDetail,
  ShotEdit,
  ShotLooks,
  Stage,
  Takes,
  SopEpisode,
} from "./types";

/** 后端 detail → 文字（422 是数组，不能直接当字符串；封板修复：对话框 capi 共用） */
export const detailText = (detail: unknown): string => (typeof detail === "string" ? detail : JSON.stringify(detail));

/** 浏览器的英文网络错误（Failed to fetch 等）统一成大白话；提交类和读取类分开说（NAVIA） */
export const NET_DOWN_WRITE = "网络不通，没有提交上，请再点一次";
export const NET_DOWN_READ = "网络不通，读不到，稍后会自动重试";
export const plainNetError = (msg: string, write = true) => msg.replace(/Failed to fetch|NetworkError when attempting to fetch resource\.?|Load failed|network error/gi, write ? NET_DOWN_WRITE : NET_DOWN_READ);

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init).catch((e: unknown) => {
    throw Object.assign(new Error(plainNetError(String((e as Error)?.message ?? e), (init?.method ?? "GET") !== "GET")), { status: 0 });
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) msg = detailText(body.detail);
    } catch {
      /* 非 JSON 错误体 */
    }
    // 带上 HTTP 状态码：调用方按状态判断（例如只有 404 才退回旧接口），不再靠匹配错误文字
    throw Object.assign(new Error(msg), { status: r.status });
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const sid = encodeURIComponent;

export const api = {
  episodes: () => req<Episode[]>("/api/episodes"),
  /** T60：集列表 + 每集摘要 + 每镜轻字段（服务端缓存，≤15 s 旧） */
  episodesSummary: () => req<{ as_of: number; build_s: number | null; episodes: Episode[] }>("/api/episodes/summary"),
  /** T60：单集完整数据（现算） */
  episode: (n: number) => req<Episode>(`/api/episodes/${n}`),
  /** 请 gpu3 重出（经桥写 gpu3 的 rerender_queue.jsonl）；last = 只重出尾帧（保留首帧） */
  // 封板修复（项目方 2026-10-30）：成人 / 🔴 集镜头需项目方本人确认，带 by:"owner"；否则后端 403
  gpu3Rerender: (id: string, stage: "image" | "last" | "video" | "both", note = "") =>
    req<{ ok: boolean; request: { stage: string; note: string; id?: string | null }; bridge: unknown; request_id?: string | null }>(
      `/api/shots/${sid(id)}/gpu3-rerender`,
      json("POST", { stage, note }), // W4a：成人镜不再要 by:"owner"（项目方：成人内容暂时不看）
    ),
  shot: (id: string) => req<ShotDetail>(`/api/shots/${sid(id)}`),
  saveEdit: (id: string, edit: ShotEdit) => req<ShotEdit>(`/api/shots/${sid(id)}/edit`, json("PUT", edit)),
  /** 项目方修改 H3 提示词（只在 H3 面板由项目方亲自确认后调用；by 固定 "owner"，note 必填） */
  putH3Override: (id: string, body: { body?: string | null; soundscape?: string | null; note: string; clear?: boolean; base_sha?: string | null }) =>
    req<{ status?: string; failed?: string[]; delivered?: boolean | null; delivery?: { ok: boolean; error?: string | null; code?: number | null } }>(
      `/api/shots/${sid(id)}/h3-override`,
      json("PUT", { ...body, by: "owner" }),
    ),
  /** 封板修复：未送达 gpu3 时原样重发（项目方点按钮） */
  gpu3Resend: (id: string, what: "h3_edit" | "override", ruleId?: string) =>
    req<{ delivered: boolean; delivery: { ok: boolean; error?: string | null; code?: number | null } }>(
      `/api/shots/${sid(id)}/gpu3-resend`,
      json("POST", { what, rule_id: ruleId ?? null, by: "owner" }),
    ),
  uploadLastFrame: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ last_frame: string; url: string | null }>(`/api/shots/${sid(id)}/last-frame`, {
      method: "POST",
      body: fd,
    });
  },
  render: (id: string, stage: Stage, seed: number | null) =>
    req<Job>(`/api/shots/${sid(id)}/render`, json("POST", { stage, seed })),
  renderBatch: (shot_ids: string[], stage: Stage, only_missing = false) =>
    req<BatchResult[]>("/api/render-batch", json("POST", { shot_ids, stage, only_missing })),
  uploadFirstFrame: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ n: number; url: string | null }>(`/api/shots/${sid(id)}/first-frame`, { method: "POST", body: fd });
  },
  episodeEdit: (n: number) => req<EpisodeEdit>(`/api/episodes/${n}/edit`),
  saveEpisodeEdit: (n: number, body: { boost_first?: string | null; boost_last?: string | null; music?: string | null }) =>
    req<EpisodeEdit>(`/api/episodes/${n}/edit`, json("PUT", body)),
  /** llm = 每处 ⚙ 覆盖（契约 §A）；不传 = 用途 director_boost 的默认 */
  boostSuggest: (id: string, which: "first" | "last", llm?: { provider: string; model: string; params?: object } | null) =>
    req<{ which: string; suggestion: string; model: string }>(`/api/shots/${sid(id)}/boost/suggest`, json("POST", llm ? { which, llm } : { which })),
  activate: (id: string, stage: Stage, n: number) =>
    req<Takes>(`/api/shots/${sid(id)}/takes/${stage}/${n}/activate`, { method: "POST" }),
  /** P5 M2（PLAN §2.4 调用点 5）：定稿 / 驳回双写——新 ns2 队列（/api/overview 的 final 唯一来源，成人镜触发也在这里清）
   *  + 旧接口（画布角标仍读旧 review.json，M3 下线旧 API 时去掉这一半）。新系统写不进去 = 报错，不静默只写一半 */
  review: async (id: string, state: ReviewState, reason = "") => {
    const r = await req<Review>(`/api/shots/${sid(id)}/review`, json("PUT", { state, reason }));
    await req<unknown>(`/ns2/api/shots/${sid(id)}/review`, json("PUT", { state, reason: reason || null }));
    return r;
  },
  jobs: () => req<Job[]>("/api/jobs"),
  /** SOP 阶段 / 关口（只读） */
  sopEpisode: (n: number) => req<SopEpisode>(`/api/sop/episode/${n}`),

  looks: {
    catalog: () => req<LookCatalog>("/api/looks"),
    episode: (n: number) => req<EpisodeLooks>(`/api/looks/episodes/${n}`),
    shot: (id: string) => req<ShotLooks>(`/api/looks/shots/${sid(id)}`),
    /** 本镜覆盖：body 里出现的字段覆盖，显式 null 清空，缺省保留 */
    patchShot: (id: string, character: string, patch: LookPatch) =>
      req<AffectedShots>(`/api/looks/shots/${sid(id)}/${sid(character)}`, json("PUT", patch)),
    clearShot: (id: string, character: string) =>
      req<AffectedShots>(`/api/looks/shots/${sid(id)}/${sid(character)}`, { method: "DELETE" }),
    refs: (id: string) => req<ShotRefs>(`/api/looks/shots/${sid(id)}/refs`),
    putLook: (look: Look) => req<AffectedShots>(`/api/looks/looks/${sid(look.id)}`, json("PUT", look)),
    setDefault: (character: string, look_id: string) =>
      req<AffectedShots>(`/api/looks/characters/${sid(character)}/default`, json("PUT", { look_id })),
    episodeRange: (character: string, episodes: string, patch: LookPatch | null) =>
      req<AffectedShots>(`/api/looks/episodes-range/${sid(character)}`, json("PUT", { episodes, patch })),
    schedule: () =>
      req<{
        character_defaults: Record<string, string>;
        episodes: Record<string, Record<string, LookPatch>>;
        shot_overrides: Record<string, Record<string, LookPatch>>;
      }>("/api/look-schedule"),
    putTags: (itemId: string, tags: string[]) =>
      req<{ id: string; tags: string[] }>(`/api/looks/wardrobe/items/${sid(itemId)}/tags`, json("PUT", { tags })),
    uploadItemImage: (itemId: string, file: File, variant: string) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("variant", variant);
      return req<AffectedShots & { image: ItemImage }>(`/api/looks/wardrobe/items/${sid(itemId)}/images`, {
        method: "POST",
        body: fd,
      });
    },
  },

  assets: {
    list: () => req<AssetCatalog>("/api/assets/characters"),
    character: (id: string) => req<CharacterAssets>(`/api/assets/characters/${sid(id)}`),
    importManifest: (id: string) => req<ImportReport>(`/api/assets/characters/${sid(id)}/import`, { method: "POST" }),
    generate: (id: string, body: GenerateRequest) => req<Job>(`/api/assets/characters/${sid(id)}/generate`, json("POST", body)),
  },


  /**
   * TODO(backend): 以下接口后端尚未提供。UI 已按规范接好，接口上线后只改这里。
   */
  pending: {
    /** 锁定 / 解锁镜头（锁定的镜头不参与批量渲染）。规范 C9。 */
    setLock: async (_id: string, _locked: boolean): Promise<{ locked: boolean }> => {
      throw new Error("后端尚未提供锁定接口");
    },
  },
};

/** 后端是否已提供锁定接口；上线后改成 true，按钮即可用 */
export const LOCK_SUPPORTED = false;

/** 后端 C：Qwen 信箱代理（内容原样转发，画布不读不改）+ T44 ComfyUI 锁状态 */
type QT = import("./types").QwenTask;
export const qwenApi = {
  health: () => req<import("./types").QwenHealth>("/api/qwen/health"),
  create: (text: string, meta: import("./types").QwenMeta) => req<QT>("/api/qwen/tasks", json("POST", { text, meta })),
  get: (id: string) => req<QT>(`/api/qwen/tasks/${sid(id)}`),
  list: (q: { shot?: string; project?: string; episode?: string | number; kind?: string; refresh?: boolean; limit?: number } = {}) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v !== undefined && p.set(k, String(v)));
    return req<import("./types").QwenTaskList>(`/api/qwen/tasks?${p}`);
  },
  files: (id: string) => req<unknown>(`/api/qwen/tasks/${sid(id)}/files`),
  fileUrl: (id: string, path: string) =>
    `/api/qwen/tasks/${sid(id)}/files/${path.split("/").map(encodeURIComponent).join("/")}`,
  scriptFetch: (id: string, project?: string) =>
    req<import("./types").QwenScriptInfo & { report: unknown }>(`/api/qwen/tasks/${sid(id)}/script/fetch`, json("POST", { project })),
  scriptRepair: (id: string) => req<QT>(`/api/qwen/tasks/${sid(id)}/script/repair`, { method: "POST" }),
  /** 只在项目方点「导入」时调用 */
  scriptImport: (id: string, project?: string) =>
    req<{ ok: boolean; project: string; at: string; out: string; sha256: string; log: string }>(
      `/api/qwen/tasks/${sid(id)}/script/import`, json("POST", { confirm: true, by: "owner", project })),
  comfyLock: () => req<import("./types").ComfyLock>("/api/comfy-lock"),
  renderBackend: () => req<import("./types").RenderBackend>("/api/render-backend"),
};

/** 「请 gpu3 重出」请求进度：桥可达读桥 /queue，否则读镜像 jsonl（POST gpu3-rerender 的响应带 request_id） */
export const gpu3RequestsApi = {
  list: (shots: string[], limit = 20) =>
    req<import("./types").Gpu3Request[]>(
      `/api/gpu3/requests?shots=${shots.map(encodeURIComponent).join(",")}&limit=${limit}`),
};

/** 人物管理页（fredw-25）：新建 / 改名 / 归档 / 上传图片 */
export const manageApi = {
  people: () => req<import("./types").PeopleList>("/api/people"),
  createPerson: (b: { id: string; name: string; role?: string; notes?: string }) =>
    req<import("./types").Person>("/api/people", json("POST", b)),
  updatePerson: (id: string, b: { name?: string; role?: string; notes?: string; archived?: boolean }) =>
    req<import("./types").Person>(`/api/people/${sid(id)}`, json("PUT", b)),
  upload: (id: string, target: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("target", target);
    return req<{ file: string; url: string | null; kind: string }>(`/api/people/${sid(id)}/upload`, { method: "POST", body: fd });
  },
};
