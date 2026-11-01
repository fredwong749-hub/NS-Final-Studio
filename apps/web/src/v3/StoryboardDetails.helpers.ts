// 从 StoryboardDetails.tsx 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）
import { useSyncExternalStore } from "react";
import type { Episode, ShotDetail, ShotSummary } from "../types";
import { sceneLabel } from "./sceneLabel";

/** 后端 storyboard（app.py _storyboard）= 剧本原文 */
export interface Storyboard {
  scene_id: string | null;
  scene_detail: string | null;
  img_note: string | null;
  img_prompt: string;
  motion_prompt: string;
  end_state: string | null;
  /** script = 剧本 **结束状态** 原文；motion = 动作最后一个“——”之后的原文 */
  end_state_source: "script" | "motion" | null;
  cast_raw: string | null;
  cast: unknown[] | null;
  link: string | null;
  link_carry: string | null;
  sound: string;
  sound_h3: string;
  sound_intimate: string;
  music_cue: string;
  h3_prompt: string | null;
  h3_check: string | null;
  dialogue_raw: string | null;
  dialogue_stage: string[];
  duration: number | null;
  duration_source: string;
}

export type Raw = Record<string, unknown>;

export const str = (v: unknown) => (typeof v === "string" ? v : "");

export const strN = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);

/** 剧本原文 → Storyboard（与后端 _storyboard 同一规则） */
export function fromScript(x: Raw): Storyboard {
  const motion = str(x.motion_prompt);
  let end = strN(x.end_state);
  let endSrc: Storyboard["end_state_source"] = end ? "script" : null;
  if (!end && motion.includes("——")) {
    end = strN(motion.slice(motion.lastIndexOf("——") + 2).trim());
    endSrc = end ? "motion" : null;
  }
  return {
    scene_id: strN(x.scene_id),
    scene_detail: strN(x.scene_detail),
    img_note: strN(x.img_note),
    img_prompt: str(x.img_prompt),
    motion_prompt: motion,
    end_state: end,
    end_state_source: endSrc,
    cast_raw: strN(x.cast_raw),
    cast: Array.isArray(x.cast) ? x.cast : null,
    link: strN(x.link),
    link_carry: strN(x.link_carry),
    sound: str(x.sound),
    sound_h3: str(x.sound_h3),
    sound_intimate: str(x.sound_intimate),
    music_cue: str(x.music_cue),
    h3_prompt: strN(x.h3_prompt),
    h3_check: strN(x.h3_check),
    dialogue_raw: strN(x.dialogue_raw),
    dialogue_stage: Array.isArray(x.dialogue_stage) ? (x.dialogue_stage as string[]) : [],
    duration: typeof x.duration === "number" ? x.duration : null,
    duration_source: str(x.duration_source) || "default",
  };
}

/** 本镜分镜原文；后端和详情都还没到时返回 null（显示“读取中”） */
export function storyboardOf(s: ShotSummary, d?: ShotDetail): Storyboard | null {
  const sb = (s as ShotSummary & { storyboard?: Raw }).storyboard;
  if (sb && typeof sb === "object") return fromScript(sb);
  if (d?.script) return fromScript(d.script as unknown as Raw);
  return null;
}

// ---------- 字段表 ----------

export type SbKey = "scene" | "cast" | "link" | "img" | "motion" | "end" | "expr" | "dialogue" | "vo" | "sound_h3" | "sound" | "intimate" | "music_cue" | "duration" | "h3";

export interface SbField {
  key: SbKey;
  label: string;
  /** 必填：v2 起所有镜头 = all；v3 新稿（有 场景 / 人物 / 衔接 行）才要求 = v3 */
  req: "all" | "v3" | null;
}

export const SB_FIELDS: SbField[] = [
  { key: "scene", label: "场景", req: "v3" },
  { key: "cast", label: "人物", req: "v3" },
  { key: "link", label: "衔接", req: "v3" },
  { key: "img", label: "画面", req: "all" },
  { key: "motion", label: "动作 / 运镜", req: "all" },
  { key: "end", label: "结束状态", req: "v3" },
  { key: "expr", label: "表情", req: null },
  { key: "dialogue", label: "对白", req: null },
  { key: "vo", label: "独白 / 画外音", req: null },
  { key: "sound_h3", label: "环境声", req: "all" },
  { key: "sound", label: "声音（剧本整行）", req: null },
  { key: "intimate", label: "亲密声", req: null },
  { key: "music_cue", label: "本镜配乐提示", req: "all" },
  { key: "duration", label: "时长", req: "all" },
  { key: "h3", label: "视频提示词", req: "all" },
];

export const H3_BLOCKS: [keyof NonNullable<ShotSummary["h3_blocks"]>, string][] = [
  ["alignment", "开头对齐"],
  ["body", "画面"],
  ["soundscape", "环境声"],
  ["music", "配乐"],
];

// ---------- 显示用的人话（UXF5 审查 #21：不出现 lnwan01 / H3 audio / gpu3 等内部词；原文本身不改，悬停可看原词） ----------

/** 视频提示词来源（后端 h3view.SOURCE_LABEL）→ 人话 */
export function srcLabel(x?: string | null): string {
  if (!x) return "当前";
  return x
    .replace(/^gpu3\s*最终/i, "最终渲染版")
    .replace(/笔记本草稿（剧本缺 ?H3 ?提示词）/, "系统草拟版（剧本没写视频提示词）")
    .replace(/笔记本草稿/, "系统草拟版")
    .replace(/画布修改/, "你在画布里改过")
    .replace(/§\s*9A/g, "提示词规则检查")
    .replace(/H3 ?提示词/g, "视频提示词")
    .replace(/\bgpu3\b/gi, "视频端");
}

