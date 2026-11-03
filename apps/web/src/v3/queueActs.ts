// W5 UIUX 11-03（C-09 / L-123 / L-134）：待办每条只给两个动作——“批准 / 用这张”+“修改”。
// 后端选项（同意 / 不同意 / 稍后、候选 + 稍后）在这里折成两个：
//   正向（approve / pass / 推荐项）→ 主按钮“批准”（挑选类 = “用这张”）；
//   反向（reject / fail …）→ “修改”：必须写一句话怎么改，那句话就是理由（学习数据照旧写进后端）；
//   “稍后”不做按钮：不点就是稍后，条目留在待办里。
// 写作闸门（gate）没有选项：两个按钮都是跳转到那一页（那一页上有“用这版 / 修改”）。
import type { QueueItem } from "./ownerQueue";
import { plainText } from "./plainWords";

/** 选项按钮：ask = 输入框提示，submit = 提交按钮文案（不给就用通用的“想怎么改？写一句话 / 提交修改”） */
export type Act = { kind: "choice"; key: string; label: string; ask?: string; submit?: string } | { kind: "link"; href: string; label: string } | { kind: "none"; label: string; why: string };

const POS = ["approve", "pass", "use", "ok", "yes", "accept", "confirm", "agree"];
const NEG = ["reject", "fail", "revise", "no", "redo", "edit", "deny"];
const LATER = ["later", "skip", "defer"];

/** W5b（A5 P2-2）：拍板类（decide：花钱 / 授权 …）的“修改”= 要求修改 + 一句话理由。
 *  后端字段口径（POST /api/owner/decide）：choice = 后端的反向选项（reject，后端记作“不同意”），reason = “要求修改：<那句话>”。
 *  也就是：这次不按原方案批准，按这句话改了再来——不是“不要了”。 */
export const DECIDE_EDIT = {
  label: "要求修改",
  ask: "要求怎么改？写一句理由（提交 = 这次先不批准，按这句话改）",
  submit: "提交：要求修改",
  prefix: "要求修改：",
} as const;

/** 提交给后端的 reason：拍板类的“修改”统一带“要求修改：”前缀（后端记录里一眼看出是要求修改而不是否决） */
export function editReason(it: QueueItem, choice: string, reason: string): string {
  const r = reason.trim();
  if (it.kind !== "decide" || !NEG.includes(choice) || !r) return r;
  return r.startsWith(DECIDE_EDIT.prefix) ? r : DECIDE_EDIT.prefix + r;
}

export function twoActs(it: QueueItem): { use: Act; edit: Act } {
  const link = it.link || (it.sid ? `#${it.sid}` : null);
  if (it.kind === "gate") {
    const href = it.link ?? "#/queue";
    return { use: { kind: "link", href, label: "去看 · 用这版" }, edit: { kind: "link", href, label: "修改" } };
  }
  const opts = (it.options ?? []).filter((o) => !LATER.includes(o.key));
  const editLink: Act = link ? { kind: "link", href: link, label: "修改" } : { kind: "none", label: "修改", why: "这一条没有对应的页面，请在详情里写一句话" };
  if (it.kind === "pick") {
    const key = it.recommend?.choice ?? opts[0]?.key;
    const o = opts.find((x) => x.key === key);
    return { use: o ? { kind: "choice", key: o.key, label: "用这张" } : link ? { kind: "link", href: link, label: "去挑" } : { kind: "none", label: "用这张", why: "没有候选" }, edit: editLink };
  }
  const pos = opts.find((o) => POS.includes(o.key)) ?? opts.find((o) => o.key === it.recommend?.choice && !NEG.includes(o.key)) ?? opts.find((o) => !NEG.includes(o.key));
  const neg = opts.find((o) => NEG.includes(o.key));
  return {
    use: pos ? { kind: "choice", key: pos.key, label: POS.includes(pos.key) ? "批准" : `用“${pos.label}”` } : link ? { kind: "link", href: link, label: "去处理" } : { kind: "none", label: "批准", why: "没有可选的动作" },
    edit: neg
      ? it.kind === "decide"
        ? { kind: "choice", key: neg.key, label: DECIDE_EDIT.label, ask: DECIDE_EDIT.ask, submit: DECIDE_EDIT.submit }
        : { kind: "choice", key: neg.key, label: "修改" }
      : editLink,
  };
}

/** 一条待办的一句人话（标题 + 为什么找你），不露命令行 / 文件路径 */
export function itemSentence(it: QueueItem): string {
  const d = (it.detail || "").replace(/`[^`]*`/g, "").replace(/(uv run|python|tools\/|data\/|\.py\b|\.json\b)[^\s，。；]*/g, "").replace(/\s+/g, " ").trim();
  const p = plainText(d);
  return p.length > 120 ? p.slice(0, 119) + "…" : p;
}
