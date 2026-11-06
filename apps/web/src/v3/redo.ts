// L-215/216“重做”：每镜首帧 / 尾帧 / 视频各一个，点一下就交给系统重出（不弹确认、不来回）。
// 后端 POST /api/owner/redo 只认登录的项目方本人，走 producer 现成的重出通道（by = 项目方（重做按钮））。
// 成人镜也一样只回文字，不回图。
export type RedoKind = "first" | "last" | "video";
export type RedoRes = { ok: boolean; obj?: string; queued?: boolean; adult?: boolean; say?: string };

export const REDO_WORD: Record<RedoKind, string> = { first: "首帧", last: "尾帧", video: "视频" };

export async function redoShot(shot: string, kind: RedoKind, run?: string): Promise<RedoRes> {
  const r = await fetch("/api/owner/redo", {
    method: "POST",
    headers: { "content-type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(run ? { run, shot, kind } : { shot, kind }),
  });
  if (!r.ok) {
    let msg = r.status === 403 ? "要用项目方本人的账号登录才能重做" : "没交出去，请再点一次";
    try {
      const j = (await r.json()) as { detail?: string };
      if (j?.detail && r.status !== 403) msg = j.detail;
    } catch {
      /* 读不出原因就用默认那句 */
    }
    throw new Error(msg);
  }
  return (await r.json()) as RedoRes;
}
