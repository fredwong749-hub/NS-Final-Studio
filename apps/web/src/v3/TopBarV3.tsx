// fredw-92/W4a：v3 顶栏 = 集切换｜步骤条 ①–⑤｜GPU · 队列｜工具▾｜主题｜?（规格 §1：四个下拉收进“工具”）
import { useMe } from "../projects/AuthGate.helpers";
import { AuditDrawer } from "./AuditDrawer";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, qwenApi } from "../api";
import { useStudio, type View } from "../store";
import { ThemeToggle } from "../themeMode";
import { useTheme } from "../themeMode.helpers";
import { useEdit } from "./edit/state";
import type { EpisodeLooks, RenderBackend, SopStage } from "../types";
import { framesLocked, scriptGaps, videoCounts } from "./status";
import { FILTER_LABEL, isInterrupted, type Filter } from "../util";
import { useSop } from "./sop.helpers";
import { fmtEta, pickDot, useEpisodePreviews, useFramesCounts, useVideosSummary, type NavDot } from "./NavTabs.helpers";
import "./navia.css";
import { Pop } from "./widgets";
import { loadReadiness } from "./Materials.helpers";
import { openMaterials } from "./MaterialsDrawer.helpers";
import { sbUi } from "./StoryboardDetails.helpers";
import type { V3Page } from "./TopBarV3.helpers";
import { ProduceButton } from "./EpisodeProduce"; // fredw-92/EB 整集出片
import { useProduceView } from "./EpisodeProduce.helpers";
import { Brand } from "../ds/Brand";
// momoso 标识（项目方挑定候选 2 · 双环）
import { setFbDrawer } from "./feedback";
import { SystemStatusButton, SystemStatusHidden } from "./SystemStatus"; // UIFIX-S：顶栏右侧只放“待你看”和“系统状态”
import { queueFailText, useOwnerQueue } from "./ownerQueue"; // UIRSI2 L-116 待你看队列
import { FeedbackToggle } from "./FeedbackLayer"; // UIRSI2 反馈模式（后端 FEEDBACK）

/** 新页面路由（W4c 的页面挂在 #/…） */

type Target = View | "#/projects" | "#/script-chat" | V3Page | `#/${string}` | "canvas" | "canvas-video" | "materials" | "classic" | "table" | "storyboard" | "jobs" | "play" | "help";
const TOOLS: { group: string; items: [Target, string, string][] }[] = [
  {
    group: "剧本",
    items: [
      // UIRSI：新建剧本 = 故事提纲 → 写作链 P1–P4 自动写 → 每段可看可改 → 送导入（你确认）
      ["#/script-create?new=1", "新建剧本", "① 故事提纲 → 自动写故事线 · 大纲 · 剧本 · 分镜 → 送导入（你确认）"],
      ["#/script-chat", "写作对话", "和写作模型对话写剧本：新对话 / 继续下一集 / 按校验返修"],
      ["#/script-ab", "剧本 A/B 对比", "两份剧本（或同一提纲两个模型）逐镜并排：首帧 / 尾帧 / 视频 / 提示词，选 A / 选 B，整集连播"],
      ["#/script-create?tab=import", "剧本导入", "② 候选稿 / 粘贴 / 上传 → 校验 → 你确认后导入"],
      ["materials", "本集资料清单", "缺什么、谁来补、补完没有"],
    ],
  },
  {
    group: "资产与设置",
    items: [
      ["#/assets", "资产中心", "角色 · 形象 · 衣橱 · 道具 · 场景 · 风格 · 音色 · 提示词模板；版本、反查、影响面与重出"],
      ["#/assets?type=people", "新建人物 · 上传参考照片", "资产中心 · 人物登记"],
      ["#/sound", "声音", "人物音色 · 旁白 · 每镜台词逐句听 · 整集配乐（波形 + 按镜头跳）"],
      ["#/settings", "项目设置", "风格、写实强度、负面词、配乐处理、成人判定等：当前值、来源，能改的直接改（可撤销）"],
      ["#/models", "模型与 API", "写作模型、出图 / 视频节点、连通测试"],
    ],
  },
  {
    group: "查看",
    items: [
      ["#/v1-library", "Version 1 视频库（只读）", "第一版冻结后的视频，只能看，不会进入 Version 2"],
      ["#/overview", "全剧总览", "10 集 × 每一镜：首尾帧 / 视频 / 通过进度，镜与镜、集与集怎么接（1）"],
      ["canvas", "画布（审片 / 精修）", "一镜一行；L / Enter / 双击进精修"],
      ["play", "串播审片", "按顺序播放本集视频（R）"],
      ["table", "表格视图", "全部镜头一张表（T）"],
      ["storyboard", "分镜表", "本集剧本分镜字段一镜一行，缺的标红，可导出 CSV"],
      ["#/cut", "成片", "本集成片版本、播放、对比、合成、交付确认（5）"],
    ],
  },
  {
    group: "运行",
    items: [
      ["jobs", "任务队列", "排队 / 运行 / 失败的生成任务"],
      ["#/trash", "回收站", "删掉的东西都在这里，可以找回"],
      ["help", "快捷键", "全部快捷键（?）"],
    ],
  },
];

