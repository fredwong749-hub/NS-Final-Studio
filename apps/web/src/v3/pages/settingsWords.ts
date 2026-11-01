// 项目设置页：把文件路径 / 内部 id 换成人话（UIMASTER UM-0288…0306：界面不得出现内部用语、文件路径、开发细节）。
// 原始路径只放在“技术细节”折叠里。

const FILES: [RegExp, string][] = [
  [/config\/voices\.json/g, "声音 · 角色音色表"],
  [/config\/script_chat_rules\.md/g, "写作规则"],
  [/config\/render_quality\.json/g, "出图质量设置"],
  [/config\/gen_contract\.json/g, "出图检查规则"],
  [/config\/face_reference\.json/g, "人物身份确认记录"],
  [/config\/script_mainline\.json/g, "主线剧本设置"],
  [/config\/adult_overrides\.json/g, "成人镜头判定表"],
  [/config\/visual_bible\.toml/g, "画面风格设置"],
  [/config\/auto_lora_triggers\.json/g, "自动触发词表"],
  [/config\/post\.json/g, "后期合成设置"],
  [/data\/looks\/face_overrides\.json/g, "人物 · 脸部设置"],
  [/data\/looks\/schedule\.json/g, "人物 · 造型排期"],
  [/data\/looks\/[\w./-]+/g, "人物造型资料"],
  [/knowledge\/rules\/[\w./-]+\.ya?ml/g, "系统规则库"],
  [/assets\/style\/[\w./-]+\.(?:png|jpe?g|webp)/g, "风格参考图"],
  [/[\w-]+\.safetensors/g, "质感模型"],
];
const PEOPLE: Record<string, string> = { lin_wan: "林晚", gu_chen: "顾沉", chen_yu: "陈宇", ch_a_lan: "阿岚", a_lan: "阿岚", narrator: "旁白" };
const PARTS: Record<string, string> = { toenails: "脚甲", nails: "美甲", shoes: "鞋", hair: "发型", makeup: "妆容", outfit: "穿搭", face: "脸" };

const BARE: Record<string, string> = {
  script_chat_rules: "写作规则", "script_chat_rules.md": "写作规则", "render_quality.json": "出图质量设置", "gen_contract.json": "出图检查规则",
  "voices.json": "声音 · 角色音色表", "visual_bible.toml": "画面风格设置", "visual_bible.tom": "画面风格设置", "face_reference.json": "人物身份确认记录",
  "face_overrides.json": "人物 · 脸部设置", "schedule.json": "人物 · 造型排期", "auto_lora_triggers.json": "自动触发词表",
};

/** 一段文字里的路径 / 内部 id → 人话 */
export function humanText(s: string): string {
  let t = s;
  for (const [re, w] of FILES) t = t.replace(re, w);
  // 人物参考图：assets/characters/lin_wan/lin_wan.png → 林晚的参考图
  t = t.replace(/(?:data\/)?assets\/characters\/(\w+)\/[\w./-]+\.(?:png|jpe?g|webp)/g, (_m, c: string) => `${PEOPLE[c] ?? "人物"}的参考图`);
  // 音色候选编号：lin_wan_cand/c2 → 林晚 · 候选 2
  t = t.replace(/\b(\w+?)_cand\/c(\d+)\b/g, (_m, c: string, n: string) => `${PEOPLE[c] ?? "人物"} · 候选 ${n}`);
  // 部件 id：toenails_lin_wan → 林晚 · 脚甲
  t = t.replace(/\b(toenails|nails|shoes|hair|makeup|outfit|face)_(\w+)\b/g, (_m, p: string, c: string) => `${PEOPLE[c] ?? "人物"} · ${PARTS[p] ?? p}`);
  t = t.replace(/\bauto_lora_triggers\b/g, "自动触发词表");
  // 材质 / 镜头类型规则的内部名
  const RULE: Record<string, string> = { patent_gloss: "漆皮光泽", needle_heel: "细跟高跟鞋", closeup: "特写", dark: "暗部", wide: "远景", medium: "中景" };
  t = t.replace(/(规则 · )([a-z]+(?:_[a-z]+)*)\b/g, (m, pre: string, id: string) => (RULE[id] ? pre + RULE[id] : m));
  // 不带目录的文件名 / 内部名（UM-0289/0290/0348…）：认得的换成人话，其余写“系统文件 / 系统规则库”
  t = t.replace(/\b[\w.-]+\.(?:json|ya?ml|toml?|md|py|safetensors)\b|\bscript_chat_rules\b/g, (m) => BARE[m] ?? (/\.ya?ml$/.test(m) ? "系统规则库" : "系统文件"));
  // 规则编号（K-OPS-R07 之类）对项目方没意义：去掉
  t = t.replace(/\bK-[A-Z]+-[A-Z0-9]+\b[、,，]?\s*/g, "");
  // 空括号、重复的“（系统文件）”收一收
  t = t.replace(/（\s*）|\(\s*\)/g, "").replace(/(（系统文件）)+/g, "（系统文件）");
  // 程序目录（services/agent/ns_agent/… 等）：不管前面是什么标点都换掉
  t = t.replace(/services\/agent\/[\w./-]*/g, "出图编译器").replace(/(?:services|tools|packages)\/[\w./-]*/g, "系统程序");
  // 其余还像路径的：只说“系统文件”
  t = t.replace(/(?:^|(?<=[\s：:（(、，,]))(?:config|data|knowledge|assets|services|tools)\/[\w./\-一-鿿]+/g, "（系统文件）");
  return t;
}

/** “已并入 X / 要改请看 X”里能跳的去处 */
const PLACES: [RegExp, string, string][] = [
  [/声音|音色|旁白/, "#/sound", "去 声音 → 角色音色"],
  [/资产中心|人物|造型|衣橱|发型|妆容|美甲|鞋|参考图/, "#/assets", "去 资产中心 → 人物"],
  [/每集剧本|剧本|写作规则|分镜/, "#/script-create", "去 剧本"],
  [/本集制作步骤|顶栏/, "#ep01", "去 画布（顶栏步骤）"],
  [/模型|LoRA|触发词/, "#/models", "去 模型与 API"],
];
export function placeOf(text: string): { href: string; label: string } | null {
  for (const [re, href, label] of PLACES) if (re.test(text)) return { href, label };
  return null;
}
