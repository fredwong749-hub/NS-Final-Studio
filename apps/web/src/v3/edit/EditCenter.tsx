// fredw-92/W4b → U2（v3.1 §2）：精修模式中区。
// 布局：左列 = 一个大格（当前聚焦的阶段：首帧 / 尾帧 / 视频，有视频时默认视频，占满可用高度），
//       紧贴大格下方 = 播放控制条（视频时）+ 这一格的操作（按钮写全名）；
//       右侧 = 另两格预览（高度 ≥ 大格 45%，点哪个放大哪个）、本镜参考小卡 + 用卡 / 预计时长 + 任务进度、聚焦阶段的版本条（110 px 高）。
// fredw-92/UXF2（审查 #7 / #11 / #22 / #23 / #25）：视频大格正下方“通过这版视频 / 打回…”（A / R），通过后跳到下一个待你审的镜头；
//       还没出的阶段收成细条（一个动作），预览固定约 220 px 高；“修改…”改成大格右边的停靠面板（大图不被盖住）；用卡写真实道名。
// 提示词 / 修改要求原样发送，不做内容检测。
import { thumb } from "../../thumb";
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import type { ShotSummary } from "../../types";
import { useStudio } from "../../store";
import { MODE_LABEL, slotToStage, type Slot } from "../api_v1";
import {
  activeN,
  currentTake,
  etaFor,
  fmtSec,
  focusSlot,
  gateOf,
  gpuLabel,
  isStale,
  lockedTake,
  pickTake,
  setEdit,
  setShotUi,
  takeUrl,
  takesOf,
  useEdit,
  type TakeX,
} from "./state";
import { frameState, shotStatus, staleOf } from "../status";
import { useUi } from "../ui.helpers";
import { LaneSelect } from "./LaneSelect";
import { laneWait } from "./LaneSelect.helpers";
import { useLanes } from "./lanes";
import { Verdict } from "../Verdict";
import { SLOT_NAME, adoptJobs, setLock, submitFrame, submitVideo } from "./actions";
import { EditLoop } from "./EditLoop";
import { CompareModal } from "./CompareModal";
import { JobStrip } from "./JobStrip";
import { RefBar } from "./RefBar";
import { AssetDrawer } from "./AssetDrawer";
import { Cell, Stage, type VideoView } from "./Stage";
import { stepFrames } from "./Stage.helpers";
import { openOverlay } from "../../keymap";
import { cardName, cardTip } from "./lanes";
import { AUTO_SHORT, AUTO_TIP, regenLabel, staleLong } from "../words";
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
const PV_MAX_H = 220; // UXF2 #22：预览固定约 220 px 高（大格才是主角）
const DOCK_W = 440; // UXF2 #23：“修改…”停靠面板的宽
/** 视频地址去掉 ?v= 再比（摘要的 video 与版本的 url 同一文件） */
const bare = (u?: string | null) => (u ?? "").split("?")[0];