// UXF5（审查 R6）：术语统一；“分镜”只指剧本里的分镜字段
// UX5（D2）：每一步点进去 = 这一步该做的事——① 本集资料清单（缺什么、谁补）；② 资产中心；③ 画布（首尾帧）；
// ④ 画布 + 只看待审；⑤ 成片页（以前 ① 去写新剧本、③④ 同一处、⑤ 去旧总览）
type TabId = SopStage | "OV" | "SB";
// NAVIA：七个一级入口，同一层级同一种样式，按工作流排：总览（全剧）→ 剧本 → 资产 → 分镜（每集一镜一行）→ 出图 → 视频 → 成片
const STEPS: { id: TabId; label: string; to: Target; hint: string }[] = [
  { id: "OV", label: "总览", to: "#/overview", hint: "全剧胶片总览：每集每镜一格（1）" },
  { id: "S1", label: "剧本", to: "#/script-create", hint: "剧本库：全部剧本与每集" },
  { id: "S2", label: "资产", to: "#/assets", hint: "资产中心" },
  { id: "SB", label: "分镜", to: "canvas", hint: "每集一镜一行的画布（默认上次看的集，页内范围条切集）" },
  { id: "S3", label: "出图", to: "#/frames", hint: "出图：全部集每镜的首帧 / 尾帧（画布在“查看”菜单里）" },
  { id: "S4", label: "视频", to: "#/videos", hint: "全部镜头的视频" },
  { id: "S5", label: "成片", to: "#/cut", hint: "每集整集预览与成片版本" },
];

/** UX5：本集资料不全的镜头数（和审片行角标同一个接口），60 s 刷新 */
function useReadyCount(n: number): { bad: number; total: number } | null {
  const [v, setV] = useState<{ bad: number; total: number } | null>(null);
  useEffect(() => {
    let alive = true;
    setV(null);
    const load = () =>
      loadReadiness(n, true).then((d) => alive && setV(d ? { bad: d.shots.filter((x) => x.missing.length).length, total: d.shots.length } : null));
    const first = window.setTimeout(load, 1200); // UIRSI r19：步骤条副文字不抢首屏
    const t = window.setInterval(load, 60000);
    return () => {
      alive = false;
      window.clearTimeout(first);
      window.clearInterval(t);
    };
  }, [n]);
  return v;
}

