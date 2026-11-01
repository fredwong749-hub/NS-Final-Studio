// PW-019：AssetCard.tsx 只导出组件（热更新不整页重载）；非组件函数放这里
import type { AssetCardData } from "./center";

export function usageText(c: AssetCardData) {
  const u = c.usage;
  if (!u) return null;
  if (u.eps != null && u.shots != null) return `用在 ${u.eps} 集 · ${u.shots} 镜`;
  if (u.shots != null) return u.shots ? `用在 ${u.shots} 镜${u.estimated ? "（盖章的）" : ""}` : "还没用过";
  return null;
}
