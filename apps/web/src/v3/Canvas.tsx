// fredw-92/W4a：分镜画布 v3 外壳——左栏｜集头（待你决定 + 审片/精修）｜审片列表 或 精修三区｜底部片段条
import { thumb } from "../thumb";
import { Fragment, useEffect, useMemo, useState } from "react";
import { ShotTable } from "../components/ShotTable";
import { seamCheck, seamState } from "../components/Seam.helpers";
import { useStudio } from "../store";
import type { Episode, ShotSummary, SopOwnerAction } from "../types";
import { EditCenter } from "./edit/EditCenter";
import { getEdit, takesOf, useEdit } from "./edit/state";
import { lockAndNext, submitFrame, submitVideo } from "./edit/actions";
import { RefSwitchPanel } from "./edit/RefSwitchPanel";
import { RightTabs } from "./edit/RightTabs";
import { RIGHT_TABS, rulesNeedYou } from "./edit/rightTabs.helpers";
import { LeftRail } from "./LeftRail";
import { ReviewRow } from "./ReviewRow";
import { rowDim } from "./ReviewRow.helpers";
import { EpisodeSettings } from "./EpisodeSettings";
import { LiveProgress } from "../ds/StageProgress";
import { useSop } from "./sop.helpers";
import { DOT_LABEL, episodeCounts, frameState, sceneOf, scriptGaps, shotMeta, shotStatus, videoBlock } from "./status";
import { OwnerDecisionDialog } from "./OwnerDecision";
import { actionTitle, chipVisible, isLookWaiting, lookWaitText, useOwnerDecisionApi } from "./OwnerDecision.helpers";
import { useUi } from "./ui.helpers";
import { Pop, StatusDot, StatusLine } from "./widgets";
import { useSbUi } from "./StoryboardDetails.helpers";
import { SbEpisodeBar, StoryboardTable } from "./StoryboardTable";
import { ProduceClipDots } from "./EpisodeProduce"; // fredw-92/EB 整集出片进度点
import { stageWords } from "./words"; // UXF5（R5）
import { queueItemsOfEp, useOwnerQueue } from "./ownerQueue"; // UIRSI2 L-116：待审计数读队列

const short = (id: string) => id.split("-")[1];

