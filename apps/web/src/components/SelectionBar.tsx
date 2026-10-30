import { LOCK_SUPPORTED } from "../api";
import { PASTE_FIELDS, useStudio } from "../store";

/** 多选时的批量操作条（规范 C8） */
export function SelectionBar() {
  const { multi, setMulti, requestBatch, setReview, setRejectFor, pasteEdit, clip } = useStudio();
  if (multi.size < 2) return null;
  const ids = [...multi];
  return (
    <div className="selection-bar">
      <b>已选 {ids.length} 镜</b>
      <button className="btn" onClick={() => requestBatch(ids, "image")}>批量渲染首帧</button>
      <button className="btn" onClick={() => requestBatch(ids, "video")}>批量渲染视频</button>
      <button className="btn" onClick={() => void setReview(ids, "passed")} title="只对当前视频已完整播放过的镜头生效">
        通过
      </button>
      <button className="btn" onClick={() => setRejectFor(ids)}>打回</button>
      <button className="btn" disabled={!clip} onClick={() => pasteEdit([...PASTE_FIELDS])} title="Ctrl+V">
        粘贴编辑
      </button>
      <button className="btn" disabled={!LOCK_SUPPORTED} title="待后端提供锁定接口">锁定</button>
      <button className="btn-mini" onClick={() => setMulti(new Set())}>取消选择</button>
    </div>
  );
}
