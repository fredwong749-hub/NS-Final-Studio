// fredw-92/W4a + v3.1 U1：审片模式的一行——首帧 | 尾帧 | 视频 三格同尺寸 9:16（视频可悬停播放 / 点击放大，有视频时强调）
// ｜文字列固定行数（剧本 2 · 表情 1 · 对白 2 · 人物小卡与提示词开关同一行）｜主按钮 = 下一步 + ⋯。状态胶囊点开 = 为什么卡住。
import { memo, useEffect, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { JobBar } from "../components/frames";
import { useStudio, type Studio } from "../store";
import type { ShotSummary, SopShot } from "../types";
import { expectedLast, matchFilter, shotLine } from "../util";
import { letterOf } from "./LeftRail";
import { frameState, shotMeta, shotStatus, staleOf, videoBlock } from "./status";
import { useUi } from "./ui";
import { useEdit } from "./edit/state";
import { Pop, StatusLine } from "./widgets";
import { apiV1 } from "./api_v1";
import { MissBadge, missingOf, StoryboardGrid, storyboardOf, useSbUi } from "./StoryboardDetails";

const short = (id: string) => id.split("-")[1];

/** 一格右上角的状态牌：过期优先于定稿（v3.1 §5.1），两者不同时出现 */
function StateTag({ state, why }: { state: ReturnType<typeof frameState>; why: string }) {
  if (state === "stale") return <span className="v3-ftag stale" title={why ? `已过期：${why}` : "已过期"}>过期·需重出</span>;
  if (state === "locked") return <span className="v3-ftag locked">已定稿</span>;
  return null;
}

function Frame({ s, stage, st }: { s: ShotSummary; stage: "image" | "last"; st: Studio }) {
  const first = stage === "image";
  const live = st.liveJob(s.id, stage);
  const d = st.details[s.id];
  let url = first ? s.first_frame : s.last_frame_target;
  let hint = "";
  if (!first && !url) {
    const e = expectedLast(s);
    if (e.url && !e.isVideo && e.kind !== "next") {
      url = e.url;
      hint = "参考，非尾帧";
    }
  }
  const take = first ? s.first_frame_take : s.last_frame_take;
  const label = first ? "首帧" : "尾帧";
  const fs = frameState(s, d, stage);
  const open = (e: MouseEvent) => {
    e.stopPropagation();
    st.select(s.id);
    if (url) st.openViewer(s.id, stage, "pair");
  };
  return (
    <div className={`v3-frame${url ? "" : " empty"}${fs === "stale" ? " stale" : ""}`} onClick={open} title={url ? `${label}：点开全屏对比（首帧 | 尾帧）` : `还没有${label}`}>
      {url ? <img src={url} alt={label} loading="lazy" draggable={false} /> : <span className="v3-frame-none">{label}未出</span>}
      <b className="v3-tag">
        {label}
        {take != null ? ` · #${take}` : ""}
      </b>
      <StateTag state={fs} why={staleOf(s, d, stage).filter(Boolean).join("；")} />
      {hint && <span className="v3-frame-hint">{hint}</span>}
      {live && (
        <div className="v3-frame-job">
          <JobBar live={live} compact />
        </div>
      )}
    </div>
  );
}

/** 放大播放（循环、带控件）；点背景或 Esc 关闭 */
function VideoBox({ src, title, onClose }: { src: string; title: string; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose]);
  return createPortal(
    <div className="v3-vbox" onMouseDown={(e) => e.target === e.currentTarget && onClose()} role="dialog" aria-label={title}>
      <div className="v3-vbox-in">
        <header>
          <b>{title}</b>
          <span className="v3-grow" />
          <button className="v3-btn" onClick={onClose}>
            关闭 Esc
          </button>
        </header>
        <video src={src} controls autoPlay loop playsInline />
      </div>
    </div>,
    document.body,
  );
}

