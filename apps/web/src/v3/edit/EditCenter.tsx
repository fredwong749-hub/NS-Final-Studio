// fredw-92/W4b → U2（v3.1 §2）：精修模式中区。
// 布局：左列 = 一个大格（当前聚焦的阶段：首帧 / 尾帧 / 视频，有视频时默认视频，占满可用高度），
//       紧贴大格下方 = 播放控制条（视频时）+ 这一格的操作（按钮写全名）；
//       右侧 = 另两格预览（高度 ≥ 大格 45%，点哪个放大哪个）、本镜参考小卡 + 用卡 / 预计时长 + 任务进度、聚焦阶段的版本条（110 px 高）。
// 提示词 / 修改要求原样发送，不做内容检测。
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ShotSummary } from "../../types";
import { useStudio } from "../../store";
import { MODE_LABEL, type Slot } from "../api_v1";
import {
  currentTake, etaFor, fmtSec, focusSlot, gateOf, gpuLabel, lockedTake, pickTake, setEdit, setShotUi, takeUrl, takesOf, useEdit, type TakeX,
} from "./state";
import { SLOT_NAME, adoptJobs, setLock, submitFrame, submitVideo } from "./actions";
import { EditLoop } from "./EditLoop";
import { CompareModal } from "./CompareModal";
import { JobStrip } from "./JobStrip";
import { RefBar } from "./RefBar";
import { AssetDrawer } from "./AssetDrawer";
import { Cell, Stage, stepFrames, type VideoView } from "./Stage";
import "./edit.css";

export interface EditCenterProps {
  /** 当前镜头（store.summaryById.get(sel)）；详情用 useStudio().details[shot.id] */
  shot: ShotSummary;
}

const SLOTS: Slot[] = ["first", "last", "video"];
const AR = 9 / 16; // 768×1344 竖屏
const GAP = 12;
const INFO_W = 150; // 预览右边的信息列（参考 / 用卡 / 任务）
const VER_H = 146; // 版本条（标题 + 110 px 缩略图）
const SIDE_HIDE = 220; // 右侧比这还窄就不显示（首尾对照 4 格并排时）

