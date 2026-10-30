import { useStudio, type Density, type View } from "../store";
import { FILTER_LABEL, type Filter } from "../util";

const VIEWS: [View, string, string][] = [
  ["overview", "总览", "1"],
  ["episode", "集", "2"],
  ["assets", "资产", "4"],
  ["nodes", "节点(次要)", ""],
];
const DENSITY_LABEL: Record<Density, string> = { compact: "紧凑", standard: "标准", detail: "详细" };

export function TopBar() {
  const {
    episodes, epNum, gotoEpisode, view, setView, filter, setFilter, jobs, drawer, setDrawer, setHelpOpen, setPaletteOpen,
    setReviewMode, density, cycleDensity, listMode, setListMode, inspectorHidden, setInspectorHidden,
  } = useStudio();
  const running = jobs.filter((j) => j.state === "running").length;
  const queued = jobs.filter((j) => j.state === "queued").length;
  const failed = jobs.filter((j) => j.state === "failed").length;
  const total = episodes?.length ?? 60;
  return (
    <header className="topbar">
      <b className="brand">NS-Final Studio</b>
      <div className="ep-picker">
        <button className="btn-mini" onClick={() => gotoEpisode(epNum - 1)} disabled={epNum <= 1} title="上一集（↑）">
          ‹
        </button>
        <button className="btn-mini tnum" onClick={() => setPaletteOpen(true)} title="跳转（G / Ctrl+K）">
          ep{String(epNum).padStart(2, "0")}/{total}
        </button>
        <button className="btn-mini" onClick={() => gotoEpisode(epNum + 1)} disabled={epNum >= total} title="下一集（↓）">
          ›
        </button>
      </div>
      <div className="seg">
        {VIEWS.map(([v, label, key]) => (
          <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)} title={key ? `快捷键 ${key}` : "按需加载的节点画布"}>
            {label}
          </button>
        ))}
      </div>
      {view === "episode" && (
        <div className="seg">
          <button className={!listMode ? "on" : ""} onClick={() => setListMode(false)} title="卡片（T 切换）">
            卡片
          </button>
          <button className={listMode ? "on" : ""} onClick={() => setListMode(true)} title="列表模式，逐字段校对（T）">
            列表
          </button>
        </div>
      )}
      {view === "episode" && !listMode && (
        <button className="btn-mini" onClick={cycleDensity} title="卡片密度：紧凑 / 标准 / 详细（D）">
          密度：{DENSITY_LABEL[density]}
        </button>
      )}
      {view !== "assets" && (
        <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} title="过滤（不匹配的镜头变暗）">
          {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
            <option key={f} value={f}>
              过滤：{FILTER_LABEL[f]}
            </option>
          ))}
        </select>
      )}
      <span className="grow" />
      {view !== "assets" && (
        <button className="btn-mini" onClick={() => setInspectorHidden(!inspectorHidden)} title="收起 / 展开检查器（\）">
          {inspectorHidden ? "展开检查器" : "收起检查器"}
        </button>
      )}
      <button className="btn-mini" onClick={() => (window.location.hash = "#/projects")} title="项目 / 新建剧 / 待办 / 进度看板（T42）">
        项目 · 新建剧
      </button>
      <button className="btn-mini" onClick={() => setReviewMode(true)} title="R">
        审片模式
      </button>
      <button
        className={`queue-pill${running || queued ? " busy" : ""}`}
        onClick={() => setDrawer({ open: !(drawer.open && drawer.tab === "jobs"), tab: "jobs" })}
        title="任务队列"
      >
        运行 {running} · 排队 {queued}
        {failed > 0 && <span className="bad"> · 失败 {failed}</span>}
      </button>
      <button className="btn-mini" onClick={() => setHelpOpen(true)} title="快捷键（?）">
        ?
      </button>
    </header>
  );
}
