import { memo, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { api } from "../api";
import { useStudio, type Density, type InspectorTab } from "../store";
import type { CharacterBrief, Job, ShotDetail, ShotSummary, Stage, TakeScore } from "../types";
import { EXPLICIT_LABEL, isFailed, JOB_LABEL, LAST_SOURCE_LABEL, parseReason, REVIEW_LABEL, shotLine, SLOT_LABEL, SLOT_NAME } from "../util";

export interface ShotCardProps {
  s: ShotSummary;
  detail?: ShotDetail;
  job?: Job;
  selected: boolean;
  inMulti: boolean;
  dim?: boolean;
  highlightChar?: string | null;
  density: Density;
  onClick: (e: MouseEvent) => void;
}

type Cell = "ok" | "warn" | "bad" | "none" | "busy";
const CARD_SLOTS = ["outfit", "shoes", "nails", "hair", "makeup", "accessory"] as const;

/** 四格状态条：首帧 / 尾帧 / 视频 / 审核（规范 §3.1） */
export function mediaChain(s: ShotSummary, d: ShotDetail | undefined, job: Job | undefined): [string, Cell, string][] {
  const failed = isFailed(s, job, d);
  const jobStage = job && (job.state === "queued" || job.state === "running" || job.state === "failed") ? job.stage : null;
  const cell = (stage: Stage, has: boolean): [Cell, string] => {
    const stale = s.stale[stage] ?? [];
    if (s.job && jobStage === stage) return ["busy", JOB_LABEL[s.job]];
    if (failed && jobStage === stage) return ["bad", "渲染失败"];
    if (!has) return ["none", "缺失"];
    if (stale.length) return ["warn", `已过期：${stale.join("、")}`];
    return ["ok", "最新"];
  };
  const [ic, it] = cell("image", !!s.first_frame);
  const [lc, lt0] = cell("last", !!s.last_frame_target);
  const lt = s.last_frame_source ? `${lt0}（来源：${LAST_SOURCE_LABEL[s.last_frame_source]}）` : lt0;
  const [vc, vt] = cell("video", !!s.video);
  const r = s.review.state;
  const rc: Cell = r === "passed" ? "ok" : r === "rejected" ? "bad" : "none";
  return [
    ["首帧", ic, it],
    ["尾帧", lc, lt],
    ["视频", vc, vt],
    ["审核", rc, REVIEW_LABEL[r] + (s.review.reason ? `：${s.review.reason}` : "")],
  ];
}

export function scoreTitle(sc: TakeScore): string {
  return [`评分 ${sc.total}`, ...(sc.missing?.length ? [`缺：${sc.missing.join("、")}`] : []), ...(sc.reasons ?? [])].join("\n");
}

export function ScoreBadge({ sc }: { sc: TakeScore | null | undefined }) {
  if (!sc || typeof sc.total !== "number") return null;
  const cls = sc.missing?.length ? "b-stale" : "b-score";
  const v = sc.total <= 1 ? Math.round(sc.total * 100) : Math.round(sc.total);
  return (
    <span className={`badge ${cls}`} title={scoreTitle(sc)}>
      {v}分{sc.missing?.length ? ` 缺${sc.missing.length}` : ""}
    </span>
  );
}

interface Actions {
  stop: (fn: () => void) => (e: MouseEvent) => void;
  render: (stage: Stage) => void;
  renderOther: (id: string, stage: Stage) => void;
  useNext: () => void;
  uploadLast: (f: File) => Promise<void>;
  openTab: (tab: InspectorTab, field?: string) => void;
  openSeam: () => void;
}

/** 首帧槽：悬停 150 ms 播放视频；空状态带就地动作 */
function FirstSlot({ s, act }: { s: ShotSummary; act: Actions }) {
  const [play, setPlay] = useState(false);
  const t = useRef<number | undefined>(undefined);
  useEffect(() => () => clearTimeout(t.current), []);
  const stale = s.stale.image ?? [];
  const busy = s.job && s.job_stage === "image";
  return (
    <div
      className="frame-slot"
      onMouseEnter={() => {
        if (s.video) t.current = window.setTimeout(() => setPlay(true), 150);
      }}
      onMouseLeave={() => {
        clearTimeout(t.current);
        setPlay(false);
      }}
    >
      <span className="slot-cap">首帧</span>
      {play && s.video ? (
        <video src={s.video} autoPlay muted loop playsInline />
      ) : s.first_frame ? (
        <img src={s.first_frame} alt="首帧" loading="lazy" draggable={false} />
      ) : (
        <div className="slot-empty">
          <span>无首帧</span>
          {busy ? (
            <span className="slot-progress">{s.job === "running" ? "渲染中…" : `排队 #${s.queue_pos ?? "?"}`}</span>
          ) : (
            <button className="btn-mini" onClick={act.stop(() => act.render("image"))} title="I">
              生成首帧 <kbd>I</kbd>
            </button>
          )}
        </div>
      )}
      <div className="slot-badges">
        {s.first_frame_take != null && <span className="badge b-ver">v{s.first_frame_take}</span>}
        {stale.length > 0 && (
          <span className="badge b-stale" title={stale.join("、")}>
            过期
          </span>
        )}
        <ScoreBadge sc={s.score?.image} />
      </div>
      {busy && s.first_frame && <div className="slot-busy">{s.job === "running" ? "渲染中" : `排队 #${s.queue_pos ?? "?"}`}</div>}
    </div>
  );
}

function LastSlot({ s, act }: { s: ShotSummary; act: Actions }) {
  const [menu, setMenu] = useState(false);
  const file = useRef<HTMLInputElement>(null);
  const stale = s.stale.last ?? [];
  const src = s.last_frame_source;
  const busy = s.job && s.job_stage === "last";
  const nextIdx = s.next_shot?.split("-")[1];
  const genDisabled = !s.first_frame ? "尾帧以首帧为底图，先出首帧" : !s.last_supported ? "尾帧生成尚未上线（render_router）" : "";
  const showActual = s.last_frame_actual && s.last_frame_target && s.last_frame_actual !== s.last_frame_target;

  let body: ReactNode;
  if (s.last_frame_target) {
    body = <img src={s.last_frame_target} alt="尾帧" loading="lazy" draggable={false} />;
  } else if (src === "next") {
    body = (
      <div className="slot-empty">
        <span>等 {nextIdx ?? "下一镜"} 首帧</span>
        {s.next_shot && (
          <button className="btn-mini" onClick={act.stop(() => act.renderOther(s.next_shot!, "image"))}>
            先出 {nextIdx} 首帧
          </button>
        )}
      </div>
    );
  } else {
    body = (
      <div className="slot-empty">
        <span>无尾帧</span>
        {busy ? (
          <span className="slot-progress">{s.job === "running" ? "渲染中…" : `排队 #${s.queue_pos ?? "?"}`}</span>
        ) : (
          <div className="split-btn" onClick={(e) => e.stopPropagation()}>
            <button className="btn-mini" disabled={!!genDisabled} title={genDisabled || "E"} onClick={() => act.render("last")}>
              生成尾帧
            </button>
            <button className="btn-mini more" onClick={() => setMenu((m) => !m)} title="用下一镜首帧 / 上传 / 从版本挑">
              其他来源 ▾
            </button>
            {menu && (
              <div className="menu" onMouseLeave={() => setMenu(false)}>
                <button disabled={!s.next_shot} onClick={() => (setMenu(false), act.useNext())}>
                  用下一镜首帧{s.next_shot ? `（${nextIdx}）` : ""}
                </button>
                <button onClick={() => (setMenu(false), file.current?.click())}>上传…</button>
                <button onClick={() => (setMenu(false), act.openTab("takes"))}>从版本挑</button>
              </div>
            )}
          </div>
        )}
        {genDisabled && !busy && <span className="slot-hint">{genDisabled}</span>}
        <input
          ref={file}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void act.uploadLast(f);
            e.target.value = "";
          }}
        />
      </div>
    );
  }
  return (
    <div className="frame-slot">
      <span className="slot-cap">尾帧</span>
      {body}
      <div className="slot-badges">
        {src && (
          <span className={`badge b-src b-src-${src}`}>
            {s.last_frame_take != null && src === "gen" ? `v${s.last_frame_take} ` : ""}
            {LAST_SOURCE_LABEL[src]}
          </span>
        )}
        {stale.length > 0 && (
          <span className="badge b-stale" title={stale.join("、")}>
            过期
          </span>
        )}
        <ScoreBadge sc={s.score?.last} />
      </div>
      {showActual && (
        <button className="actual-inset" title="视频实际尾帧与目标不同：点击打开接缝对比" onClick={act.stop(act.openSeam)}>
          <img src={s.last_frame_actual!} alt="实际" />
          <span>实际</span>
        </button>
      )}
    </div>
  );
}

