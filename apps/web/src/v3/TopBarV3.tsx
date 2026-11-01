// fredw-92/W4a：v3 顶栏 = 集切换｜步骤条 ①–⑤｜GPU · 队列｜工具▾｜主题｜?（规格 §1：四个下拉收进“工具”）
import { useMe } from "../projects/AuthGate.helpers";
import { AuditDrawer } from "./AuditDrawer";
import { useEffect, useState, type ReactNode } from "react";
import { api, qwenApi } from "../api";
import { GpuButton } from "../components/GpuPanel";
import { RenderTasksButton } from "../components/RenderTasks";
import { useStudio, type View } from "../store";
import { ThemeToggle } from "../themeMode";
import { useTheme } from "../themeMode.helpers";
import { useEdit } from "./edit/state";
import type { EpisodeLooks, RenderBackend, SopStage } from "../types";
import { framesLocked, scriptGaps, videoCounts } from "./status";
import { FILTER_LABEL, isInterrupted, type Filter } from "../util";
import { useSop } from "./sop.helpers";
import { Pop } from "./widgets";
import { loadReadiness } from "./Materials.helpers";
import { openMaterials } from "./MaterialsDrawer.helpers";
import { sbUi } from "./StoryboardDetails.helpers";
import type { V3Page } from "./TopBarV3.helpers";
import { LiveIndicator } from "./LiveBridge";
import { InfraChip } from "./InfraStatus";
import { useInfra } from "./InfraStatus.helpers";
import { ProduceButton } from "./EpisodeProduce"; // fredw-92/EB 整集出片
import { useProduceView } from "./EpisodeProduce.helpers";
import { Brand } from "../ds/Brand"; // momoso 标识（项目方挑定候选 2 · 双环）

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
const STEPS: { id: SopStage; label: string; to: Target; hint: string }[] = [
  { id: "S1", label: "剧本", to: "materials", hint: "打开本集资料清单" },
  { id: "S2", label: "资产", to: "#/assets", hint: "资产中心：本集造型确认在最上面" },
  { id: "S3", label: "出图", to: "canvas", hint: "画布：首帧 / 尾帧" },
  { id: "S4", label: "视频", to: "canvas-video", hint: "画布：只看待审的镜头" },
  { id: "S5", label: "成片", to: "#/cut", hint: "成片页：播放、对比、合成" },
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

export function TopBarV3({ page }: { page: V3Page | null }) {
  const st = useStudio();
  const { episodes, epNum, gotoEpisode, view, setView, jobs, drawer, setDrawer, setHelpOpen, setPaletteOpen, episode, filter, setFilter } = st;
  const { sop } = useSop();
  const total = episodes?.length ?? 60;
  const ep = episodes?.find((e) => e.number === epNum);

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
  const failed = unresolved.length - interrupted;
  const offline = backend != null && !backend.reachable;
  const qCls = failed || offline ? "bad" : running || queued ? "busy" : "ok";
  // UXF1：整集出片进度与队列合成一个胶囊（整集进度条只在“整集出片”弹窗和片段条的进度点里看）
  const prod = useProduceView(epNum);
  const prodOn = prod?.state === "running" || prod?.state === "waiting";
  const pc = prod?.counts ?? {};
  const pDone = (pc.done ?? 0) + (pc.skipped ?? 0);
  const pTotal = Object.values(pc).reduce((a, b) => a + b, 0);
  const etaMin = prod?.eta_s ? Math.max(1, Math.round(prod.eta_s / 60)) : null;
  const infraOn = !!useInfra().data; // r39：顶栏连接胶囊有数据时，“出图未连上”不在按钮尾巴重复
  const qText = prodOn
    ? `整集 ${pDone}/${pTotal}${etaMin ? ` · 约 ${etaMin} 分钟` : ""}`
    : running || queued
      ? `生成中 ${running} · 排队 ${queued}`
      : offline
        ? "出图未连上"
        : "队列空";
  const [themeMode, toggleTheme] = useTheme();
  const { me, logout } = useMe();
  const [auditOpen, setAuditOpen] = useState(false);

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
        setFilter("unreviewed");
        return leavePage();
      case "canvas":
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
  const loading: Record<SopStage, boolean> = { S1: !sop || !gaps, S2: !looks, S3: !n, S4: !n, S5: !sop };
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
  const order: SopStage[] = ["S1", "S2", "S3", "S4", "S5"];
  const doneUpTo = (i: number) => !!sop && sop.total > 0 && order.slice(0, i + 1).every((k) => !sop.counts[k]);
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
      <div className="v3-ep">
        <button className="v3-icon" onClick={() => gotoEpisode(epNum - 1)} disabled={epNum <= 1} title="上一集（[ 或 PgUp）">
          ‹
        </button>
        <EpisodePicker label={<>第 {epNum} 集{ep ? ` · ${ep.title}` : ""} ▾</>} total={total} onSearch={() => setPaletteOpen(true)} />
        <button className="v3-icon" onClick={() => gotoEpisode(epNum + 1)} disabled={epNum >= total} title="下一集（] 或 PgDn）">
          ›
        </button>
      </div>
      {onCanvas && <ProduceButton ep={epNum} />}
      </div>
      <ol className="v3-steps" aria-label="本集制作步骤">
        {STEPS.map((s, i) => {
          const done = doneUpTo(i);
          const here = page ? s.to === page : onCanvas ? (filter === "unreviewed" ? s.id === "S4" : s.id === "S3") : false; // 当前所在的页面
          return (
            <li key={s.id}>
              <button className={`v3-step${done ? " done" : ""}${here ? " on" : ""}${cur === s.id ? " cur" : ""}`} onClick={() => go(s.to)} title={`${i + 1} ${s.label}${sub[s.id] ? ` · ${sub[s.id]}` : ""}
点击：${s.hint}${s.id === "S5" && dlgSrc ? `
成片对白：${dlgSrc.label}（${dlgSrc.hint}）` : ""}${s.id === "S4" && n ? `
有视频 ${vids} · 待你审 ${Math.max(0, vids - passed)} · 生成中 ${vidRunning}` : ""}${cur === s.id ? "（本集停在这一步）" : ""}`}>
                <i>{done ? "✓" : i + 1}</i>
                <span>{s.label}</span>
                {sub[s.id] ? <small>{sub[s.id]}</small> : loading[s.id] ? <small className="sk" aria-hidden="true" /> : <small className="none" aria-hidden="true" />}
              </button>
            </li>
          );
        })}
      </ol>
      <div className="v3-top-r">
      <LiveIndicator />
      {/* UIRSI r38（项目方 22:1x：“uiux加个实时连接状态”）：跳板 / 6 条连接 / 服务器常驻 / 本机 / 自动重连，一个胶囊点开看 */}
      <InfraChip />
      <GpuButton labels="short" className="v3-gpu" />
      {/* GPUVIEW 11-01（项目方：“顶部我需要一个rendering任务tasks…”）：原“● 生成中 · 排队 · 失败”胶囊换成“渲染任务”中心
          （全系统：各 agent 的 ComfyUI 任务 + 画布任务 + 写作 + 计划中的镜头）；原胶囊的整集进度 / 出图未连上 / 中断写在按钮尾巴和悬停里，
          原任务队列页从抽屉头部“任务队列页”进入（G10 不删功能） */}
      <RenderTasksButton
        className={`v3-queue q-${prodOn && qCls === "ok" ? "busy" : qCls}`}
        onOpenJobsPage={() => go("jobs")}
        alert={offline}
        extraTitle={[prodOn ? `整集出片进行中：${pDone}/${pTotal} 步完成；画布队列 生成中 ${running} · 排队 ${queued}` : "", offline ? `${backend!.url} 连不上：${backend!.error ?? ""}` : "", interrupted ? `中断 ${interrupted}：API 重启时打断，不是画面问题，可重试` : ""].filter(Boolean).join("\n")}
        extra={
          <>
            {/* UIRSI r39：“出图未连上”和顶栏连接胶囊重复，有连接状态时只留在悬停提示里（整集出片进度照常显示） */}
            {prodOn || (offline && !infraOn) ? <span className="v3-q-int"> · {qText}</span> : null}
          </>
        }
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

function EpisodePicker({ label, total, onSearch }: { label: ReactNode; total: number; onSearch: () => void }) {
  const { episodes, epNum, gotoEpisode } = useStudio();
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
