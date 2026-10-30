// fredw-92/W4a：v3 顶栏 = 集切换｜步骤条 ①–⑤｜GPU · 队列｜工具▾｜主题｜?（规格 §1：四个下拉收进“工具”）
import { useEffect, useState } from "react";
import { api, qwenApi } from "../api";
import { GpuButton } from "../components/GpuPanel";
import { useStudio, type View } from "../store";
import { ThemeToggle } from "../themeMode";
import { useEdit } from "./edit/state";
import type { EpisodeLooks, RenderBackend, SopStage } from "../types";
import { framesLocked } from "./status";
import { FILTER_LABEL, type Filter } from "../util";
import { useSop } from "./sop";
import { Pop } from "./widgets";
import { sbUi } from "./StoryboardDetails";
import { ProduceButton } from "./EpisodeProduce"; // fredw-92/EB 整集出片

/** 新页面路由（W4c 的页面挂在 #/…） */
export const V3_PAGES = ["#/script-create", "#/models", "#/assets"] as const;
export type V3Page = (typeof V3_PAGES)[number];
export const pageOf = (hash: string): V3Page | null => V3_PAGES.find((p) => hash === p || hash.startsWith(`${p}/`) || hash.startsWith(`${p}?`)) ?? null;

type Target = View | "#/projects" | "#/script-chat" | V3Page | "canvas" | "classic" | "table" | "storyboard" | "jobs" | "play" | "help";
const TOOLS: { group: string; items: [Target, string, string][] }[] = [
  {
    group: "剧本",
    items: [
      ["#/script-create", "剧本创作", "提纲 → 写作模型写剧本与分镜 → 校验 → 送导入"],
      ["import", "剧本导入", "粘贴或上传剧本、校验格式、确认导入"],
      ["ab", "剧本 A/B 对比", "两版剧本并排对照"],
      ["#/script-chat", "剧本对话（旧）", "原剧本创作对话框"],
    ],
  },
  {
    group: "资产与配置",
    items: [
      ["#/assets", "资产页", "角色卡、形象、服装 / 鞋 / 妆 / 甲 / 发、按集排期"],
      ["assets", "角色卡（旧）", "造型 A/B/C、单品、出图"],
      ["people", "人物管理", "新建人物、上传参考图"],
      ["#/models", "模型与 API", "写作模型、出图 / 视频节点、连通测试"],
    ],
  },
  {
    group: "查看",
    items: [
      ["canvas", "分镜画布（审片 / 精修）", "一镜一行；L / Enter / 双击进精修"],
      ["table", "表格视图", "全部镜头一张表（T）"],
      ["storyboard", "分镜表", "本集一镜一行、全部分镜字段（画面 / 动作 / 声音 / 配乐 / 时长 / H3），缺的标红，可导出 CSV"],
      ["classic", "旧版镜头行 + 检查器", "原画布：H3 机检、请 gpu3 重出、版本、导演加强、配乐"],
      ["play", "串播审片", "按顺序播放本集视频（R）"],
      ["overview", "全部集总览", "所有集的进度网格（1）"],
      ["nodes", "节点画布", "按需加载的节点画布"],
    ],
  },
  {
    group: "运行",
    items: [
      ["jobs", "任务队列", "排队 / 运行 / 失败的生成任务"],
      ["#/projects", "项目 · 新建剧", "项目 / 新建剧 / 待办 / 进度看板"],
      ["help", "快捷键", "全部快捷键（?）"],
    ],
  },
];

