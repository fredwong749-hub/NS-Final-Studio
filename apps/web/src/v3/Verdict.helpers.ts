import { editApi } from "../ds/editdel.api";

export type VStage = "first" | "last" | "video";
const STAGE_KEY = { first: "image", last: "last", video: "video" } as const;
export const NAME = { first: "首帧", last: "尾帧", video: "视频" } as const;
/** “修改”里的建议 chip（正向措辞；原来“不要”的原因词表改写而来，点一下追加到那句话里） */
export const EDIT_SUGGESTIONS: Record<VStage, string[]> = {
  first: ["脸更像本人", "手 / 手指画自然", "衣服鞋子按设定", "换个构图 / 景别", "表情自然一点", "更写实", "场景按剧本"],
  last: ["和首帧接得上", "脸更像本人", "手 / 手指画自然", "动作结束状态按剧本", "更写实"],
  video: ["动作更自然", "脸保持不变", "手 / 手指别崩", "镜头运动按剧本", "节奏快一点 / 慢一点", "声音再对一下"],
};

/** 镜头“修改”的提交。首帧 / 尾帧：只把这条修改原样记下（后端立即 202，改写 / 检查 / 排队都在后台，失败也不拒收），
 *  格子上马上显示“排队中”（出图页读 /api/frames-index 的 edit 字段）。视频仍走 /api/edits。 */
export async function submitShotEdit(shot: string, stage: VStage, n: number, text: string, chips: string[] = []) {
  const nm = NAME[stage];
  if (stage === "video") {
    await editApi.create({ type: "video", id: `take:${shot}/${STAGE_KEY[stage]}/${n}`, feedback: text || `同样的要求，换个种子再出一版${nm}`, by: "owner" });
    return;
  }
  let r: Response;
  try {
    r = await fetch(`/api/shots/${encodeURIComponent(shot)}/frame-edit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage, n, text, chips }) });
  } catch {
    throw new Error("网络不通，没有记下来，请再点一次“生成”");
  }
  if (!r.ok) throw new Error("没有记下来，请再点一次“生成”");
  window.dispatchEvent(new Event("ns-frames-refresh"));
}
