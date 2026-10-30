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

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const body = await r.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new Error(msg);
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
  /** 请 gpu3 重出（经桥写 gpu3 的 rerender_queue.jsonl）；last = 只重出尾帧（保留首帧） */
  gpu3Rerender: (id: string, stage: "image" | "last" | "video" | "both", note = "") =>
    req<{ ok: boolean; request: { stage: string; note: string }; bridge: unknown }>(
      `/api/shots/${sid(id)}/gpu3-rerender`,
      json("POST", { stage, note }),
    ),
  shot: (id: string) => req<ShotDetail>(`/api/shots/${sid(id)}`),
  saveEdit: (id: string, edit: ShotEdit) => req<ShotEdit>(`/api/shots/${sid(id)}/edit`, json("PUT", edit)),
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
  boostSuggest: (id: string, which: "first" | "last") =>
    req<{ which: string; suggestion: string; model: string }>(`/api/shots/${sid(id)}/boost/suggest`, json("POST", { which })),
  activate: (id: string, stage: Stage, n: number) =>
    req<Takes>(`/api/shots/${sid(id)}/takes/${stage}/${n}/activate`, { method: "POST" }),
  review: (id: string, state: ReviewState, reason = "") =>
    req<Review>(`/api/shots/${sid(id)}/review`, json("PUT", { state, reason })),
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
