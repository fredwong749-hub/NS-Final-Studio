import { memo, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { api } from "../api";
import { useStudio, type FrameStage } from "../store";
import type { CharacterBrief, Job, LookPatch, ReadinessItem, ShotDetail, ShotSummary, SopShot, Stage } from "../types";
import { SopChip } from "./SopBar";
import { EXPLICIT_LABEL, expectedLast, isFailed, LAST_SOURCE_LABEL, laptopVideoEnabled, SLOT_NAME, stageActive, stageTakes, STAGE_LABEL } from "../util";
import { JobBar, Score, StepChips } from "./frames";
import "../t54b.css";

type Studio = ReturnType<typeof useStudio>;

/** 行内的一个 9:16 大图槽（首帧或尾帧） */
const GPU3_OWNS = "gpu3 负责此镜（避免两条链）";

/** 行内显示的帧来自 gpu3 链（gpu3 负责，或已有 gpu3 链）：笔记本版本号 / 过期 / 新版本提示都不适用 */
export const isGpu3Row = (s: ShotSummary) => s.owner === "gpu3" || s.frames_source === "gpu3";

function FrameTile({ s, stage, st, onPair }: { s: ShotSummary; stage: FrameStage; st: Studio; onPair: () => void }) {
  const g3 = isGpu3Row(s);
  const [menu, setMenu] = useState(false);
  const [play, setPlay] = useState(false);
  const hover = useRef<number | undefined>(undefined);
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => () => clearTimeout(hover.current), []);
  const live = st.liveJob(s.id, stage);
  const isFirst = stage === "image";
  const url = isFirst ? s.first_frame : s.last_frame_target;
  const active = isFirst ? s.first_frame_take : s.last_frame_take;
  const latest = s.latest_take?.[stage] ?? null;
  const fresh = latest != null && (active == null || latest > active) && !live;
  const stale = s.stale[stage] ?? [];
  const src = s.last_frame_source;
  const nextIdx = s.next_shot?.split("-")[1];
  const lastBlocked = !s.first_frame ? "尾帧以首帧为底图，先出首帧" : !s.last_supported ? "尾帧生成尚未上线（等 render_router）" : "";
  const label = isFirst ? "首帧" : "尾帧";

  const stop = (fn: () => void) => (e: MouseEvent) => {
    e.stopPropagation();
    fn();
  };
  const gen = () => {
    st.select(s.id);
    // 成人路由的镜头走确认（F2）；其它直接入队
    if (s.adult) st.requestRender(s.id, stage);
    else void st.render(s.id, stage);
  };
  const upload = async (f: File) => {
    try {
      if (isFirst) await api.uploadFirstFrame(s.id, f);
      else await api.uploadLastFrame(s.id, f);
      st.notify(`${s.id} ${label}已上传`);
      await st.refreshAfter([s.id]);
    } catch (e) {
      st.notify(`上传失败：${(e as Error).message}`, "err");
    }
  };
  const useNext = async () => {
    // 封板修复：拉详情失败要提示，不留未处理的 rejection
    const d = st.details[s.id] ?? (await api.shot(s.id).catch((e: Error) => void st.notify(`${s.id} 加载失败：${e.message}`, "err")));
    if (!d) return;
    await st.saveEdit(s.id, { ...d.edit, last_frame: "next", last_source: "next" });
  };

  const g = s.gpu3;
  const mirrored = !g ? true : isFirst ? g.first_mirrored : g.last_mirrored;
  const from = !g ? "" : isFirst ? g.first_from : g.last_from;
  // E1/E3：没有独立尾帧时也要让人一眼看到“尾帧应该从哪来”+ 一个动作（不留空白格）
  const exp = !isFirst && !url && src !== "next" ? expectedLast(s) : null;
  const showExp = !!exp && (g3 || !!exp.url);
  let body: ReactNode;
  if (exp && showExp) {
    const canAsk = g3 && !!s.first_frame && !s.explicit_hold;
    body = (
      <>
        {exp.url &&
          (exp.isVideo ? (
            <video
              src={exp.url}
              muted
              playsInline
              preload="metadata"
              onLoadedMetadata={(e) => {
                const v = e.currentTarget;
                if (Number.isFinite(v.duration)) v.currentTime = Math.max(0, v.duration - 0.05);
              }}
            />
          ) : (
            <img src={exp.url} alt={exp.label} loading="lazy" draggable={false} />
          ))}
        {!live && (
          <div className="tile-expect" onClick={(e) => e.stopPropagation()} title={exp.hint}>
            <span className="tile-expect-k">没有独立尾帧 · 预期来源</span>
            <span className="tile-expect-t">{exp.label}</span>
            {g3 ? (
              <button className="btn primary" disabled={!canAsk} title={canAsk ? "写进 gpu3 重渲队列：保留首帧，由首帧编辑出尾帧" : exp.hint} onClick={() => st.requestGpu3(s.id, "last")}>
                请 gpu3 出尾帧
              </button>
            ) : (
              <button className="btn primary" disabled={!!lastBlocked} title={lastBlocked || "以首帧为底图，按尾帧提示词生成"} onClick={gen}>
                生成尾帧
              </button>
            )}
            {exp.url && (
              <button className="link" onClick={() => (st.select(s.id), onPair())} title="全屏：首帧 | 尾帧 | 视频">
                放大看
              </button>
            )}
          </div>
        )}
      </>
    );
  } else if (g3 && !url) {
    const needFirst = !isFirst && !s.first_frame;
    body = (
      <div className="tile-empty" onClick={(e) => e.stopPropagation()}>
        <span className="tile-empty-t">gpu3 未出{label}</span>
        <span className="tile-hint">{needFirst ? "尾帧由本链首帧编辑得到，先等 gpu3 出首帧" : "这一镜由 gpu3 出整条链，笔记本不出图"}</span>
        {!live && (
          <button
            className="btn primary"
            disabled={needFirst || !!s.explicit_hold}
            onClick={() => st.requestGpu3(s.id, isFirst ? "image" : "last")}
            title="写进 gpu3 的重渲队列（docs/canvas.md §2）"
          >
            请 gpu3 出{label}
          </button>
        )}
      </div>
    );
  } else if (url) {
    body =
      play && s.video && isFirst ? (
        <video src={s.video} autoPlay muted loop playsInline />
      ) : (
        <img src={url} alt={label} loading="lazy" draggable={false} />
      );
  } else if (!isFirst && src === "next") {
    body = (
      <div className="tile-empty" onClick={(e) => e.stopPropagation()}>
        <span className="tile-empty-t">尾帧 = 下一镜首帧</span>
        <span className="muted">等 {nextIdx} 出首帧</span>
        {s.next_shot && (
          <button className="btn" onClick={() => void st.render(s.next_shot!, "image")}>
            先出 {nextIdx} 首帧
          </button>
        )}
      </div>
    );
  } else {
    body = (
      <div className="tile-empty" onClick={(e) => e.stopPropagation()}>
        <span className="tile-empty-t">还没有{label}</span>
        {!live && (
          <>
            <button
              className="btn primary"
              disabled={!isFirst && !!lastBlocked}
              title={!isFirst ? lastBlocked || "以首帧为底图，按尾帧提示词生成" : "按首帧提示词生成"}
              onClick={gen}
            >
              生成{label}
            </button>
            <div className="menu-anchor">
              <button className="btn ghost" onClick={() => setMenu((m) => !m)}>
                其他来源 ▾
              </button>
              {menu && (
                <div className="menu" onMouseLeave={() => setMenu(false)}>
                  {!isFirst && (
                    <button disabled={!s.next_shot} onClick={() => (setMenu(false), void useNext())}>
                      用下一镜首帧{s.next_shot ? `（${nextIdx}）` : ""}
                    </button>
                  )}
                  <button onClick={() => (setMenu(false), file.current?.click())}>上传图片…</button>
                  <button
                    onClick={() => {
                      setMenu(false);
                      st.select(s.id);
                      st.openInspTab(isFirst ? "first" : "last");
                    }}
                  >
                    从版本里挑
                  </button>
                </div>
              )}
            </div>
            {!isFirst && lastBlocked && <span className="tile-hint">{lastBlocked}</span>}
          </>
        )}
      </div>
    );
  }

  return (
    <div
      className={`tile${url ? " has" : showExp ? ` expect${exp?.url ? "" : " noimg"}` : " empty"}${live ? " busy" : ""}`}
      onClick={(e) => {
        st.select(s.id);
        if (url) {
          // gpu3 镜头也进完整查看器（gpu3 版本链，可翻版本 / A/B）；Shift+点 = 首帧|尾帧|视频 三联
          if (g3 && e.shiftKey) onPair();
          else st.openViewer(s.id, stage);
        }
      }}
      onMouseEnter={() => {
        if (isFirst && s.video) hover.current = window.setTimeout(() => setPlay(true), 400);
      }}
      onMouseLeave={() => {
        clearTimeout(hover.current);
        setPlay(false);
      }}
      title={
        url
          ? g3
            ? `gpu3 链：${from}${mirrored ? "" : "（笔记本镜像还没同步，经 gpu3 桥读取）"}\n点击全屏看首尾帧和视频`
            : "点击全屏查看（←/→ 翻版本，A/B 对比）"
          : undefined
      }
    >
      {body}
      <div className="tile-top">
        <span className="chip chip-dark">
          {label}
          {active != null && ` v${active}`}
          {showExp && " · 缺"}
          {!isFirst && src && src !== "gen" && src !== "gpu3" && ` · ${LAST_SOURCE_LABEL[src]}`}
        </span>
        {url && (
          <span className={`chip ${g3 ? "chip-src-gpu3" : "chip-src-laptop"}`} title={g3 ? "出视频实际用的 gpu3 take 链" : "笔记本出的帧"}>
            {g3 ? "gpu3" : "笔记本"}
          </span>
        )}
        {url && g3 && !mirrored && (
          <span className="chip chip-warn" title="笔记本镜像还没同步这张图，经 gpu3 桥读取">
            经桥
          </span>
        )}
        {stale.length > 0 && (
          <span className="chip chip-warn" title={stale.join("、")}>
            过期
          </span>
        )}
        <span className="grow" />
        <Score sc={s.score?.[stage]} />
      </div>
      {isFirst && s.video && url && !play && <span className="tile-video chip chip-dark">▶ 有视频</span>}
      {fresh && (
        <button
          className="tile-fresh"
          onClick={stop(() => {
            st.select(s.id);
            st.openViewer(s.id, stage, "ab", latest);
          })}
          title="有比当前更新的版本：点开 A/B 对比后设为当前"
        >
          新版本 v{latest} 待选 · 对比
        </button>
      )}
      {live && (
        <div className="tile-job" onClick={(e) => e.stopPropagation()}>
          <JobBar live={live} />
        </div>
      )}
      <input
        ref={file}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

/** 行内版本条（E7④；canvas_research §3 模式 8“新版本衍生、不覆盖原图”+ §4.3 线框“版本条 [v1][v2][v3●]”）：
 *  每个格子下面一排小图，当前描绿框，比当前新的标“新”，进行中 / 已请 gpu3 的在末尾虚线占位；
 *  点任一版本 = 全屏 A/B（A = 当前，B = 点的那个），查看器里 Enter 设为当前 */
function RowTakes({ s, d, st }: { s: ShotSummary; d?: ShotDetail; st: Studio }) {
  if (!d) return null;
  const MAX = 5;
  const col = (stage: "image" | "last") => {
    const list = stageTakes(d, stage).filter((t) => stage === "image" || t.url);
    const act = stageActive(d, stage);
    const live = st.liveJob(s.id, stage);
    const worth = list.length >= 2 || !!live || (list.length === 1 && list[0].n !== act);
    if (!worth) return <div className="vstrip-col" key={stage} />;
    return (
      <div className="vstrip-col" key={stage}>
        <span className="vstrip-k" title={`${STAGE_LABEL[stage]}共 ${list.length} 个版本${d.gpu3_takes ? "（gpu3 版本链，当前由 gpu3 决定）" : ""}`}>
          {STAGE_LABEL[stage]} {list.length}
        </span>
        {list.slice(-MAX).map((t) => {
          const cur = t.n === act;
          const isNew = act != null && t.n > act;
          return (
            <button
              key={t.n}
              className={`vthumb${cur ? " cur" : ""}${isNew ? " new" : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                st.select(s.id);
                st.openViewer(s.id, stage, cur ? "pair" : "ab", cur ? null : t.n);
              }}
              title={`v${t.n}${cur ? "（当前）" : isNew ? "（比当前新：点开 A/B 对比）" : " · 点开 A/B 对比"}`}
            >
              {t.url ? <img src={t.url} alt="" loading="lazy" /> : <span className="vthumb empty-u">缺</span>}
              <i>v{t.n}</i>
            </button>
          );
        })}
        {live && (
          <span className="vthumb pending" title={live.gpu3 ? "已请 gpu3，等新 take" : live.job.state === "running" ? "渲染中" : `排队第 ${live.pos} 位`}>
            {live.gpu3 ? "gpu3" : live.job.state === "running" ? "出图" : `#${live.pos}`}
          </span>
        )}
      </div>
    );
  };
  return (
    <div className="vstrip" onClick={(e) => e.stopPropagation()}>
      {col("image")}
      {col("last")}
    </div>
  );
}

/** 行头忙碌状态：哪一步在排队 / 渲染 / 已请 gpu3（E7④ busy/queued 在行上可见） */
function BusyChip({ s, st }: { s: ShotSummary; st: Studio }) {
  const parts = (["image", "last", "video"] as Stage[]).flatMap((stage) => {
    const l = st.liveJob(s.id, stage);
    return l ? [{ stage, l }] : [];
  });
  if (!parts.length) return null;
  const g = parts.every((p) => p.l.gpu3);
  const what = parts.map((p) => STAGE_LABEL[p.stage]).join("+");
  const run = parts.some((p) => !p.l.gpu3 && p.l.job.state === "running");
  const why = parts.map((p) => `${STAGE_LABEL[p.stage]}：${p.l.gpu3 ? "已请 gpu3，等新 take" : p.l.job.state === "running" ? "渲染中" : `排队第 ${p.l.pos} 位`}`);
  return (
    <span className={`srow-busy${g ? "" : " laptop"}`} title={why.join("\n")}>
      {g ? `⟳ 已请 gpu3 · ${what}` : run ? `⟳ 渲染中 · ${what}` : `⟳ 排队 · ${what}`}
    </span>
  );
}

const STRIP_SLOTS = ["outfit", "shoes", "nails", "makeup", "hair", "accessory"] as const;
const STRIP_LABEL: Record<string, string> = { outfit: "衣", shoes: "鞋", nails: "甲", makeup: "妆", hair: "发", accessory: "饰" };

/** 本镜造型切换（T54-B / 调研 #1：小云雀“按分镜选择形象版本”）：写本镜覆盖 look_id；选「沿用集计划」= look_id 置空 */
function LookPicker({ shotId, c }: { shotId: string; c: CharacterBrief }) {
  const st = useStudio();
  const [busy, setBusy] = useState(false);
  const looks = (st.catalog?.looks ?? []).filter((lk) => lk.character === c.character);
  const label = c.look_label ? `造型 ${c.look_label}` : c.look_name || "默认";
  if (looks.length < 2 && !c.has_override)
    return (
      <span className="p3-look" title={c.label}>
        {label}
      </span>
    );
  const pick = async (lookId: string) => {
    setBusy(true);
    try {
      const r = await api.looks.patchShot(shotId, c.character, { look_id: lookId || null } as LookPatch);
      const what = `${shotId} · ${c.name}：${lookId ? "本镜改用 " + (looks.find((l) => l.id === lookId)?.name ?? lookId) : "沿用集计划"}`;
      if (r.affected_count > 1) st.showAffected(r, what); // 波及多镜才弹影响范围（T54-B #3）
      else st.notify(`${what}（影响 ${r.affected_count} 镜，未自动重出）`);
      await st.refreshAfter([shotId]);
    } catch (e) {
      st.notify(`切换造型失败：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };
  return (
    <select
      className="p3-look-sel"
      value={c.has_override ? c.look_id ?? "" : ""}
      disabled={busy}
      onClick={(e) => e.stopPropagation()}
      onChange={(e) => void pick(e.target.value)}
      title={`${c.label}
切换本镜造型（只改本镜；首帧需重出才会变）`}
    >
      <option value="">{c.has_override ? "沿用集计划" : label}</option>
      {looks.map((lk) => (
        <option key={lk.id} value={lk.id}>
          {lk.label ? `造型 ${lk.label} · ` : ""}
          {lk.name}
        </option>
      ))}
    </select>
  );
}

/** 人物条：头像 + 名字 + 本镜造型（可切换）+ 本镜单品小图（缺参考图汇总成红点） */
export function PeopleStrip({ chars, hl, onOpen, shotId }: { chars: CharacterBrief[]; hl?: string | null; onOpen: (c: CharacterBrief) => void; shotId?: string }) {
  if (!chars.length) return <div className="muted">本镜无出场角色</div>;
  return (
    <div className="people3">
      {chars.map((c) => {
        const err = c.conflicts.filter((x) => x.severity === "error");
        const noImg = c.slots.flatMap((v) => (v.items.length && !v.items.some((x) => x.thumb_url) ? [SLOT_NAME[v.slot] ?? v.slot] : []));
        return (
          <div key={c.character} className={`p3${hl === c.character ? " hl" : ""}`}>
            <button
              className={`p3-face${c.face_url ? "" : " missing"}`}
              onClick={(e) => (e.stopPropagation(), onOpen(c))}
              title={c.face_url ? `${c.name}：打开资产页` : `${c.name} 没有脸图：去资产页补身份底板`}
            >
              {c.face_url ? <img src={c.face_url} alt={c.name} loading="lazy" /> : <span>{c.name.slice(0, 1)}</span>}
            </button>
            <div className="p3-name">
              <b>{c.name}</b>
              {shotId ? (
                <LookPicker shotId={shotId} c={c} />
              ) : (
                <span className="p3-look" title={c.label}>
                  {c.look_label ? `造型 ${c.look_label}` : c.look_name || "默认"}
                </span>
              )}
              {c.d_state && <span className="p3-look">· {c.d_state}</span>}
              {noImg.length > 0 && (
                <span className="p3-miss" title={`缺参考图（只用文字描述）：${noImg.join("、")}`}>
                  缺图 {noImg.length}
                </span>
              )}
              {c.changed_from_prev && (
                <span className="chip chip-warn" title={`与上一镜不同：${c.changed_fields.join("、")}`}>
                  换装
                </span>
              )}
              {c.has_override && <span className="chip chip-accent" title="本镜单独覆盖了造型">本镜改</span>}
              {err.length > 0 && (
                <span className="chip chip-bad" title={err.map((x) => x.message).join("\n")}>
                  冲突
                </span>
              )}
            </div>
            <div className="p3-items">
              {STRIP_SLOTS.map((slot) => {
                const v = c.slots.find((x) => x.slot === slot);
                const items = v?.items ?? [];
                if (!items.length) {
                  if (slot === "accessory" || shotId) return null; // 镜头行只显示本镜用到的单品（未设的空格子不占位）
                  return (
                    <span key={slot} className="it unset" title={`${SLOT_NAME[slot]}：本镜未设`}>
                      {STRIP_LABEL[slot]}
                    </span>
                  );
                }
                const it = items.find((x) => x.thumb_url) ?? items[0];
                return (
                  <span
                    key={slot}
                    className={`it${it.thumb_url ? "" : " noimg"}${v?.changed ? " chg" : ""}`}
                    title={`${SLOT_NAME[slot]}：${items.map((x) => x.name).join("、")}${it.thumb_url ? "" : "\n缺参考图：只用文字描述"}`}
                  >
                    {it.thumb_url ? <img src={it.thumb_url} alt="" loading="lazy" /> : STRIP_LABEL[slot]}
                    <i>{STRIP_LABEL[slot]}</i>
                    {items.length > 1 && <em>{items.length}</em>}
                  </span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Lines({ s }: { s: ShotSummary }) {
  if (!s.dialogue.length && !s.voiceover) return null;
  return (
    <div className="lines3">
      {s.dialogue.map((d, i) => (
        <div key={i} className="line3">
          <span className="line-k k3">对白</span>
          <span>
            {d.stage && <span className="stage-dir">〔{d.stage}〕</span>}
            {d.speaker_note && <b className="spk">{d.speaker_note}：</b>}
            {d.text}
          </span>
        </div>
      ))}
      {s.voiceover && (
        <div className="line3 vo">
          <span className="line-k k3">独白</span>
          <span>
            {s.voiceover.note && <span className="stage-dir">〔{s.voiceover.note}〕</span>}
            {s.voiceover.text}
          </span>
        </div>
      )}
    </div>
  );
}

function Expression({ s, st }: { s: ShotSummary; st: Studio }) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(s.expression.text);
  useEffect(() => setV(s.expression.text), [s.expression.text]);
  const save = async () => {
    const d = st.details[s.id] ?? (await api.shot(s.id).catch((e: Error) => void st.notify(`${s.id} 加载失败：${e.message}`, "err")));
    if (!d) return;
    if (await st.saveEdit(s.id, { ...d.edit, expression: v.trim() || null })) setEditing(false);
  };
  return (
    <div className="kv3" onClick={(e) => e.stopPropagation()}>
      <span className="k3">表情</span>
      {editing ? (
        <input
          autoFocus
          value={v}
          onChange={(e) => setV(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void save();
            if (e.key === "Escape") setEditing(false);
          }}
          onBlur={() => setEditing(false)}
          placeholder="2–4 个可观察线索，回车保存"
        />
      ) : s.expression.source === "none" ? (
        <button className="unlabeled" onClick={() => setEditing(true)}>
          未标注 · 点击填写
        </button>
      ) : (
        <span className={`v3${s.expression.source === "auto" ? " auto" : ""}`} onClick={() => setEditing(true)} title="点击修改">
          {s.expression.text}
        </span>
      )}
    </div>
  );
}

function PromptLine({ label, text, edited, onOpen, lint }: { label: string; text: string; edited?: boolean; onOpen: () => void; lint?: ShotSummary }) {
  return (
    <div className="pl3" onClick={(e) => (e.stopPropagation(), onOpen())} title={text}>
      <span className="k3">{label}</span>
      <span className="pl3-text">{text || "—"}</span>
      {edited && <span className="chip chip-accent">已改</span>}
      {lint?.h3_lint && (
        <span
          className={`chip ${lint.h3_lint_ok ? "chip-ok" : "chip-bad"}`}
          title={`${lint.h3_prompt_source_label ?? ""}；${lint.h3_lint_ok ? "§9A 机检通过" : `未通过：${(lint.h3_failed ?? []).join("、")}`}`}
        >
          §9A {lint.h3_lint_ok ? "✓" : `✗${(lint.h3_failed ?? []).length}`}
        </span>
      )}
      <button className="link" title="在检查器里编辑">编辑</button>
    </div>
  );
}

/** 🔊 环境声（进 H3）| 🎵 配乐（英文进 H3，中文只给后期）：各一行预览，点击打开检查器视频页的编辑框 */
function SoundLine({ s, onOpen }: { s: ShotSummary; onOpen: (field: "soundscape" | "music") => void }) {
  const a = s.audio;
  if (!a) return null;
  const sc = a.soundscape;
  const cue = a.music;
  const ep = a.episode_music;
  return (
    <div className="sound3">
      <div className="pl3" onClick={(e) => (e.stopPropagation(), onOpen("soundscape"))} title={`环境声 overall_soundscape（进 H3）
${sc.text || "未设"}`}>
        <span className="k3">环境声</span>
        <span className={`pl3-text${sc.text ? "" : " warn"}`}>{sc.text || "未设 · 点击填写"}</span>
        {sc.source === "edit" && <span className="chip chip-accent">已改</span>}
      </div>
      <div className="pl3" onClick={(e) => (e.stopPropagation(), onOpen("music"))} title={`配乐：英文进 H3 non_diegetic_music，中文只给后期
H3 实际：${s.h3_blocks?.music || "N/A"}
本镜：${cue.text || "—"}
本集：${ep.text || "—"}`}>
        <span className="k3">配乐</span>
        <span className="pl3-text">
          {cue.text ? cue.text : ep.text ? <span className="muted">继承本集 · {ep.text}</span> : <span className="muted">未设</span>}
        </span>
        {cue.source === "edit" && <span className="chip chip-accent">已改</span>}
      </div>
    </div>
  );
}

/** gpu3 链全屏：首帧 | 尾帧 | 视频（就是出视频用的那一对） */
function Gpu3Pair({ s, onClose }: { s: ShotSummary; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose]);
  const g = s.gpu3;
  const ex = s.last_frame_target ? null : expectedLast(s);
  const frames: [string, string | null][] = [
    ["首帧", s.first_frame],
    [ex?.url && !ex.isVideo ? `尾帧（缺 · 预期：${ex.label}）` : "尾帧", s.last_frame_target ?? (ex?.isVideo ? null : ex?.url ?? null)],
  ];
  return (
    <div className="pair3" onClick={(e) => (e.stopPropagation(), onClose())}>
      <div className="pair3-head" onClick={(e) => e.stopPropagation()}>
        <b>{s.id}</b>
        <span className="chip chip-src-gpu3">gpu3 take 链</span>
        <span className="muted">
          首帧 {g?.first_from || "—"} · 尾帧 {g?.last_from || "—"} · 视频 {g?.video_take != null ? `v${g.video_take}` : "未出"}
        </span>
        <span className="grow" />
        <button className="btn" onClick={onClose}>
          关闭（Esc）
        </button>
      </div>
      <div className="pair3-body" onClick={(e) => e.stopPropagation()}>
        {frames.map(([k, u]) => (
          <figure key={k}>
            {u ? <img src={u} alt={k} /> : <div className="pair3-empty">gpu3 未出{k}</div>}
            <figcaption>{k}</figcaption>
          </figure>
        ))}
        <figure>
          {s.video ? <video src={s.video} controls autoPlay muted loop playsInline /> : <div className="pair3-empty">gpu3 未出视频</div>}
          <figcaption>视频</figcaption>
        </figure>
      </div>
    </div>
  );
}

/** gpu3 负责时：笔记本已有的帧只作历史 */
function LaptopHistoryStrip({ s, st }: { s: ShotSummary; st: Studio }) {
  const h = s.laptop_history;
  if (!h) return null;
  return (
    <button
      className="hist3"
      onClick={(e) => (e.stopPropagation(), st.select(s.id), st.openViewer(s.id, "image"))}
      title={`${h.note}：这一镜由 gpu3 出整条链，这些笔记本版本不会进视频。点击查看笔记本版本`}
    >
      <span className="hist3-k">{h.note}</span>
      {h.first && <img src={h.first} alt="笔记本首帧" loading="lazy" />}
      {h.last && <img src={h.last} alt="笔记本尾帧" loading="lazy" />}
      {h.video && <span className="muted small">+视频</span>}
    </button>
  );
}

const R_ICON = { ok: "✓", warn: "!", fail: "✗" } as const;

/** 行内就绪（E7③ 行内只留关键信息）：一个状态 + 一行“缺什么”；原因悬停看，点击进检查器「审片」页 */
function ReadinessLine({ s, onOpen }: { s: ShotSummary; onOpen: () => void }) {
  const r = s.readiness;
  if (!r) return null;
  const notOk = r.items.filter((i) => i.level !== "ok");
  const fails = notOk.filter((i) => i.level === "fail");
  const why = [...notOk.map((i) => `${R_ICON[i.level]} ${i.label}：${i.reason}`), ...r.gpu3_blocked_reasons.map((x) => `✗ gpu3：${x}`)].join("\n");
  return (
    <div className="ready3-line" onClick={(e) => (e.stopPropagation(), onOpen())} title={why || "全部要素齐全，衔接通过：可以出视频"}>
      <span className={`ready3-state ${r.ready ? "r-ok" : "r-fail"}`}>{r.ready ? "✓ 就绪" : "✗ 未就绪"}</span>
      {!r.ready && (
        <span className="ready3-miss">
          {fails.length > 0 && <span className="r-fail">缺 {fails.map((i) => i.label).join("、")}</span>}
          {notOk.length > fails.length && <span className="r-warn"> · 待查 {notOk.length - fails.length}</span>}
          {r.gpu3_blocked_reasons.length > 0 && <span className="r-fail"> · gpu3 阻塞 {r.gpu3_blocked_reasons.length}</span>}
        </span>
      )}
    </div>
  );
}

/** 未选中行的提示词 / 声音：一排小标签，点击打开检查器对应字段 */
function PromptChips({ s, onOpen }: { s: ShotSummary; onOpen: (tab: "first" | "video", field: string) => void }) {
  const a = s.audio;
  const chip = (key: string, label: string, cls: string, title: string, tab: "first" | "video", field: string) => (
    <button key={key} className={`chip ${cls}`} title={title} onClick={(e) => (e.stopPropagation(), onOpen(tab, field))}>
      {label}
    </button>
  );
  return (
    <div className="pchips3">
      {chip("img", `首帧词${s.image_prompt_edited ? "·已改" : ""}`, s.image_prompt_edited ? "chip-accent" : "chip-dark", s.image_prompt_focus || s.image_prompt, "first", "image_prompt")}
      {s.h3_lint
        ? chip("h3", `H3 §9A ${s.h3_lint_ok ? "✓" : `✗${(s.h3_failed ?? []).length}`}`, s.h3_lint_ok ? "chip-ok" : "chip-bad",
            `${s.h3_prompt_source_label ?? ""}\n${s.h3_blocks?.body || s.video_prompt}`, "video", "h3_body")
        : chip("h3", "视频词", "chip-dark", s.video_prompt, "video", "h3_body")}
      {a && chip("sc", `🔊${a.soundscape.text ? "" : " 未设"}`, a.soundscape.text ? "chip-dark" : "chip-warn", `环境声（进 H3）\n${a.soundscape.text || "未设"}`, "video", "soundscape")}
      {a && chip("mu", `🎵 ${s.h3_blocks?.music && s.h3_blocks.music !== "N/A" ? "进 H3" : "N/A"}`, "chip-dark",
        `配乐（H3 non_diegetic_music）：${s.h3_blocks?.music || "N/A"}\n本镜提示：${a.music.text || "—"}\n本集：${a.episode_music.text || "—"}`, "video", "music")}
    </div>
  );
}

/** 就绪清单（docs/audit/shot_readiness_and_continuity.md §2/§4）：8 要素 + 衔接，缺什么写明（检查器用） */
export function ReadinessList({ s }: { s: ShotSummary }) {
  const r = s.readiness;
  if (!r) return null;
  const notOk = r.items.filter((i) => i.level !== "ok");
  const chipText = (i: ReadinessItem) =>
    i.key === "duration"
      ? `时长 ${i.level === "warn" ? "默认" : ""}${s.duration?.seconds ?? 10}s`
      : i.key === "continuity" && !i.ok && i.level === "warn"
        ? "衔接 未检查"
        : i.label;
  return (
    <div className={`ready3${r.ready ? " is-ready" : " is-blocked"}`} onClick={(e) => e.stopPropagation()}>
      <div className="ready3-chips">
        <span className={`ready3-state ${r.ready ? "r-ok" : "r-fail"}`} title={r.ready ? "全部要素齐全，衔接通过：可以出视频" : r.blocked_reasons.join("\n")}>
          {r.ready ? "✓ 就绪" : "✗ 未就绪"}
        </span>
        {r.items.map((i) => (
          <span key={i.key} className={`rchip r-${i.level}`} title={`${i.label}：${i.reason}\n来源：${i.source}`}>
            <b>{i.level === "warn" && !i.ok ? "?" : R_ICON[i.level]}</b>
            {chipText(i)}
          </span>
        ))}
      </div>
      {(notOk.length > 0 || r.gpu3_blocked_reasons.length > 0) && (
        <ul className="ready3-why">
          {notOk.map((i) => (
            <li key={i.key} className={`r-${i.level}`}>
              <b>{i.label}</b>
              {i.reason}
            </li>
          ))}
          {r.gpu3_blocked_reasons.map((x, k) => (
            <li key={`g${k}`} className="r-fail">
              <b>gpu3 blocked</b>
              {x}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export interface ShotRowProps {
  s: ShotSummary;
  detail?: ShotDetail;
  job?: Job;
  selected: boolean;
  inMulti: boolean;
  dim?: boolean;
  hlChar?: string | null;
  compact: boolean;
  /** SOP 阶段与阻塞（/api/sop/episode/{n}） */
  sop?: SopShot;
  onClick: (e: MouseEvent) => void;
}

export const ShotRow = memo(function ShotRow({ s, detail, job, selected, inMulti, dim, hlChar, compact, sop, onClick }: ShotRowProps) {
  const st = useStudio();
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const [pair, setPair] = useState(false);
  const g3 = isGpu3Row(s);
  const anyLive = !!(st.liveJob(s.id, "image") || st.liveJob(s.id, "last") || st.liveJob(s.id, "video"));
  const cam = s.camera;
  const failed = isFailed(s, job, detail);
  // 运镜常写成「camera tilt up 缓慢上摇」：有中文就只显示中文
  const zh = (t: string) => (/[一-鿿]/.test(t) ? t.replace(/^[A-Za-z][A-Za-z ]*\s+(?=[一-鿿])/, "") : t);
  const openTab = (tab: Parameters<Studio["openInspTab"]>[0], field?: string) => {
    st.select(s.id);
    st.openInspTab(tab, field);
  };
  const idx = s.id.split("-")[1];
  return (
    <article
      className={`srow${selected ? " selected" : ""}${inMulti ? " multi" : ""}${dim ? " dim" : ""}${anyLive ? " live" : ""}`}
      onClick={onClick}
      data-shot={s.id}
    >
      <div className="srow-left">
        <div className="srow-frames">
          <FrameTile s={s} stage="image" st={st} onPair={() => setPair(true)} />
          <FrameTile s={s} stage="last" st={st} onPair={() => setPair(true)} />
        </div>
        {selected && <RowTakes s={s} d={detail} st={st} />}
        {selected && <LaptopHistoryStrip s={s} st={st} />}
      </div>
      {pair && <Gpu3Pair s={s} onClose={() => setPair(false)} />}
      <div className="srow-info">
        <header className="srow-head">
          <b className="srow-id">{idx}</b>
          <span className="srow-meta" title={[cam.size, cam.angle, cam.move].filter(Boolean).join(" · ")}>
            {[cam.size, cam.angle, zh(cam.move)].filter(Boolean).map((h) => (
              <span key={h}>{h}</span>
            ))}
          </span>
          {/* fredw-b3：时长单独一枚，数字醒目；“默认”只在剧本没写时出现，细节在悬停里 */}
          <span
            className={`srow-dur${s.duration?.source === "script" ? "" : " dflt"}`}
            title={`${s.duration?.source === "script" ? "剧本写明的时长" : "剧本没写时长，按默认 10 秒"}${s.h3_frames ? `；H3 按 17k+5 取 ${s.h3_frames} 帧` : ""}`}
          >
            <b>{s.duration?.seconds ?? 10}</b> 秒
            {s.h3_frames ? <span className="srow-frm">{s.h3_frames} 帧</span> : null}
            {s.duration?.source !== "script" && <span className="srow-dflt">默认</span>}
          </span>
          <span className="srow-tags">
          {selected && (<>
          <span
            className={`chip ${g3 ? "chip-src-gpu3" : s.frames_source === "laptop" ? "chip-src-laptop" : ""}`}
            title={`首尾帧与视频来源：${s.frames_source === "gpu3" ? "gpu3 take 链" : s.frames_source === "laptop" ? "笔记本" : "还没有"}\n负责：${s.owner ?? "—"}（${s.owner_reason ?? ""}）`}
          >
            {g3 ? (s.frames_source === "none" ? "gpu3 未出" : "gpu3") : s.frames_source === "laptop" ? "笔记本" : "未出图"}
          </span>
          <SopChip s={sop} />
          {s.adult && (
            <span className="chip chip-adult" title="成人路由，本地渲染">
              本地
            </span>
          )}
          {s.has_boost && <span className="chip chip-boost">导演加强</span>}
          </>)}
          <BusyChip s={s} st={st} />
          {s.explicit_hold && (
            <span className="chip chip-explicit" title={`来源：${s.explicit_hold.sources.join("、")}。项目方自己改剧本；重新导入 + gpu3 复查清掉后自动恢复`}>
              {EXPLICIT_LABEL}
            </span>
          )}
          {failed && (
            <span className="chip chip-bad" title={`${job?.error ?? detail?.error?.last ?? ""}\n处理：选中这一镜，在右侧检查器底部点「重出」（或按 I / E）重试；仍失败看底部抽屉「任务」日志`}>
              渲染失败
            </span>
          )}
          </span>
          <span className="srow-right">
          <StepChips s={s} liveOf={(stage: Stage) => st.liveJob(s.id, stage)} />
          <span className="menu-anchor" onClick={(e) => e.stopPropagation()}>
            <button className="btn ghost dots" onClick={() => setMenu((m) => !m)} title="更多操作">
              ⋯
            </button>
            {menu && s.explicit_hold && (
              <div className="menu right" onMouseLeave={() => setMenu(false)}>
                <button disabled title="露骨红标镜头：不做任何自动出图 / 重出 / 生成">{EXPLICIT_LABEL}：自动操作已停用</button>
                <button onClick={() => (setMenu(false), openTab("script"))}>看剧本…</button>
              </div>
            )}
            {menu && !s.explicit_hold && (
              <div className="menu right" onMouseLeave={() => setMenu(false)}>
                {g3 ? (
                  <>
                    <button disabled title={GPU3_OWNS}>重出首帧（笔记本）</button>
                    <button disabled title={GPU3_OWNS}>重出尾帧（笔记本）</button>
                    <button disabled title={GPU3_OWNS}>出视频（笔记本）</button>
                    <button onClick={() => (setMenu(false), st.requestGpu3(s.id, "image"))} title="写进 gpu3 重渲队列：重画首帧，尾帧随之重编">
                      请 gpu3 重出首帧（I）
                    </button>
                    <button disabled={!s.first_frame} onClick={() => (setMenu(false), st.requestGpu3(s.id, "last"))} title="保留首帧，由首帧重编尾帧">
                      请 gpu3 重出尾帧（E）
                    </button>
                    <button disabled={!s.first_frame} onClick={() => (setMenu(false), st.requestGpu3(s.id, "video"))} title="保留首尾帧，只重出视频">
                      请 gpu3 重出视频（V）
                    </button>
                  </>
                ) : (
                  <>
                    <button onClick={() => (setMenu(false), st.requestRender(s.id, "image"))}>重出首帧（I）</button>
                    <button disabled={!s.first_frame || !s.last_supported} onClick={() => (setMenu(false), st.requestRender(s.id, "last"))}>
                      重出尾帧（E）
                    </button>
                    <button disabled={!s.first_frame} onClick={() => (setMenu(false), st.requestRender(s.id, "video"))}>
                      {laptopVideoEnabled() ? "出视频·本机（V）" : "请 gpu3 出视频（V）"}
                    </button>
                  </>
                )}
                <button onClick={() => (setMenu(false), openTab("boost"))}>导演加强…</button>
                <button onClick={() => (setMenu(false), openTab("people"))}>本镜造型…</button>
              </div>
            )}
          </span>
          </span>
        </header>

        {selected && <ReadinessLine s={s} onOpen={() => openTab("review")} />}

        <div className={`script3${open ? " open" : ""}`} onClick={(e) => e.stopPropagation()}>
          <span className="script3-text">{s.script_text || <span className="muted">（剧本无画面描述）</span>}</span>
          {s.script_text.length > 70 && (
            <button className="link" onClick={() => setOpen((o) => !o)}>
              {open ? "收起" : "展开"}
            </button>
          )}
        </div>

        <Expression s={s} st={st} />
        <Lines s={s} />

        <PeopleStrip shotId={s.id} chars={s.characters} hl={hlChar} onOpen={(c) => st.openAssets({ character: c.character, lookId: c.look_id })} />

        {compact && selected && <PromptChips s={s} onOpen={(tab, f) => openTab(tab, f)} />}
        {!compact && selected && (
          <div className="prompts3">
            <PromptLine label="首帧提示词" text={s.image_prompt_focus || s.image_prompt} edited={s.image_prompt_edited} onOpen={() => openTab("first", "image_prompt")} />
            <PromptLine label="H3 提示词" text={s.h3_blocks?.body || s.video_prompt} edited={s.video_prompt_edited} lint={s} onOpen={() => openTab("video", "h3_body")} />
            <SoundLine s={s} onOpen={(f) => openTab("video", f)} />
          </div>
        )}
      </div>
    </article>
  );
});
