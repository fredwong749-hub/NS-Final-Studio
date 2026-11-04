import { useCallback, useEffect, useState } from "react";
import type { AFlow } from "./AutoflowPanel";

/** 轮到项目方看：只有 verdict = 等你看故事线（= 评审过了门槛）才给按钮；其他状态一律不显示（W-25：不能绕过评审门槛） */
export function canShowP1(d: AFlow | null | undefined): boolean {
  if (!d) return false;
  // 总调度把低于门槛的稿转给你定方向：你可以看，也可以拍板
  if (d.verdict === "owner_direction") return d.owner_gates?.gates?.P1?.status !== "revise_requested";
  return d.verdict === "awaiting_owner_p1" && d.p1_review?.latest?.passed !== false && d.owner_gates?.gates?.P1?.status !== "revise_requested";
}

/** 现在是第几轮：上一轮没过 → 下一轮；上一轮还在评（没出分）→ 就是这一轮 */
export function p1Round(d: AFlow): number {
  const l = d.p1_review?.latest;
  return l ? (l.passed === false ? l.n + 1 : l.n) : 1;
}

/** 故事线闸门的唯一状态函数：链条节点、P1 段标签、页头、左侧列表、面板状态行都用它（没走写作流程 = null）。
 *  tone：gray 在进行 / amber 要有人处理 / green 已定。最后一轮按后端 threshold.max_rounds 判断，不写死。 */
export type P1Status = { key: "direction" | "writer" | "revising" | "judging" | "look" | "approved" | "handoff" | "rewrite"; text: string; tone: "gray" | "amber" | "green"; short: string };
export function p1Status(d: AFlow | null | undefined): P1Status | null {
  const r = p1StatusLong(d);
  if (!r) return null;
  const n = d ? p1Round(d) : 1;
  // 短词：给左侧列表这种窄地方用（剧名一行要完整，状态放第二行）
  const short: Record<P1Status["key"], string> = { writer: "写手在写", revising: `返修第${n}稿`, judging: `评审第${n}稿`, look: "等你看", direction: "等你定方向", approved: "已用这版", handoff: "转总调度", rewrite: "重写中" };
  return { ...r, short: short[r.key] };
}
function p1StatusLong(d: AFlow | null | undefined): Omit<P1Status, "short"> | null {
  if (!d || !d.stages?.some((s) => s.id === "P1G")) return null;
  const gate = d.owner_gates?.gates?.P1?.status;
  const max = d.p1_review?.threshold?.max_rounds ?? 3;
  const n = p1Round(d);
  const last = n >= max ? "，最后一轮" : "";
  if (gate === "approved") return { key: "approved", text: "已用这版", tone: "green" };
  if (d.verdict === "p1_review_failed") return { key: "handoff", text: "评审没过，转总调度", tone: "amber" };
  if (d.verdict === "owner_direction") return { key: "direction", text: "等你定方向", tone: "amber" };
  if (gate === "revise_requested") return { key: "rewrite", text: "按你的修改重写中", tone: "gray" };
  if (canShowP1(d)) return { key: "look", text: "等你看", tone: "amber" };
  if (d.verdict === "awaiting_p1_judges" || d.verdict === "waiting_p1_review") return { key: "judging", text: `评审中，第 ${n} 稿${last}`, tone: "gray" };
  if (d.verdict === "awaiting_writer") {
    const failed = d.p1_review?.latest?.passed === false;
    return failed ? { key: "revising", text: `返修中，第 ${n} 稿${last}`, tone: "gray" } : { key: "writer", text: "写手在写", tone: "gray" };
  }
  return null;
}

/** 故事线还在评审 / 返修（没过门槛、也没点“用这版”）：页面上的节点写“评审中”，“通过”只有过了门槛才能用 */
export function p1InReview(d: AFlow | null | undefined): boolean {
  return !!d && !!d.stages?.some((s) => s.id === "P1G") && d.owner_gates?.gates?.P1?.status !== "approved" && !canShowP1(d) && d.verdict !== "p1_review_failed";
}

/** 项目方拍板前要知道的“还没写完”的地方：文字从 /status 的 p1_owner_hold_fields（如 episodes[2].logline）生成，不写死是哪一集 */
const HOLD_FIELD: Record<string, string> = { logline: "一句简介", title: "标题", owner_line: "一句话", premise: "总简介" };
export function holdText(fields?: string[] | null): string {
  if (!fields?.length) return "";
  const parts = fields.map((f) => {
    const m = /^episodes\[(\d+)\]\.(\w+)$/.exec(f);
    return m ? `第 ${Number(m[1]) + 1} 集${HOLD_FIELD[m[2]] ?? "内容"}` : "有一处内容";
  });
  return `${[...new Set(parts)].join("、")}还没写完，你点“用这版”后写手会自动补上，不影响你选的这版。`;
}

/** 取这部剧的写作状态（8 秒刷新）；没开始写作流程返回 null */
export function useAutoflow(runId: string): { d: AFlow | null; reload: () => void } {
  const [d, setD] = useState<AFlow | null>(null);
  const load = useCallback(() => {
    fetch(`/api/script-autoflow/${encodeURIComponent(runId)}`)
      .then((r) => (r.ok ? (r.json() as Promise<AFlow>) : null))
      .then((x) => setD(x && x.verdict !== "not_started" ? x : null))
      .catch(() => setD(null));
  }, [runId]);
  useEffect(() => {
    setD(null);
    load();
    const t = window.setInterval(load, 8000);
    return () => window.clearInterval(t);
  }, [load]);
  return { d, reload: load };
}
