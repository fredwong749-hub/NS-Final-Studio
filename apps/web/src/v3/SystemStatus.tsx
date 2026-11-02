// UIFIX-S：顶栏“系统状态”入口 + 面板。每行 = 灰 / 琥珀 / 绿圆点 + 是什么 + 人话加数字；有异常的行写一句原因；全部正常时顶栏只有一个绿点。
// 原来平铺在顶栏的 实时 · 连接 · 卡 · 渲染任务 不删：面板里每行有入口（显卡面板 / 渲染任务抽屉 / 连接明细），悬停出声开关也在这里。
import { GpuButton } from "../components/GpuPanel";
import { RenderTasksButton } from "../components/RenderTasks";
import { InfraPanel } from "./InfraStatus";
import { useInfra } from "./InfraStatus.helpers";
import { useFilmSound } from "./filmSound";
import { useSystemStatus, type SysLevel } from "./SystemStatus.helpers";
import { Pop } from "./widgets";
import "./sysstatus.css";

const DOT: Record<SysLevel | "loading", string> = { ok: "green", warn: "yellow", idle: "gray", loading: "gray" };

/** 隐藏挂载：显卡面板 / 渲染任务抽屉的状态在这两个组件里，面板里的入口去点它们（功能不删） */
export function SystemStatusHidden({ onOpenJobsPage, extraTitle, alert }: { onOpenJobsPage: () => void; extraTitle: string; alert: boolean }) {
  return (
    <span className="v3-top-hidden" aria-hidden="true">
      <GpuButton labels="short" className="v3-gpu" />
      <RenderTasksButton className="v3-queue" onOpenJobsPage={onOpenJobsPage} alert={alert} extraTitle={extraTitle} />
    </span>
  );
}

export function SystemStatusButton() {
  const { rows, level, warnN } = useSystemStatus();
  const infra = useInfra();
  const [sound, setSound] = useFilmSound();
  const summary = level === "loading" ? "正在读系统状态…" : warnN ? `${warnN} 项需要留意` : "全部正常";
  return (
    <Pop
      className="v3-sys-pop"
      btnClass={`v3-sys lv-${level}`}
      align="right"
      title={`系统状态：${summary}。点开看每一项是什么、有没有问题`}
      label={
        <>
          <span className="v3-sys-t">系统状态</span>
          <i className={`v3-sdot d-${DOT[level]}`} aria-hidden="true" />
        </>
      }
    >
      {(close) => (
        <div className="v3-sys-panel" role="status">
          <header>
            <i className={`v3-sdot d-${DOT[level]}`} aria-hidden="true" />
            <b>{summary}</b>
          </header>
          <ul>
            {rows.map((r) => (
              <li key={r.id} className={`lv-${r.level}`}>
                <i className={`v3-sdot d-${DOT[r.level]}`} aria-hidden="true" />
                <span className="k">{r.name}</span>
                <span className="v">{r.value}</span>
                {r.why && <p className="why">{r.why}</p>}
              </li>
            ))}
            {rows.length === 0 && (
              <li className="lv-idle">
                <span className="k">正在读取…</span>
              </li>
            )}
          </ul>
          <div className="v3-sys-acts">
            <button type="button" onClick={() => (close(), window.dispatchEvent(new Event("ns:gpu-open")))} title="每张卡在做什么、温度、显存">
              显卡面板
            </button>
            <button type="button" onClick={() => (close(), document.querySelector<HTMLButtonElement>(".v3-top-hidden .rt-btn")?.click())} title="每个任务：剧本 / 首帧 / 尾帧 / 视频，进度与失败原因">
              渲染任务
            </button>
          </div>
          {infra.data && (
            <details className="v3-sys-det">
              <summary>连接明细（跳板 · 每条到服务器的连接 · 常驻程序）</summary>
              <InfraPanel d={infra.data} />
            </details>
          )}
          <label className="v3-sys-snd" title="悬停在全剧总览（胶片样式）的片条帧上，播放这一镜视频的声音。浏览器要求页面上先点一下 / 按一次键才允许出声。">
            <input type="checkbox" checked={sound} onChange={(e) => setSound(e.target.checked)} /> 全剧总览悬停播放时出声（默认开）
          </label>
        </div>
      )}
    </Pop>
  );
}
