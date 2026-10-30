import { useEffect, useRef, useState, type ReactNode } from "react";
import { qwenApi } from "../api";
import { ThemeToggle } from "../themeMode";
import { GpuButton } from "./GpuPanel"; // GPU 实时面板（fredw-92，独立组件）
import { useStudio, type Density, type View } from "../store";
import type { RenderBackend } from "../types";
import { FILTER_LABEL, type Filter } from "../util";

/** T59 顶栏（干净清晰）：集切换｜主入口 镜头 / 资产▾ / 剧本▾ / 更多▾｜一个出图与队列状态｜审片｜主题｜帮助。
 *  卡片/列表、密度、过滤、检查器收进「视图」菜单（快捷键 T / D / \ 不变）。 */
type Target = View | "#/projects" | "#/script-chat";
type Entry = [Target, string, string];
const ASSETS: Entry[] = [
  ["assets", "角色卡", "造型 A/B/C、单品、出图（4）"],
  ["people", "人物管理", "新建人物、上传参考图"],
];
const SCRIPT: Entry[] = [
  ["import", "输入 / 导入", "粘贴或上传剧本、校验格式、确认导入"],
  ["#/script-chat", "创作", "输入大纲，写作模型按规则写剧本与镜头分镜"],
  ["ab", "A/B 对照", "两版剧本对照"],
];
const MORE: Entry[] = [
  ["overview", "总览", "全部集的进度网格（1）"],
  ["#/projects", "项目 · 新建剧", "项目 / 新建剧 / 待办 / 进度看板"],
  ["nodes", "节点画布", "按需加载的节点画布（次要）"],
];
const DENSITY_LABEL: Record<Density, string> = { compact: "紧凑", standard: "标准", detail: "详细" };