/** UX5：本集成片版本数 + 最新一版落后几镜（GET /api/episodes/{n}/cuts；没上线 → null） */
function useCutsCount(n: number): { n: number; behind: number } | null {
  const [v, setV] = useState<{ n: number; behind: number } | null>(null);
  useEffect(() => {
    let alive = true;
    setV(null);
    new Promise((r) => setTimeout(r, 1300)) // UIRSI r19：步骤条副文字不抢首屏
      .then(() => fetch(`/api/episodes/${n}/cuts`))
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { cuts?: { tags: string[]; changed: unknown[] }[] } | null) => {
        if (!alive || !d?.cuts) return;
        const ok = d.cuts.filter((c) => !c.tags.includes("勿用"));
        setV({ n: d.cuts.length, behind: ok[0]?.changed.length ?? 0 });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [n]);
  return v;
}

/** 本集造型确认情况（步骤条②副文字用）；换集重取，60 s 刷新 */
function useEpisodeLooks(n: number): EpisodeLooks | null {
  const [v, setV] = useState<EpisodeLooks | null>(null);
  useEffect(() => {
    let alive = true;
    setV(null);
    const load = () => api.looks.episode(n).then((d) => alive && setV(d), () => undefined);
    void load();
    const t = window.setInterval(load, 60000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [n]);
  return v;
}

/** UX4：成片对白用哪种声音（GET /api/post/dialogue-source，只读 config）；接口没上线（API 未重启）就不显示 */
function useDialogueSource(n: number): { label: string; hint: string } | null {
  const [v, setV] = useState<{ label: string; hint: string } | null>(null);
  useEffect(() => {
    let alive = true;
    // UIRSI r12（W-02）：只用于悬停说明，晚 2.5 s 再取
    new Promise((r) => setTimeout(r, 2500))
      .then(() => fetch(`/api/post/dialogue-source?ep=${n}`))
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => alive && setV(d && d.label ? { label: d.label, hint: d.hint ?? "" } : null))
      .catch(() => alive && setV(null));
    return () => {
      alive = false;
    };
  }, [n]);
  return v;
}

// UIAUDIT F26（UIRSI r43）：恢复“立即推进一步”入口（git 0a91a20 删了按钮，后端 POST /api/projects/{slug}/production/tick 仍在；
// 旧 BoardView 的 papi.tick(slug)，标题“立即推进一步（后台每 20 秒自动推进）”）。点一下即生效，不让打字；slug 取默认项目。
async function tickProduction(notify: (m: string, k?: "ok" | "err") => void) {
  try {
    const ps = (await fetch("/api/projects").then((r) => r.json())) as { slug: string; is_default?: boolean }[];
    const slug = (ps.find((p) => p.is_default) ?? ps[0])?.slug;
    if (!slug) return notify("没有找到项目，没法推进", "err");
    const r = await fetch(`/api/projects/${encodeURIComponent(slug)}/production/tick`, { method: "POST" });
    if (!r.ok) return notify(`推进失败（${r.status}）`, "err");
    notify("已推进一步（后台本来每 20 秒也会自动推进）");
  } catch (e) {
    notify(`推进失败：${(e as Error).message}`, "err");
  }
}

/** UIRSI2 L-116：顶栏常驻“待你看 ● N”——有必须拍板的事 = 琥珀点，其余 = 灰点；队列读取失败 = 琥珀点 + “!”（不显示成 0）。点开 = #/queue 阵列页 */
function OwnerQueueButton({ on }: { on: boolean }) {
  const { q, err } = useOwnerQueue();
  const fail = queueFailText(q, err);
  const n = q?.count ?? 0;
  const amber = !!fail || (q?.counts.decide ?? 0) > 0;
  const title = fail
    ? fail
    : q
      ? `待你看 ${n} 项：必须你拍板 ${q.counts.decide} · 机签抽检 ${q.counts.spot} · 审美挑选 ${q.counts.pick}
今天系统自动处理 ${q.auto_today.total} 项，不进队列`
      : "正在读待你看队列";
  return (
    <button className={`v3-oq${on ? " on" : ""}`} data-oq-count={fail ? "error" : String(n)} onClick={() => (location.hash = "#/queue")} title={title}>
      待你看 <span className={`v3-dot d-${amber ? "yellow" : "gray"}`} aria-hidden /> <b>{fail ? "!" : q ? n : "…"}</b>
    </button>
  );
}

export function TopBarV3({ page }: { page: V3Page | null }) {
  const st = useStudio();
  const { q: oq } = useOwnerQueue();
  const { episodes, epNum, view, setView, jobs, drawer, setDrawer, setHelpOpen, episode, filter, setFilter } = st;
  const { sop } = useSop();
  const total = episodes?.length ?? 60;

  // 出图后端 + 队列（原顶栏逻辑）
  const [backend, setBackend] = useState<RenderBackend | null>(null);
  useEffect(() => {
    let alive = true;
    // F2：后端探测超时只有 1.5 s，隧道忙时偶尔一次不通；连续两次不通才显示“出图未连上”
    let miss = 0;
    const poll = () =>
      qwenApi.renderBackend().then(
        (b) => {
          if (!alive) return;
          miss = b.reachable ? 0 : miss + 1;
          if (b.reachable || miss >= 2) setBackend(b);
        },
        () => alive && setBackend(null),
      );
    const first = window.setTimeout(poll, 1600); // UIRSI r16：出图后端探测（1.5 s 超时）不抢首屏
    const t = window.setInterval(poll, 15000);
    return () => {
      alive = false;
      window.clearTimeout(first);
      window.clearInterval(t);
    };
  }, []);
  // F2：连 v1 任务（frame-jobs / video-jobs / 资产生成）一起算，否则出视频时顶栏仍显示“队列空”
  const v1 = useEdit().jobs.filter((j) => !j.notReady);
  const running = jobs.filter((j) => j.state === "running").length + v1.filter((j) => j.state === "running").length;
  const queued = jobs.filter((j) => j.state === "queued").length + v1.filter((j) => j.state === "queued").length;
  // UXF1（审查 #5）：同镜同阶段后来成功过的旧失败算“已解决”，只数没解决的
  // UXF5（审查 #5 / N10）：API 重启打断的单独算“中断”（灰色，不标红）
  const unresolved = jobs.filter(
    (j) => j.state === "failed" && !jobs.some((k) => k.shot_id === j.shot_id && k.stage === j.stage && k.state === "done" && k.created_at > j.created_at),
  );
  const interrupted = unresolved.filter(isInterrupted).length;
  const offline = backend != null && !backend.reachable;
  // UXF1：整集出片进度与队列合成一个胶囊（整集进度条只在“整集出片”弹窗和片段条的进度点里看）
  const prod = useProduceView(epNum);
  const prodOn = prod?.state === "running" || prod?.state === "waiting";
  const pc = prod?.counts ?? {};
  const pDone = (pc.done ?? 0) + (pc.skipped ?? 0);
  const pTotal = Object.values(pc).reduce((a, b) => a + b, 0);
  const [themeMode, toggleTheme] = useTheme();
  const { me, logout } = useMe();
  const [auditOpen, setAuditOpen] = useState(false);

  const [, setVidTab] = useState(false); // 点了“视频”：即使退到“全部”也要亮在 ④
  // 顶部轻提示条：3 秒自动消失，不用点掉
  const [hint, setHint] = useState("");
  const hintT = useRef(0);
  const showHint = (m: string) => {
    setHint(m);
    window.clearTimeout(hintT.current);
    hintT.current = window.setTimeout(() => setHint(""), 3000);
  };
  useEffect(() => () => window.clearTimeout(hintT.current), []);
  const leavePage = () => {
    if (location.hash.startsWith("#/")) location.hash = `#${st.sel ?? `ep${String(epNum).padStart(2, "0")}`}`;
  };
  const go = (to: Target) => {
    if (to.startsWith("#/")) {
      location.hash = to;
      return;
    }
    switch (to) {
      case "materials":
        return openMaterials();
      case "canvas-video":
        st.setClassic(false);
        st.setListMode(false);
        setView("episode");
        setVidTab(true);
        {
          // NAVIA：没有待审视频时不再整页变灰——退到“全部”，并说明现在是什么情况
          const list = episode && !episode.light ? episode.shots : [];
          const pending = list.filter((x) => x.review?.state === "unreviewed" && !!x.video).length;
          if (pending > 0) setFilter("unreviewed");
          else {
            setFilter("all");
            const run = jobs.filter((j) => j.stage === "video" && (j.state === "running" || j.state === "queued")).length;
            showHint(`现在没有要你看的视频${run ? `，正在出 ${run} 条` : ""}；下面是本集全部镜头（想只看待审，用顶部筛选“待审”）`);
          }
        }
        return leavePage();
      case "canvas":
        setVidTab(false);
        if (filter === "unreviewed") setFilter("all");
        st.setClassic(false);
        st.setListMode(false);
        setView("episode");
        return leavePage();
      case "table":
        st.setClassic(false);
        st.setListMode(true);
        setView("episode");
        return leavePage();
      case "storyboard":
        st.setClassic(false);
        st.setListMode(false);
        setView("episode");
        sbUi.setTable(true);
        return leavePage();
      case "jobs":
        return setDrawer({ open: !(drawer.open && drawer.tab === "jobs"), tab: "jobs" });
      case "play":
        return st.setReviewMode(true);
      case "help":
        return setHelpOpen(true);
      default:
        setView(to as View);
        return leavePage();
    }
  };
  const isOn = (to: Target) =>
    page ? to === page || (to.startsWith("#/") && location.hash === to) : to === "canvas" ? view === "episode" && !st.classic && !st.listMode : to === "classic" ? view === "episode" && st.classic : to === "table" ? view === "episode" && !st.classic && st.listMode : to === view;

  // 步骤条状态：某步之前（含）没有停留的镜头 = 完成
  // v3.1 §4.2：副文字全部来自真实数据——造型看本集造型确认（/api/looks/episodes/N 的 owner_confirmed_at），
  // 首尾帧“已定”与片段条统计同一判定（status.framesLocked）
  const shots = episode && !episode.light ? episode.shots : [];
  const n = shots.length;
  const both = shots.filter((s) => framesLocked(s, st.details[s.id])).length;
  const vids = shots.filter((s) => videoCounts(s, st.details[s.id])).length; // UXF1 #10：链不完整 / 过期的视频不算
  // UX4（审查 R11）：④ 数“已通过”，不数“有视频”（以前 11/11 看起来像视频阶段做完了）；有视频 / 待你审 / 生成中 放悬停
  const passed = shots.filter((s) => s.review?.state === "passed").length;
  const vidRunning = v1.filter((j) => j.slot === "video" && (j.state === "running" || j.state === "queued")).length + jobs.filter((j) => j.stage === "video" && (j.state === "running" || j.state === "queued")).length;
  // UXF1 #4：步骤①与集头“N 镜待补 / 分镜字段齐全”同一份判定
  const gaps = episode && !episode.light ? scriptGaps(episode, st.details, sop) : null;
  const looks = useEpisodeLooks(epNum);
  const ready = useReadyCount(epNum);
  const cuts = useCutsCount(epNum);
  const dlgSrc = useDialogueSource(epNum);
  const lookChars = looks ? Object.values(looks.characters) : [];
  const lookOk = lookChars.filter((c) => !!(c.plan as { owner_confirmed_at?: string | null } | null)?.owner_confirmed_at).length;
  // UXF4（审查 #1）：造型还没读到时不写“就绪”（以前先闪“就绪”再变“造型待确认 3”）
  const s2 = !looks ? "" : !lookChars.length ? (sop && !sop.counts.S2 ? "就绪" : "") : lookOk === lookChars.length ? "造型已确认" : `造型待确认 ${lookChars.length - lookOk}`;
  const sub: Record<SopStage, string> = {
    // UX5（D 口径冲突）：① 和审片行“资料不全 N”用同一份检查（/readiness）；读不到再退回剧本字段统计
    S1: ready ? (ready.bad ? `${ready.bad} 镜还缺资料` : "资料都齐了") : !sop || !gaps ? "" : gaps.size ? `${gaps.size} 镜待补` : "已验收",
    S2: s2, // 设定图挑选在资产中心人物页里（ASSETUX），口径以那里为准，步骤条不再另算
    S3: n ? `首尾帧定了 ${both}/${n}` : "",
    S4: n ? `视频过了 ${passed}/${n}` : "",
    // UX5：⑤ 写真实成片情况（有几版、最新一版落后几镜）；成片接口没上线时退回旧写法
    S5: cuts
      ? cuts.n
        ? `${cuts.n} 版${cuts.behind ? ` · ${cuts.behind} 镜有新视频` : ""}`
        : sop?.stage === "done" ? "可合成" : "还没成片"
      : `${sop?.stage === "done" ? "可合成" : "未合成"}${dlgSrc ? ` · 对白${dlgSrc.label.replace("视频", "")}` : ""}`,
  };
  // NAVIA：五个 tab 的圆点（灰 / 琥珀呼吸 / 琥珀实心 / 绿）；读不到数据 = 灰点，不白板
  const vs = useVideosSummary();
  const fc = useFramesCounts();
  const pv = useEpisodePreviews(episodes?.length ?? 0);
  const dots: Record<TabId, NavDot> = {
    OV: pickDot(false, (vs?.rendering ?? 0) > 0, !vs, "", vs ? `全剧 ${vs.total} 镜 · 视频已定稿 ${vs.final}` : "全剧总览"),
    SB: pickDot(!!gaps?.size, false, !gaps, n ? `${n} 镜` : "", gaps ? (gaps.size ? `本集 ${gaps.size} 镜分镜字段待补` : "本集分镜字段齐全") : "本集分镜"),
    S1: pickDot(!!ready?.bad, false, !ready, `${total} 集`, ready ? (ready.bad ? `${ready.bad} 镜还缺资料` : "资料都齐了") : "还在读"),
    S2: pickDot(lookChars.length > lookOk, false, !looks, lookChars.length > lookOk ? `${lookChars.length - lookOk} 待确认` : "", s2 || "资产中心"),
    S3: fc
      ? pickDot(fc.counts.new + fc.counts.missing > 0, fc.gen.running > 0, fc.gen.queued > 0 || fc.counts.final < fc.counts.shots, `${fc.counts.final}/${fc.counts.shots}`, `首尾帧已定稿 ${fc.counts.final}/${fc.counts.shots}\n待你看 ${fc.counts.new} · 缺图 ${fc.counts.missing} · 出图中 ${fc.gen.running} · 排队 ${fc.gen.queued}`)
      : pickDot(false, false, true, "", "还在读"),
    S4: vs
      ? pickDot(vs.pending_review + vs.need_frames + vs.failed > 0, vs.rendering > 0, vs.queued + vs.todo > 0, `${vs.final}/${vs.total}`, `已定稿 ${vs.final}/${vs.total}\n待你看 ${vs.pending_review} · 缺首尾帧 ${vs.need_frames} · 出视频中 ${vs.rendering} · 排队 ${vs.queued} · 未出 ${vs.todo}${vs.eta_all ? `\n全部预计 ${fmtEta(vs.eta_all)} 出完` : ""}`)
      : pickDot(false, false, true, "", "还在读"),
    S5: pv
      ? pickDot(false, pv.building > 0, pv.have < pv.total || pv.stale > 0, `${pv.have}/${pv.total} 集`, `整集预览 ${pv.have}/${pv.total} 集已拼好${pv.building ? ` · 正在拼 ${pv.building}` : ""}${pv.stale ? ` · ${pv.stale} 集有新镜头，会自动重拼` : ""}`)
      : pickDot(false, false, !cuts?.n, cuts?.n ? `${cuts.n} 版` : "", cuts ? (cuts.n ? `本集 ${cuts.n} 版成片` : "本集还没成片") : "还在读"),
  };
  const cur = sop?.stage === "done" ? null : sop?.stage ?? null;
  const onCanvas = !page && view === "episode";

  // UXF4（审查 #1 / #3）：顶栏三段网格（左：集 + 整集出片｜中：步骤条｜右：卡 · 队列 · 工具），步骤条居中不随两边宽度变；
  // 每步的副文字固定占位（读数据时显示骨架），首屏不再跳
  return (
    <header className="v3-top v3-top-grid">
      <div className="v3-top-l">
      {/* 项目方 2026-10-31：产品名改为 momoso Agentic Drama Studio；窄屏只写 momoso，悬停看全称 */}
      <a className="v3-brand" href={`#ep${String(epNum).padStart(2, "0")}`} title="momoso Agentic Drama Studio · 回到画布">
        <Brand mode="full" size={22} className="v3-brand-full" />
        <Brand mode="word" size={22} className="v3-brand-short" />
      </a>
      {/* UIRSI：新建剧本的入口一直在顶栏（UX5 D2 把步骤①改去资料清单后，这个入口只剩工具菜单里一行，项目方找不到） */}
      <a className={`v3-new${page === "#/script-create" ? " on" : ""}`} href="#/script-create?new=1" title="新建剧本：给故事提纲，写作模型自动写故事线 → 大纲 → 剧本 → 分镜，你确认后导入（N）">
        ＋ 新建剧本
      </a>
      {/* UIRSI B4：声音一级入口（音色 · 旁白 · 对白 · 配乐） */}
      <a className={`v3-new v3-sound${page === "#/sound" ? " on" : ""}`} href={`#/sound?ep=${epNum}`} title="声音：人物音色、旁白、每镜台词逐句听、整集配乐">
        ♪ 声音
      </a>
      </div>
      {hint && (
        <div className="v3-hintstrip" role="status" aria-live="polite" style={{ position: "fixed", top: 54, left: "50%", transform: "translateX(-50%)", zIndex: 70, pointerEvents: "none", background: "var(--bg-3)", border: "1px solid var(--line-2)", borderLeft: "3px solid var(--warn, #e0a030)", padding: "6px 14px", borderRadius: 6, boxShadow: "0 4px 16px rgba(0,0,0,.4)", fontSize: 13 }}>
          {hint}
        </div>
      )}
      <ol className="v3-steps" aria-label="本集制作步骤">
        {STEPS.map((s, i) => {
          const here = page ? s.to === page : onCanvas ? s.id === "SB" : false; // 当前所在的页面
          return (
            <li key={s.id}>
              <button className={`v3-step${here ? " on" : ""}`} onClick={() => go(s.to)} title={`${i + 1} ${s.label}${(sub as Record<string, string>)[s.id] ? ` · ${(sub as Record<string, string>)[s.id]}` : ""}
${dots[s.id].title}
点击：${s.hint}${s.id === "S5" && dlgSrc ? `
成片对白：${dlgSrc.label}（${dlgSrc.hint}）` : ""}${s.id === "S4" && n ? `
有视频 ${vids} · 通过 ${passed} · 生成中 ${vidRunning} · 待你看 ${oq?.count ?? "…"}（顶栏“待你看”）` : ""}${cur === s.id ? "（本集停在这一步）" : ""}`}>
                <i className={`v3-sdot ${dots[s.id].cls}`} aria-hidden="true" />
                <span>{s.label}</span>
                {dots[s.id].text && <small className="v3-step-n">{dots[s.id].text}</small>}
              </button>
            </li>
          );
        })}
      </ol>
      <div className="v3-top-r">
      <OwnerQueueButton on={page === "#/queue"} />
      <FeedbackToggle />
      {/* UIFIX-S：顶栏右侧只放“待你看 N”和“系统状态”；实时 / 连接 / 卡 / 渲染任务 / 悬停出声 都在系统状态面板里（功能不删） */}
      <SystemStatusButton />
      <SystemStatusHidden
        onOpenJobsPage={() => go("jobs")}
        alert={offline}
        extraTitle={[prodOn ? `整集出片进行中：${pDone}/${pTotal} 步完成；画布队列 生成中 ${running} · 排队 ${queued}` : "", offline ? `${backend!.url} 连不上：${backend!.error ?? ""}` : "", interrupted ? `中断 ${interrupted}：API 重启时打断，不是画面问题，可重试` : ""].filter(Boolean).join("\n")}
      />
      <Pop label={<>工具 ▾</>} btnClass="v3-btn" align="right" title="剧本、资产、模型配置、旧视图与运行工具">
        {(close) => (
          <div className="v3-tools">
            {TOOLS.map((g) => (
              <section key={g.group}>
                <h4>{g.group}</h4>
                {g.items.map(([to, label, hint]) => (
                  <button key={to} className={isOn(to) ? "on" : ""} onClick={() => (go(to), close())} title={hint}>
                    <span>{label}</span>
                    <small>{hint}</small>
                  </button>
                ))}
                {g.group === "运行" && (
                  <button data-tool="feedback-list" onClick={() => (setFbDrawer(true), close())} title="你提过的所有反馈：处理进度、被打回的、已修的">
                    <span>反馈列表</span>
                    <small>看每条反馈处理到哪一步</small>
                  </button>
                )}
                {g.group === "运行" && (
                  <button data-tool="tick" onClick={() => (void tickProduction(st.notify), close())} title="立即推进一步（后台每 20 秒自动推进）">
                    <span>立即推进一步</span>
                    <small>不等 20 秒，马上让整集出片往下走一步</small>
                  </button>
                )}
              </section>
            ))}
            {me && (
              <section>
                <h4>账户 · {me.name}</h4>
                <button onClick={() => ((location.hash = "#/audit"), close())}>
                  <span>操作记录</span>
                  <small>你做过的每个选择、导入、定稿，谁 · 什么时候 · 对哪个</small>
                </button>
                <button onClick={() => (logout(), close())}>
                  <span>登出</span>
                  <small>换账户或离开</small>
                </button>
              </section>
            )}
            <section className="v3-tools-narrow">
              <h4>界面</h4>
              <button onClick={() => (toggleTheme(), close())}>
                <span>{themeMode === "dark" ? "切到浅色" : "切到深色"}</span>
                <small>深色 / 浅色主题</small>
              </button>
            </section>
            {onCanvas && (
              <section>
                <h4>过滤镜头</h4>
                <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} title="不匹配的镜头变暗">
                  {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
                    <option key={f} value={f}>
                      {FILTER_LABEL[f]}
                    </option>
                  ))}
                </select>
              </section>
            )}
          </div>
        )}
      </Pop>
      <span className="v3-top-wide">
        <ThemeToggle />
      </span>
      <button className="v3-icon v3-top-wide" onClick={() => setHelpOpen(true)} title="快捷键（?）">
        ?
      </button>
      </div>
      {auditOpen && <AuditDrawer onClose={() => setAuditOpen(false)} />}
    </header>
  );
}

