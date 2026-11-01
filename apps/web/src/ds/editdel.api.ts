// PW-019：从 ds/editdel.tsx 挪出来的接口与小工具（组件文件只导出组件，热更新才不会整页重载）。
/* ================================================================ API */
export type EditType = "image" | "video" | "script" | "prompt" | "asset";
export type TrashType = "story_run" | "import_candidate" | "take" | "cut" | "asset_version" | "asset_ref" | "asset_gen" | "asset" | "edit_version" | "sheet_candidate" | "prop";
export type Box = [number, number, number, number];
export interface EditPlan {
  understanding?: string;
  action: string;
  instruction?: string;
  region?: Box | null;
  strength?: string;
  use_identity_ref?: boolean;
  lock_conflicts?: { rule: string; message: string; level?: string }[];
  fixes?: string[];
  notes?: string;
  rewrite_brief?: string;
}
export interface EditItem {
  edit_id: string;
  type: EditType;
  id: string;
  feedback: string;
  status: "planning" | "planned" | "blocked" | "running" | "done" | "proposed" | "adopted" | "rejected" | "rolled_back" | "failed" | "cancelled" | "contract_failed" | "base_rejected";
  plan?: EditPlan;
  planner?: { model?: string; cost_usd?: number | null; seconds?: number };
  result?: {
    kind?: "take" | "chain" | "proposal";
    job_id?: string;
    url?: string | null;
    take_n?: number;
    version?: number;
    text?: string;
    diff?: string;
    status?: string;
    chain_check?: { ok: boolean | null; error?: string } | null;
    lock_checks?: { rule: string; message: string }[];
    engine?: string;
    preflight?: { status?: string; reasons?: string[] };
    attempts?: { k: number; change?: string; skipped?: string; engine?: string; ok?: boolean; failed?: string[]; reasons?: string[] }[];
    contract_failed?: boolean;
    message?: string;
    postflight?: { status?: string; ok?: boolean; reasons?: string[]; detail?: string; items?: { id: string; status: string }[] };
  };
  job?: { state?: string; eta_s?: number; started_at?: string; error?: string };
  error?: string;
  created_at?: string;
  learning?: { key: string; count: number; draft: string | null; rule_id?: string } | null;
}
export interface TrashImpact {
  name: string;
  type_label: string;
  files: string[];
  blocked: string[];
  confirm: string[];
  notes: string[];
  needs_confirm: boolean;
  can_delete: boolean;
}
export interface TrashEntry {
  entry_id: string;
  type: TrashType;
  type_label: string;
  id: string;
  name: string;
  day: string;
  deleted_at: string;
  by?: string | null;
  reason?: string;
  state: "trashed" | "restored" | "purged";
  files: { from: string; to: string }[];
  preview?: string | null;
}

export async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const d = body?.detail;
    const msg = typeof d === "string" ? d : d?.message ? `${d.message}` : `${r.status} ${r.statusText}`;
    throw Object.assign(new Error(msg), { status: r.status, detail: d });
  }
  return body as T;
}
export const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const enc = encodeURIComponent;

export const editApi = {
  create: (b: { type: EditType; id: string; feedback: string; annotations?: unknown; version?: number; gpu?: string | number; dry_run?: boolean; plan?: EditPlan; by?: string; engine?: string }) =>
    call<EditItem>("/api/edits", post(b)),
  get: (id: string) => call<EditItem>(`/api/edits/${id}`),
  list: (type?: string, id?: string, limit = 20) => call<{ edits: EditItem[] }>(`/api/edits?type=${enc(type ?? "")}&id=${enc(id ?? "")}&limit=${limit}`),
  adopt: (id: string, by = "owner") => call<EditItem>(`/api/edits/${id}/adopt`, post({ by })),
  reject: (id: string, reason?: string) => call<EditItem>(`/api/edits/${id}/reject`, post({ reason })),
  rollback: (id: string) => call<EditItem>(`/api/edits/${id}/rollback`, post({})),
  engines: () => call<{ default: string; engines: { id: string; label: string; enabled: boolean; note?: string }[] }>("/api/edits/engines"),
  versions: (type: string, id: string) => call<{ kind: string; current: number | null; versions: { v?: number; n?: number; url?: string | null; label?: string }[] }>(`/api/edits/versions?type=${enc(type)}&id=${enc(id)}`),
};
export const trashApi = {
  impact: (type: TrashType, id: string) => call<TrashImpact>(`/api/trash/impact?type=${enc(type)}&id=${enc(id)}`),
  remove: (type: TrashType, id: string, confirm = false, by = "owner", reason = "") =>
    call<TrashEntry>(`/api/trash/object?type=${enc(type)}&id=${enc(id)}&confirm=${confirm}&by=${enc(by)}&reason=${enc(reason)}`, { method: "DELETE" }),
  list: (include_purged = false) => call<{ entries: TrashEntry[] }>(`/api/trash?include_purged=${include_purged}`),
  restore: (entry: string) => call<TrashEntry>(`/api/trash/${entry}/restore`, post({})),
  /** 永久删除：登录的项目方本人（后端从会话取身份）+ 界面二次确认 */
  purge: (entry: string) => call<{ ok: boolean }>(`/api/trash/${entry}/purge`, post({ confirm: true, by: "owner" })),
};

/** 浏览器地址 → 后端对象路径：/files/x → data/x；/api/assets/file?path=x → x；/api/thumb?…path=… 同理 */
export function relFromUrl(url?: string | null): string | null {
  if (!url) return null;
  try {
    const u = new URL(url, location.origin);
    const p = u.searchParams.get("path") || u.searchParams.get("src");
    if (p) return relFromUrl(p) ?? p;
    if (u.pathname.startsWith("/files/")) return "data/" + decodeURIComponent(u.pathname.slice(7));
  } catch {
    /* 非 URL */
  }
  return null;
}