/** 轻量下拉：点外面关闭 */
function Menu({ label, title, children, active }: { label: ReactNode; title?: string; children: (close: () => void) => ReactNode; active?: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("mousedown", off);
    return () => window.removeEventListener("mousedown", off);
  }, [open]);
  return (
    <div className="tb-menu" ref={ref}>
      <button className={`tb-link${active ? " on" : ""}${open ? " open" : ""}`} onClick={() => setOpen((v) => !v)} title={title}>
        {label}
        <i className="tb-caret" />
      </button>
      {open && <div className="tb-pop">{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function TopBar() {
  const {
    episodes, epNum, gotoEpisode, view, setView, filter, setFilter, jobs, drawer, setDrawer, setHelpOpen, setPaletteOpen,
    setReviewMode, density, setDensity, listMode, setListMode, inspectorHidden, setInspectorHidden,
  } = useStudio();
  const running = jobs.filter((j) => j.state === "running").length;
  const queued = jobs.filter((j) => j.state === "queued").length;
  const failed = jobs.filter((j) => j.state === "failed").length;
  const total = episodes?.length ?? 60;
  const ep = episodes?.find((e) => e.number === epNum);
  const [backend, setBackend] = useState<RenderBackend | null>(null);
  useEffect(() => {
    let alive = true;
    const poll = () => qwenApi.renderBackend().then((b) => alive && setBackend(b), () => alive && setBackend(null));
    poll();
    const t = window.setInterval(poll, 15000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);
  const waiting = jobs.some((j) => j.comfy_wait?.who === "offline");
  const offline = backend != null && !backend.reachable;
  const statusCls = failed || offline ? "bad" : running || queued ? "busy" : "ok";
  const statusText = [
    offline ? "本机出图未启动" : "出图",
    running || queued ? `运行 ${running} · 排队 ${queued}` : "队列空",
    failed ? `失败 ${failed}` : "",
  ].filter(Boolean).join(" · ");
  const statusTitle = [
    offline ? `${backend!.url} 连不上：${backend!.error ?? ""}\n出图任务会排队等待，ComfyUI 启动后自动继续。视频在 gpu3 出，不受影响。${waiting ? "\n有任务在等待。" : ""}` : "",
    backend?.reachable && backend.vram_total_mb != null
      ? `${backend.gpu ?? ""} 显存 ${Math.round((backend.vram_used_mb ?? 0) / 1024)}/${Math.round(backend.vram_total_mb / 1024)} GB`
      : "",
    "点击打开任务队列",
  ].filter(Boolean).join("\n");
  const go = (to: Target) => (to.startsWith("#/") ? (window.location.hash = to) : setView(to as View));
  const items = (list: Entry[]) => (close: () => void) =>
    list.map(([to, label, hint]) => (
      <button key={to} className={`tb-item${view === to ? " on" : ""}`} onClick={() => (go(to), close())} title={hint}>
        {label}
      </button>
    ));
  const inGroup = (list: Entry[]) => list.some(([to]) => to === view);
  return (
    <header className="topbar t59">
      <b className="brand">NS Studio</b>
      <div className="tb-ep">
        <button className="tb-arrow" onClick={() => gotoEpisode(epNum - 1)} disabled={epNum <= 1} title="上一集（↑）">
          ‹
        </button>
        <button className="tb-ep-name" onClick={() => setPaletteOpen(true)} title={`跳转（G / Ctrl+K）· 共 ${total} 集`}>
          第 {epNum} 集{ep ? ` · ${ep.title}` : ""}
        </button>
        <button className="tb-arrow" onClick={() => gotoEpisode(epNum + 1)} disabled={epNum >= total} title="下一集（↓）">
          ›
        </button>
      </div>
      <nav className="tb-nav">
        <button className={`tb-link${view === "episode" ? " on" : ""}`} onClick={() => setView("episode")} title="快捷键 2">
          镜头
        </button>
        <Menu label="资产" active={inGroup(ASSETS)}>
          {items(ASSETS)}
        </Menu>
        <Menu label="剧本" active={inGroup(SCRIPT)}>
          {items(SCRIPT)}
        </Menu>
        <Menu label="更多" active={inGroup(MORE)}>
          {items(MORE)}
        </Menu>
      </nav>
      {view === "episode" && (
        <Menu label={filter === "all" ? "视图" : `视图 · ${FILTER_LABEL[filter]}`} title="镜头行 / 表格（T）· 密度（D）· 过滤 · 检查器（\）" active={filter !== "all"}>
          {() => (
            <div className="tb-view">
              <div className="tb-row">
                <span>显示</span>
                <div className="tb-seg">
                  <button className={!listMode ? "on" : ""} onClick={() => setListMode(false)}>
                    镜头行
                  </button>
                  <button className={listMode ? "on" : ""} onClick={() => setListMode(true)}>
                    表格
                  </button>
                </div>
              </div>
              {!listMode && (
                <div className="tb-row">
                  <span>密度</span>
                  <div className="tb-seg">
                    {(Object.keys(DENSITY_LABEL) as Density[]).map((d) => (
                      <button key={d} className={density === d ? "on" : ""} onClick={() => setDensity(d)}>
                        {DENSITY_LABEL[d]}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="tb-row">
                <span>过滤</span>
                <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} title="不匹配的镜头变暗">
                  {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
                    <option key={f} value={f}>
                      {FILTER_LABEL[f]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="tb-row">
                <span>检查器</span>
                <div className="tb-seg">
                  <button className={!inspectorHidden ? "on" : ""} onClick={() => setInspectorHidden(false)}>
                    显示
                  </button>
                  <button className={inspectorHidden ? "on" : ""} onClick={() => setInspectorHidden(true)}>
                    收起
                  </button>
                </div>
              </div>
            </div>
          )}
        </Menu>
      )}
      <span className="grow" />
      <GpuButton />
      <button
        className={`tb-status ${statusCls}`}
        onClick={() => setDrawer({ open: !(drawer.open && drawer.tab === "jobs"), tab: "jobs" })}
        title={statusTitle}
      >
        <i className="tb-dot" />
        {statusText}
      </button>
      <button className="tb-link" onClick={() => setReviewMode(true)} title="审片模式（R）">
        审片
      </button>
      <ThemeToggle />
      <button className="tb-link" onClick={() => setHelpOpen(true)} title="快捷键（?）">
        ?
      </button>
    </header>
  );
}
