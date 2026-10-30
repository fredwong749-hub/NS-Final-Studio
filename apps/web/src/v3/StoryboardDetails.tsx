// fredw-92/U4：本镜分镜字段（只读、逐字显示剧本原文）——审片行“分镜详情”、精修右栏“本镜分镜”、分镜表共用。
// 数据：/api/episodes/{n} 每镜 storyboard（后端 U4 加的原文字段）；旧后端没有时退回 /api/shots/{id} 的 script（画布已按集加载）。
// 只显示、不改写、不做内容检测；缺的字段明确标红“缺”。
import { useSyncExternalStore, type ReactNode } from "react";
import type { Episode, ShotDetail, ShotSummary } from "../types";
import "./storyboard.css";

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

type Raw = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : "");
const strN = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);

/** 剧本原文 → Storyboard（与后端 _storyboard 同一规则） */
function fromScript(x: Raw): Storyboard {
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
  { key: "cast", label: "人物行", req: "v3" },
  { key: "link", label: "衔接行", req: "v3" },
  { key: "img", label: "画面（首帧提示词）", req: "all" },
  { key: "motion", label: "动作 / 运镜", req: "all" },
  { key: "end", label: "结束状态", req: "v3" },
  { key: "expr", label: "表情", req: null },
  { key: "dialogue", label: "对白", req: null },
  { key: "vo", label: "独白 / 画外音", req: null },
  { key: "sound_h3", label: "环境声（H3 audio）", req: "all" },
  { key: "sound", label: "sound 整行", req: null },
  { key: "intimate", label: "亲密声", req: null },
  { key: "music_cue", label: "配乐提示（本镜 cue）", req: "all" },
  { key: "duration", label: "时长", req: "all" },
  { key: "h3", label: "H3 提示词", req: "all" },
];

export const H3_BLOCKS: [keyof NonNullable<ShotSummary["h3_blocks"]>, string][] = [
  ["alignment", "对齐句"],
  ["body", "画面"],
  ["soundscape", "环境声"],
  ["music", "配乐"],
];

const isV3 = (sb: Storyboard) => sb.scene_id != null || sb.cast != null || sb.link != null;