function VideoTile({ s, st }: { s: ShotSummary; st: Studio }) {
  const live = st.liveJob(s.id, "video");
  const ref = useRef<HTMLVideoElement>(null);
  const [big, setBig] = useState(false);
  const d = st.details[s.id];
  const fs = frameState(s, d, "video");
  const blk = s.video ? null : videoBlock(s, d);
  const play = () => void ref.current?.play().catch(() => undefined);
  const stop = () => {
    const v = ref.current;
    if (!v) return;
    v.pause();
    v.currentTime = 0;
  };
  return (
    <div
      className={`v3-vid${s.video ? " has" : " empty"}${fs === "stale" ? " stale" : ""}`}
      onMouseEnter={s.video ? play : undefined}
      onMouseLeave={s.video ? stop : undefined}
      onClick={(e) => {
        e.stopPropagation();
        st.select(s.id);
        if (s.video) setBig(true);
      }}
      title={s.video ? "悬停预览，点击放大播放" : blk ? `还没有视频：${blk}` : "还没有视频"}
    >
      {s.video ? (
        <>
          <video ref={ref} src={s.video} muted loop playsInline preload="metadata" />
          <i className="v3-play" />
        </>
      ) : (
        <span className="v3-frame-none">
          视频未出
          {blk && blk !== "还没有首帧" && <small>{blk}</small>}
        </span>
      )}
      <b className="v3-tag">视频 · {s.duration.seconds}s</b>
      <StateTag state={fs} why={staleOf(s, d, "video").filter(Boolean).join("；")} />
      {live && (
        <div className="v3-frame-job">
          <JobBar live={live} compact />
        </div>
      )}
      {big && s.video && <VideoBox src={s.video} title={`${short(s.id)} 视频`} onClose={() => setBig(false)} />}
    </div>
  );
}

/** 本镜场景（v3.1 追加）：id 取 state_timeline 的 scene_id（SOP 接口带出），名称优先 scene_library（S-back 加好后摘要里有就用），其次 data/scenes.json 的场景名，
 *  再次剧本的地点（visual_spec.scene.place），最后 scene_id；底图缩略图取 /api/shots/{id}/refs 的当前生效底图（按镜缓存） */
const plateCache = new Map<string, Promise<string | null>>();
function plateUrl(shot: string): Promise<string | null> {
  let p = plateCache.get(shot);
  if (!p) {
    p = apiV1.shotRefs(shot).then(
      (r) => {
        const e = r.scene?.effective;
        return e && typeof e === "object" ? e.url ?? null : null;
      },
      () => null,
    );
    plateCache.set(shot, p);
  }
  return p;
}
/** data/scenes.json（state_timeline 的场景分组）scene_id → 名称：经项目文件接口读一次，整页共用 */
let sceneNames: Promise<Map<string, string>> | null = null;
function loadSceneNames(): Promise<Map<string, string>> {
  if (!sceneNames)
    sceneNames = fetch("/api/projects")
      .then((r) => (r.ok ? r.json() : []))
      .then((ps: { slug: string; is_default?: boolean }[]) => {
        const slug = (ps.find((p) => p.is_default) ?? ps[0])?.slug;
        if (!slug) return null;
        return fetch(`/api/projects/${encodeURIComponent(slug)}/file/data/scenes.json`).then((r) => (r.ok ? r.json() : null));
      })
      .then((d: { scenes?: { scene_id: string; place?: string; name?: string }[] } | null) => new Map((d?.scenes ?? []).map((x) => [x.scene_id, x.name || x.place || x.scene_id] as [string, string])))
      .catch(() => new Map<string, string>());
  return sceneNames;
}

function useShotScene(s: ShotSummary, d: { visual_spec?: Record<string, unknown> | null } | undefined, sop?: SopShot) {
  const [plate, setPlate] = useState<string | null>(null);
  const [names, setNames] = useState<Map<string, string> | null>(null);
  useEffect(() => {
    let alive = true;
    void plateUrl(s.id).then((u) => alive && setPlate(u));
    void loadSceneNames().then((m) => alive && setNames(m));
    return () => {
      alive = false;
    };
  }, [s.id]);
  const vs = (d?.visual_spec?.scene ?? null) as Record<string, unknown> | string | null;
  const x = s as { scene_name?: string | null; scene?: { name?: string } | null };
  const lib = x.scene_name ?? x.scene?.name;
  const id = (sop as { scene_id?: string | null } | undefined)?.scene_id ?? (vs && typeof vs === "object" && typeof vs.id === "string" ? vs.id : null);
  const place = vs && typeof vs === "object" && typeof vs.place === "string" ? vs.place : typeof vs === "string" ? vs : null;
  const time = vs && typeof vs === "object" && typeof vs.time_of_day === "string" ? vs.time_of_day : null;
  return { id, name: lib || (id ? names?.get(id) : null) || place || id || null, time, plate };
}

