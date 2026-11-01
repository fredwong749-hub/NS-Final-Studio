// PW-019：从 Seam.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import type { ShotSummary } from "../types";

export type SeamState = "linked" | "stale" | "custom" | "none";

/** 卡间衔接（规范 §3.2）：绿 = 尾帧就是下一镜当前首帧；黄 = 下一镜首帧在视频之后换过；蓝 = 独立尾帧；灰虚线 = 无 */
/** 下一镜就绪清单里的衔接检查（gpu3 status.json continuity，§3.4） */
export function seamCheck(right?: ShotSummary) {
  return right?.readiness?.items.find((i) => i.key === "continuity");
}

export function seamState(left: ShotSummary, right?: ShotSummary): { state: SeamState; title: string } {
  // gpu3 链：接缝颜色按 gpu3 的衔接检查（上一镜尾帧 vs 本镜首帧）
  if (left.last_frame_source === "gpu3" || left.owner === "gpu3") {
    if (right && right.id.split("-")[0] !== left.id.split("-")[0]) return { state: "none", title: "跨集：不做衔接检查" };
    const c = seamCheck(right);
    if (!c) return { state: "none", title: "没有衔接检查结果" };
    if (c.level === "fail") return { state: "stale", title: c.reason };
    if (c.ok) return { state: "linked", title: c.reason };
    return { state: "none", title: c.reason };
  }
  const vstale = left.stale.video ?? [];
  if (left.last_frame_source === "next") {
    if (vstale.includes("下一镜首帧已换")) return { state: "stale", title: "下一镜首帧在视频生成后换过：本镜视频已过期" };
    if (!left.next_first_frame) return { state: "none", title: "已设尾帧 = 下一镜首帧，但下一镜还没有首帧" };
    return { state: "linked", title: left.video ? "本镜视频按下一镜当前首帧收尾" : "尾帧 = 下一镜首帧（还没出视频）" };
  }
  if (left.last_frame_source === "gen" || left.last_frame_source === "upload")
    return { state: "custom", title: `本镜使用独立尾帧（${left.last_frame_source === "gen" ? "生成" : "上传"}）` };
  return { state: "none", title: left.last_frame_source === "video" ? "只有视频抽帧，没有设目标尾帧" : "没有衔接" };
}
