// L-123（项目方 16:4x）：只有正向动作。每个待审对象（首帧 / 尾帧 / 视频）两个按钮：
//   用这张（视频：用这版）—— 一键生效，提示条 10 秒内撤销；首帧 / 尾帧 = 定稿这一版，视频 = 通过；
//   修改 —— 写一句话改（EditBox）；“换个种子再来”在框里。没被选中的版本自动留在历史里，不需要任何操作。
// 原来的“不要 + 原因”数据口径不变：改由“修改”那一句话写 /api/edits 的 feedback。
import { useState } from "react";
import { showUndo } from "../ds/Undo.helpers";
import { useStudio } from "../store";
import { setLock } from "./edit/actions";
import { reloadCandidates, epOf } from "./candidates";
import { EditBox } from "./EditBox";
import { EDIT_SUGGESTIONS, NAME, submitShotEdit, type VStage } from "./Verdict.helpers";
import "./verdict.css";

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
