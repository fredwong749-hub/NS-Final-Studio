// PW-019：从 LookStrip.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。
import type { LookTag } from "../util";

export const FIELD_LABEL: Record<string, string> = {
  look_id: "造型",
  outfit: "套装",
  shoes: "鞋",
  makeup: "妆",
  hair: "发",
  nails: "指甲",
  accessory: "配饰",
  other: "其他",
  d_state: "装饰状态",
  visibility: "可见性",
};

export function lookTagTitle(t: LookTag): string {
  return [
    t.label,
    t.override ? "来源：本镜覆盖" : "来源：继承（默认 / 集计划）",
    t.changed ? `换装点：与上一次出场不同（${t.changedFields.map((f) => FIELD_LABEL[f] ?? f).join("、")}）` : "",
    ...t.conflicts.map((c) => `${c.severity === "error" ? "✖" : "⚠"} ${c.message}`),
  ]
    .filter(Boolean)
    .join("\n");
}
