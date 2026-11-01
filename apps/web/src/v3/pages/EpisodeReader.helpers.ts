// 从 EpisodeReader.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）

export type Shot = { n: number; img: string; fields: Record<string, string> };

export type Parsed = { title: string; plot: string; cast: string; shots: Shot[] };

/** P4 剧本分镜 Markdown → 结构（只拆字段，不改字；HTML 注释等系统标注不显示） */
export function parseP4(text: string): Parsed {
  const t = text.replace(/<!--[\s\S]*?-->/g, "");
  const title = /^##\s*ep\d+\s*《([^》]*)》/m.exec(t)?.[1] ?? "";
  const plot = /^\*\*剧情\*\*[：:]\s*(.*)$/m.exec(t)?.[1] ?? "";
  const cast = /^\*\*出场人物\*\*[：:]\s*(.*)$/m.exec(t)?.[1] ?? "";
  const parts = t.split(/\n(?=\*\*镜\s*\d+)/).slice(1);
  const shots = parts.map((p) => {
    const lines = p.split("\n");
    const m0 = /^\*\*镜\s*(\d+)[^*]*\*\*[：:]?\s*(.*)$/.exec(lines[0]) ?? ["", "0", ""];
    const fields: Record<string, string> = {};
    for (const ln of lines.slice(1)) {
      const m = /^\*\*([^*]{1,16})\*\*[：:]\s*(.*)$/.exec(ln);
      if (m) fields[m[1]] = m[2];
    }
    return { n: Number(m0[1]), img: m0[2], fields };
  });
  return { title, plot, cast, shots };
}

/** 只为“读”做的显示整理：开头的出图触发词（hh12clear、pose_、lnwan01 这类英文标识）不显示；sk_xxx 场景 id 换成场景名 */
export function readable(t: string, scenes: Record<string, string>): string {
  let x = t.replace(/^(?:\s*[A-Za-z][A-Za-z0-9_]*_?\s*[，,]\s*)+/, "");
  x = x.replace(/sk_[a-z0-9_]+/g, (m) => scenes[m] ?? "这个场景");
  return x;
}
