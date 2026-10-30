// fredw-92/W4a：分镜画布 v3 外壳——左栏｜集头（待你决定 + 审片/精修）｜审片列表 或 精修三区｜底部片段条
import { Fragment, useEffect, useMemo } from "react";
import { ShotTable } from "../components/ShotTable";
import { seamCheck, seamState } from "../components/Seam";
import { useStudio } from "../store";
import type { Episode, ShotSummary } from "../types";
import { EditCenter } from "./edit/EditCenter";
import { getEdit, useEdit } from "./edit/state";
import { submitFrame, submitVideo } from "./edit/actions";
import { RefSwitchPanel } from "./edit/RefSwitchPanel";
import { RIGHT_TABS, RightTabs } from "./edit/RightTabs";
import { LeftRail } from "./LeftRail";
import { ReviewRow, rowDim } from "./ReviewRow";
import { useSop } from "./sop";
import { DOT_LABEL, episodeCounts, frameState, sceneOf, shotMeta, shotStatus, videoBlock } from "./status";
import { useUi } from "./ui";
import { Pop, StatusDot, StatusLine } from "./widgets";
import { episodeMissing, useSbUi } from "./StoryboardDetails";
import { SbEpisodeBar, StoryboardTable } from "./StoryboardTable";
import { ProduceClipDots } from "./EpisodeProduce"; // fredw-92/EB 整集出片进度点

const short = (id: string) => id.split("-")[1];

/** 集头“待你决定”条（规格 §3）：只列项目方本人要拍板的事；没有就不显示 */
function DecideBar() {
  const { sop } = useSop();
  const acts = sop?.owner_actions ?? [];
  const now = acts.filter((a) => a.actionable).length;
  if (!now) return null; // 规格 §3：没有要你拍板的事就不显示（未到的关口在“为什么卡住”里看）
  return (
    <div className="v3-decide">
      <b>待你决定 {now}</b>
      {acts.map((a, i) => (
        <Pop key={i} label={<>{a.title}{a.actionable ? <i className="v3-badge">!</i> : <small>未到</small>}</>} btnClass={`v3-decide-chip${a.actionable ? "" : " wait"}`} title={a.why}>
          {() => (
            <div className="v3-why-pop">
              <b>{a.title}</b>
              <p>{a.why}</p>
              {a.waiting_on.length > 0 && (
                <>
                  <b>还在等</b>
                  <ul>
                    {a.waiting_on.map((w, j) => (
                      <li key={j}>{w}</li>
                    ))}
                  </ul>
                </>
              )}
              {a.cli && (
                <>
                  <b>你本人执行</b>
                  <code>{a.cli}</code>
                </>
              )}
            </div>
          )}
        </Pop>
      ))}
    </div>
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
  const miss = useMemo(() => (sbui.onlyMissing ? episodeMissing(ep, st.details) : null), [sbui.onlyMissing, ep, st.details]);
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
  const nVer = (d?.takes.takes.length ?? 0) + (d?.gpu3_takes?.takes.length ?? 0);
  const nRule = (sop?.shots.find((x) => x.id === s.id)?.blockers.length ?? 0) + (s.h3_lint?.filter((l) => !l.ok && !l.overridden).length ?? 0);
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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const c = useMemo(() => episodeCounts(ep.shots, st, sop), [ep, st, sop, es.jobs]);
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
  useEffect(() => {
    if (!sel) return;
    document.querySelector(`.v3-clip[data-shot="${sel}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [sel]);
  return (
    <footer className="v3-strip">
      <div className="v3-clips">
        {ep.shots.map((s) => [s, c.status.get(s.id)!] as const).map(([s, x]) => (
          <button
            key={s.id}
            data-shot={s.id}
            className={`v3-clip${s.id === sel ? " sel" : ""}${multi.has(s.id) ? " multi" : ""}`}
            onClick={(e) => st.select(s.id, { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey })}
            onDoubleClick={() => (st.select(s.id), st.setCanvasMode("edit"))}
            title={`${short(s.id)} · ${s.duration.seconds}s · ${x.text}\nCtrl / Shift 点击多选；双击精修`}
          >
            {s.first_frame ? <img src={s.first_frame} alt="" loading="lazy" draggable={false} /> : null}
            <b>{short(s.id)}</b>
            <small>{s.duration.seconds}s</small>
            <StatusDot dot={x.dot} title={`${DOT_LABEL[x.dot]}：${x.text}`} />
            <ProduceClipDots ep={ep.number} shotId={s.id} />
          </button>
        ))}
      </div>
      <div className="v3-strip-side">
        <p className="v3-strip-stats" title={`状态点：已定（视频审过）${c.dots.green} · 待你审 ${c.dots.yellow} · 生成中 ${c.dots.blue} · 失败 ${c.dots.red} · 未出 ${c.dots.gray}`}>
          <span>
            {ep.shots.length} 镜 · {c.secs}s
          </span>
          <span>
            首尾帧已定 <b>{c.locked}</b>
          </span>
          <span>
            有视频 <b>{c.videos}</b>
          </span>
          <span className="s-yellow">
            <StatusDot dot="yellow" /> 待你审 {c.dots.yellow}
          </span>
          {c.dots.blue > 0 && (
            <span className="s-blue">
              <StatusDot dot="blue" /> 生成中 {c.dots.blue}
            </span>
          )}
          {c.dots.red > 0 && (
            <span className="s-red">
              <StatusDot dot="red" /> 失败 {c.dots.red}
            </span>
          )}
          <span>
            <StatusDot dot="gray" /> 未出 {c.dots.gray}
          </span>
        </p>
        {pick.length > 0 ? (
          <div className="v3-strip-batch">
            <b>对已选 {pick.length} 镜：</b>
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
            <button className="v3-btn" onClick={() => void st.setReview(ids, "passed")} title="只对视频已完整播放过的镜头生效">
              通过
            </button>
            <button className="v3-btn" onClick={() => st.setRejectFor(ids)}>
              打回
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
          <ModeSwitch />
        </header>
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