const STEPS: { id: SopStage; label: string; to: Target }[] = [
  { id: "S1", label: "剧本", to: "#/script-create" },
  { id: "S2", label: "角色·场景", to: "#/assets" },
  { id: "S3", label: "分镜（首尾帧）", to: "canvas" },
  { id: "S4", label: "视频", to: "canvas" },
  { id: "S5", label: "成片", to: "overview" },
];

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
    poll();
    const t = window.setInterval(poll, 15000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  // F2：连 v1 任务（frame-jobs / video-jobs / 资产生成）一起算，否则出视频时顶栏仍显示“队列空”
  const v1 = useEdit().jobs.filter((j) => !j.notReady);
  const running = jobs.filter((j) => j.state === "running").length + v1.filter((j) => j.state === "running").length;
  const queued = jobs.filter((j) => j.state === "queued").length + v1.filter((j) => j.state === "queued").length;
  const failed = jobs.filter((j) => j.state === "failed").length;
  const offline = backend != null && !backend.reachable;
  const qCls = failed || offline ? "bad" : running || queued ? "busy" : "ok";
  const qText = running || queued ? `生成中 ${running} · 排队 ${queued}` : offline ? "出图未连上" : "队列空";

  const leavePage = () => {
    if (location.hash.startsWith("#/")) location.hash = `#${st.sel ?? `ep${String(epNum).padStart(2, "0")}`}`;
  };
  const go = (to: Target) => {
    if (to.startsWith("#/")) {
      location.hash = to;
      return;
    }
    switch (to) {
      case "canvas":
        st.setClassic(false);
        st.setListMode(false);
        setView("episode");
        return leavePage();
      case "classic":
        st.setClassic(true);
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
    page ? to === page : to === "canvas" ? view === "episode" && !st.classic && !st.listMode : to === "classic" ? view === "episode" && st.classic : to === "table" ? view === "episode" && !st.classic && st.listMode : to === view;

  // 步骤条状态：某步之前（含）没有停留的镜头 = 完成
  // v3.1 §4.2：副文字全部来自真实数据——造型看本集造型确认（/api/looks/episodes/N 的 owner_confirmed_at），
  // 首尾帧“已定”与片段条统计同一判定（status.framesLocked）
  const shots = episode && !episode.light ? episode.shots : [];
  const n = shots.length;
  const both = shots.filter((s) => framesLocked(s, st.details[s.id])).length;
  const vids = shots.filter((s) => s.video).length;
  const looks = useEpisodeLooks(epNum);
  const lookChars = looks ? Object.values(looks.characters) : [];
  const lookOk = lookChars.filter((c) => !!(c.plan as { owner_confirmed_at?: string | null } | null)?.owner_confirmed_at).length;
  const s2 = !looks || !lookChars.length ? (sop && !sop.counts.S2 ? "就绪" : "") : lookOk === lookChars.length ? "造型已确认" : `造型待确认 ${lookChars.length - lookOk}`;
  const sub: Record<SopStage, string> = {
    S1: !sop ? "" : sop.counts.S1 ? `${sop.counts.S1} 镜待补` : "已验收",
    S2: s2,
    S3: n ? `已定 ${both}/${n}` : "",
    S4: n ? `${vids}/${n}` : "",
    S5: sop?.stage === "done" ? "可合成" : "未合成",
  };
  const order: SopStage[] = ["S1", "S2", "S3", "S4", "S5"];
  const doneUpTo = (i: number) => !!sop && sop.total > 0 && order.slice(0, i + 1).every((k) => !sop.counts[k]);
  const cur = sop?.stage === "done" ? null : sop?.stage ?? null;
  const onCanvas = !page && view === "episode";

  return (
    <header className="v3-top">
      <b className="v3-brand">
        NS · 分集编辑器
      </b>
      <div className="v3-ep">
        <button className="v3-icon" onClick={() => gotoEpisode(epNum - 1)} disabled={epNum <= 1} title="上一集（↑）">
          ‹
        </button>
        <button className="v3-ep-name" onClick={() => setPaletteOpen(true)} title={`跳转到某集（G / Ctrl+K）· 共 ${total} 集`}>
          第 {epNum} 集{ep ? ` · ${ep.title}` : ""}
        </button>
        <button className="v3-icon" onClick={() => gotoEpisode(epNum + 1)} disabled={epNum >= total} title="下一集（↓）">
          ›
        </button>
      </div>
      {onCanvas && <ProduceButton ep={epNum} />}
      <span className="v3-grow" />
      <ol className="v3-steps" aria-label="本集制作步骤">
        {STEPS.map((s, i) => {
          const done = doneUpTo(i);
          const here = page ? s.to === page : onCanvas ? s.id === "S3" : view === "overview" ? s.id === "S5" : false; // 当前所在的页面
          return (
            <li key={s.id}>
              <button className={`v3-step${done ? " done" : ""}${here ? " on" : ""}${cur === s.id ? " cur" : ""}`} onClick={() => go(s.to)} title={`${s.label}${cur === s.id ? "（本集停在这一步）" : ""}`}>
                <i>{done ? "✓" : i + 1}</i>
                <span>{s.label}</span>
                {sub[s.id] && <small>{sub[s.id]}</small>}
              </button>
            </li>
          );
        })}
      </ol>
      <span className="v3-grow" />
      <GpuButton labels="cards" className="v3-gpu" />
      <button className={`v3-queue q-${qCls}`} onClick={() => go("jobs")} title={[offline ? `${backend!.url} 连不上：${backend!.error ?? ""}` : "", failed ? `失败 ${failed}` : "", "点击打开任务队列"].filter(Boolean).join("\n")}>
        <i />
        {qText}
        {failed ? ` · 失败 ${failed}` : ""}
      </button>
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
      <ThemeToggle />
      <button className="v3-icon" onClick={() => setHelpOpen(true)} title="快捷键（?）">
        ?
      </button>
    </header>
  );
}
