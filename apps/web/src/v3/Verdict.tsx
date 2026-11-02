// L-123（项目方 16:4x）：只有正向动作。每个待审对象（首帧 / 尾帧 / 视频）两个按钮：
//   用这张（视频：用这版）—— 一键生效，提示条 10 秒内撤销；首帧 / 尾帧 = 定稿这一版，视频 = 通过；
//   修改 —— 写一句话改（EditBox）；“换个种子再来”在框里。没被选中的版本自动留在历史里，不需要任何操作。
// 原来的“不要 + 原因”数据口径不变：改由“修改”那一句话写 /api/edits 的 feedback。
import { useState } from "react";
import { editApi } from "../ds/editdel.api";
import { showUndo } from "../ds/Undo.helpers";
import { useStudio } from "../store";
import { setLock } from "./edit/actions";
import { reloadCandidates, epOf } from "./candidates";
import { EditBox } from "./EditBox";
import "./verdict.css";

export type VStage = "first" | "last" | "video";
const STAGE_KEY = { first: "image", last: "last", video: "video" } as const;
const NAME = { first: "首帧", last: "尾帧", video: "视频" } as const;
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

export function Verdict({ shot, stage, n, size = "sm", auto, onAccept }: { shot: string; stage: VStage; n: number | null; size?: "sm" | "md"; auto?: boolean; onAccept?: () => Promise<unknown> }) {
  const st = useStudio();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  if (n == null) return null;
  const nm = NAME[stage];
  const refresh = async (ids: string[]) => {
    reloadCandidates(epOf(shot));
    await st.refreshAfter(ids);
  };
  const accept = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setBusy(true);
    try {
      if (onAccept) await onAccept();
      else if (stage === "video") {
        await st.setReview([shot], "passed");
        showUndo(`已用 ${shot.split("-")[1]} 视频 #${n}`, async () => void (await st.setReview([shot], "unreviewed")));
      } else if (await setLock(shot, stage, n, true, () => undefined, refresh)) {
        showUndo(`已用 ${shot.split("-")[1]} ${nm} #${n}`, async () => void (await setLock(shot, stage, n, false, () => undefined, refresh)));
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className={`vd vd-${size}`} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      {auto ? (
        <span className="vd-auto" title="这一版系统检查通过，按你的授权已自动采用；想改点“修改”">
          已自动采用（可改）
        </span>
      ) : (
        <button type="button" className="vd-yes" disabled={busy} onClick={(e) => void accept(e)} title={`${stage === "video" ? "通过这版视频" : `定稿这张${nm}`}（10 秒内可撤销）`}>
          {stage === "video" ? "用这版" : "用这张"}
        </button>
      )}
      <button type="button" className="vd-edit" disabled={busy} onClick={() => setOpen(true)} title={`写一句话改这${stage === "video" ? "版" : "张"}${nm}`}>
        修改
      </button>
      {open && (
        <EditBox
          title={`修改 ${shot.split("-")[1]} ${nm} #${n}`}
          suggestions={EDIT_SUGGESTIONS[stage]}
          onSubmit={async (text, chips) => {
            await submitShotEdit(shot, stage, n, text, chips);
            await refresh([shot]);
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </span>
  );
}