export function PersonRow({ c, hl, onFace }: { c: CharacterBrief; hl: boolean; onFace: () => void }) {
  const err = c.conflicts.some((x) => x.severity === "error");
  const title = [
    c.label,
    c.has_override ? "本镜覆盖" : "继承（默认 / 集计划）",
    c.changed_from_prev ? `换装点：${c.changed_fields.join("、")}` : "",
    ...c.conflicts.map((x) => `${x.severity === "error" ? "✖" : "⚠"} ${x.message}`),
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <div className={`person${c.has_override ? " ov" : ""}${c.changed_from_prev ? " chg" : ""}${hl ? " hl" : ""}${err ? " err" : ""}`} title={title}>
      <div className="person-head">
        <button className="face" onClick={(e) => (e.stopPropagation(), onFace())} title={c.face_url ? "打开资产页：该角色该造型" : "没有脸图：去资产页补 plates"}>
          {c.face_url ? <img src={c.face_url} alt={c.name} loading="lazy" /> : <span className="face-missing" />}
        </button>
        <span className="person-name">
          {c.name}
          <b className="look-letter">{c.look_label || c.look_name || "—"}</b>
          {c.look_label && c.look_name && <span className="muted">{c.look_name}</span>}
        </span>
        {c.d_state && <span className="dstate">{c.d_state}</span>}
        {c.has_override && <b className="lt-mark">改</b>}
      </div>
      <div className="item-row">
        {CARD_SLOTS.map((slot) => {
          const v = c.slots.find((x) => x.slot === slot);
          const items = v?.items ?? [];
          if (!items.length)
            return (
              <span key={slot} className="item-thumb unset" title={`${SLOT_NAME[slot]}：未设`}>
                {SLOT_LABEL[slot]}
              </span>
            );
          const it = items[0];
          return (
            <span
              key={slot}
              className={`item-thumb${it.thumb_url ? "" : " noimg"}${v?.changed ? " chg" : ""}${v?.source === "shot" ? " ov" : ""}`}
              title={`${SLOT_NAME[slot]}：${items.map((x) => x.name).join("、")}${it.thumb_url ? "" : "\n没有参考图：只用文字描述"}`}
            >
              {it.thumb_url ? <img src={it.thumb_url} alt="" loading="lazy" /> : SLOT_LABEL[slot]}
              {items.length > 1 && <i>{items.length}</i>}
            </span>
          );
        })}
      </div>
    </div>
  );
}