function ReviewRowInner({ s, sop, selected, inMulti, dim }: { s: ShotSummary; sop?: SopShot; selected: boolean; inMulti: boolean; dim: boolean }) {
  const st = useStudio();
  const ui = useUi();
  useEdit(); // F2：v1 任务进度（状态点 / 一句话）随任务轮询刷新
  const [open, setOpen] = useState<null | "first" | "h3">(null);
  const [full, setFull] = useState(false);
  const status = shotStatus(s, st, sop);
  const d = st.details[s.id];
  const meta = shotMeta(s); // 场景名只在人物行的场景小卡里出现一次
  const line = shotLine(s);
  const dlg = s.dialogue.length ? s.dialogue : [];
  const hl = st.hlChar && s.characters.some((c) => c.character === st.hlChar);
  const h3 = s.h3_prompt || s.video_prompt;
  const vblk = videoBlock(s, d);
  const sc = useShotScene(s, d, sop);
  // U4：分镜详情——本行自己的开关优先；“展开全部”切换时清掉各行自己的选择
  const sbui = useSbUi();
  const [sbOwn, setSbOwn] = useState<boolean | null>(null);
  useEffect(() => setSbOwn(null), [sbui.rev]);
  const sbOpen = sbOwn ?? sbui.expandAll;
  const miss = missingOf(s, storyboardOf(s, d));
  return (
    <article
      className={`v3-row${selected ? " sel" : ""}${inMulti ? " multi" : ""}${dim ? " dim" : ""}${hl ? " hl" : ""}${s.video ? " has-vid" : ""}`}
      data-shot={s.id}
      onClick={(e) => st.select(s.id, { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey })}
      onDoubleClick={() => (st.select(s.id), st.setCanvasMode("edit"))}
    >
      <div className="v3-frames">
        <Frame s={s} stage="image" st={st} />
        <Frame s={s} stage="last" st={st} />
        <VideoTile s={s} st={st} />
      </div>
      <div className="v3-info">
        <div className="v3-l1">
          <b className="v3-sid">{short(s.id)}</b>
          <MissBadge miss={miss} />
          <span className="v3-meta">{meta.join(" · ")}</span>
          <span className="v3-grow" />
          <StatusLine st={status} />
        </div>
        <div className="v3-field">
          <span className="v3-k">剧本</span>
          <p className={`v3-script${full ? " full" : ""}`} title={full ? "收起" : s.script_text} onClick={(e) => (e.stopPropagation(), setFull((v) => !v))}>
            {s.script_text || s.img_summary || "—"}
          </p>
        </div>
        <div className="v3-field">
          <span className="v3-k">表情</span>
          <p className="v3-one" title={s.expression.text}>
            {s.expression.text || "—"}
          </p>
        </div>
        <div className="v3-field">
          <span className="v3-k">{dlg.length ? "对白" : s.voiceover ? "独白" : "对白"}</span>
          <p className="v3-two" title={dlg.map((x) => `${x.speaker_note ?? ""}：${x.text}`).join("\n") || line.text}>
            {dlg.length ? (
              dlg.slice(0, 2).map((x, i) => (
                <span key={i} className="v3-dl">
                  {x.speaker_note && <em>{x.speaker_note}：</em>}
                  {x.text}
                </span>
              ))
            ) : s.voiceover ? (
              <span className="v3-dl">
                <em>独白：</em>
                {s.voiceover.text}
              </span>
            ) : (
              "—"
            )}
          </p>
        </div>
        <div className="v3-people">
          {s.characters.map((c) => (
            <button
              key={c.character}
              className={`v3-look${c.has_override ? " ovr" : ""}`}
              title={`${c.label}${c.has_override ? "（本镜改过）" : ""}\n点击：切换本镜参考（服装 / 鞋 / 妆 / 甲 / 发）`}
              onClick={(e) => (e.stopPropagation(), st.select(s.id), ui.openRefSwitch(s.id, { kind: "character", id: c.character }))}
              onDoubleClick={(e) => e.stopPropagation()}
            >
              <span className="v3-look-img">{c.face_url ? <img src={c.face_url} alt="" loading="lazy" /> : c.name.slice(0, 1)}</span>
              <span className="v3-look-name">{c.name}</span>
              <i>{letterOf(c)}</i>
            </button>
          ))}
          <button
            className={`v3-look scene${sc.plate ? " has" : ""}`}
            title={`场景：${sc.name ?? "未标"}${sc.time ? ` · ${sc.time}` : ""}${sc.id ? `（${sc.id}）` : ""}\n${sc.plate ? "底图已挂" : "无底图"}；点击：切换本镜场景参考（底图）`}
            onClick={(e) => (e.stopPropagation(), st.select(s.id), ui.openRefSwitch(s.id, { kind: "scene" }))}
            onDoubleClick={(e) => e.stopPropagation()}
          >
            {sc.plate ? <img className="v3-look-plate" src={sc.plate} alt="" loading="lazy" /> : <span className="v3-look-plate none">景</span>}
            <span className="v3-look-name">{sc.name ?? "场景未标"}</span>
          </button>
          <span className="v3-grow" />
          <div className="v3-ptog">
            <button
              className={`sb-toggle${sbOpen ? " on" : ""}`}
              onClick={(e) => (e.stopPropagation(), setSbOwn(!sbOpen))}
              title="本镜全部分镜字段（剧本原文，只读）：场景、画面、动作、结束状态、表情、对白、独白、环境声、配乐提示、时长、H3 四块"
            >
              分镜详情 {sbOpen ? "▾" : "▸"}
            </button>
            <button className={open === "first" ? "on" : ""} onClick={(e) => (e.stopPropagation(), setOpen(open === "first" ? null : "first"))} title="首帧提示词（原样，只读）">
              首帧 {open === "first" ? "▾" : "▸"}
            </button>
            <button className={open === "h3" ? "on" : ""} onClick={(e) => (e.stopPropagation(), setOpen(open === "h3" ? null : "h3"))} title={`H3 视频提示词（${s.h3_prompt_source_label ?? "剧本"}，原样，只读）`}>
              H3 {open === "h3" ? "▾" : "▸"}
            </button>
          </div>
        </div>
        {open && (
          <pre className="v3-prompt" onClick={(e) => e.stopPropagation()}>
            {(open === "first" ? s.image_prompt : h3) || "（空）"}
          </pre>
        )}
      </div>
      <div className="v3-act" onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
        {status.action && (
          <button className="v3-btn primary" onClick={status.action.run} title={status.action.title}>
            {status.action.label}
          </button>
        )}
        <Pop label="⋯" btnClass="v3-btn icon" align="right" title="更多操作">
          {(close) => (
            <div className="v3-menu" onClick={close}>
              <button onClick={() => (st.select(s.id), st.setCanvasMode("edit"))}>进精修</button>
              <button disabled={!s.first_frame} onClick={() => st.openViewer(s.id, "image", "pair")}>全屏看首尾帧</button>
              <i />
              <button onClick={() => st.requestRender(s.id, "image")}>出首帧</button>
              <button disabled={!s.first_frame} onClick={() => st.requestRender(s.id, "last")}>出尾帧</button>
              <button disabled={!!vblk} title={vblk ?? ""} onClick={() => st.requestRender(s.id, "video")}>
                出视频{vblk ? `（${vblk}）` : ""}
              </button>
              <i />
              <button onClick={() => void st.setReview([s.id], "passed")}>通过</button>
              <button onClick={() => st.setRejectFor([s.id])}>打回</button>
            </div>
          )}
        </Pop>
      </div>
      {sbOpen && (
        <div className="sb-wrap" onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
          <StoryboardGrid s={s} d={d} />
        </div>
      )}
    </article>
  );
}

export const ReviewRow = memo(ReviewRowInner);

/** 是否被过滤变暗 */
export const rowDim = (st: Studio, s: ShotSummary) => !matchFilter(st.filter, s, st.latest.get(s.id));
