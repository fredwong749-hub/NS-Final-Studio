// fredw-92/W4a + v3.1 U1：审片模式的一行——首帧 | 尾帧 | 视频 三格同尺寸 9:16（视频可悬停播放 / 点击放大，有视频时强调）
// ｜文字列固定行数（剧本 2 · 表情 1 · 对白 2 · 人物小卡与提示词开关同一行）｜主按钮 = 下一步 + ⋯。状态胶囊点开 = 为什么卡住。
import { Lightbox } from "../ds/MediaPlayer";
import { thumb } from "../thumb";
import { FilmStrip } from "./pages/FilmOverview";
import { filmOn } from "./uiStyle";
import { storyFrame, useStoryImages } from "./storyImages";
import { candidateFor, candLabel, epOf, passed, pickTake, rejectedFor, useCandidates } from "./candidates";
import { HistoryBox } from "./HistoryBox";
import { CandidateBox } from "./CandidateBox";
import { Verdict, type VStage } from "./Verdict";
import { memo, useEffect, useRef, useState, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import { JobBar } from "../components/frames";
import { useStudio, type Studio } from "../store";
import type { ShotSummary, SopShot } from "../types";
import { expectedLast, shotLine } from "../util";
import { letterOf } from "./LeftRail.helpers";
import { badOf, camRaw, frameState, shotMeta, shotStatus, staleOf, videoBlock, breatheDelay, useLens } from "./status";
import { useUi } from "./ui.helpers";
import { useEdit } from "./edit/state";
import { Pop, StatusLine } from "./widgets";
import { apiV1 } from "./api_v1";
import { PlayShotLines } from "./sound/ShotLines";
import { sceneLabel } from "./sceneLabel";
import { useFlash } from "./live";
import "../ds/live.css";
import { MissBadge, StoryboardGrid } from "./StoryboardDetails";
import { missingOf, sbUi, srcLabel, storyboardOf, useSbUi } from "./StoryboardDetails.helpers";
import { AUTO_SHORT, AUTO_TIP, STALE_SHORT } from "./words";
import { MotionQcBadge } from "./MotionQc";
import { setLock } from "./edit/actions";
import { MaterialsBadge } from "./Materials";
import { TileActionButtons } from "../ds/editdel";
import { relFromUrl } from "../ds/editdel.api";
import { TileBar, TileTop } from "../ds/TileBar";

import { passBlock } from "./ReviewRow.helpers";
import { useOwnerQueue } from "./ownerQueue"; // UIRSI2 L-116
import { FbDot } from "./FeedbackLayer"; // UIRSI2 反馈模式：帧角标
import { RegenButton } from "./RegenButton";
import "./rowcalm.css"; // UIFIX-S 第 2 轮：行内状态收静
import { TAG_WORD, tagsTitle } from "./StatusTags.helpers";
import type { ShotStatusTags } from "./StatusTags.helpers";
const short = (id: string) => id.split("-")[1];
/** UIFIX-S：同一镜行上只显示一条状态（StatusLine）；原来并排的“看图没过 +1”这类彩色胶囊收进它的悬停提示 */
const mainTip = (st: ShotStatusTags | null | undefined) => (st?.main ? `${TAG_WORD[st.main]}${st.tags.length > 1 ? `（共 ${new Set(st.tags.map((t) => t.kind)).size} 项）` : ""}${nl0}${tagsTitle(st)}` : undefined);
const nl0 = String.fromCharCode(10);

/** 一格右上角的状态牌：过期优先于定稿（v3.1 §5.1），两者不同时出现 */
/** UIPIXEL：状态牌放进格子底栏（ds/TileBar），单行省略号 + title 看全文（以前按“·”分段换行，窄格里换成两行后压到“渲染中 / ✎ 改”） */

/** StateTag 有内容的状态（none / draft 不出牌） */
const hasTag = (fs: ReturnType<typeof frameState>) => fs !== "none" && fs !== "draft";

function StateTag({ state, why }: { state: ReturnType<typeof frameState>; why: string }) {
  // fredw-92/UXF1：坏图（太小 / 尺寸不符）红色；链不完整（没有首帧的尾帧 / 视频）灰掉写“作废”
  if (state === "bad") return <span className="v3-ftag bad" title={why ? `坏图：${why}` : "坏图"}>坏图</span>;
  if (state === "orphan") return <span className="v3-ftag orphan" title="无首帧·作废：这一格不是由定稿首帧来的，已作废，不计入完成数"><span className="ft-full">无首帧·作废</span><span className="ft-short">作废</span></span>;
  if (state === "stale") return <span className="v3-ftag stale" title={why ? `${STALE_SHORT}：${why}` : STALE_SHORT}><span className="ft-full">{STALE_SHORT}</span><span className="ft-short">过期</span></span>;
  if (state === "locked") return <span className="v3-ftag locked" title="已定稿">已定稿</span>;
  // fredw-92/UXF4（审查 N1）：整集出片自动测试定稿——虚线标，不算已定稿 / 已通过
  if (state === "auto") return <span className="v3-ftag auto" title={AUTO_TIP}>{AUTO_SHORT}</span>;
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
  // UIRSI（BE-5）：流水线图已登记成版本但还没设为当前 → 显示最新候选“候选 #n · 暂定 · 旧配方”，一键“用这张”
  const cands = useCandidates(epOf(s.id));
  const cstage = cands?.[s.id]?.[stage];
  // UIRSI r37（UIAUDIT P1-2，K-UI-D01）：候选还没读回来时说“读取中”，不能说“未出”（把“还在读”说成“没有”）
  // UIRSI r40（项目方 11-02 00:0x：“我…看到很多错误的图”）：剧本 23:21 逐集重导、镜头重新编号后，旧剧本出的图还挂在新镜号下
  // （有的甚至还是“当前”尾帧）。/api/candidates 给每版标 script（current / old）：当前版本是旧剧本出的 → 不显示、按“未出（剧本已更新）”处理；
  // 旧版本不作候选、不计数，只在“旧图”历史入口里能看
  const oldCur = (cstage?.active != null && cstage.takes.find((t) => t.n === cstage.active)?.script === "old") || cstage?.active_quarantined != null; // r41：已隔离的当前版本也不显示
  if (oldCur && !hint) url = null;
  const oldN = cstage?.takes.filter((t) => t.script === "old").length ?? 0;
  const candLoading = cands === null && !url;
  const cand = !url || hint ? (oldCur ? ([...cstage!.takes].reverse().find(passed) ?? null) : candidateFor(cands, s.id, stage)) : null;
  if (cand) {
    url = cand.url;
    hint = "";
  }
  // 还没登记成 take 的新图（IMGGEN 出图目录）兜底显示，标“草图·还没进版本”（有候选版本时不再出现）
  const fresh = storyFrame(useStoryImages(3000), s.id, stage);
  if (!url && fresh && !cstage?.takes.length) {
    url = fresh.url;
    hint = "草图·还没进版本";
  }
  const [box, setBox] = useState(false);
  const rejected = !url ? (oldCur ? cstage!.takes.filter((t) => !passed(t)) : rejectedFor(cands, s.id, stage)) : [];
  const take = cand ? cand.n : oldCur ? null : first ? s.first_frame_take : s.last_frame_take;
  const label = first ? "首帧" : "尾帧";
  const fs = frameState(s, d, stage);
  // UIAUDIT P0-1：列表、大图、剧本阅读页看同一张——还没登记成版本的草图点开就是这张草图（不去版本看图器里显示“0 版”）
  const draft = !!fresh && url === fresh.url;
  const [big, setBig] = useState<string | null>(null);
  const open = (e: MouseEvent) => {
    e.stopPropagation();
    st.select(s.id);
    if (cand && cstage) setBox(true);
    else if (draft) setBig(url);
    else if (url) st.openViewer(s.id, stage, "pair");
  };
  // PAGEWATCH PW-017：只闪这一格（这一格的图 / 版本真变了），不闪整行
  const tileFlash = useFlash([url, take]);
  return (
    <>
    {big && <Lightbox src={big} onClose={() => setBig(null)} />}
    {box && cstage && <CandidateBox shot={s.id} stage={stage} data={cstage} start={cand?.n ?? rejected[rejected.length - 1]?.n} stale={s.stale_global?.[stage]} onClose={() => setBox(false)} />}
    <div className={`v3-frame${url ? "" : " empty"}${cand ? " cand" : ""}${fs === "stale" ? " stale" : ""}${fs === "bad" ? " bad" : ""}${fs === "orphan" ? " orphan" : ""}${tileFlash ? " live-flash" : ""}`} onClick={open} data-zoom-own title={url ? (cand ? `${label}候选：点开看全部候选、对比（悬停右上角放大镜看原图）` : `${label}：点开全屏对比（首帧 | 尾帧）`) : candLoading ? `正在读取${label}候选` : `还没有${label}`}>
      <FbDot sid={s.id} kind={stage === "image" ? "first" : "last"} />
      {url ? <img key={url} className="live-img" src={thumb(url, 360) ?? url} alt={label} loading="lazy" decoding="async" draggable={false} data-zoom-label={`${short(s.id)} · ${label}${take != null ? ` #${take}` : ""}${cand ? " · 候选" : ""}`} /> : <span className="v3-frame-none">{candLoading ? "读取中…" : oldN ? `${label}未出（剧本已更新）` : `${label}未出`}</span>}
      <TileTop>
        {/* UIRSI r36：78px 窄格里“首帧候选”四个字会把右上角的 ↻ 挤到标签上 → 标签只写“首帧 #n”，“候选”写进底下的候选条（和“用这张”在一起） */}
        <b className="v3-tag" title={cand ? `${label}候选 #${take}：还没设为当前，点“用这张”才用它` : undefined}>
          <span>{label}</span>
          {take != null ? <span className="v3-tag-n">#{take}</span> : null}
        </b>
        {/* 项目方 11-01：“添加一个生成按钮,基于现在再生成一个新的图” → ↻ 再生成（可写要求、传装备图；新图进版本链）。
            放顶栏、不放底栏：底栏窄格会把操作收进 ⋯，这个按钮要一直看得见 */}
        {take != null && !draft && !live && (
          <RegenButton
            shot={s.id}
            stage={stage}
            n={take}
            label={label}
            compact
            chars={s.characters.map((c) => ({ id: c.character, name: c.name }))}
            onDone={(m, k) => {
              st.notify(m, k ?? "ok");
              void st.refreshAfter([s.id]);
            }}
          />
        )}
      </TileTop>
      {cand && !live && (
        <div className="v3-cand-bar" onClick={(e) => e.stopPropagation()}>
          {/* 只在有标签（暂定 / 新配方…）时占一行：没标签时不多占一行，免得把 78px 窄格里的图再压矮 */}
          {candLabel(cand) && <span className="v3-cand-lbl" title={`候选 #${cand.n}：${candLabel(cand)}；点图看全部候选、对比`}>候选 · {candLabel(cand)}</span>}
          <button
            type="button"
            className="v3-cand-use"
            onClick={() => void pickTake(s.id, stage, cand.n, cstage!.active, () => void st.refreshAfter([s.id]), st.notify)}
            title="设为这一镜当前用的图（10 秒内可撤销）"
          >
            用这张
          </button>
        </div>
      )}
      {/* UIPIXEL：底边的旧图入口 / 状态牌 / 提示 / 任务条 / ✎ 改 🗑 统一放进一条 TileBar（flex + gap，不再各自 absolute 叠在一起） */}
      <TileBar
        job={live ? <JobBar live={live} compact /> : null}
        status={
          (!url && rejected.length > 0 && cstage) || hasTag(fs) || hint ? (
            <>
              {!url && rejected.length > 0 && cstage && (
                <button type="button" className="v3-cand-old" onClick={(e) => (e.stopPropagation(), setBox(true))} title={`${rejected[0].why_not ?? "不合格"}：点开看（不作候选）`}>
                  旧图 ×{rejected.length}
                </button>
              )}
              <StateTag state={fs} why={fs === "bad" ? badOf(s, d, stage) ?? "" : staleOf(s, d, stage).filter(Boolean).join("；")} />
              {hint && <span className="v3-frame-hint" title={hint}>{hint}</span>}
            </>
          ) : null
        }
        actions={
          /* EDITDEL：修改（指出问题 → 系统修，结果进版本链）/ 删除这一版（回收站，可撤销） */
          url && !hint.startsWith("参考") && (take != null || relFromUrl(url)) ? (
            <TileActionButtons
              edit={take != null ? { type: "image", id: `take:${s.id}/${stage}/${take}`, src: url, label: `${s.id} ${label} #${take}` } : relFromUrl(url) ? { type: "image", id: `file:${relFromUrl(url)}#${s.id}`, src: url, label: `${s.id} ${label}（未登记）` } : null}
              del={take != null ? { type: "take", id: `${s.id}/${stage}/${take}` } : null}
              onChanged={() => void st.refreshAfter([s.id])}
            />
          ) : null
        }
      />
    </div>
    </>
  );
}

/** 放大播放（循环、带控件）；点背景或 Esc 关闭 */
function VideoBox({ src, title, onClose }: { src: string; title: string; onClose: () => void }) {
  const st = useStudio();
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
        {/* UXF1 #13：完整播完一遍记“已看完”，行主按钮随即变成“通过”（不循环，否则 ended 不触发） */}
        <video src={src} controls autoPlay playsInline onEnded={() => st.markWatched(src)} />
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
  // UIRSI r37（UIAUDIT P2）：精修页会播最新一版，画布却写“视频未出”——有版本没设当前时两边都说“有 N 版，还没设为当前”
  // r40：只数现行剧本出的视频版本（旧剧本的视频不算“待选”）
  const vc = useCandidates(epOf(s.id))?.[s.id]?.video;
  const vNew = vc ? vc.takes.filter((t) => t.script !== "old").length : (s.takes_count?.video ?? 0);
  const vOld = vc ? vc.takes.length - vNew : 0;
  const vPending = !s.video && vNew > 0;
  const vtake = d?.takes?.active?.video ?? s.latest_take?.video ?? null;
  const vidFlash = useFlash([s.video, vtake]); // PW-017：只闪视频格
  const play = () => void ref.current?.play().catch(() => undefined);
  const stop = () => {
    const v = ref.current;
    if (!v) return;
    v.pause();
    v.currentTime = 0;
  };
  return (
    <div
      className={`v3-vid${s.video ? " has" : " empty"}${fs === "stale" ? " stale" : ""}${fs === "orphan" ? " orphan" : ""}${vidFlash ? " live-flash" : ""}`}
      onMouseEnter={s.video ? play : undefined}
      onMouseLeave={s.video ? stop : undefined}
      onClick={(e) => {
        e.stopPropagation();
        st.select(s.id);
        if (s.video) setBig(true);
        else if (vPending) st.setCanvasMode("edit");
      }}
      title={s.video ? "悬停预览，点击放大播放" : vPending ? `有 ${vNew} 版视频，还没设为当前：点进精修挑一版` : vOld ? `有 ${vOld} 版是剧本更新前出的旧视频，不作候选` : blk ? `还没有视频：${blk}` : "还没有视频"}
    >
      <FbDot sid={s.id} kind="video" />
      {s.video ? (
        <>
          <video ref={ref} src={s.video} poster={s.first_frame ?? undefined} muted loop playsInline preload="metadata" />
          <i className="v3-play" />
        </>
      ) : (
        <span className="v3-frame-none">
          {vPending ? `视频 ${vNew} 版待选` : vOld ? "视频未出（剧本已更新）" : "视频未出"}
          {!vPending && blk && blk !== "还没有首帧" && <small>{blk}</small>}
        </span>
      )}
      <TileTop>
        <b className="v3-tag">视频 · {s.duration.seconds}s</b>
        {s.video && <MotionQcBadge q={s.video_qc} className="v3-mqc" />}
      </TileTop>
      <TileBar
        job={live ? <JobBar live={live} compact /> : null}
        status={hasTag(fs) ? <StateTag state={fs} why={staleOf(s, d, "video").filter(Boolean).join("；")} /> : null}
        actions={
          s.video && vtake != null ? (
            <TileActionButtons
              edit={{ type: "video", id: `take:${s.id}/video/${vtake}`, src: s.video, label: `${s.id} 视频 #${vtake}` }}
              del={{ type: "take", id: `${s.id}/video/${vtake}` }}
              onChanged={() => void st.refreshAfter([s.id])}
            />
          ) : null
        }
      />
      {big && s.video && <VideoBox src={s.video} title={`${short(s.id)} 视频`} onClose={() => setBig(false)} />}
    </div>
  );
}

/** 本镜场景（v3.1 追加）：id 取 state_timeline 的 scene_id（SOP 接口带出），名称优先 scene_library（S-back 加好后摘要里有就用），其次 data/scenes.json 的场景名，
 *  再次剧本的地点（visual_spec.scene.place），最后 scene_id；底图缩略图取 /api/shots/{id}/refs 的当前生效底图（按镜缓存） */
const plateCache = new Map<string, Promise<string | null | false>>();
let plateN = 0;
/** → 底图地址 / null（后端说没有）/ false（请求失败，K-UI-D01：不能说成“无底图”；失败不缓存，下次再取） */
function plateUrl(shot: string): Promise<string | null | false> {
  let p = plateCache.get(shot);
  if (!p) {
    // UIRSI r12（W-02）：场景底图缩略图不抢首屏——1.5 s 后再错开取（以前 11 镜同时发，排队 4–7 s）
    const delay = 3000 + (plateN++ % 24) * 150;
    p = new Promise((r) => setTimeout(r, delay)).then(() => apiV1.shotRefs(shot)).then(
      (r) => {
        const e = r.scene?.effective;
        return e && typeof e === "object" ? e.url ?? null : null;
      },
      () => {
        plateCache.delete(shot);
        return false as const;
      },
    );
    plateCache.set(shot, p);
  }
  return p;
}
/** data/scenes.json（state_timeline 的场景分组）scene_id → 名称：经项目文件接口读一次，整页共用 */
let sceneNames: Promise<Map<string, string>> | null = null;
function loadSceneNames(): Promise<Map<string, string>> {
  if (!sceneNames)
    sceneNames = new Promise((r) => setTimeout(r, 3000)) // UIRSI r12：场景名不抢首屏
      .then(() => fetch("/api/projects"))
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
  // undefined = 还在读；null = 后端说没有；false = 读不到
  const [plate, setPlate] = useState<string | null | false | undefined>(undefined);
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
  return { id, name: sceneLabel(lib || (id ? names?.get(id) : null) || place || id || null), time, plate };
}

function ReviewRowInner({ s, sop, selected, inMulti, dim }: { s: ShotSummary; sop?: SopShot; selected: boolean; inMulti: boolean; dim: boolean }) {
  const st = useStudio();
  const ui = useUi();
  useEdit(); // F2：v1 任务进度（状态点 / 一句话）随任务轮询刷新
  useOwnerQueue(); // UIRSI2 L-116：“机签通过 vN”随待你看队列刷新
  const [open, setOpen] = useState<null | "first" | "h3">(null);
  const [full, setFull] = useState(false);
  const status0 = shotStatus(s, st, sop);
  const rowCands = useCandidates(epOf(s.id));
  // UIRSI（BE-5）：没有当前首帧、但有登记好的候选 → 不说“还没有首帧”，主按钮 = 一键用最新候选（10 秒撤销）
  const cands = useCandidates(epOf(s.id));
  const cfirst = !s.first_frame ? candidateFor(cands, s.id, "image") : null;
  const status = cfirst && status0.key === "no_first"
    ? {
        ...status0,
        dot: "yellow" as const,
        text: `有 ${cands?.[s.id]?.image?.takes.length ?? 1} 张候选首帧，挑一张用`,
        action: { label: `用候选 #${cfirst.n}`, title: `把候选 #${cfirst.n}${candLabel(cfirst) ? `（${candLabel(cfirst)}）` : ""} 设为首帧，10 秒内可撤销；点首帧图可对比全部候选`, run: () => void pickTake(s.id, "image", cfirst.n, null, () => void st.refreshAfter([s.id]), st.notify) },
      }
    : status0;
  const d = st.details[s.id];
  // UM-P0-01：现在待你看的是哪一格的哪一版
  const contractOk = (stage: "image" | "last", n: number | null) => n != null && cands?.[s.id]?.[stage]?.takes.find((x) => x.n === n)?.contract === "pass";
  const vtakeN = d?.takes?.active?.video ?? s.latest_take?.video ?? null;
  // UIRSI2 L-116：机签通过的镜也保留“用这张 / 不要”（不删功能），但收成灰色小按钮、不提示（quiet）
  const pend: { stage: VStage; n: number; auto?: boolean; quiet?: boolean; accept?: () => Promise<unknown> } | null = status.key === "machine_first" && s.first_frame_take != null
    ? { stage: "first", n: s.first_frame_take, quiet: true }
    : status.key === "machine_last" && s.last_frame_take != null
      ? { stage: "last", n: s.last_frame_take, quiet: true }
      : cfirst && status0.key === "no_first"
    ? { stage: "first", n: cfirst.n, accept: () => pickTake(s.id, "image", cfirst.n, null, () => void st.refreshAfter([s.id]), st.notify) }
    : (status.key === "review_first" || status.key === "auto_first") && s.first_frame_take != null
      ? { stage: "first", n: s.first_frame_take, auto: contractOk("image", s.first_frame_take) }
      : (status.key === "review_last" || status.key === "auto_last") && s.last_frame_take != null
        ? { stage: "last", n: s.last_frame_take, auto: contractOk("last", s.last_frame_take) }
        : (status.key === "review_video" || status.key === "review_video_watched") && vtakeN != null
          ? { stage: "video", n: vtakeN }
          : null;
  // 实时：这一镜的首帧 / 尾帧 / 视频 / 审核 / 状态真的变了，整行柔和地闪一下
  // PW-017：整行不闪；状态胶囊自己闪（文字真变了才闪）
  const statusFlash = useFlash([s.review?.state, status.text]);
  const meta = shotMeta(s); // 场景名只在人物行的场景小卡里出现一次
  const lens = useLens(s.id); // r45 · L-113：每镜一行加“镜头”字段
  const film = filmOn();
  const filmH = Math.round(Math.max(427, Math.min(569, window.innerWidth * 0.296))); // 1440 宽每格 ≥ 240 px、1920 宽 ≥ 320 px（9:16）
  const procTakes = film ? [...(rowCands?.[s.id]?.image?.takes ?? []), ...(rowCands?.[s.id]?.last?.takes ?? [])].slice(-8).reverse() : [];
  const line = shotLine(s);
  const dlg = s.dialogue.length ? s.dialogue : [];
  const hl = st.hlChar && s.characters.some((c) => c.character === st.hlChar);
  const h3 = s.h3_prompt || s.video_prompt;
  const vblk = videoBlock(s, d);
  const pblk = passBlock(s, d);
  const sc = useShotScene(s, d, sop);
  // U4：分镜详情——本行自己的开关优先；“展开全部”切换时清掉各行自己的选择
  const sbui = useSbUi();
  const [sbOwn, setSbOwn] = useState<boolean | null>(null);
  useEffect(() => setSbOwn(null), [sbui.rev]);
  const sbOpen = sbOwn ?? sbui.expandAll;
  // UIRSI r41（项目方 00:5x：“数据有点太多了”）：一行默认只留首帧 / 尾帧 / 视频、剧本 / 表情 / 对白和一行状态；
  // 声音、人物造型与场景参考、分镜详情 / 首帧提示词 / 视频提示词收进“详情 ▸”（“展开全部分镜详情”时一起展开）
  const [moreOwn, setMoreOwn] = useState<boolean | null>(null);
  const [hist, setHist] = useState(false);
  const more = moreOwn ?? (sbOpen || !!open);
  const miss = missingOf(s, storyboardOf(s, d));
  return (
    <article
      className={`v3-row${film ? " film-row" : ""}${more ? "" : " lean"}${selected ? " sel" : ""}${inMulti ? " multi" : ""}${dim ? " dim" : ""}${hl ? " hl" : ""}${s.video ? " has-vid" : ""}`}
      data-shot={s.id}
      style={breatheDelay(s.id)}
      onClick={(e) => st.select(s.id, { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey })}
      onDoubleClick={() => (st.select(s.id), st.setCanvasMode("edit"))}
    >
      {film ? (
        // r46 · L-114（总调度亲审：首尾帧必须大图；片上只放这一镜的当前首帧 / 尾帧 / 视频，候选和过程小图放右侧）
        <div className="film-cut">
          <FilmStrip
            H={filmH}
            thumbW={480}
            kk={`EASTMAN 2383  ${short(s.id)}`}
            frames={[
              { key: "f", src: s.first_frame, ed: s.first_frame ? `首帧 · 定稿 #${s.first_frame_take ?? "?"}` : "首帧 · 未出", empty: "首帧未出", cap: `${short(s.id)} · 首帧` },
              { key: "l", src: s.last_frame_target, ed: s.last_frame_target ? `尾帧 · 定稿 #${s.last_frame_take ?? "?"}` : "尾帧 · 未出", empty: "尾帧未出", cap: `${short(s.id)} · 尾帧` },
              s.video ? { key: "v", src: s.video, kind: "video", ed: `视频 · 当前`, cap: `${short(s.id)} · 视频` } : { key: "v", src: null, ed: "视频 · 未出", empty: "视频未出" },
            ]}
            onFrame={(i) => (st.select(s.id), i === 2 && s.video ? st.setCanvasMode("edit") : undefined)}
          />
        </div>
      ) : (
        <div className="v3-frames">
          <Frame s={s} stage="image" st={st} />
          <Frame s={s} stage="last" st={st} />
          <VideoTile s={s} st={st} />
        </div>
      )}
      <div className="v3-info">
        <div className="v3-l1">
          <b className="v3-sid">{short(s.id)}</b>
          {/* UIRSI r40：和全剧总览同一套彩色状态标签（最严重的一个；悬停看全部） */}
          <MissBadge miss={miss} onJump={() => (st.select(s.id), sbUi.openTableAt(s.id))} />
          <MaterialsBadge shotId={s.id} />
          <span className="v3-meta" title={camRaw(s) ? `剧本原文：${camRaw(s)}` : undefined}>{meta.join(" · ")}</span>
          {lens && <span className="v3-lens" title="镜头（D-LENS：实拍取本版出图提示词；和计划不一致时两个都写）">{lens}</span>}
          {/* r42（总调度定 A：行高不变，只收文字区留白）：“详情 ▸”挪到镜号这一行，不再单占一行；收起时剧本多显示一行 */}
          {!more && (
            <button
              type="button"
              className="v3-more"
              onClick={(e) => (e.stopPropagation(), setMoreOwn(true))}
              title="详情：本镜配乐 / 环境声 · 人物造型（本镜造型角标）与场景参考 · 分镜详情 · 首帧提示词 · 视频提示词"
            >
              详情 ▸
            </button>
          )}
          {!more && s.characters.some((c) => c.has_override) && <small className="v3-look-ovr">本镜造型</small>}
          <span className="v3-grow" />
          <span className={`v3-status-wrap${statusFlash ? " live-flash" : ""}`} title={mainTip(rowCands?.[s.id]?.status)}>
            <StatusLine st={pend?.auto && !pend.quiet ? { ...status, dot: "green", text: `${pend.stage === "first" ? "首帧" : "尾帧"} #${pend.n} 已自动采用（可改）` } : status} />
          </span>
        </div>
        {film && procTakes.length > 0 && (
          <div className="film-proc" onClick={(e) => e.stopPropagation()}>
            <span className="v3-k">候选 · 过程</span>
            <div className="film-proc-row">
              {procTakes.map((t) => (
                <img key={t.url} src={thumb(t.url, 160) ?? t.url} alt="" loading="lazy" title={`#${t.n}${t.ok === false || t.bad ? ` · 没过：${t.why_not ?? t.bad ?? ""}` : " · 通过"}`}
                  className={t.ok === false || t.bad ? "bad" : ""} data-zoom-label={`${short(s.id)} · 第 ${t.n} 版${t.ok === false || t.bad ? ` · 没过：${t.why_not ?? t.bad ?? ""}` : " · 通过"}`} />
              ))}
            </div>
          </div>
        )}
        <div className="v3-field">
          <span className="v3-k">剧本</span>
          <p className={`v3-script${full ? " full" : ""}`} title={full ? "点击收起" : `${s.script_text || s.img_summary || ""}${s.script_text || s.img_summary ? "\n（点击展开全文）" : ""}`} onClick={(e) => (e.stopPropagation(), setFull((v) => !v))}>
            {s.script_text || s.img_summary || "—"}
          </p>
        </div>
        <div className="v3-field">
          <span className="v3-k">表情</span>
          <p className="v3-one" title={s.expression.text}>
            {s.expression.text || "—"}
          </p>
        </div>
        <div className={`v3-field${dlg.length || s.voiceover ? " has-play" : ""}`}>
          <span className="v3-k">{dlg.length ? "对白" : s.voiceover ? "独白" : "对白"}</span>
          <p className="v3-two" title={dlg.map((x) => `${x.speaker_note ?? ""}：${x.text}`).join("\n") || line.text}>
            {dlg.length ? (
              <>
                {dlg.slice(0, 2).map((x, i) => (
                  <span key={i} className="v3-dl">
                    {x.speaker_note && <em>{x.speaker_note}：</em>}
                    {x.text}
                  </span>
                ))}
                {/* UXF5（审查 R10）：对白多于 2 行时写明还有几行（悬停看全部） */}
                {dlg.length > 2 && <span className="v3-dl-more">+{dlg.length - 2} 行</span>}
              </>
            ) : s.voiceover ? (
              <span className="v3-dl">
                <em>独白：</em>
                {s.voiceover.text}
              </span>
            ) : (
              "—"
            )}
          </p>
          {/* UIRSI B4：整镜台词 ▶（点了才读，首屏不多发请求） */}
          {(dlg.length > 0 || s.voiceover) && <PlayShotLines shot={s.id} />}
        </div>
        {/* UX4（项目方：分镜字段缺“配乐提示词”等）：声音一行——环境声 + 配乐提示，剧本原文只读；没写就写“剧本没写”，悬停看全文 */}
        {more && (() => {
          const sb = storyboardOf(s, d);
          const amb = sb ? sb.sound_h3 || sb.sound : "";
          const mus = sb?.music_cue ?? "";
          const tip = sb ? `环境声：${amb || "剧本没写"}
配乐提示：${mus || "剧本没写（用本集配乐）"}` : "分镜字段读取中";
          return (
            <div className="v3-field v3-sound">
              <span className="v3-k">声音</span>
              <p className="v3-one" title={tip}>
                {!sb ? (
                  <span className="v3-muted">读取中…</span>
                ) : (
                  <>
                    <span className="v3-snd-m">
                      <em>配乐</em> {mus || <span className="v3-muted">用本集配乐</span>}
                    </span>
                    <span className="v3-snd-a">
                      <em>环境</em> {amb || <span className="v3-muted">剧本没写</span>}
                    </span>
                  </>
                )}
              </p>
            </div>
          );
        })()}
        {more && <div className="v3-people">
          {s.characters.map((c) => (
            <button
              key={c.character}
              className={`v3-look${c.has_override ? " ovr" : ""}`}
              title={`${c.label}${c.has_override ? "（本镜单独覆盖了造型）" : ""}\n点击：切换本镜参考（服装 / 鞋 / 妆 / 甲 / 发）`}
              onClick={(e) => (e.stopPropagation(), st.select(s.id), ui.openRefSwitch(s.id, { kind: "character", id: c.character }))}
              onDoubleClick={(e) => e.stopPropagation()}
            >
              <span className="v3-look-img" data-zoom-label={`${c.name} · 造型${letterOf(c)} · 身份脸`}>{c.face_url ? <img src={thumb(c.face_url, 120) ?? c.face_url} alt="" loading="lazy" data-zoom-label={`${c.name} · 造型${letterOf(c)} · 身份脸`} /> : c.name.slice(0, 1)}</span>
              <span className="v3-look-name">{c.name}</span>
              <i>{letterOf(c)}</i>
              {/* 回退补回（regress_r1 #12）：本镜单独覆盖了造型，行上直接标出来 */}
              {c.has_override && <small className="v3-look-ovr">本镜造型</small>}
            </button>
          ))}
          <button
            className={`v3-look scene${sc.plate ? " has" : sc.name ? " known" : " unknown"}`}
            data-plate={sc.plate ? "has" : sc.plate === null ? "none" : sc.plate === false ? "err" : "loading"}
            title={`场景：${sc.name ?? "未标"}${sc.time ? ` · ${sc.time}` : ""}${sc.id ? `（${sc.id}）` : ""}\n${sc.plate ? "底图已挂" : sc.plate === null ? "无底图" : sc.plate === false ? "底图暂时读不到" : "底图读取中"}；点击：切换本镜场景参考（底图）`}
            onClick={(e) => (e.stopPropagation(), st.select(s.id), ui.openRefSwitch(s.id, { kind: "scene" }))}
            onDoubleClick={(e) => e.stopPropagation()}
          >
            {sc.plate ? <img className="v3-look-plate" src={thumb(sc.plate, 240) ?? sc.plate} alt="" loading="lazy" data-zoom-label={`场景 · ${sc.name ?? "未标"} · 底图`} /> : <span className="v3-look-plate none">景</span>}
            <span className="v3-look-name">{sc.name ?? "场景未标"}</span>
            {/* UXF5（审查 #17）：三种真实状态——有底图（实线 + 缩略图）/ 认出了场景但没底图（实线 + “无底图”）/ 场景没标（虚线 + 警示色） */}
            {sc.plate === null && sc.name && <small className="v3-look-np">无底图</small>}
            {sc.plate === false && sc.name && <small className="v3-look-np">读不到</small>}
          </button>
          <span className="v3-grow" />
          <div className="v3-ptog">
            <button
              className={`sb-toggle${sbOpen ? " on" : ""}`}
              onClick={(e) => (e.stopPropagation(), setSbOwn(!sbOpen))}
              title="本镜全部分镜字段（剧本原文，只读）：场景、画面、动作、结束状态、表情、对白、独白、环境声、配乐提示、时长、视频提示词"
            >
              分镜详情 {sbOpen ? "▾" : "▸"}
            </button>
            <button className={open === "first" ? "on" : ""} onClick={(e) => (e.stopPropagation(), setOpen(open === "first" ? null : "first"))} title="首帧提示词（原样，只读）">
              首帧提示词 {open === "first" ? "▾" : "▸"}
            </button>
            <button className={open === "h3" ? "on" : ""} onClick={(e) => (e.stopPropagation(), setOpen(open === "h3" ? null : "h3"))} title={`视频提示词（${srcLabel(s.h3_prompt_source_label ?? "剧本")}，原样，只读）`}>
              视频提示词 {open === "h3" ? "▾" : "▸"}
            </button>
            <button type="button" onClick={(e) => (e.stopPropagation(), setMoreOwn(false), setOpen(null), setSbOwn(false))} title="收起详情，只留首帧 / 尾帧 / 视频和一行状态">
              收起 ▴
            </button>
          </div>
        </div>}
        {hist && <HistoryBox shot={s.id} onClose={() => setHist(false)} />}
        {open && (
          <pre className="v3-prompt" onClick={(e) => e.stopPropagation()}>
            {(open === "first" ? s.image_prompt : h3) || "（空）"}
          </pre>
        )}
      </div>
      <div className="v3-act" onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
        {/* UM-P0-01：待审对象一对明确按钮（✓ 用这张 / ✗ 不要）；“定稿并出下一步”收进 ⋯ */}
        {pend ? (
          <span className={pend.quiet ? "v3-quiet" : undefined} title={pend.quiet ? "机签已通过并设为当前，不需要你点；要手动定稿或不要，仍可用这两个按钮" : undefined}>
            <Verdict shot={s.id} stage={pend.stage} n={pend.n} auto={pend.auto} onAccept={pend.accept} />
          </span>
        ) : (
          status.action && (
            <button className="v3-btn primary" onClick={status.action.run} title={status.action.title}>
              {status.action.label}
            </button>
          )
        )}
        <Pop label="⋯" btnClass="v3-btn icon" align="right" title="更多操作">
          {(close) => (
            <div className="v3-menu" onClick={close}>
              <button onClick={() => (st.select(s.id), st.setCanvasMode("edit"))}>进精修（对比版本 / 改图）</button>
              <button onClick={() => setHist(true)} title="剧本更新前出的旧版本（已隔离，只看不挑）">历史版本</button>
              {pend && status0.action && <button onClick={status0.action.run} title={status0.action.title}>{status0.action.label.replace(/\n/g, " ")}</button>}
              {/* XYQ（小云雀走查 #1）：主按钮是“定稿并出下一步”；只想定稿、先不出卡，用这里 */}
              {(status.key === "review_first" || status.key === "auto_first") && s.first_frame_take != null && (
                <button onClick={() => void setLock(s.id, "first", s.first_frame_take!, true, st.notify, st.refreshAfter)}>只定稿首帧 #{s.first_frame_take}（不出尾帧）</button>
              )}
              {(status.key === "review_last" || status.key === "auto_last") && s.last_frame_take != null && (
                <button onClick={() => void setLock(s.id, "last", s.last_frame_take!, true, st.notify, st.refreshAfter)}>只定稿尾帧 #{s.last_frame_take}（不出视频）</button>
              )}
              <button disabled={!s.first_frame} onClick={() => st.openViewer(s.id, "image", "pair")}>全屏看首尾帧</button>
              <i />
              {/* 回退补回（regress_r1 #7）：三档重出写清楚各动哪一格 */}
              <button onClick={() => st.requestRender(s.id, "image")} title="重画首帧；之后尾帧、视频要跟着重出">{s.first_frame ? "重画首帧（尾帧、视频随后要重出）" : "出首帧"}</button>
              <button disabled={!s.first_frame} onClick={() => st.requestRender(s.id, "last")} title="首帧不动，只重编尾帧">{s.last_frame_target ? "保留首帧，重编尾帧" : "出尾帧"}</button>
              <button disabled={!!vblk} title={vblk ?? "首尾帧不动，只重出视频"} onClick={() => st.requestRender(s.id, "video")}>
                只重出视频（首尾帧不动）{vblk ? `（${vblk}）` : ""}
              </button>
              <i />
              <button disabled={!!pblk} title={pblk ? `不能通过：${pblk}` : "通过这版视频"} onClick={() => void st.setReview([s.id], "passed")}>
                通过{pblk ? `（${pblk}）` : ""}
              </button>
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