export function EditCenter({ shot }: EditCenterProps) {
  const studio = useStudio();
  const es = useEdit();
  const id = shot.id;
  const d = studio.details[id];
  const slot = focusSlot(es, d, id);
  const [menu, setMenu] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const menuBtn = useRef<HTMLButtonElement>(null);
  const [menuPos, setMenuPos] = useState<CSSProperties | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const barsRef = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState({ w: 900, h: 600 });
  const [barsH, setBarsH] = useState(90);
  const [view, setView] = useState<VideoView>("single");
  const [loop, setLoop] = useState(true);
  const [slow, setSlow] = useState(false);
  const ui = useUi();
  const { lanes } = useLanes();
  const firstId = useRef(id);
  /** A / R 键用的最新动作（键盘监听只装一次） */
  const keyAct = useRef<{
    approve: () => void;
    edit: () => void;
    on: boolean;
  }>({ approve: () => undefined, edit: () => undefined, on: false });

  useEffect(() => {
    if (!studio.details[id]) void studio.refreshShots([id]);
    void adoptJobs(id, studio.notify, studio.refreshAfter); // F2：刷新页面后接回本镜进行中的任务
    setView("single");
    // UXF2 #27：换镜后右栏回到“提示词”（规格：默认停在提示词）；第一次进精修尊重 ?rtab=
    if (id !== firstId.current) ui.setRightTab("prompt");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  useEffect(() => {
    if (slot !== "video") setView("single");
  }, [slot]);
  // UXF4（审查 N2）：“对比上一版 / 首尾对照”算一层浮层——Esc 先回单格，不退出精修（上面还有菜单 / 弹窗时让它们先关）
  useEffect(() => {
    if (view === "single") return;
    const on = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || e.defaultPrevented || openOverlay()) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      setView("single");
    };
    window.addEventListener("keydown", on, true);
    return () => window.removeEventListener("keydown", on, true);
  }, [view]);
  useEffect(() => {
    if (!menu) return;
    const off = (e: MouseEvent) => !menuRef.current?.contains(e.target as Node) && !popRef.current?.contains(e.target as Node) && setMenu(false);
    document.addEventListener("mousedown", off);
    return () => document.removeEventListener("mousedown", off);
  }, [menu]);
  // UM-0180/0181：⋯ 菜单用视口坐标定位（fixed + 挂到 body），不被顶栏 / 集头盖住：
  // 上方放得下就向上弹，否则向下；都放不下就放到空间大的一侧并限高滚动；上沿不高于顶栏底边
  useLayoutEffect(() => {
    if (!menu) {
      setMenuPos(null);
      return;
    }
    const place = () => {
      const b = menuBtn.current?.getBoundingClientRect();
      const pop = popRef.current;
      if (!b || !pop) return;
      const gap = 4;
      const vh = window.innerHeight;
      const vw = window.innerWidth;
      const floor = Math.max(8, ...[...document.querySelectorAll("header.v3-top, .v3-top")].map((el) => el.getBoundingClientRect().bottom)) + gap;
      const h = pop.scrollHeight;
      const w = Math.max(pop.offsetWidth, 220);
      const above = b.top - gap - floor;
      const below = vh - b.bottom - gap - 8;
      const left = Math.min(Math.max(8, b.right - w), vw - w - 8);
      let top: number;
      let maxHeight: number | undefined;
      if (h <= above) top = b.top - gap - h;
      else if (h <= below) top = b.bottom + gap;
      else if (above >= below) {
        top = floor;
        maxHeight = above;
      } else {
        top = b.bottom + gap;
        maxHeight = below;
      }
      setMenuPos({
        position: "fixed",
        top,
        left,
        bottom: "auto",
        right: "auto",
        width: "max-content",
        maxWidth: vw - 16,
        maxHeight,
        overflowY: maxHeight ? "auto" : undefined,
        zIndex: 1000,
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
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
      // L-123：A = 用这张（视频 = 用这版），E = 修改；没有“不要”。R 仍是串播
      const k = e.key.toLowerCase();
      if ((k === "a" || k === "e") && !e.shiftKey && keyAct.current.on && !document.querySelector(".modal-back, .v3e-modal")) {
        e.preventDefault();
        e.stopImmediatePropagation();
        (k === "a" ? keyAct.current.approve : keyAct.current.edit)();
        return;
      }
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
  const running = (s: Slot) => es.jobs.find((j) => j.shot === id && j.slot === s && (j.state === "queued" || j.state === "running") && !j.notReady);
  const gate = gateOf(d, slot);
  const kind = slot === "video" ? "video" : "image";
  const eta0 = etaFor(slot, es.gpu, shot.duration?.seconds);
  // 预计 = 单次耗时 × 本页排队 + 这条道上已有的活（含别人的外部任务 / 训练锁时显示提示）
  const eta = { ...eta0, eta: eta0.eta + laneWait(es.gpu, kind, lanes) };
  const isLocked = !!cur?.locked;
  const list = takesOf(d, slot);
  const nm = SLOT_NAME[slot];
  const prevVid = slot === "video" && cur ? (list.find((t) => t.n === cur.parent) ?? [...list].reverse().find((t) => t.n < cur.n) ?? null) : null;
  const job = running(slot);
  const loopOpen = es.loop?.shot === id;
  // UXF2 #11：过期判定和审片行同源（status.frameState / staleOf）；过期时不给“定稿”，换成“重出（已过期：原因）”
  const stage = slotToStage(slot);
  const curIsMain = !!cur && slot !== "video" && (cur.locked || cur.n === activeN(d, slot));
  const staleWhy = cur
    ? isStale(cur)
      ? [...(cur.stale ?? []), ...(cur.stale_global ?? [])].filter(Boolean).join("；")
      : curIsMain && frameState(shot, d, stage) === "stale"
        ? staleOf(shot, d, stage).filter(Boolean).join("；")
        : null
    : null;
  const curStale = staleWhy != null;
  const lockedDone = slot !== "video" && isLocked && !curStale && !cur?.auto && !cur?.bad;

  // ---- 视频审片（UXF2 #7）：与审片行 ⋯ / 片段条同一个接口（PUT /api/shots/{id}/review，store.setReview） ----
  const vidCur = slot === "video" && !!cur?.url && !!shot.video && bare(cur.url) === bare(shot.video);
  const watched = studio.canPass(shot);
  const rv = shot.review.state;
  const nextToReview = (): string | null => {
    const prefix = id.split("-")[0] + "-";
    const ep = studio.shots.filter((s) => s.id.startsWith(prefix));
    const i = ep.findIndex((s) => s.id === id);
    const order = [...ep.slice(i + 1), ...ep.slice(0, Math.max(0, i))];
    return order.find((s) => shotStatus(s, studio).key === "review_video")?.id ?? null;
  };
  const approve = async () => {
    if (slot !== "video" || !cur?.url) return;
    if (!vidCur) return notify(`现在看的是视频 #${cur.n}，不是本镜在用的那版；先在版本条里选回在用的版本再通过`, "err");
    if (!watched) return notify("先把这版视频完整看一遍再通过（拖到结尾也算）", "err");
    const ok = await studio.setReview([id], "passed");
    if (!ok) return;
    const nx = nextToReview();
    if (nx) {
      setShotUi(nx, { slot: "video" });
      studio.select(nx);
      notify(`${id} 已通过 · 下一个待你审：${nx}`);
    } else notify(`${id} 已通过 · 本集没有待你审的视频了`);
  };
  // L-123：A = 用这张（视频 = 用这版）；E = 修改（图 = 打开修改面板，视频 = 改参数 / 换种子面板）
  const useFrame = () => {
    if (slot === "video" || !cur || gate || isLocked) return;
    void setLock(id, slot, cur.n, true, notify, refresh);
  };
  const editIt = () => (slot === "video" ? openVideoParams() : openLoop());
  keyAct.current = {
    approve: () => (slot === "video" ? void approve() : useFrame()),
    edit: () => !gate && editIt(),
    on: !loopOpen && (slot === "video" ? !!cur?.url && vidCur : !!cur && !gate),
  };

  // ---- 尺寸 ----
  // 大格：高 = 可用高度 − 下方条；宽 = 高 × 9:16。首尾对照 4 格并排时整行给大格
  const n = view === "ends" && slot === "video" && cur?.url ? 4 : view === "prev" && prevVid?.url ? 2 : 1;
  const stageH = Math.max(240, top.h - barsH - 8);
  const sideMin = loopOpen ? DOCK_W : 260; // 右侧至少留 260；“修改…”面板打开时留面板的宽
  const maxW = n === 4 ? (top.w - 3 * GAP - 16) / 4 : (top.w - GAP - sideMin - (n - 1) * GAP) / n;
  const cw = Math.max(150, Math.min(stageH * AR, maxW));
  const size = { w: Math.round(cw), h: Math.round(Math.min(stageH, cw / AR)) };
  // XYQ（小云雀走查 #5）：左列最窄 360 → 460（宽屏时）：播放条、审片、操作各占一行，不再折成 4 行，省下的高度全给视频大格
  const actInSide = top.w >= 860 && !loopOpen && !(view === "ends" && slot === "video" && cur?.url);
  const barW = actInSide ? 470 : top.w >= 1100 ? 540 : top.w >= 1000 ? 460 : 360; // 左列最窄（播放条 / 操作按钮可以折行，不再为一行放下而撑出空隙）
  const colW = Math.max(barW, n === 4 ? top.w : size.w * n + (n - 1) * GAP);
  // 右侧：宽时 = 预览两张 + 信息列，版本条在下面横跨；窄时信息排在预览下面
  const sideW = n === 4 ? 0 : top.w - colW - GAP;
  const showSide = sideW >= SIDE_HIDE;
  const wideSide = sideW >= 2 * (size.h * 0.45 * AR) + INFO_W + 2 * GAP;
  const pvH = Math.round(
    Math.min(
      PV_MAX_H,
      Math.max(
        140,
        wideSide ? Math.min(top.h - VER_H - GAP, (sideW - INFO_W - 2 * GAP) / 2 / AR) : Math.min((sideW - GAP) / 2 / AR, top.h - VER_H - 150 - 2 * GAP),
      ),
    ),
  );
  const pvW = Math.round(pvH * AR);

  const regen = () => {
    if (gate) return notify(gate, "err");
    if (slot === "video") void submitVideo(id, { gpu: es.gpu, ...(cur ? { parent: cur.n } : {}) }, notify, refresh);
    else void submitFrame(id, { stage: slot, mode: "regen", gpu: es.gpu }, regenLabel(nm), notify, refresh);
  };
  /** 细条上的“一个动作”：直接出这一格（不切大格） */
  const genSlot = (s: Slot) => {
    const g = gateOf(d, s);
    if (g) return notify(g, "err");
    const c = currentTake(es, d, id, s);
    if (s === "video") void submitVideo(id, { gpu: es.gpu, ...(c ? { parent: c.n } : {}) }, notify, refresh);
    else void submitFrame(id, { stage: s, mode: "regen", gpu: es.gpu }, `出${SLOT_NAME[s]}`, notify, refresh);
  };
  const openLoop = (parent: number | null = cur?.n ?? null) =>
    setEdit(() => ({
      loop: {
        shot: id,
        slot,
        mode: slot === "video" ? "video" : parent != null ? "instruct" : "regen",
        parent,
      },
    }));
  const openVideoParams = () =>
    setEdit(() => ({
      loop: {
        shot: id,
        slot: "video",
        mode: "video",
        parent: currentTake(es, d, id, "video")?.n ?? null,
      },
    }));
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

  const slotToStageX = (x: Slot) => (x === "first" ? "image" : x === "last" ? "last" : "video") as "image" | "last" | "video";
  const menuItems: [string, () => void, boolean][] = [
    [`从这一版继续改${nm}…`, () => openLoop(), !cur || slot === "video"],
    [
      `和上一版${nm}并排对比`,
      () =>
        slot === "video"
          ? setView("prev")
          : cur?.parent != null &&
            setEdit(() => ({
              compare: { shot: id, slot, a: cur.n, b: cur.parent! },
            })),
      slot === "video" ? !prevVid : cur?.parent == null,
    ],
    // 回退补回（regress_r1 #8）：版本 A/B + 提示词差异（绿增红删）在底部抽屉“对比”页，以前没有按钮能打开
    [
      `${nm}版本 A/B + 提示词差异（和上一版）`,
      () => {
        const prevN =
          cur?.parent ??
          takesOf(d, slot)
            .filter((t) => cur && t.n < cur.n)
            .slice(-1)[0]?.n;
        if (cur && prevN != null)
          (studio.setCompare({
            shotId: id,
            stage: slotToStageX(slot),
            a: prevN,
            b: cur.n,
          }),
            studio.setDrawer({ open: true, tab: "compare" }));
      },
      !cur || takesOf(d, slot).length < 2,
    ],
    // 回退补回（regress_r1 #9）：目标尾帧 vs 视频实际尾帧（底部抽屉“接缝对比”，左边是这一镜的目标尾帧与视频末帧）
    [
      "目标尾帧 vs 视频实际尾帧",
      () => {
        const nx = studio.summaryById.get(id)?.next_shot;
        studio.setSeam({ from: id, to: nx ?? id });
        studio.setDrawer({ open: true, tab: "seam" });
      },
      !studio.summaryById.get(id)?.video,
    ],
    ["把这张设为资产参考…", openDrawerFromTake, !cur || slot === "video"],
    [
      "复制这一版的提示词",
      () =>
        void navigator.clipboard?.writeText(cur?.prompt ?? "").then(
          () => notify("已复制"),
          () => notify("复制失败", "err"),
        ),
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
        <div className="mini">
          {g
            ? s === "last"
              ? "尾帧由定稿首帧编辑而来"
              : "首尾帧定稿后这里出视频"
            : s === "video"
              ? "点「出视频」"
              : `点「${regenLabel(SLOT_NAME[s])}」出第一张`}
        </div>
      </div>
    );
  };
  const genOverlay = (j: ReturnType<typeof running>) =>
    j ? (
      <div className="v3e-genov" title={cardTip(j.gpu)}>
        <div className="spin" />
        <div>
          {j.state === "queued" ? "排队中" : "生成中"} · {gpuLabel(j.gpu)}
        </div>
      </div>
    ) : null;

  const vidTools = slot === "video" && cur?.url;

  const others = SLOTS.filter((s) => s !== slot);
  // UXF2 #22：还没有版本、也没在生成的阶段收成细条（写清卡在哪 + 一个动作），不再占 250×450 的黑格
  const isEmpty = (s: Slot) => !takesOf(d, s).length && !running(s);
  const slimBar = (s: Slot) => {
    const g = gateOf(d, s);
    // 卡在哪一格：首帧没定稿 / 过期 → 首帧；否则尾帧
    const lf = lockedTake(d, "first");
    const need: Slot | null = g ? (!lf || isStale(lf) ? "first" : "last") : null;
    return (
      <div key={s} className="v3e-slim" role="group" aria-label={`${SLOT_NAME[s]}还没有`}>
        <span className="ic">{s === "first" ? "◧" : s === "last" ? "◨" : "▶"}</span>
        <span className="tx">
          <b>{SLOT_NAME[s]}</b>：{g ?? `还没有${SLOT_NAME[s]}`}
        </span>
        {g ? (
          need && need !== slot ? (
            <button className="v3e-btn sm" onClick={() => focus(need)}>
              去看{SLOT_NAME[need]}
            </button>
          ) : null
        ) : (
          <button className="v3e-btn sm primary" onClick={() => genSlot(s)} title={`用${gpuLabel(es.gpu)}出${SLOT_NAME[s]}`}>
            出{SLOT_NAME[s]}
          </button>
        )}
      </div>
    );
  };
  const previews = (
    <div className="v3e-previews">
      {others
        .filter((s) => !isEmpty(s))
        .map((s) => {
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
              {u ? <img src={thumb(u, 240) ?? u} alt="" loading="lazy" /> : <div className="v3e-ph sm">{gateOf(d, s) ?? `还没有${SLOT_NAME[s]}`}</div>}
              {s === "video" && u && <span className="v3e-playic">▶</span>}
              {genOverlay(running(s))}
            </Cell>
          );
        })}
    </div>
  );
  const slims = others.some(isEmpty) ? <div className="v3e-slims">{others.filter(isEmpty).map(slimBar)}</div> : null;
  const info = (
    <div className={`v3e-info ${wideSide ? "col" : "row"}`}>
      <RefBar shot={shot} />
      <div className="v3e-cost">
        <label>
          用卡
          <LaneSelect value={es.gpu} onChange={(g) => setEdit(() => ({ gpu: g }))} kind={kind} frames={shot.h3_frames} />
        </label>
        <span
          title={
            eta.n
              ? `按${es.gpu === "auto" ? "自动会用的那张卡" : cardName(es.gpu)}最近 ${eta.n} 次实际耗时（中位数），加上这张卡前面已有的活`
              : "这张卡还没有这类任务的耗时记录，按默认值估（出图约 1 分钟、视频约 14 分钟）"
          }
        >
          {slot === "video" ? "出视频" : `出${nm}`}预计约 {fmtSec(eta.eta)}
          {eta.n ? "" : "（无样本）"}
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
              // UXF4（审查 N3）：坏图在版本条里也标出（与查看器同一来源 take.bad），置灰；自动测试定稿标“自动”
              className={`v3e-cand ${cur?.n === t.n ? "sel" : ""} ${t.locked && t.stage !== "video" && !t.auto ? "locked" : ""} ${t.bad ? "bad" : ""} ${t.auto ? "auto" : ""}`}
              title={`#${t.n}${t.mode ? ` · ${MODE_LABEL[t.mode] ?? t.mode}` : ""}${t.bad ? ` · ${t.bad}（不能定稿、不能设为当前）` : ""}${t.auto ? " · 自动测试定稿，待你复审" : ""}${t.passed ? " · 已通过" : ""}${t.instruction ? `\n${t.instruction}` : ""}`}
              onClick={() => pickTake(id, slot, t.n)}
              onDoubleClick={() => {
                if (slot === "video") {
                  pickTake(id, slot, t.n);
                  setView("prev");
                } else if (t.parent != null)
                  setEdit(() => ({
                    compare: { shot: id, slot, a: t.n, b: t.parent! },
                  }));
              }}
            >
              {takeUrl(t) ? (
                <img src={thumb(takeUrl(t)!, 240) ?? takeUrl(t)!} alt="" loading="lazy" />
              ) : (
                <span className="e">{slot === "video" ? "▶" : "—"}</span>
              )}
              <span className="no">#{t.n}</span>
              {t.parent != null && <span className="par">←{t.parent}</span>}
              {t.bad ? (
                <span className="badmk">坏图</span>
              ) : t.auto ? (
                <span className="automk" title={AUTO_TIP}>
                  {AUTO_SHORT}
                </span>
              ) : (t.stage === "video" ? t.passed : t.locked) ? (
                <span className="lk">✓</span>
              ) : null}
            </button>
          ))
        ) : (
          <span className="none">还没有{nm}</span>
        )}
      </div>
    </div>
  );

  // UX4（项目方：视频太小、布局分布不好）：右侧有位置时，审片 / 定稿 / 改参数这一组按钮挪到右列（首尾帧预览下面），
  // 大格下面只留一行播放条，省下的高度全给视频大格（1600×900：291×521 → 约 340×600）
  const actbar = (
    <div className="v3e-actbar">
      {slot === "video" ? (
        <>
          {cur?.url && (
            <div className="v3e-review" role="group" aria-label="这版视频">
              {rv === "passed" && vidCur ? (
                <>
                  <span className="v3e-rvst ok">已用这版</span>
                  <button className="v3e-btn sm" onClick={() => void studio.setReview([id], "unreviewed")} title="撤销，回到待你审">
                    撤销
                  </button>
                </>
              ) : (
                <>
                  {vidCur && (
                    <button className="v3e-btn ok strong" onClick={() => void approve()} title="用这版视频，跳到下一个待你审的镜头（A）">
                      用这版<kbd>A</kbd>
                    </button>
                  )}
                  {cur.auto && (
                    <span className="v3e-rvst auto" title={AUTO_TIP}>
                      {AUTO_SHORT}
                    </span>
                  )}
                </>
              )}
            </div>
          )}
          {/* L-123：“重新出视频”“改参数重渲”并入“修改”（种子 / 步数 / 时长 / LoRA / 提示词都在面板里）；条件没满足时按钮不出现 */}
          {!gate &&
            (list.length ? (
              <button className="v3e-btn" onClick={openVideoParams} title="改一句话 / 换个种子 / 改参数后重出这条视频（E）">
                修改<kbd>E</kbd>
              </button>
            ) : (
              <button className="v3e-btn primary" onClick={regen}>
                出视频
              </button>
            ))}
        </>
      ) : (
        <>
          <button className="v3e-btn" disabled={!cur} hidden={!!gate} onClick={() => openLoop()} title="改提示词重出 / 指令改图 / 换参考再改 / 局部重绘（E）">
            修改<kbd>E</kbd>
          </button>
          {/* UXF5（审查 R9）：已定稿（没过期）时主按钮是下一步，不是重出；重出降为次按钮并写明后果 */}
          {lockedDone && (
            <button
              className="v3e-btn primary"
              onClick={() => focus(slot === "first" ? "last" : "video")}
              title={slot === "first" ? "首帧已定稿，去出 / 审尾帧" : "尾帧已定稿，去出 / 审视频"}
            >
              {slot === "first" ? "去看尾帧 →" : "去看视频 →"}
            </button>
          )}
          <button
            className={`v3e-btn${lockedDone ? "" : " primary"}`}
            disabled={!!gate}
            onClick={regen}
            title={
              curStale
                ? `${staleLong(nm)}：${staleWhy || "上游改过"}`
                : lockedDone
                  ? `已定稿；重出会让${slot === "first" ? "尾帧和视频" : "视频"}过期`
                  : (gate ?? undefined)
            }
          >
            {regenLabel(nm)}
          </button>
          {cur && curStale ? (
            <span className="v3e-gate" title={staleWhy || undefined}>
              #{cur.n} {staleLong(nm)}
              {staleWhy ? `（${staleWhy}）` : ""}，点“{regenLabel(nm)}”
            </span>
          ) : cur && cur.bad ? (
            // UXF1 #6：坏图不能定稿（后端也 409），换成红字说明
            <span className="v3e-gate" style={{ color: "var(--c-bad-text)" }} title={cur.bad}>
              #{cur.n} {cur.bad}，不能定稿，点“{regenLabel(nm)}”
            </span>
          ) : cur && cur.auto ? (
            // UXF4（审查 N1）：自动测试定稿 → 项目方复审：确认这一版（后端去掉“自动”标记），或取消定稿
            <>
              <button
                className="v3e-btn ok"
                disabled={!!gate}
                title={`#${cur.n} 是整集出片自动测试定稿的；确认后才算你定稿（进度、整集出片按已定稿算）`}
                onClick={() => void setLock(id, slot, cur.n, true, notify, refresh)}
              >
                确认定稿{nm} #{cur.n}
              </button>
              <button
                className="v3e-btn"
                disabled={!!gate}
                title="取消后，之后的尾帧 / 视频会标过期"
                onClick={() => void setLock(id, slot, cur.n, false, notify, refresh)}
              >
                取消定稿
              </button>
            </>
          ) : cur && isLocked ? (
            <button
              className="v3e-btn"
              disabled={!!gate}
              title="取消后，之后的尾帧 / 视频会标过期"
              onClick={() => void setLock(id, slot, cur.n, false, notify, refresh)}
            >
              取消定稿{nm}
            </button>
          ) : cur && !gate ? (
            // UM-P0-01：待审的这一版给一对明确按钮——✓ 用这张（= 定稿，10 秒撤销）/ ✗ 不要（原因 → 按原因重出或只标记）
            <span title={`用这张 = 定稿${nm}（A）`}>
              <Verdict
                shot={id}
                stage={slot as "first" | "last"}
                n={cur.n}
                size="md"
                auto={(cur as { gen_contract?: { post?: { status?: string } } }).gen_contract?.post?.status === "pass"}
              />
            </span>
          ) : null}
        </>
      )}
      <div className="v3e-more" ref={menuRef}>
        <button ref={menuBtn} className="v3e-btn" onClick={() => setMenu((m) => !m)} aria-label="更多" title="更多">
          ⋯
        </button>
        {menu &&
          createPortal(
            <div
              className="v3e-menu"
              ref={popRef}
              style={
                // 先不可见地按自然尺寸量一次（覆盖 CSS 的 right: 0 / bottom: 42px，否则 fixed 时被拉满整屏）
                menuPos ?? { position: "fixed", visibility: "hidden", top: 0, left: 0, right: "auto", bottom: "auto", width: "max-content" }
              }
            >
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
            </div>,
            document.body,
          )}
      </div>
    </div>
  );
  // UIMASTER（G10 回退 F05 / F09，总调度 11-01 指派）：精修首屏常驻两样——全屏看首尾帧（首帧 | 尾帧并排，←/→ 翻版本）、完整视频提示词（可收起，原文只读）
  const h3Full = shot.h3_prompt ?? d?.compiled?.video_prompt ?? "";
  const negText = (d?.edit?.image_negative ?? d?.compiled?.image_negative ?? "").trim();
  const lockedSeed = slot === "last" ? d?.edit?.last_seed : slot === "video" ? d?.edit?.video_seed : d?.edit?.image_seed;
  const seedText = lockedSeed != null ? `${lockedSeed}（已锁定）` : cur?.seed != null ? `${cur.seed}（这一版，随机）` : "随机";
  const quick = (
    <div className="v3e-quick">
      <button className="v3e-btn sm" disabled={!shot.first_frame} title={shot.first_frame ? "全屏看首帧 | 尾帧并排（←/→ 翻版本，Esc 关）" : "还没有首帧"} onClick={() => studio.openViewer(id, "image", "pair")}>
        ⛶ 全屏看首尾帧
      </button>
      {/* F11：负面词 · 种子在首屏能看到（改在右栏「参数」） */}
      <div className="v3e-ro v3e-negseed" title={negText ? `负面词（${d?.edit?.image_negative != null ? "本镜改过" : "编译结果"}）：${negText}` : "没有负面词"}>
        <b>负面词</b> {negText ? (negText.length > 60 ? negText.slice(0, 60) + "…" : negText) : "—"}
        <span className="sep"> · </span>
        <b>种子</b> {seedText}
      </div>
      <details className="v3e-fold v3e-h3full">
        <summary>视频提示词（完整）{h3Full ? "" : " · 还没有"}</summary>
        {h3Full ? <pre className="v3e-ro v3e-pre">{h3Full}</pre> : <div className="v3e-ro">这一镜还没有视频提示词（剧本导入后自动生成）</div>}
      </details>
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
            onWatched={() => vidCur && shot.video && studio.markWatched(shot.video)}
            shot={id}
            onChanged={() => void refresh([id])}
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

            {(!actInSide || !showSide) && actbar}
            {(!showSide || loopOpen) && quick}
          </div>
        </div>

        {loopOpen ? (
          <EditLoop shot={shot} />
        ) : (
          showSide && (
            <aside className={`v3e-side ${wideSide ? "wide" : "stack"}`}>
              {wideSide ? (
                <>
                  {quick}
                  <div className="v3e-sidetop">
                    <div className="v3e-pvcol">
                      {previews}
                      {slims}
                    </div>
                    {info}
                  </div>
                  {actInSide && <div className="v3e-sideact">{actbar}</div>}
                  {versions}
                </>
              ) : (
                <>
                  {quick}
                  {previews}
                  {slims}
                  {actInSide && <div className="v3e-sideact">{actbar}</div>}
                  {versions}
                  {info}
                </>
              )}
            </aside>
          )
        )}
      </div>

      {es.compare?.shot === id && <CompareModal shot={shot} />}
      {es.drawer?.shot === id && <AssetDrawer shot={shot} open={es.drawer} onClose={() => setEdit(() => ({ drawer: null }))} />}
    </div>
  );
}

export default EditCenter;