/** UX4（小云雀 #8）：换集下拉——每集一行写进度（首帧 x/n · 视频 x/n · 通过 x/n + 进度条），不用逐集点开找下一集。
 *  数据来自集列表摘要（/api/episodes/summary 的 summary；没有就按轻量镜头字段现数），不额外请求。G / Ctrl+K 仍是搜索跳转。 */
function epProgress(e: { shots: ShotLite[]; summary?: { shots: number; first_frames: number; videos: number; passed: number } }) {
  const sm = e.summary;
  if (sm) return { n: sm.shots, ff: sm.first_frames, vid: sm.videos, pass: sm.passed };
  const sh = e.shots ?? [];
  return { n: sh.length, ff: sh.filter((s) => !!s.first_frame).length, vid: sh.filter((s) => !!s.video).length, pass: sh.filter((s) => s.review?.state === "passed").length };
}
type ShotLite = { first_frame?: unknown; video?: unknown; review?: { state?: string } };

function EpisodePicker({ label, total, onSearch, onPick }: { label: ReactNode; total: number; onSearch: () => void; onPick?: (n: number) => void }) {
  const { episodes, epNum, gotoEpisode: goto0 } = useStudio();
  const gotoEpisode = onPick ?? goto0;
  const [onlyTodo, setOnlyTodo] = useState(false);
  return (
    <Pop label={label} btnClass="v3-ep-name" title={`换集：每集进度一眼看到（G / Ctrl+K 搜索）· 共 ${total} 集`} className="v3-ep-pick">
      {(close) => {
        const rows = (episodes ?? []).map((e) => ({ e, p: epProgress(e as never) }));
        const shown = onlyTodo ? rows.filter(({ p }) => p.n > 0 && p.pass < p.n && (p.ff > 0 || p.vid > 0)) : rows;
        return (
          <div className="v3-eplist">
            <div className="v3-eplist-h">
              <label title="只列已经开始、还没全部通过的集">
                <input type="checkbox" checked={onlyTodo} onChange={(ev) => setOnlyTodo(ev.target.checked)} /> 只看进行中
              </label>
              <button className="v3-btn sm" onClick={() => (close(), onSearch())} title="按集号 / 标题 / 镜头号搜索（G）">
                搜索…
              </button>
              <a className="v3-btn sm" href="#/overview" onClick={() => close()} title="全剧总览：每集每镜一格，看衔接与进度（1）">
                全剧总览
              </a>
            </div>
            <div className="v3-eplist-legend" aria-hidden="true">
              <span>集</span>
              <span>首帧</span>
              <span>视频</span>
              <span>通过</span>
            </div>
            <div className="v3-eplist-scroll">
              {!episodes && <p className="v3-muted small">正在读集列表…</p>}
              {episodes && shown.length === 0 && <p className="v3-muted small">没有进行中的集。取消勾选看全部 {rows.length} 集。</p>}
              {shown.map(({ e, p }) => {
                const pct = (x: number) => (p.n ? Math.round((x / p.n) * 100) : 0);
                const state = !p.n ? "空" : p.pass === p.n ? "全部通过" : p.vid ? "审视频中" : p.ff ? "出图中" : "未开始";
                return (
                  <button
                    key={e.number}
                    className={`v3-eprow${e.number === epNum ? " on" : ""}${p.pass === p.n && p.n ? " done" : ""}`}
                    onClick={() => (close(), gotoEpisode(e.number))}
                    title={`第 ${e.number} 集 · ${e.title}\n${p.n} 镜 · 有首帧 ${p.ff} · 有视频 ${p.vid} · 已通过 ${p.pass}（${state}）`}
                  >
                    <span className="v3-eprow-name">
                      <b>{e.number}</b> {e.title}
                    </span>
                    <span className="v3-eprow-num">
                      {p.ff}/{p.n}
                    </span>
                    <span className="v3-eprow-num">
                      {p.vid}/{p.n}
                    </span>
                    <span className="v3-eprow-num pass">
                      {p.pass}/{p.n}
                    </span>
                    <span className="v3-eprow-bar" aria-hidden="true">
                      <i className="ff" style={{ width: `${pct(p.ff)}%` }} />
                      <i className="vid" style={{ width: `${pct(p.vid)}%` }} />
                      <i className="pass" style={{ width: `${pct(p.pass)}%` }} />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      }}
    </Pop>
  );
}

/** NAVIA：页内范围条（集选择下放到页面；顶栏不再放集号）。出图 / 视频 / 成片 / 画布共用；
 *  视频页多一个“全部集”（hash 的 ep=all）；单集时带“一键出片 · 第 N 集”（原整集出片组件，同一接口）。
 *  出图页（#/frames）有自己的集筛选，不重复放。 */
export function EpisodeScope({ page }: { page: V3Page | null }) {
  const { episodes, epNum, gotoEpisode, setPaletteOpen } = useStudio();
  const total = episodes?.length ?? 60;
  const ep = episodes?.find((e) => e.number === epNum);
  const isVideos = page === "#/videos" || page === "#/frames"; // 出图页、视频页共用：全部集 / 某一集
  const base = page === "#/frames" ? "#/frames" : "#/videos";
  const hashEp = new URLSearchParams(location.hash.split("?")[1] ?? "").get("ep");
  const all = isVideos && (hashEp == null || hashEp === "all");
  const pick = (n: number) => {
    gotoEpisode(n);
    if (isVideos) location.hash = `${base}?ep=${n}`;
  };
  return (
    <div className="v3-scope" role="toolbar" aria-label="集范围">
      <span className="v3-scope-k">范围</span>
      {isVideos && (
        <button className={`v3-scope-chip${all ? " on" : ""}`} onClick={() => (location.hash = `${base}?ep=all`)} title="全部集，按集顺序排">
          全部集
        </button>
      )}
      <button className="v3-icon" onClick={() => pick(epNum - 1)} disabled={epNum <= 1} title="上一集（[ 或 PgUp）">
        ‹
      </button>
      <span className={all ? "v3-scope-off" : ""}>
        <EpisodePicker label={<>第 {epNum} 集{ep ? ` · ${ep.title}` : ""} ▾</>} total={total} onSearch={() => setPaletteOpen(true)} onPick={isVideos ? pick : undefined} />
      </span>
      <button className="v3-icon" onClick={() => pick(epNum + 1)} disabled={epNum >= total} title="下一集（] 或 PgDn）">
        ›
      </button>
      <span className="v3-scope-k">［ ］ 切集</span>
      <span className="sp" />
      {!all && page !== "#/frames" && <ProduceButton ep={epNum} label={`一键出片 · 第 ${epNum} 集`} />}
    </div>
  );
}
