// fredw-92/U4：本镜分镜字段（只读、逐字显示剧本原文）——审片行“分镜详情”、精修右栏“本镜分镜”、分镜表共用。
// 数据：/api/episodes/{n} 每镜 storyboard（后端 U4 加的原文字段）；旧后端没有时退回 /api/shots/{id} 的 script（画布已按集加载）。
// 只显示、不改写、不做内容检测；缺的字段明确标红“缺”。
import { type ReactNode } from "react";
import type { ShotDetail, ShotSummary } from "../types";
import "./storyboard.css";

import { H3_BLOCKS, SB_FIELDS, type SbField, type SbKey, TRIGGER_LABEL, TRIGGER_RE, isV3, missingOf, sbText, soundFallback, srcLabel, storyboardOf, who } from "./StoryboardDetails.helpers";

/** 富文本版：触发词显示成小标签，悬停看原词 */
export function Plain({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(TRIGGER_RE)) {
    if (m.index! > last) out.push(text.slice(last, m.index));
    out.push(
      <span key={m.index} className="sb-trig" title={`LoRA 触发词“${m[1]}”（原样送给模型，界面上只显示用途）`}>
        {TRIGGER_LABEL[m[1]]}
      </span>,
    );
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <>{out}</>;
}

// ---------- 显示 ----------

function Miss({ why }: { why?: string }) {
  return <span className="sb-miss">缺{why ? <small>{why}</small> : null}</span>;
}

function Txt({ children, mono }: { children: ReactNode; mono?: boolean }) {
  return <div className={`sb-txt${mono ? " mono" : ""}`}>{typeof children === "string" ? <Plain text={children} /> : children}</div>;
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
                {who(x) && <b>{who(x)}</b>}
                {x.stage ? <em>（{x.stage}）</em> : null}
                {who(x) || x.stage ? "：" : ""}
                {x.text}
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
          <span className="sb-none">—</span>
        );
      case "duration":
        return sb.duration != null ? (
          <span className="sb-dur">
            <b>{sb.duration} 秒</b>
            {sb.duration_source === "script" ? (
              <small className="sb-src ok">剧本写明</small>
            ) : (
              <Miss why={`剧本没写时长 · 现在按系统默认 ${sb.duration} 秒出（行头的 ${sb.duration}s 就是它）`} />
            )}
          </span>
        ) : (
          <Miss />
        );
      case "h3": {
        const hasBlocks = blocks && H3_BLOCKS.some(([b]) => blocks[b]);
        return (
          <div className="sb-h3">
            {miss.has("h3") && <Miss why={hasBlocks ? `剧本没写视频提示词；下面是${srcLabel(s.h3_prompt_source_label).replace(/版.*$/, "")}版` : "剧本没写视频提示词"} />}
            {!miss.has("h3") && s.h3_prompt_source_label && <small className="sb-src">当前显示：{srcLabel(s.h3_prompt_source_label)}</small>}
            {sb.h3_check && <small className="sb-src warn">视频提示词检查：{srcLabel(sb.h3_check)}</small>}
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
      case "sound_h3": {
        if (t) return <Txt>{t}</Txt>;
        const fb = soundFallback(s, sb);
        return fb ? (
          <Txt>
            {fb.text}
            <small className="sb-src">剧本没单独写这一行 · 已从{fb.from}取到</small>
          </Txt>
        ) : (
          <Miss why="剧本没写环境声，整行声音里也没有" />
        );
      }
      default:
        return t ? <Txt>{t}</Txt> : miss.has(k) ? <Miss /> : <span className="sb-none">—</span>;
    }
  };
  // 旧格式剧本（没有 场景 / 人物 / 衔接 行）：这几项不逐条写“—（旧稿没有这一行）”，合成末尾一句说明
  const old = !isV3(sb);
  const oldSkip = new Set<SbKey>(old ? (["scene", "cast", "link", ...(sb.end_state ? [] : ["end"])] as SbKey[]) : []);
  return (
    <dl className={`sb-grid${narrow ? " narrow" : ""}`} onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      {SB_FIELDS.filter((f) => !oldSkip.has(f.key)).map((f) => (
        <div key={f.key} className={`sb-item k-${f.key}${miss.has(f.key) ? " missing" : ""}`} data-sb={f.key}>
          <dt>{f.label}</dt>
          <dd>{body(f.key)}</dd>
        </div>
      ))}
      {old && (
        <div className="sb-item sb-oldnote">
          <dt>说明</dt>
          <dd className="sb-none">这一集剧本是较早的格式，没有单独的{[...oldSkip].map((k) => SB_FIELDS.find((f) => f.key === k)!.label).join(" / ")}行（不算缺）</dd>
        </div>
      )}
    </dl>
  );
}

/** 行上的“缺 N 项”红标（悬停列出）；给了 onJump 就是按钮——点了跳到缺的格子（审查 #20） */
export function MissBadge({ miss, onJump }: { miss: SbField[]; onJump?: () => void }) {
  if (!miss.length) return null;
  const title = `缺分镜字段：\n${miss.map((f) => `· ${f.label}`).join("\n")}`;
  if (!onJump)
    return (
      <span className="sb-badge" title={title}>
        缺 {miss.length} 项
      </span>
    );
  return (
    <button
      type="button"
      className="sb-badge btn"
      title={`${title}\n点击：跳到这些格子`}
      onClick={(e) => (e.stopPropagation(), onJump())}
      onDoubleClick={(e) => e.stopPropagation()}
    >
      缺 {miss.length} 项 →
    </button>
  );
}