/** 集头“待你决定”条（规格 §3）：只列项目方本人要拍板的事；没有就不显示 */
// fredw-92/UXF1（审查 #8 / #9）：芯片用中文名、不写关口代号；点开就是确认框（勾“我是项目方本人”+ 原话），
// 不再显示命令行。窄屏（≤1440）收成一个“待你决定 N ▾”下拉，不挤工具栏。
function DecideBar() {
  const { sop } = useSop();
  const [open, setOpen] = useState<SopOwnerAction | null>(null);
  const api = useOwnerDecisionApi(); // UIFIX-F 11-03：后端没有确认接口 → 可点的入口整个不显示
  const all = sop?.owner_actions ?? [];
  // UIFIX-F 11-03：造型确认属于资产阶段——身份脸没选定的人不给“确认造型”芯片，改成一句话
  const waits = all.filter(isLookWaiting);
  const acts = all.filter((a) => chipVisible(a, api));
  const now = acts.filter((a) => a.actionable).length;
  if (!now && !waits.length) return null; // 规格 §3：没有要你拍板的事就不显示（未到的关口在“为什么卡住”里看）
  if (!now)
    return (
      <div className="v3-decide">
        {waits.map((a, i) => (
          <small key={i} className="v3-decide-wait">{lookWaitText(a)}</small>
        ))}
      </div>
    );
  const chip = (a: SopOwnerAction, i: number, close?: () => void) => (
    <button
      key={i}
      className={`v3-decide-chip${a.actionable ? "" : " wait"}`}
      title={`${stageWords(a.why)}${a.actionable ? "\n点开确认" : `\n还不能做：${a.waiting_on.join("；")}`}`}
      onClick={() => (close?.(), setOpen(a))}
    >
      {actionTitle(a)}
      {a.actionable ? <i className="v3-badge">!</i> : <small>未到</small>}
    </button>
  );
  return (
    <>
      <div className="v3-decide">
        <b>待你决定 {now}</b>
        <span className="v3-decide-chips">{acts.map((a, i) => chip(a, i))}</span>
        <Pop label={<>查看 ▾</>} btnClass="v3-decide-chip v3-decide-more" title="全部待你决定的事">
          {(close) => (
            <div className="v3-decide-list">
              {acts.map((a, i) => chip(a, i, close))}
              {waits.map((a, i) => (
                <small key={`w${i}`} className="v3-decide-wait">{lookWaitText(a)}</small>
              ))}
            </div>
          )}
        </Pop>
      </div>
      {open && <OwnerDecisionDialog a={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function ModeSwitch() {
  const { canvasMode, setCanvasMode } = useStudio();
  return (
    <div className="v3-seg" role="tablist" aria-label="审片 / 精修（L）">
      <button className={canvasMode === "review" ? "on" : ""} onClick={() => setCanvasMode("review")} title="一镜一行看整集（Esc）">
        审片
      </button>
      <button className={canvasMode === "edit" ? "on" : ""} onClick={() => setCanvasMode("edit")} title="单镜精修（Enter / 双击行）">
        精修
      </button>
    </div>
  );
}

function SeamLine({ a, b }: { a: ShotSummary; b: ShotSummary }) {
  const { setSeam, setDrawer } = useStudio();
  const same = a.id.split("-")[0] === b.id.split("-")[0];
  const ck = same ? seamCheck(b) : undefined;
  const ss = seamState(a, b);
  const cls = ck ? (ck.level === "fail" ? "bad" : ck.ok ? "ok" : "none") : ss.state === "linked" ? "ok" : ss.state === "stale" ? "bad" : "none";
  const text = cls === "ok" ? "衔接通过" : cls === "bad" ? "不通过" : "未检查";
  return (
    <button
      className={`v3-seam ${cls}`}
      onClick={() => (setSeam({ from: a.id, to: b.id }), setDrawer({ open: true, tab: "seam" }))}
      title={`${short(a.id)} 尾帧 → ${short(b.id)} 首帧：${ck?.reason ?? ss.title}\n点击打开接缝对比`}
    >
      <i />
      <span>{text}</span>
    </button>
  );
}

function ReviewList({ ep }: { ep: Episode }) {
  const st = useStudio();
  const { sop } = useSop();
  const { sel, multi } = st;
  useEffect(() => {
    if (!sel) return;
    const t = setTimeout(() => document.querySelector(`.v3-row[data-shot="${sel}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 60);
    return () => clearTimeout(t);
  }, [sel, ep.number]);
  // U4：集头“N 镜缺分镜字段”点开 = 只列这些镜头（不显示衔接线）
  const sbui = useSbUi();
  // UXF1 #4：“只看待补”与集头 / 步骤条同一份判定（分镜字段 ∪ SOP 剧本阻塞）
  const miss = useMemo(() => (sbui.onlyMissing ? scriptGaps(ep, st.details, sop) : null), [sbui.onlyMissing, ep, st.details, sop]);
  if (st.listMode) return <ShotTable ep={ep} />;
  const shots = miss ? ep.shots.filter((s) => miss.get(s.id)?.length) : ep.shots;
  return (
    <div className="v3-rows">
      {shots.map((s, i) => {
        const next = miss ? undefined : shots[i + 1];
        return (
          <Fragment key={s.id}>
            <ReviewRow s={s} sop={sop?.shots.find((x) => x.id === s.id)} selected={s.id === sel} inMulti={multi.has(s.id)} dim={rowDim(st, s)} />
            {next && <SeamLine a={s} b={next} />}
          </Fragment>
        );
      })}
    </div>
  );
}

/** 精修模式外壳：中区（W4b 的 EditCenter）+ 右栏标签容器（W4b 的 RightTabs） */
// v3.1 §2.5：“← 审片”与右上切换重复、“3 / 11 · ←→ 切镜”与片段条重复，都删
function EditHead({ s }: { s: ShotSummary }) {
  const st = useStudio();
  const { sop } = useSop();
  useEdit(); // F2：v1 任务进度
  useOwnerQueue(); // UIRSI2 L-116：机签通过随队列刷新
  const status = shotStatus(s, st, sop?.shots.find((x) => x.id === s.id));
  return (
    <div className="v3-edit-head">
      <b className="v3-sid">{short(s.id)}</b>
      <span className="v3-meta">{shotMeta(s, sceneOf(st.details[s.id])).join(" · ")}</span>
      <StatusLine st={status} align="left" />
    </div>
  );
}

function RightPanel({ s }: { s: ShotSummary }) {
  const ui = useUi();
  const { sop } = useSop();
  const d = useStudio().details[s.id];
  // UXF5（审查 N11）：标签数字 = 版本页里实际列出的条数（首帧 + 尾帧 + 视频，与 VersionChain 同一个 takesOf）
  const nVer = (["first", "last", "video"] as const).reduce((n, sl) => n + takesOf(d, sl).length, 0);
  // UXF1：规则标签的数字只数“需要你处理”的（UXF2 的 rulesNeedYou），系统提示不再显示成红色错误数
  const nRule = rulesNeedYou(s, sop?.shots.find((x) => x.id === s.id));
  const badge: Record<string, number> = { versions: nVer, rules: nRule };
  return (
    <aside className="v3-right">
      <nav className="v3-tabs" role="tablist">
        {RIGHT_TABS.map(([k, label]) => (
          <button key={k} role="tab" aria-selected={ui.rightTab === k} className={ui.rightTab === k ? "on" : ""} onClick={() => ui.setRightTab(k)}>
            {label}
            {badge[k] ? <small className={k === "rules" ? "warn" : ""}>{badge[k]}</small> : null}
          </button>
        ))}
      </nav>
      <div className="v3-right-body">
        <RightTabs shot={s} tab={ui.rightTab} />
      </div>
    </aside>
  );
}

/** 底部片段条（规格 §2）：缩略图 + 时长 + 状态点；多选后批量“先出首尾帧预演 → 出视频” */
function ClipStrip({ ep }: { ep: Episode }) {
  const st = useStudio();
  const { sop } = useSop();
  const { sel, multi, details } = st;
  const es = useEdit();
  // v3.1 §1.7：统计与状态点同一套判定（status.ts）；已定 = 首尾帧都已定稿且未过期，视频另计
  const { q: oq } = useOwnerQueue(); // UIRSI2 L-116：机签通过 / 待你看计数读队列
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const c = useMemo(() => episodeCounts(ep.shots, st, sop), [ep, st, sop, es.jobs, oq]);
  // v3.1 §1.6：批量操作只对片段条的多选生效，没有选择就不显示
  const pick = ep.shots.filter((s) => multi.has(s.id));
  const firstList = pick.filter((s) => frameState(s, details[s.id], "image") === "none");
  const lastList = pick.filter((s) => s.first_frame && ["none", "stale"].includes(frameState(s, details[s.id], "last")));
  const vidList = pick.filter((s) => !s.video && !videoBlock(s, details[s.id]));
  const vidStale = pick.filter((s) => !s.video && (videoBlock(s, details[s.id]) ?? "").includes("过期"));
  const frameList = firstList.length ? firstList : lastList;
  const frameWhat: "first" | "last" = firstList.length ? "first" : "last";
  // F2：批量也走 v1 任务（frame-jobs / video-jobs），不走旧 /render 与 gpu3 桥
  const batch = (what: "first" | "last" | "video") => {
    const gpu = getEdit().gpu;
    const list = what === "video" ? vidList : frameList;
    for (const s of list) {
      if (what === "video") void submitVideo(s.id, { gpu: gpu as 3 | 0 }, st.notify, st.refreshAfter);
      else void submitFrame(s.id, { stage: what, mode: "regen", gpu }, what === "first" ? "出首帧" : "出尾帧", st.notify, st.refreshAfter);
    }
  };
  const ids = pick.map((s) => s.id);
  // XYQ（小云雀走查 #2 / #3）：片段条上有明确的“多选”开关（开着时单击 = 加选 / 去选，不用按 Ctrl），
  // “选中待审” = 一次选上所有待你定稿首帧 / 尾帧的镜头；批量“定稿并出下一步”与审片行主按钮同一个 lockAndNext
  const [pickMode, setPickMode] = useState(false);
  const keyOf = (s: ShotSummary) => c.status.get(s.id)?.key;
  const lockFirstList = pick.filter((s) => s.first_frame_take != null && (keyOf(s) === "review_first" || keyOf(s) === "auto_first"));
  const lockLastList = pick.filter((s) => s.last_frame_take != null && (keyOf(s) === "review_last" || keyOf(s) === "auto_last"));
  const toReview0 = ep.shots.filter((s) => ["review_first", "auto_first", "review_last", "auto_last"].includes(keyOf(s) ?? ""));
  // UIRSI2 L-116：“选中待审 N”的 N = 本集在“待你看”队列里的条目数（D-QUEUE）；点了选上这些镜 + 还要人工定稿的镜（功能不变）
  const qEp = queueItemsOfEp(oq, ep.number);
  const qIds = new Set(qEp.map((x) => x.sid!));
  const toReview = ep.shots.filter((s) => qIds.has(s.id) || toReview0.includes(s));
  const batchLock = async (slot: "first" | "last") => {
    const gpu = getEdit().gpu;
    for (const s of slot === "first" ? lockFirstList : lockLastList) {
      const n = slot === "first" ? s.first_frame_take! : s.last_frame_take!;
      await lockAndNext(s.id, slot, n, gpu, st.notify, st.refreshAfter, slot === "first" ? !s.last_frame_target : !s.video);
    }
  };
  useEffect(() => {
    if (!sel) return;
    document.querySelector(`.v3-clip[data-shot="${sel}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [sel]);
  return (
    <footer className={`v3-strip${pickMode ? " picking" : ""}`}>
      <div className="v3-strip-pick" role="group" aria-label="多选">
        <button className={`v3-btn${pickMode ? " on" : ""}`} aria-pressed={pickMode} onClick={() => setPickMode((v) => !v)} title="开着时单击片段 = 加选 / 去选（不用按 Ctrl）">
          多选
        </button>
        <button className="v3-btn" disabled={!toReview.length} onClick={() => (setPickMode(true), st.setMulti(new Set(toReview.map((s) => s.id))))} title={toReview.length ? `选上待你定稿首帧 / 尾帧的镜头：${toReview.map((s) => short(s.id)).join("、")}` : "没有待你定稿首帧 / 尾帧的镜头"}>
          选中待审{qEp.length ? ` ${qEp.length}` : ""}
        </button>
      </div>
      <div className="v3-clips">
        {ep.shots.map((s) => [s, c.status.get(s.id)!] as const).map(([s, x]) => (
          <button
            key={s.id}
            data-shot={s.id}
            className={`v3-clip${s.id === sel ? " sel" : ""}${multi.has(s.id) ? " multi" : ""}`}
            onClick={(e) => st.select(s.id, { shift: e.shiftKey, ctrl: pickMode || e.ctrlKey || e.metaKey })}
            onDoubleClick={() => (st.select(s.id), st.setCanvasMode("edit"))}
            title={`${short(s.id)} · ${s.duration.seconds}s · ${x.text}\nCtrl / Shift 点击多选（或打开左边的“多选”）；双击精修`}
          >
            {s.first_frame ? <img src={thumb(s.first_frame, 120) ?? s.first_frame} alt="" loading="lazy" draggable={false} /> : null}
            <b>{short(s.id)}</b>
            <small>{s.duration.seconds}s</small>
            <StatusDot dot={x.dot} title={`${DOT_LABEL[x.dot]}：${x.text}`} />
            <ProduceClipDots ep={ep.number} shotId={s.id} />
          </button>
        ))}
      </div>
      <div className="v3-strip-side">
        <p className="v3-strip-stats" title={`状态点：已定（视频审过）${c.dots.green} · 琥珀（要处理，系统多数自动做）${c.dots.yellow} · 生成中 ${c.dots.blue} · 失败 ${c.dots.red} · 灰（未出 / 机签通过）${c.dots.gray}
待你看 ${oq?.count ?? "…"}（全剧队列，顶栏“待你看”）`}>
          <span>
            {ep.shots.length} 镜 · {c.secs}s
          </span>
          <span>
            首尾帧已定 <b>{c.locked}</b>
          </span>
          <span>
            有视频 <b>{c.videos}</b>
          </span>
          <a className="s-yellow" href="#/queue" data-oq-count={oq ? String(oq.count) : ""} title="待你看：只放必须你拍板、机签抽检、审美挑选的事（全剧）">
            <StatusDot dot={oq && oq.count > 0 ? "yellow" : "gray"} /> 待你看 {oq?.count ?? "…"}
          </a>
          {c.dots.blue > 0 && (
            <span className="s-blue">
              <StatusDot dot="blue" /> 生成中 {c.dots.blue}
            </span>
          )}
          {c.dots.red > 0 && (
            <span className="s-red">
              <StatusDot dot="red" /> 出错 {c.dots.red}
            </span>
          )}
          <span>
            <StatusDot dot="gray" /> 未出 {c.dots.gray}
          </span>
        </p>
        {pick.length > 0 ? (
          <div className="v3-strip-batch">
            <b>对已选 {pick.length} 镜：</b>
            {lockFirstList.length > 0 && (
              <button className="v3-btn primary" onClick={() => void batchLock("first")} title={`定稿当前这一版首帧并由它出尾帧：${lockFirstList.map((s) => `${short(s.id)} #${s.first_frame_take}`).join("、")}`}>
                定稿首帧 → 出尾帧（{lockFirstList.length}）
              </button>
            )}
            {lockLastList.length > 0 && (
              <button className="v3-btn primary" onClick={() => void batchLock("last")} title={`定稿当前这一版尾帧并出视频：${lockLastList.map((s) => `${short(s.id)} #${s.last_frame_take}`).join("、")}`}>
                定稿尾帧 → 出视频（{lockLastList.length}）
              </button>
            )}
            <button
              className="v3-btn"
              disabled={!frameList.length}
              onClick={() => batch(frameWhat)}
              title={frameList.length ? `${frameList.map((s) => short(s.id)).join("、")}` : "已选镜头的首尾帧都已有"}
            >
              {frameList.length ? `出${frameWhat === "first" ? "首帧" : "尾帧"}（${frameList.length}）` : "首尾帧已齐"}
            </button>
            <button
              className="v3-btn primary"
              disabled={!vidList.length}
              onClick={() => batch("video")}
              title={vidList.length ? vidList.map((s) => short(s.id)).join("、") : vidStale.length ? (videoBlock(vidStale[0], details[vidStale[0].id]) ?? "") : "已选镜头没有可出视频的（要首尾帧都在、尾帧没过期、还没视频）"}
            >
              出视频{vidList.length ? `（${vidList.length}）` : ""}
            </button>
            <button className="v3-btn" onClick={() => void st.setReview(ids, "passed")}>
              用这版
            </button>
            <button className="v3-icon" onClick={() => st.setMulti(new Set())} title="取消选择">
              ×
            </button>
            {vidStale.length > 0 && <small className="v3-warn-text">{vidStale.map((s) => `${short(s.id)}：${videoBlock(s, details[s.id])}`).join("；")}</small>}
          </div>
        ) : null}
      </div>
    </footer>
  );
}

/** 参考切换浮层：Esc 只关浮层（不连带退出精修） */
function useOverlayEsc(open: boolean, close: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      close();
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [open, close]);
}

export function CanvasV3() {
  const st = useStudio();
  const ui = useUi();
  const { episode, canvasMode, sel, summaryById } = st;
  useOverlayEsc(!!ui.refSwitch, ui.closeRefSwitch);
  if (!episode) return <div className="empty">请选择一集</div>;
  if (episode.light) return <div className="empty">加载第 {episode.number} 集…</div>;
  const cur = (sel && summaryById.get(sel)) || episode.shots[0];
  const edit = canvasMode === "edit" && !!cur;
  const rs = ui.refSwitch ? summaryById.get(ui.refSwitch.shotId) : undefined;
  return (
    <div className={`v3-canvas${edit ? " edit" : ""}${ui.railMini ? " rail-mini" : ""}`}>
      <LeftRail ep={episode} />
      <main className="v3-main">
        {/* v3.1 §1.5：集名只在顶栏出现，这里不再重复页面标题 */}
        <header className="v3-head">
          <DecideBar />
          <SbEpisodeBar ep={episode} />
          <span className="v3-grow" />
          <EpisodeSettings ep={episode} />
          {/* 回退补回（regress_r1 #11）：串播审片按钮（以前只剩快捷键 R） */}
          <button className="v3-btn sm" onClick={() => st.setReviewMode(true)} title="按顺序连播本集视频，边看边用这版 / 修改（R）">
            ▶ 串播审片
          </button>
          <ModeSwitch />
        </header>
        {/* 实时分段进度（剧本 → 分镜 → 首帧 → 尾帧 → 视频 → 声音 → 成片）单独一行：集头按钮多时不再把“串播审片”挤出屏（UIAUDIT F19） */}
        <div className="v3-head-progress">
          <LiveProgress run={null} episode={episode.number} compact />
        </div>
        {edit ? (
          <div className="v3-edit">
            <EditHead s={cur} />
            <div className="v3-edit-center">
              <EditCenter shot={cur} />
            </div>
          </div>
        ) : (
          <ReviewList ep={episode} />
        )}
      </main>
      {edit && <RightPanel s={cur} />}
      <ClipStrip ep={episode} />
      <StoryboardTable ep={episode} />
      {ui.refSwitch && rs && (
        <div className="v3-overlay" onMouseDown={(e) => e.target === e.currentTarget && ui.closeRefSwitch()}>
          <div className="v3-overlay-box" role="dialog" aria-label="本镜参考切换">
            <RefSwitchPanel shot={rs} target={ui.refSwitch.target} onClose={ui.closeRefSwitch} />
          </div>
        </div>
      )}
    </div>
  );
}
