// UIFIX-S（项目方 13:1x：“交互非常难用……顶部的东西……我也看不到什么信息”）：顶栏“系统状态”面板的数据层。
// 只读后端已有接口，没有的行不显示，不编数：
//   /api/factory/health（出图卡 / 看图打分 / 自动出片）、/api/render-tasks（在出 / 等待 / 失败）、/api/infra/status（服务器连接）、
//   实时事件流状态（live.ts）、集列表里每镜当前首帧 / 尾帧 / 视频（和全剧总览同口径）。
import { useStudio } from "../store";
import { useRenderTasks } from "../components/RenderTasks.helpers";
import { useFactory } from "./FactoryHealth.helpers";
import { useInfra } from "./InfraStatus.helpers";
import { useLiveStatus } from "./live";

export type SysLevel = "ok" | "warn" | "idle";
export type SysRow = { id: string; name: string; value: string; level: SysLevel; why?: string };
type Prog = { ff: [number, number]; lf: [number, number]; vid: [number, number] };

/** 全剧制作进度：和“全剧总览”页头同一口径（SeasonPage：按集列表里每镜“当前有没有首帧 / 尾帧 / 视频”数，分母 = 全剧镜数）。
 *  以前读 项目制作接口的 lights（只数“定稿锁”的镜：首帧 16 对总览的 90），两处对不上，已改掉；
 *  tools/qa/data_parity.py D-PROG 守住：两处数字必须一致。 */
export function progOf(eps: { shots: { first_frame?: unknown; last_frame_target?: unknown; video?: unknown }[] }[] | null | undefined): Prog | null {
  if (!eps?.length) return null;
  const all = eps.flatMap((e) => e.shots ?? []);
  const n = all.length;
  return { ff: [all.filter((s) => !!s.first_frame).length, n], lf: [all.filter((s) => !!s.last_frame_target).length, n], vid: [all.filter((s) => !!s.video).length, n] };
}

export function useSystemStatus(): { rows: SysRow[]; level: "ok" | "warn" | "loading"; warnN: number } {
  const fac = useFactory().data;
  const rt = useRenderTasks().data;
  const infra = useInfra();
  const live = useLiveStatus();
  const pg = progOf(useStudio().episodes as never);
  const rows: SysRow[] = [];
  if (fac?.total) {
    const bad = fac.lanes.filter((l) => l.state === "warn" || l.state === "down" || l.state === "faulty");
    rows.push({
      id: "gpu",
      name: "GPU 出图卡",
      value: `${fac.total} 张里 ${fac.busy ?? 0} 张在工作`,
      level: bad.length ? "warn" : "ok",
      why: bad.length ? bad.slice(0, 3).map((l) => `${l.label} ${l.text.split(" · ")[0]}`).join("；") + (bad.length > 3 ? ` 等 ${bad.length} 张` : "") : undefined,
    });
  }
  if (rt?.counts) {
    const c = rt.counts;
    const fail = c.failed_recent ?? 0;
    rows.push({
      id: "queue",
      name: "出图队列",
      value: `在出 ${c.rendering} · 等待 ${c.queued ?? c.pending}`,
      level: fail ? "warn" : "ok",
      why: fail ? `近 ${c.recent_fail_h ?? 6} 小时有 ${fail} 个任务失败，在“渲染任务”里看` : undefined,
    });
  }
  if (infra.data) {
    const t = infra.data.tunnels;
    const okN = t.filter((x) => x.ok).length;
    rows.push({
      id: "conn",
      name: "服务器连接",
      value: infra.data.level === "ok" ? `正常（${okN}/${t.length}）` : !infra.data.relay.ok ? "跳板断了" : `${okN}/${t.length} 条通`,
      level: infra.data.level === "ok" ? "ok" : "warn",
      why: infra.data.level === "ok" ? undefined : infra.data.summary,
    });
  }
  if (fac?.producer) {
    const okState = ["busy", "idle", "ok"].includes(fac.producer.state);
    rows.push({ id: "producer", name: "自动出片程序", value: fac.producer.text, level: okState ? "ok" : "warn", why: okState ? undefined : "常驻出片程序没有心跳，可能没在运行" });
  }
  if (fac?.vqa?.length) {
    const bad = fac.vqa.filter((v) => v.state === "down" || v.state === "warn");
    rows.push({
      id: "vqa",
      name: "看图打分卡",
      value: fac.vqa.map((v) => `${v.label.replace("看图卡", "").trim() || v.label} ${v.state === "down" ? "未运行" : "正常"}`).join(" · "),
      level: bad.length ? "warn" : "ok",
      why: bad.length ? `${bad.map((v) => v.label).join("、")}：${bad[0].text}。出图仍可继续，打分会慢` : undefined,
    });
  }
  rows.push({
    id: "live",
    name: "页面实时更新",
    value: live === "live" ? "正常" : live === "reconnecting" ? "重连中" : live === "poll" ? "已断开，每 10 秒刷新" : "连接中",
    level: live === "live" ? "ok" : live === "poll" ? "warn" : "idle",
    why: live === "poll" ? "实时通道断了，页面改成每 10 秒自己刷新一次，连上后自动恢复" : undefined,
  });
  if (pg && pg.ff[1]) rows.push({ id: "prog", name: "全剧制作进度", value: `首帧 ${pg.ff[0]}/${pg.ff[1]} · 尾帧 ${pg.lf[0]}/${pg.lf[1]} · 视频 ${pg.vid[0]}/${pg.vid[1]}`, level: "idle" });
  const warnN = rows.filter((r) => r.level === "warn").length;
  const loading = !fac && !rt && !infra.data;
  return { rows, level: loading ? "loading" : warnN ? "warn" : "ok", warnN };
}