/** 表情 / 镜头：edit = 普通文字，auto = 灰色斜体，none = 黄色「未标注」，点一下就地编辑 */
function InlineField({
  label,
  value,
  source,
  parts,
  onSave,
  onOpen,
}: {
  label: string;
  value: string;
  source: "edit" | "auto" | "none";
  parts?: [string, "edit" | "auto" | "none" | undefined][];
  onSave: (v: string) => Promise<boolean>;
  onOpen: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  if (editing)
    return (
      <div className="cf-row" onClick={(e) => e.stopPropagation()}>
        <span className="cf-k">{label}</span>
        <input
          autoFocus
          className="cf-input"
          value={v}
          onChange={(e) => setV(e.target.value)}
          onKeyDown={async (e) => {
            if (e.key === "Enter") {
              if (await onSave(v)) setEditing(false);
            } else if (e.key === "Escape") {
              setEditing(false);
              setV(value);
            }
          }}
          onBlur={() => setEditing(false)}
          placeholder="回车保存，Esc 取消"
        />
      </div>
    );
  return (
    <div className="cf-row" onDoubleClick={(e) => (e.stopPropagation(), onOpen())}>
      <span className="cf-k">{label}</span>
      {source === "none" ? (
        <button className="unlabeled" onClick={(e) => (e.stopPropagation(), setEditing(true))} title="点击就地标注">
          未标注
        </button>
      ) : (
        <span
          className="cf-v clamp2"
          title={`${value}\n（${source === "edit" ? "人工" : "自动解析"}；点击修改，双击打开检查器）`}
          onClick={(e) => (e.stopPropagation(), setEditing(true))}
        >
          {parts ? (
            parts
              .filter(([t]) => t)
              .map(([t, src], i) => (
                <span key={i} className={src === "auto" ? "auto" : ""}>
                  {i > 0 && " · "}
                  {t}
                </span>
              ))
          ) : (
            <span className={source === "auto" ? "auto" : ""}>{value}</span>
          )}
        </span>
      )}
    </div>
  );
}

function TextField({
  k,
  text,
  edited,
  lines,
  onOpen,
  cls,
  full,
}: {
  k: ReactNode;
  text: string;
  full?: string;
  edited?: boolean;
  lines: number;
  onOpen: () => void;
  cls?: string;
}) {
  return (
    <div className={`cf-row cf-text ${cls ?? ""}`} onDoubleClick={(e) => (e.stopPropagation(), onOpen())} title={`${full ?? text}\n（双击打开检查器）`}>
      <span className="cf-k">
        {k}
        {edited && <b className="edit-mark">改</b>}
      </span>
      <span className={`cf-v clamp${lines}`}>{text || <span className="muted">—</span>}</span>
    </div>
  );
}

export const ShotCard = memo(function ShotCard({ s, detail, job, selected, inMulti, dim, highlightChar, density, onClick }: ShotCardProps) {
  const st = useStudio();
  const line = shotLine(s);
  const failed = isFailed(s, job, detail);
  const reason = parseReason(s.review.reason);
  const [menu, setMenu] = useState(false);

  const getDetail = async () => detail ?? (await api.shot(s.id));
  const act: Actions = {
    stop: (fn) => (e) => {
      e.stopPropagation();
      fn();
    },
    render: (stage) => st.requestRender(s.id, stage),
    renderOther: (id, stage) => st.requestRender(id, stage),
    useNext: async () => {
      const d = await getDetail();
      await st.saveEdit(s.id, { ...d.edit, last_frame: "next", last_source: "next" });
    },
    uploadLast: async (f) => {
      try {
        await api.uploadLastFrame(s.id, f);
        st.notify(`${s.id} 尾帧已上传`);
        await st.refreshAfter([s.id]);
      } catch (e) {
        st.notify(`上传失败：${(e as Error).message}`, "err");
      }
    },
    openTab: (tab, field) => {
      st.select(s.id);
      st.openInspTab(tab, field);
    },
    openSeam: () => {
      if (!s.next_shot) return;
      st.setSeam({ from: s.id, to: s.next_shot });
      st.setDrawer({ open: true, tab: "seam" });
    },
  };
  const saveField = (field: "expression" | "camera") => async (v: string) => {
    const d = await getDetail();
    return st.saveEdit(s.id, { ...d.edit, [field]: v.trim() || null });
  };
  const cam = s.camera;
  const compact = density === "compact";
  const lines = density === "detail" ? 99 : 2;

  return (
    <div
      className={`shot-card v2 d-${density}${selected ? " selected" : ""}${inMulti ? " multi" : ""}${dim ? " dim" : ""}`}
      onClick={onClick}
      data-shot={s.id}
    >
      <div className="card-id-row">
        <b>{s.id}</b>
        <span className={`rv-dot r-${s.review.state}`} title={REVIEW_LABEL[s.review.state] + (reason.code ? ` · ${reason.code}` : "")} />
        <span className="rv-text">{REVIEW_LABEL[s.review.state]}</span>
        <span className="grow" />
        {s.adult && (
          <span className="badge b-adult" title="成人路由，本地渲染">
            本地
          </span>
        )}
        {s.explicit_hold && (
          <span className="badge b-explicit" title={`${EXPLICIT_LABEL}（${s.explicit_hold.sources.join("、")}）`}>
            露骨
          </span>
        )}
        {s.has_boost && (
          <span className="badge b-boost" title="有导演加强（本镜或本集）">
            加强
          </span>
        )}
        {s.edited && (
          <span className="badge b-edited" title="有人工修改">
            改
          </span>
        )}
        {failed && (
          <span className="badge b-failed" title={job?.error ?? detail?.error?.last ?? ""}>
            失败
          </span>
        )}
        <span className="card-menu" onClick={(e) => e.stopPropagation()}>
          <button className="btn-mini ghost" onClick={() => setMenu((m) => !m)} title="更多操作">
            ⋯
          </button>
          {menu && (
            <div className="menu right" onMouseLeave={() => setMenu(false)}>
              <button onClick={() => (setMenu(false), act.render("image"))}>重出首帧（I）</button>
              <button disabled={!s.first_frame || !s.last_supported} onClick={() => (setMenu(false), act.render("last"))}>
                生成尾帧（E）
              </button>
              <button disabled={!s.first_frame} onClick={() => (setMenu(false), act.render("video"))}>
                出视频（V）
              </button>
              <button onClick={() => (setMenu(false), act.openTab("boost"))}>导演加强…</button>
              <button onClick={() => (setMenu(false), act.openTab("takes"))}>版本…</button>
            </div>
          )}
        </span>
      </div>

      <div className="frame-pair-card">
        <FirstSlot s={s} act={act} />
        <LastSlot s={s} act={act} />
      </div>

      <div className="people">
        {s.characters.length ? (
          s.characters.map((c) => (
            <PersonRow key={c.character} c={c} hl={highlightChar === c.character} onFace={() => st.openAssets({ character: c.character, lookId: c.look_id })} />
          ))
        ) : (
          <div className="muted small">无出场角色</div>
        )}
      </div>

      {!compact && (
        <div className="card-fields">
          <InlineField
            label="表情"
            value={s.expression.text}
            source={s.expression.source}
            onSave={saveField("expression")}
            onOpen={() => act.openTab("video", "expression")}
          />
          <InlineField
            label="镜头"
            value={cam.text}
            source={cam.source}
            parts={[
              [cam.size, cam.sources.size],
              [cam.angle, cam.sources.angle],
              [cam.move, cam.sources.move],
              [cam.lens, cam.sources.lens],
            ]}
            onSave={saveField("camera")}
            onOpen={() => act.openTab("video", "camera")}
          />
          <TextField k="剧本" text={s.script_text} lines={lines} onOpen={() => act.openTab("script")} />
          <TextField
            k={line.vo && !s.dialogue.length ? "🎙" : "💬"}
            text={line.text}
            lines={density === "detail" ? 99 : 1}
            onOpen={() => act.openTab("script")}
            cls="cf-line"
          />
          <TextField
            k="图"
            text={density === "detail" ? s.image_prompt : s.image_prompt_focus ?? s.image_prompt}
            full={s.image_prompt}
            edited={s.image_prompt_edited}
            lines={lines}
            onOpen={() => act.openTab("first", "image_prompt")}
          />
          <TextField
            k="尾"
            text={density === "detail" ? s.last_prompt : s.last_prompt_focus ?? s.last_prompt}
            full={s.last_prompt}
            edited={s.last_prompt_source === "edit"}
            lines={density === "detail" ? 99 : 1}
            onOpen={() => act.openTab("last", "last_prompt")}
          />
          <TextField k="视" text={s.h3_blocks?.body || s.video_prompt} edited={s.video_prompt_edited} lines={lines} onOpen={() => act.openTab("video", "h3_body")} />
        </div>
      )}

      <div className="chain">
        {mediaChain(s, detail, job).map(([k, c, t]) => (
          <span key={k} className={`chain-cell c-${c}`} title={`${k}：${t}`}>
            {k}
          </span>
        ))}
      </div>
    </div>
  );
});