/** LoRA 触发词 → 人话（来源：config/visual_bible.toml detect_she_with_trigger、config/auto_lora_triggers.json）。
 *  只在界面上换成标签；送给模型的原文不动。 */
export const TRIGGER_LABEL: Record<string, string> = { lnwan01: "林晚身份 LoRA", lnwan_qi: "林晚身份 LoRA" };

export const TRIGGER_RE = new RegExp(`\\b(${Object.keys(TRIGGER_LABEL).join("|")})\\b[，,、]?\\s*`, "g");

/** 纯文本版（分镜表、悬停）：触发词写成【林晚身份 LoRA】 */
export const plainText = (t: string) => t.replace(TRIGGER_RE, (_m, w: string) => `【${TRIGGER_LABEL[w]}】`);

/** 对白一行：说话人为空时不写“—：” */
export const who = (x: { speaker_note?: string | null }) => (x.speaker_note?.trim() ? x.speaker_note.trim() : null);

export const isV3 = (sb: Storyboard) => sb.scene_id != null || sb.cast != null || sb.link != null;

/** 各字段的纯文本（分镜表 / CSV / 悬停用）；空 = "" */
export function sbText(s: ShotSummary, sb: Storyboard, k: SbKey): string {
  switch (k) {
    case "scene":
      // UM-0102/0103：不把内部场景 id（sk_home_kitchen）给项目方看，换成场景名
      return [sceneLabel(sb.scene_id), sb.scene_detail].filter(Boolean).join("｜");
    case "cast":
      return sb.cast_raw ?? "";
    case "link":
      return [sb.link, sb.link_carry ? `承：${sb.link_carry}` : ""].filter(Boolean).join("；");
    case "img":
      return [sb.img_note ? `（${sb.img_note}）` : "", sb.img_prompt].filter(Boolean).join("");
    case "motion":
      return sb.motion_prompt;
    case "end":
      return sb.end_state ?? "";
    case "expr":
      return s.expression?.text ?? "";
    case "dialogue":
      return [...s.dialogue.map((x) => (who(x) ? `${who(x)}：${x.text}` : x.text)), ...sb.dialogue_stage.map((x) => `（${x}）`)].join("\n");
    case "vo":
      return s.voiceover ? `${s.voiceover.note ? `${s.voiceover.note}：` : ""}${s.voiceover.text}` : "";
    case "sound_h3":
      return sb.sound_h3;
    case "sound":
      return sb.sound;
    case "intimate":
      return sb.sound_intimate;
    case "music_cue":
      return sb.music_cue;
    case "duration":
      return sb.duration != null ? `${sb.duration} 秒（${sb.duration_source === "script" ? "剧本写明" : "系统默认"}）` : "";
    case "h3": {
      if (!sb.h3_prompt) return "";
      return sb.h3_prompt;
    }
  }
}

/** UX4（R10）：环境声的替代出处——剧本整行声音，或视频提示词里的环境声段；都没有返回 null */
export function soundFallback(s: ShotSummary, sb: Storyboard): { from: string; text: string } | null {
  if (sb.sound?.trim()) return { from: "整行声音", text: sb.sound };
  const b = s.h3_blocks?.soundscape;
  if (b && b.trim()) return { from: "视频提示词的环境声段", text: b };
  return null;
}

/** 本镜缺哪些必填字段（按剧本原文判断） */
export function missingOf(s: ShotSummary, sb: Storyboard | null): SbField[] {
  if (!sb) return [];
  const v3 = isV3(sb);
  return SB_FIELDS.filter((f) => {
    if (!f.req || (f.req === "v3" && !v3)) return false;
    if (f.key === "duration") return sb.duration_source !== "script";
    // UX4（审查 R10）：环境声没单独一行，但剧本整行声音 / 视频提示词的环境声段有内容 → 不算缺（显示时注明出处）
    if (f.key === "sound_h3" && !sb.sound_h3.trim()) return !soundFallback(s, sb);
    return !sbText(s, sb, f.key).trim();
  });
}

// ---------- 界面状态：全部展开（记住）、只看缺字段、分镜表开关 ----------

export const KEY = "ns.v3.sbExpandAll";

export function load() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export let state = { expandAll: load(), rev: 0, onlyMissing: false, table: false, focus: null as string | null, focusRev: 0 };

export const subs = new Set<() => void>();

export const set = (p: Partial<typeof state>) => {
  state = { ...state, ...p };
  subs.forEach((f) => f());
};

export const sbUi = {
  setExpandAll(v: boolean) {
    try {
      localStorage.setItem(KEY, v ? "1" : "0");
    } catch {
      /* 隐私模式 */
    }
    set({ expandAll: v, rev: state.rev + 1 });
  },
  setOnlyMissing: (v: boolean) => set({ onlyMissing: v }),
  setTable: (v: boolean) => set({ table: v }),
  /** UXF5（审查 #20）：打开分镜表并跳到这一镜缺的格子（横向滚过去、标红闪一下） */
  openTableAt: (shot: string) => set({ table: true, focus: shot, focusRev: state.focusRev + 1 }),
};

export function useSbUi() {
  return useSyncExternalStore(
    (f) => (subs.add(f), () => void subs.delete(f)),
    () => state,
  );
}

/** 本集：每镜缺字段（分镜表、集头共用） */
export function episodeMissing(ep: Episode, details: Record<string, ShotDetail>) {
  return new Map(ep.shots.map((s) => [s.id, missingOf(s, storyboardOf(s, details[s.id]))] as const));
}