export function EditCenter({ shot }: EditCenterProps) {
  const studio = useStudio();
  const es = useEdit();
  const id = shot.id;
  const d = studio.details[id];
  const slot = focusSlot(es, d, id);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const barsRef = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState({ w: 900, h: 600 });
  const [barsH, setBarsH] = useState(90);
  const [view, setView] = useState<VideoView>("single");
  const [loop, setLoop] = useState(true);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (!studio.details[id]) void studio.refreshShots([id]);
    void adoptJobs(id, studio.notify, studio.refreshAfter); // F2：刷新页面后接回本镜进行中的任务
    setView("single");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => {
    if (slot !== "video") setView("single");
  }, [slot]);
  useEffect(() => {
    if (!menu) return;
    const off = (e: MouseEvent) => !menuRef.current?.contains(e.target as Node) && setMenu(false);
    document.addEventListener("mousedown", off);
    return () => document.removeEventListener("mousedown", off);
  }, [menu]);
  // 大格尺寸跟着可用高度走（减去紧贴下方的播放条 + 操作行）
  const hasD = !!d;
  useLayoutEffect(() => {
    const el = topRef.current;
    const bars = barsRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      setTop({ w: el.clientWidth, h: el.clientHeight });
      if (bars) setBarsH(bars.offsetHeight);
    });
    ro.observe(el);
    if (bars) ro.observe(bars);
    setTop({ w: el.clientWidth, h: el.clientHeight });
    if (bars) setBarsH(bars.offsetHeight);
    return () => ro.disconnect();
  }, [hasD]);
  // 1 / 2 / 3 聚焦首帧 / 尾帧 / 视频；, . 逐帧（输入框里不拦）
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.ctrlKey || e.metaKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(el.tagName) || el.isContentEditable) return;
      const s = ({ "1": "first", "2": "last", "3": "video" } as Record<string, Slot>)[e.key];
      if (s) setShotUi(id, { slot: s });
      if (e.key === "," || e.key === ".") stepFrames(rootRef.current, e.key === "," ? -1 : 1);
      // 精修里 1/2/3 只切大格（全局快捷键 1/2 会切页面视图，这里先拦下）
      if (s || e.key === "," || e.key === ".") {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    window.addEventListener("keydown", on, true);
    return () => window.removeEventListener("keydown", on, true);
  }, [id]);

  if (!d) {
    return (
      <div className="v3e">
        <div className="v3e-empty">{studio.detailErr[id] ? `读取 ${id} 失败：${studio.detailErr[id]}` : `正在读取 ${id}…`}</div>
      </div>
    );
  }

  const notify = studio.notify;
  const refresh = studio.refreshAfter; // F2：连摘要一起刷（审片行、片段条、状态点跟着变）
  const focus = (s: Slot) => setShotUi(id, { slot: s });
  const cur = currentTake(es, d, id, slot);
  const lockFirst = lockedTake(d, "first");
  const lockLast = lockedTake(d, "last");
  const running = (s: Slot) =>
    es.jobs.find((j) => j.shot === id && j.slot === s && (j.state === "queued" || j.state === "running") && !j.notReady);
  const gate = gateOf(d, slot);
  const eta = etaFor(slot, es.gpu, shot.duration?.seconds);
  const isLocked = !!cur?.locked;
  const list = takesOf(d, slot);
  const nm = SLOT_NAME[slot];
  const prevVid = slot === "video" && cur ? list.find((t) => t.n === cur.parent) ?? [...list].reverse().find((t) => t.n < cur.n) ?? null : null;
  const job = running(slot);

  // ---- 尺寸 ----
  // 大格：高 = 可用高度 − 下方条；宽 = 高 × 9:16。首尾对照 4 格并排时整行给大格
  const n = view === "ends" && slot === "video" && cur?.url ? 4 : view === "prev" && prevVid?.url ? 2 : 1;
  const stageH = Math.max(240, top.h - barsH - 8);
  const maxW = n === 4 ? (top.w - 3 * GAP - 16) / 4 : (top.w - GAP - 260 - (n - 1) * GAP) / n; // 右侧至少留 260
  const cw = Math.max(150, Math.min(stageH * AR, maxW));
  const size = { w: Math.round(cw), h: Math.round(Math.min(stageH, cw / AR)) };
  const barW = slot === "video" && cur?.url ? 470 : 450; // 左列最窄：播放条 / 阶段操作一行放得下
  const colW = Math.max(barW, n === 4 ? top.w : size.w * n + (n - 1) * GAP);
  // 右侧：宽时 = 预览两张 + 信息列，版本条在下面横跨；窄时信息排在预览下面
  const sideW = n === 4 ? 0 : top.w - colW - GAP;
  const showSide = sideW >= SIDE_HIDE;
  const wideSide = sideW >= 2 * (size.h * 0.45 * AR) + INFO_W + 2 * GAP;
  const pvH = Math.round(
    Math.max(
      140,
      wideSide
        ? Math.min(top.h - VER_H - GAP, (sideW - INFO_W - 2 * GAP) / 2 / AR)
        : Math.min((sideW - GAP) / 2 / AR, top.h - VER_H - 150 - 2 * GAP),
    ),
  );
  const pvW = Math.round(pvH * AR);

  const regen = () => {
    if (gate) return notify(gate, "err");
    if (slot === "video") void submitVideo(id, { gpu: es.gpu as 3 | 0, ...(cur ? { parent: cur.n } : {}) }, notify, refresh);
    else void submitFrame(id, { stage: slot, mode: "regen", gpu: es.gpu }, `重新生成${nm}`, notify, refresh);
  };
  const openLoop = (parent: number | null = cur?.n ?? null) =>
    setEdit(() => ({
      loop: { shot: id, slot, mode: slot === "video" ? "video" : parent != null ? "instruct" : "regen", parent },
    }));
  const openVideoParams = () =>
    setEdit(() => ({ loop: { shot: id, slot: "video", mode: "video", parent: currentTake(es, d, id, "video")?.n ?? null } }));
  const openDrawerFromTake = () => {
    const ch = shot.characters?.[0];
    if (!ch) return notify("本镜没有出场人物，先在资产页选资产", "err");
    setEdit(() => ({
      drawer: {
        shot: id,
        asset: ch.look_id ?? ch.character,
        character: ch.character,
        label: `${ch.name}${ch.look_label ? ` · 形象 ${ch.look_label}` : ""}`,
        kind: "look",
        fromTake: cur ? { slot, n: cur.n } : null,
      },
    }));
  };

  const menuItems: [string, () => void, boolean][] = [
    [`从这一版继续改${nm}…`, () => openLoop(), !cur || slot === "video"],
    [
      `和上一版${nm}并排对比`,
      () => (slot === "video" ? setView("prev") : cur?.parent != null && setEdit(() => ({ compare: { shot: id, slot, a: cur.n, b: cur.parent! } }))),
      slot === "video" ? !prevVid : cur?.parent == null,
    ],
    ["把这张设为资产参考…", openDrawerFromTake, !cur || slot === "video"],
    [
      "复制这一版的提示词",
      () => void navigator.clipboard?.writeText(cur?.prompt ?? "").then(() => notify("已复制"), () => notify("复制失败", "err")),
      !cur?.prompt,
    ],
    [slot === "video" ? "打开原视频" : "打开原图", () => cur?.url && window.open(cur.url, "_blank"), !cur?.url],
  ];

  const placeholder = (s: Slot) => {
    const g = gateOf(d, s);
    return (
      <div className="v3e-ph">
        <div className="big">{s === "first" ? "◧" : s === "last" ? "◨" : "▶"}</div>
        <b>{g ?? `还没有${SLOT_NAME[s]}`}</b>
        <div className="mini">{g ? (s === "last" ? "尾帧由定稿首帧编辑而来" : "首尾帧定稿后这里出视频") : s === "video" ? "点「出视频」" : `点「重新生成${SLOT_NAME[s]}」出第一张`}</div>
      </div>
    );
  };
  const genOverlay = (j: ReturnType<typeof running>) =>
    j ? (
      <div className="v3e-genov">
        <div className="spin" />
        <div>
          {j.state === "queued" ? "排队中" : "生成中"} · {gpuLabel(j.gpu)}
        </div>
      </div>
    ) : null;

  const vidTools = slot === "video" && cur?.url;

  const previews = (
    <div className="v3e-previews">
      {SLOTS.filter((s) => s !== slot).map((s) => {
        const t = currentTake(es, d, id, s);
        const u = takeUrl(t);
        return (
          <Cell
            key={s}
            className="pv"
            style={{ width: pvW, height: pvH }}
            label={`${SLOT_NAME[s]}${t ? ` · #${t.n}` : ""}`}
            t={t}
            onClick={() => focus(s)}
            title={`放大${SLOT_NAME[s]}（${SLOTS.indexOf(s) + 1}）`}
          >
            {u ? <img src={u} alt="" loading="lazy" /> : <div className="v3e-ph sm">{gateOf(d, s) ?? `还没有${SLOT_NAME[s]}`}</div>}
            {s === "video" && u && <span className="v3e-playic">▶</span>}
            {genOverlay(running(s))}
          </Cell>
        );
      })}
    </div>
  );
  const info = (
    <div className={`v3e-info ${wideSide ? "col" : "row"}`}>
      <RefBar shot={shot} />
      <div className="v3e-cost">
        <label>
          用卡
          <select value={es.gpu} onChange={(e) => setEdit(() => ({ gpu: Number(e.target.value) as 0 | 3 }))}>
            <option value={3}>{gpuLabel(3)}</option>
            <option value={0}>{gpuLabel(0)}</option>
          </select>
        </label>
        <span title={eta.n ? `按这张卡最近 ${eta.n} 次实际耗时平均` : "还没有这张卡的实际耗时记录，先按粗估"}>
          {slot === "video" ? "出视频" : `出${nm}`}预计约 {fmtSec(eta.eta)}
          {eta.queue ? `（前面 ${eta.queue} 个）` : ""}
        </span>
      </div>
      <JobStrip shot={id} />
    </div>
  );
  const versions = (
    <div className="v3e-cands">
      <div className="ct">
        <b>
          {nm}版本 · {list.length} 版{cur ? ` · 当前 #${cur.n}` : ""}
        </b>
        {list.length > 1 && <span>点一张选中，双击和它的上一版对比</span>}
      </div>
      <div className="row">
        {list.length ? (
          [...list].reverse().map((t: TakeX) => (
            <button
              key={t.n}
              className={`v3e-cand ${cur?.n === t.n ? "sel" : ""} ${t.locked ? "locked" : ""}`}
              title={`#${t.n}${t.mode ? ` · ${MODE_LABEL[t.mode] ?? t.mode}` : ""}${t.instruction ? `\n${t.instruction}` : ""}`}
              onClick={() => pickTake(id, slot, t.n)}
              onDoubleClick={() => {
                if (slot === "video") {
                  pickTake(id, slot, t.n);
                  setView("prev");
                } else if (t.parent != null) setEdit(() => ({ compare: { shot: id, slot, a: t.n, b: t.parent! } }));
              }}
            >
              {takeUrl(t) ? <img src={takeUrl(t)!} alt="" loading="lazy" /> : <span className="e">{slot === "video" ? "▶" : "—"}</span>}
              <span className="no">#{t.n}</span>
              {t.parent != null && <span className="par">←{t.parent}</span>}
              {t.locked && <span className="lk">✓</span>}
            </button>
          ))
        ) : (
          <span className="none">还没有{nm}</span>
        )}
      </div>
    </div>
  );

  return (
    <div className={`v3e v31 ${n === 4 ? "wide" : ""}`} ref={rootRef}>
      <div className="v3e-top" ref={topRef}>
        <div className="v3e-maincol" style={{ width: colW }}>
          <Stage
            slot={slot}
            cur={cur}
            size={size}
            view={view}
            prev={prevVid}
            lockFirst={lockFirst}
            lockLast={lockLast}
            loop={loop}
            rate={slow ? 0.5 : 1}
            placeholder={placeholder(slot)}
            overlay={genOverlay(job)}
          />

          <div className="v3e-bars" ref={barsRef}>
            {vidTools && (
              <div className="v3e-vtools" role="toolbar" aria-label="视频播放控制">
                <button className={`v3e-tg ${loop ? "on" : ""}`} aria-pressed={loop} onClick={() => setLoop((x) => !x)} title="循环播放">
                  循环
                </button>
                <button className={`v3e-tg ${slow ? "on" : ""}`} aria-pressed={slow} onClick={() => setSlow((x) => !x)} title="0.5 倍速">
                  0.5×
                </button>
                <button className="v3e-tg" onClick={() => stepFrames(rootRef.current, -1)} title="上一帧（,）">
                  ‹ 上一帧
                </button>
                <button className="v3e-tg" onClick={() => stepFrames(rootRef.current, 1)} title="下一帧（.）">
                  下一帧 ›
                </button>
                <span className="sep" />
                <button
                  className={`v3e-tg ${view === "ends" ? "on" : ""}`}
                  aria-pressed={view === "ends"}
                  onClick={() => setView((v) => (v === "ends" ? "single" : "ends"))}
                  title="视频第一帧 | 定稿首帧、视频最后一帧 | 定稿尾帧 并排"
                >
                  首尾对照
                </button>
                <button
                  className={`v3e-tg ${view === "prev" ? "on" : ""}`}
                  aria-pressed={view === "prev"}
                  disabled={!prevVid?.url}
                  onClick={() => setView((v) => (v === "prev" ? "single" : "prev"))}
                  title={prevVid ? `和视频 #${prevVid.n} 并排同步播放` : "只有一版视频"}
                >
                  {prevVid ? `对比上一版 #${prevVid.n}` : "对比上一版"}
                </button>
              </div>
            )}

            <div className="v3e-actbar">
              {slot === "video" ? (
                <>
                  <button className="v3e-btn primary" disabled={!!gate} onClick={regen} title={gate ?? undefined}>
                    {list.length ? "重新出视频" : "出视频"}
                  </button>
                  <button className="v3e-btn" disabled={!!gate} onClick={openVideoParams} title="改种子 / 步数 / 时长 / LoRA 强度 / 提示词后重渲">
                    改参数重渲…
                  </button>
                </>
              ) : (
                <>
                  <button className="v3e-btn" disabled={!!gate || !cur} onClick={() => openLoop()} title="改提示词重出 / 指令改图 / 换参考再改 / 局部重绘">
                    修改{nm}…
                  </button>
                  <button className="v3e-btn primary" disabled={!!gate} onClick={regen} title={gate ?? undefined}>
                    重新生成{nm}
                  </button>
                  {cur && (
                    <button
                      className={`v3e-btn ${isLocked ? "" : "ok"}`}
                      disabled={!!gate}
                      title={isLocked ? "取消后，之后的尾帧 / 视频会标过期" : slot === "first" ? "定稿后才能做尾帧" : "首尾帧都定稿后才能出视频"}
                      onClick={() => void setLock(id, slot, cur.n, !isLocked, notify, refresh)}
                    >
                      {isLocked ? `取消定稿${nm}` : `定稿${nm} #${cur.n}`}
                    </button>
                  )}
                </>
              )}
              <div className="v3e-more" ref={menuRef}>
                <button className="v3e-btn" onClick={() => setMenu((m) => !m)} aria-label="更多" title="更多">
                  ⋯
                </button>
                {menu && (
                  <div className="v3e-menu">
                    {menuItems.map(([t, f, dis]) => (
                      <button
                        key={t}
                        disabled={dis}
                        onClick={() => {
                          setMenu(false);
                          f();
                        }}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {gate && <span className="v3e-gate">{gate}</span>}
            </div>
          </div>
        </div>

        {showSide && (
          <aside className={`v3e-side ${wideSide ? "wide" : "stack"}`}>
            {wideSide ? (
              <>
                <div className="v3e-sidetop">
                  {previews}
                  {info}
                </div>
                {versions}
              </>
            ) : (
              <>
                {previews}
                {versions}
                {info}
              </>
            )}
          </aside>
        )}
      </div>

      {es.loop?.shot === id && <EditLoop shot={shot} />}
      {es.compare?.shot === id && <CompareModal shot={shot} />}
      {es.drawer?.shot === id && <AssetDrawer shot={shot} open={es.drawer} onClose={() => setEdit(() => ({ drawer: null }))} />}
    </div>
  );
}

export default EditCenter;
