// 镜头参数的统一写法（项目方 11-02：光圈 F 大写、徕卡刻字）。全站只用这里的函数：总览 / 分镜行 / 出图 / 视频。
/** 项目方 11-02 16:4x：参考徕卡刻字——光圈 F 大写，写徕卡镜头名（50mm f/2 → SUMMICRON-M 50mm F2）；认不出的焦段只做大写规范化 */
const LEICA: Record<string, string> = {
  "21/1.4": "SUMMILUX-M", "24/1.4": "SUMMILUX-M", "28/1.4": "SUMMILUX-M", "28/2": "SUMMICRON-M", "35/1.4": "SUMMILUX-M", "35/2": "SUMMICRON-M",
  "50/0.95": "NOCTILUX-M", "50/1.2": "NOCTILUX-M", "50/1.4": "SUMMILUX-M", "50/2": "SUMMICRON-M", "75/1.25": "NOCTILUX-M", "75/2": "APO-SUMMICRON-M",
  "90/1.5": "SUMMILUX-M", "90/2": "APO-SUMMICRON-M", "135/3.4": "APO-TELYT-M",
};
export function leicaLens(raw: string | null | undefined): string | null {
  if (!raw) return raw ?? null;
  const t = raw.split(" · ")[0].replace(/^实拍\s*/, "");
  const m = t.match(/(\d+)\s*mm\s*f\s*\/?\s*([\d.]+)/i);
  if (!m) return t.replace(/f\s*\/\s*([\d.]+)/gi, "F$1");
  const ap = String(Number(m[2]));
  const name = LEICA[`${m[1]}/${ap}`];
  return `${name ? `${name} ` : ""}${m[1]}mm F${ap}`;
}


/** “实拍 50mm f/2 · 计划 85mm f/1.2” → “实拍 SUMMICRON-M 50mm F2 · 计划 APO-SUMMICRON-M 85mm F1.2”（每段单独规范化，保留“实拍 / 计划”前缀） */
export function leicaLine(raw: string | null | undefined): string | null {
  if (!raw) return raw ?? null;
  return raw
    .split(" · ")
    .map((part) => {
      const m = part.match(/^(实拍|计划)\s*(.*)$/);
      return m ? `${m[1]} ${leicaLens(m[2]) ?? m[2]}` : leicaLens(part) ?? part;
    })
    .join(" · ");
}
