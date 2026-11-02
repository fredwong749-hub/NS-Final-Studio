// L-123（项目方 16:4x：“去掉这个逻辑，我不太喜欢什么要这个，不要那个”）：资产卡只有两个动作——“用这张”和“修改”。
// 没选中的图不需要任何操作，留在候选 / 历史里；界面不再有“不要 / 已标不要 / 原因弹框”。
// “修改”：父组件给 onEdit 就打开它自己的修改面板（人物页：带装备图的那个）；没给就用 EditBox 写一句话。
// 原来“不要 + 原因”喂学习环的数据，现在由“修改”那一句话提供：写 /api/edits（feedback）+ 兼容的 /api/asset-rejects 记录（口径不变）。
// 后端 reject 接口保留给系统内部和自动闸门。
import { useState } from "react";
import { EditBox } from "../EditBox";
import "./verdict.css";

export type RejectKind = "face" | "sheet" | "scene_plate" | "item_image";
const SUGGEST: Record<RejectKind, string[]> = {
  face: ["脸更像本人", "脸型再改一点", "妆淡一点", "表情自然一点", "更写实", "画质更清晰"],
  sheet: ["衣服按设定", "鞋按设定", "饰品按设定", "身材比例再好看一点", "脸更像本人", "画质更清晰"],
  scene_plate: ["更像剧本里的地方", "光线再调", "更干净一点", "去掉人影", "画质更清晰"],
  item_image: ["就是这一件", "颜色再准一点", "换个角度", "背景干净一点", "画质更清晰"],
};

export type Rejected = { reasons: string[]; note: string } | null | undefined;

/** “修改”的一句话 → 学习环（/api/edits feedback + 兼容 asset-rejects 记录）；失败不挡出图 */
function toLearning(kind: RejectKind, file: string, cid: string | undefined, text: string, chips: string[]) {
  void fetch("/api/edits", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ type: "image", id: `file:${file}`, feedback: text, dry_run: false }) }).catch(() => undefined);
  void fetch("/api/asset-rejects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, file, cid, reasons: chips, note: text, redo: true }) }).catch(() => undefined);
}

export function Verdict({
  kind,
  file,
  label,
  current,
  cid,
  busy,
  onUse,
  onEdit,
  onChanged,
  notify,
}: {
  kind: RejectKind;
  file: string;
  label: string;
  current: boolean;
  /** 兼容旧调用：不再使用 */
  rejected?: Rejected;
  cid?: string;
  busy?: boolean;
  /** 不给 = 这类对象没有“用这张”（例如单品附图） */
  onUse?: () => void;
  /** 给了就用父组件自己的“修改”面板 */
  onEdit?: () => void;
  onChanged?: () => void;
  notify?: (text: string, undo?: () => Promise<unknown>, err?: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="vd">
      {current ? (
        <span className="vd-cur">当前</span>
      ) : onUse ? (
        <button className="vd-use" disabled={busy} onClick={onUse} title={`用这张作为${label}（10 秒内可撤销）`}>
          用这张
        </button>
      ) : null}
      <button className="vd-edit" disabled={busy} onClick={() => (onEdit ? onEdit() : setOpen(true))} title={`写一句话改${label}`}>
        修改
      </button>
      {open && (
        <EditBox
          title={`修改 · ${label}`}
          suggestions={SUGGEST[kind]}
          onSubmit={async (text, chips) => {
            toLearning(kind, file, cid, text || "同样的要求，换个种子再出", chips);
            notify?.(text ? "已提交修改，出好后在候选里" : "已换个种子再出，出好后在候选里");
            onChanged?.();
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}
