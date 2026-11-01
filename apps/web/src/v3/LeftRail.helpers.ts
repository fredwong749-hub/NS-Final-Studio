// 从 LeftRail.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）

import type { CharacterBrief, Episode } from "../types";

export interface CharAgg {
  c: CharacterBrief;
  letters: string[];
  shots: string[];
}

export function aggChars(ep: Episode): CharAgg[] {
  const m = new Map<string, CharAgg>();
  for (const s of ep.shots)
    for (const c of s.characters) {
      const a = m.get(c.character) ?? { c, letters: [], shots: [] };
      const l = c.look_label || (c.cast_source ? "" : c.look_name);
      if (l && !a.letters.includes(l)) a.letters.push(l);
      a.shots.push(s.id);
      if (!a.c.face_url && c.face_url) a.c = c;
      m.set(c.character, a);
    }
  return [...m.values()];
}

/** 首字母徽标：A/B/C；旧造型库“默认”显示 A。DATAALIGN：与出图同源的人物（cast_source）造型对不上登记 → “?”，不再冒充 A */
export const letterOf = (c: CharacterBrief) => (c.look_label || (c.cast_source ? "?" : "A")).slice(0, 2);
