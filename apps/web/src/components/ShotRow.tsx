import { memo, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { api } from "../api";
import { useStudio, type FrameStage } from "../store";
import type { CharacterBrief, Job, ReadinessItem, ShotDetail, ShotSummary, SopShot, Stage } from "../types";
import { SopChip } from "./SopBar";
import { isFailed, LAST_SOURCE_LABEL, SLOT_NAME } from "../util";
import { JobBar, Score, StepChips } from "./frames";

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
    const d = st.details[s.id] ?? (await api.shot(s.id));
    await st.saveEdit(s.id, { ...d.edit, last_frame: "next", last_source: "next" });
  };

  const g = s.gpu3;
  const mirrored = !g ? true : isFirst ? g.first_mirrored : g.last_mirrored;
  const from = !g ? "" : isFirst ? g.first_from : g.last_from;
  let body: ReactNode;
  if (g3 && !url) {
    const needFirst = !isFirst && !s.first_frame;
    body = (
      <div className="tile-empty" onClick={(e) => e.stopPropagation()}>
        <span className="tile-empty-t">gpu3 未出{label}</span>
        <span className="tile-hint">{needFirst ? "尾帧由本链首帧编辑得到，先等 gpu3 出首帧" : "这一镜由 gpu3 出整条链，笔记本不出图"}</span>
        <button className="btn" onClick={() => st.requestGpu3(s.id, isFirst ? "image" : "last")} title="写进 gpu3 的重渲队列（docs/canvas.md §2）">
          请 gpu3 出{label}
        </button>
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
      className={`tile${url ? " has" : " empty"}${live ? " busy" : ""}`}
      onClick={() => {
        st.select(s.id);
        if (url) {
          if (g3) onPair();
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

const STRIP_SLOTS = ["outfit", "shoes", "nails", "makeup", "hair", "accessory"] as const;
const STRIP_LABEL: Record<string, string> = { outfit: "衣", shoes: "鞋", nails: "甲", makeup: "妆", hair: "发", accessory: "饰" };

/** 人物条：脸 + 本镜造型的单品真图（缺图红框） */
export function PeopleStrip({ chars, hl, onOpen }: { chars: CharacterBrief[]; hl?: string | null; onOpen: (c: CharacterBrief) => void }) {
  if (!chars.length) return <div className="muted">本镜无出场角色</div>;
  return (
    <div className="people3">
      {chars.map((c) => {
        const err = c.conflicts.filter((x) => x.severity === "error");
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
              <span className="p3-look" title={c.label}>
                {c.look_label ? `造型 ${c.look_label}` : c.look_name || "默认"}
                {c.d_state ? ` · ${c.d_state}` : ""}
              </span>
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
                  if (slot === "accessory") return null;
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
          <span className="line-k">💬</span>
          <span>
            {d.stage && <span className="stage-dir">〔{d.stage}〕</span>}
            {d.speaker_note && <b className="spk">{d.speaker_note}：</b>}
            {d.text}
          </span>
        </div>
      ))}
      {s.voiceover && (
        <div className="line3 vo">
          <span className="line-k">🎙</span>
          <span>
            {s.voiceover.note && <span className="stage-dir">〔{s.voiceover.note}〕</span>}
            <b className="spk">独白：</b>
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
    const d = st.details[s.id] ?? (await api.shot(s.id));
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
      <button className="link">展开/编辑</button>
    </div>
  );
}

/** 🔊 环境声（进 H3）| 🎵 配乐（后期）：各一行预览，点击打开检查器视频页的编辑框 */
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
        <span className="k3">🔊 环境声</span>
        <span className={`pl3-text${sc.text ? "" : " warn"}`}>{sc.text || "未设 · 点击填写"}</span>
        {sc.source === "edit" && <span className="chip chip-accent">已改</span>}
      </div>
      <div className="pl3" onClick={(e) => (e.stopPropagation(), onOpen("music"))} title={`背景音乐（后期混音）
本镜：${cue.text || "—"}
本集：${ep.text || "—"}`}>
        <span className="k3">🎵 背景音乐</span>
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
  const frames: [string, string | null][] = [
    ["首帧", s.first_frame],
    ["尾帧", s.last_frame_target],
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

/** 就绪清单（docs/audit/shot_readiness_and_continuity.md §2/§4）：8 要素 + 衔接，缺什么写明 */
function ReadinessList({ s }: { s: ShotSummary }) {
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
  const head = [cam.size, zh(cam.move || cam.angle)].filter(Boolean);
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
        <LaptopHistoryStrip s={s} st={st} />
      </div>
      {pair && <Gpu3Pair s={s} onClose={() => setPair(false)} />}
      <div className="srow-info">
        <header className="srow-head">
          <b className="srow-id">{idx}</b>
          {head.map((h) => (
            <span key={h} className="srow-cam">
              · {h}
            </span>
          ))}
          <span className="srow-cam" title={s.duration?.source === "script" ? "剧本写明的时长" : "剧本没写，默认 10 秒"}>
            · 时长 {s.duration?.seconds ?? 10}s
          </span>
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
          {failed && (
            <span className="chip chip-bad" title={job?.error ?? detail?.error?.last ?? ""}>
              渲染失败
            </span>
          )}
          <span className="srow-right">
          <StepChips s={s} liveOf={(stage: Stage) => st.liveJob(s.id, stage)} />
          <span className="menu-anchor" onClick={(e) => e.stopPropagation()}>
            <button className="btn ghost dots" onClick={() => setMenu((m) => !m)} title="更多操作">
              ⋯
            </button>
            {menu && (
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
                      出视频（V）
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

        <ReadinessList s={s} />

        {cam.angle && cam.move && <div className="srow-sub muted">机位 {cam.angle}{cam.lens ? ` · ${cam.lens}` : ""}</div>}

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

        <PeopleStrip chars={s.characters} hl={hlChar} onOpen={(c) => st.openAssets({ character: c.character, lookId: c.look_id })} />

        {!compact && (
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