/** 各字段的纯文本（分镜表 / CSV / 悬停用）；空 = "" */
export function sbText(s: ShotSummary, sb: Storyboard, k: SbKey): string {
  switch (k) {
    case "scene":
      return [sb.scene_id, sb.scene_detail].filter(Boolean).join("｜");
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
      return [...s.dialogue.map((x) => `${x.speaker_note ?? "—"}：${x.text}`), ...sb.dialogue_stage.map((x) => `（${x}）`)].join("\n");
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

/** 本镜缺哪些必填字段（按剧本原文判断） */
export function missingOf(s: ShotSummary, sb: Storyboard | null): SbField[] {
  if (!sb) return [];
  const v3 = isV3(sb);
  return SB_FIELDS.filter((f) => {
    if (!f.req || (f.req === "v3" && !v3)) return false;
    if (f.key === "duration") return sb.duration_source !== "script";
    return !sbText(s, sb, f.key).trim();
  });
}

// ---------- 界面状态：全部展开（记住）、只看缺字段、分镜表开关 ----------

const KEY = "ns.v3.sbExpandAll";
function load() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}
let state = { expandAll: load(), rev: 0, onlyMissing: false, table: false };
const subs = new Set<() => void>();
const set = (p: Partial<typeof state>) => {
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
};
export function useSbUi() {
  return useSyncExternalStore(
    (f) => (subs.add(f), () => void subs.delete(f)),
    () => state,
  );
}

// ---------- 显示 ----------

function Miss({ why }: { why?: string }) {
  return <span className="sb-miss">缺{why ? <small>{why}</small> : null}</span>;
}

function Txt({ children, mono }: { children: ReactNode; mono?: boolean }) {
  return <div className={`sb-txt${mono ? " mono" : ""}`}>{children}</div>;
}

/** 本镜全部分镜字段（结构化网格）。narrow = 精修右栏：标签在上 */
export function StoryboardGrid({ s, d, narrow }: { s: ShotSummary; d?: ShotDetail; narrow?: boolean }) {
  const sb = storyboardOf(s, d);
  if (!sb) return <div className="sb-grid-loading">正在读取本镜剧本原文…</div>;
  const miss = new Set(missingOf(s, sb).map((f) => f.key));
  const blocks = s.h3_blocks;
  const body = (k: SbKey): ReactNode => {
    const t = sbText(s, sb, k);
    switch (k) {
      case "dialogue":
        return s.dialogue.length || sb.dialogue_stage.length ? (
          <Txt>
            {s.dialogue.map((x, i) => (
              <span key={i} className="sb-line">
                <b>{x.speaker_note ?? "—"}</b>
                {x.stage ? <em>（{x.stage}）</em> : null}：{x.text}
              </span>
            ))}
            {sb.dialogue_stage.map((x, i) => (
              <span key={`st${i}`} className="sb-line sb-dim">
                （{x}）
              </span>
            ))}
          </Txt>
        ) : (
          <span className="sb-none">本镜无对白</span>
        );
      case "vo":
        return s.voiceover ? (
          <Txt>
            <span className="sb-line">
              {s.voiceover.note && <b>{s.voiceover.note}</b>}
              {s.voiceover.note ? "：" : ""}
              {s.voiceover.text}
            </span>
          </Txt>
        ) : (
          <span className="sb-none">无</span>
        );
      case "intimate":
        return t ? <Txt>{t}</Txt> : <span className="sb-none">无</span>;
      case "expr":
        return t ? (
          <Txt>
            {t}
            <small className="sb-src">{s.expression.source === "edit" ? "人工改过" : "从剧本画面 / 动作里提取"}</small>
          </Txt>
        ) : (
          <span className="sb-none">—</span>
        );
      case "end":
        return t ? (
          <Txt>
            {t}
            {sb.end_state_source === "motion" && <small className="sb-src">取自动作最后一个“——”之后</small>}
          </Txt>
        ) : miss.has(k) ? (
          <Miss why="剧本没写结束状态，动作里也没有“——”" />
        ) : (
          <span className="sb-none">—（动作里没有“——”）</span>
        );
      case "duration":
        return sb.duration != null ? (
          <span className="sb-dur">
            <b>{sb.duration} 秒</b>
            {sb.duration_source === "script" ? <small className="sb-src ok">剧本写明</small> : <Miss why="剧本没写时长，系统默认" />}
          </span>
        ) : (
          <Miss />
        );
      case "h3": {
        const hasBlocks = blocks && H3_BLOCKS.some(([b]) => blocks[b]);
        return (
          <div className="sb-h3">
            {miss.has("h3") && <Miss why={hasBlocks ? `剧本没写 H3提示词；下面是 ${s.h3_prompt_source_label ?? "当前"} 版` : "剧本没写 H3提示词"} />}
            {!miss.has("h3") && s.h3_prompt_source_label && <small className="sb-src">当前显示：{s.h3_prompt_source_label}</small>}
            {sb.h3_check && <small className="sb-src warn">H3校验：{sb.h3_check}</small>}
            {hasBlocks ? (
              H3_BLOCKS.map(([b, label]) => (
                <div key={b} className="sb-h3b">
                  <span>{label}</span>
                  {blocks[b] ? <Txt mono>{blocks[b]}</Txt> : <Miss />}
                </div>
              ))
            ) : sb.h3_prompt ? (
              <Txt mono>{sb.h3_prompt}</Txt>
            ) : null}
          </div>
        );
      }
      case "sound":
        return t ? <Txt>{t}</Txt> : <span className="sb-none">—</span>;
      default:
        return t ? (
          <Txt mono={k === "sound_h3"}>{t}</Txt>
        ) : miss.has(k) ? (
          <Miss />
        ) : (
          <span className="sb-none">{k === "scene" || k === "cast" || k === "link" ? "—（旧稿没有这一行）" : "—"}</span>
        );
    }
  };
  return (
    <dl className={`sb-grid${narrow ? " narrow" : ""}`} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      {SB_FIELDS.map((f) => (
        <div key={f.key} className={`sb-item k-${f.key}${miss.has(f.key) ? " missing" : ""}`}>
          <dt>{f.label}</dt>
          <dd>{body(f.key)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 行上的“缺 N 项”红标（悬停列出） */
export function MissBadge({ miss }: { miss: SbField[] }) {
  if (!miss.length) return null;
  return (
    <span className="sb-badge" title={`缺分镜字段：\n${miss.map((f) => `· ${f.label}`).join("\n")}`}>
      缺 {miss.length} 项
    </span>
  );
}

/** 本集：每镜缺字段（分镜表、集头共用） */
export function episodeMissing(ep: Episode, details: Record<string, ShotDetail>) {
  return new Map(ep.shots.map((s) => [s.id, missingOf(s, storyboardOf(s, details[s.id]))] as const));
}
