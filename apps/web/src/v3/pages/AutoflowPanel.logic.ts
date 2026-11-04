const VERDICT: Record<string, string> = {
  not_started: "还没开始", running: "正在写", awaiting_writer: "等写手交稿", awaiting_reviewer: "等核查", awaiting_owner_p1: "等你看故事线",
  held_by_p1_gate: "等你看完故事线再写", needs_patch: "正在返修", reopened: "重新打开了", stopped_in_chain: "写到一半停了", not_importable: "还有没过的项",
  blocked_by_gate: "导入前的检查没过", importable: "可以导入", imported: "已导入", awaiting_owner: "等你看", owner_direction: "等你定方向", reused: "复用", ok: "通过", pending: "等待",
  fails_left: "还有没过的项", failed: "没过", needs_writer: "等写手", dry_run: "试跑", revise_requested: "已收下修改，正在重写", waiting_p1_review: "评审中", awaiting_p1_judges: "故事线在评审", awaiting_judges: "等评委打分", voided: "已作废，重写中", p1_review_failed: "评审三轮没过，已转总调度",
};
export const zhState = (k?: string | null) => (k ? VERDICT[k] ?? "进行中" : "");

/** 提纲表单提交后通知面板切到这部剧 */
export const FLOW_EVENT = "ns:flowrun";
