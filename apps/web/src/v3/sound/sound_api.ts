// UIRSI（B4）：声音页 / 镜头逐句试听 / 配乐 的接口类型（后端 services/api/ns_api/shot_audio.py）
export interface Line {
  i: number;
  kind: "dialogue" | "voiceover";
  speaker: string;
  speaker_name: string;
  label: "对白" | "独白" | "旁白";
  text: string;
  note: string;
  play: string | null;
  cached: boolean;
  dur: number | null;
  reason: string | null;
}
export interface ShotLines {
  shot: string;
  index?: number;
  lines: Line[];
}
export interface EpisodeLines {
  episode: number;
  title?: string;
  shots: ShotLines[];
}
export interface MusicShot {
  shot: string;
  index: number;
  start_s: number;
  dur_s: number | null;
}
export interface MusicCue {
  shot: number | null;
  start_s: number | null;
  action: string | null;
  intensity: string | number | null;
  text: string | null;
}
export interface Music {
  episode: number;
  url: string;
  duration_s: number | null;
  shots: MusicShot[];
  cues: MusicCue[];
  old_script: boolean;
}

async function j<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const d = await r.json();
      if (d?.detail) msg = String(d.detail);
    } catch {
      /* 不是 JSON */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const getShotLines = (shot: string) => j<ShotLines>(`/api/shots/${encodeURIComponent(shot)}/audio`);
export const getEpisodeLines = (ep: number) => j<EpisodeLines>(`/api/sound/lines?ep=${ep}`);
export const getMusicList = () => j<{ episodes: Music[] }>("/api/music");

/** 配乐提示点的动作 → 人话 */
export const CUE_WORD: Record<string, string> = { enter: "进", in: "进", swell: "渐强", up: "推高", continue: "延续", drop: "撤", fade: "渐弱", down: "压低", out: "出", stop: "停", change: "换" };
export const cueWord = (a: string | null) => (a ? CUE_WORD[a] ?? a : "提示");
/** 提示点原文里的内部词换成人话（只改显示，不改剧本） */
export const cueText = (t: string | null) => (t ?? "").replace(/（H3 已带配乐）/g, "（这一镜视频自带配乐）").replace(/H3/g, "成人镜头");

// BGM10（2026-11-01）：整集配乐候选 + 一键换用（后端 services/api/ns_api/bgm_api.py）
export interface BgmCand {
  id: string;
  round: number;
  url: string;
  chosen: boolean;
  model: string | null;
  seed: number | null;
  bpm: number | null;
  flags: string[];
  /** 系统提示的人话版（源头生成；老记录没有就前端回退 plainReason） */
  flags_plain?: string[];
  metrics: { duration_s?: number; clap?: number; energy_r?: number; tempo_bpm?: number; tempo_ok?: boolean; vocal_rel_db?: number; tags?: Record<string, number> };
}
export interface BgmCands {
  episode: number;
  status: string | null;
  chosen: { id: string; by: string; reason: string; at: string; previous?: string | null; reason_plain?: string; reason_evidence?: string } | null;
  needs_owner_listen: boolean;
  review: { reason?: string | null; model?: string | null };
  rounds: number;
  candidates: BgmCand[];
  hidden_failed: number;
}
export const getBgmCands = (ep: number) => j<BgmCands>(`/api/music/${ep}/candidates`);
export async function chooseBgm(ep: number, body: { id?: string; undo?: boolean }): Promise<BgmCands> {
  const r = await fetch(`/api/music/${ep}/choose`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const d = await r.json();
      if (d?.detail) msg = String(d.detail);
    } catch {
      /* 不是 JSON */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<BgmCands>;
}

// BGM10（UIAUDIT P2）：审听理由 / 提示里的内部度量名 → 人话；数值去掉（原文放悬停提示，记录不改）
const PLAIN: [RegExp, string][] = [
  [/\benergy_inverse\b/g, "起伏方向相反"],
  [/\benergy_weak\b/g, "起伏贴合偏弱"],
  [/\benergy_r\b/g, "起伏走向贴合度"],
  [/\bclap_low\b/g, "听感和描述不像"],
  [/\bclap\b/gi, "听感贴合度"],
  [/\bvocal_rel_db\b/g, "人声残留"],
  [/\bp_vocal\b/g, "人声可能性"],
  [/\bvocal_active_frac\b/g, "人声时长占比"],
  [/\btempo_off\b/g, "速度偏离"],
  [/\btempo_ok\b/g, "速度对得上"],
  [/\btempo_bpm\b|\btempo\b/g, "速度"],
  [/\bsilence_gap\b/g, "有长空白"],
  [/\blongest_gap_s\b/g, "最长空白"],
  [/\bgate_pass\b/g, "自动检查"],
  [/\bgate_fail\b/g, "没过自动检查"],
  [/\bspectral_centroid(_hz)?\b/g, "音色明暗"],
  [/\bonset_rate\b/g, "音符密度"],
  [/\btags\b/g, "乐器识别"],
  [/\bduration_s\b/g, "时长"],
  [/\blufs(_raw)?\b/gi, "响度"],
  [/\btrue_peak(_raw)?\b/g, "峰值"],
  [/\bcomposite\b/g, "综合分"],
  [/\bbrief\b/g, "配乐说明"],
  [/频谱质心/g, "音色明暗"],
  [/闸门/g, "自动检查"],
];
/** 句子里的空位：“最高值 相当”“的 是 60 的 倍”“（r1_c1 仅）”；“是反的。”这类正常句尾不算（与 tools/bgm/plain.py DANGLING 同一套） */
export const DANGLING =
  /(?:的|与|和|为|是|仅|约|从|至|到|对|达|比|在)\s+(?:[，。；、）)！？]|$)|\s(?:倍|相当|仅|左右)(?=[\s，。；、）)]|$)|的\s+(?:是|为|与|和)\s|仅\s*[）)]|[（(]\s*[，、；]|[\u4e00-\u9fff]\s+[，。；、！？]|\S\s{2,}\S/;
/** 老记录（没有 reason_plain / flags_plain）的回退：内部用语换人话；句中删掉数值的地方留一个看不见的空位标记，
 *  带标记或带空位的整句丢掉——宁可少说一句，不显示半句话（UIAUDIT P2 v2）。新记录用 reason_plain（审听模型改写，tools/bgm/plain.py） */
export function plainReason(t: string | null | undefined): string {
  const HOLE = "\u2063";
  const NUM = String.raw`[-−]?\d+(?:\.\d+)?`;
  const ID = /\br\d+_c\d+\b/g;                       // 候选号 r1_c3：先存起来，下面的规则不碰它
  const ids: string[] = [];
  let s = (t ?? "").replace(ID, (m) => `§${ids.push(m) - 1}§`);
  s = s
    // 整段括号（只有数值 / 实测说明 / r=…）：整段删，句子本身完整
    .replace(/[（(]实测[^）)]*[)）]/g, "")
    .replace(new RegExp(String.raw`[（(]\s*(?:r\s*[=:]\s*)?(?:${NUM}\s*(?:dBTP|dB|s|Hz)?\s*(?:[/／,，、~～…]|到)?\s*)+[)）]`, "g"), "")
    // 拍速：小数取整，BPM → 拍/分（保留，是人话）
    .replace(/(\d+)(?:\.\d+)?\s*(?:BPM|拍\/分)/gi, (_m, n) => `${n} 拍/分`)
    .replace(/\bBPM\b/gi, "拍/分")
    .replace(/(\d+)\s*s\b(?![a-z])/g, (m, n) => (m.includes(".") ? m : `${n} 秒`))
    // 句中的数值读数：删掉并留空位标记
    .replace(new RegExp(String.raw`\br\s*[=:]\s*${NUM}`, "g"), HOLE)
    .replace(new RegExp(String.raw`\b([a-z][a-z_\-]*)\s*[=:]\s*(?:true|false|${NUM})\s*(?:dBTP|dB|s|Hz)?`, "g"), `$1${HOLE}`)
    .replace(new RegExp(String.raw`${NUM}\s*(?:dBTP|dBFS|dB|LUFS|Hz)`, "g"), HOLE)
    .replace(new RegExp(String.raw`[-−]?\d+\.\d+\s*(?:s\b|秒)?\s*(?:[~～…–-]\s*[-−]?\d*(?:\.\d+)?)?`, "g"), HOLE)
    .replace(/\bp10\s*[-–]\s*p95\b/gi, "响度范围")
    .replace(/\btarget\b/gi, "目标");
  for (const [re, w] of PLAIN) s = s.replace(re, w);
  s = s
    .replace(/\b(?:longest_gap|silence)\b/g, "最长空白")
    .replace(/\bcentroid\b/g, "音色明暗")
    .replace(/\bcue_change\b/g, "换段")
    .replace(/\bduck\b/g, "人声让位")
    .replace(/\bgate\b/g, "自动检查")
    .replace(/\bvocals?\b/g, "人声")
    .replace(/人声\s+人声让位/g, "人声让位")
    // 只剩候选号 / 空位标记的括号：整段删
    .replace(new RegExp(String.raw`[（(][\s${HOLE}]*(?:(?:§\d+§|c\d+)[\s${HOLE}]*(?:仅)?[\s${HOLE}]*[/／,，、]?[\s${HOLE}]*)*[)）]`, "g"), "")
    .replace(/[（(]\s*[a-z]?\s*[)）]/g, "");
  const sentences = s.match(/[^。；！？\n]+[。；！？]?/g) ?? [];
  return sentences
    .map((x) => x.trim())
    .filter((x) => x && !x.includes(HOLE) && !DANGLING.test(x) && !/[A-Za-z]+_[A-Za-z_]+/.test(x))
    .map((x) =>
      x
        .replace(/\s+([，。；、）)])/g, "$1")
        .replace(/([（(])\s+/g, "$1")
        .replace(/([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])/g, "$1"),   // 换词时留下的中文之间的空格
    )
    .join("")
    .replace(/§(\d+)§/g, (_m, i) => ids[Number(i)])
    .replace(/\s{2,}/g, " ")
    .trim();
}
