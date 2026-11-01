// UIRSI r38（项目方 22:1x：“uiux加个实时连接状态”）：实时连接状态的数据层。
// 后端 GET /api/infra/status 只读看门狗 / 常驻健康已经写好的状态文件，不在请求里连服务器；这里全站共用一份轮询（8 s），
// 顶栏胶囊、GPU 面板顶部、GPU 卡片的“连不上”原因都读它。接口没上线（404）就停止轮询，界面不显示这一块（不报错）。
import { useEffect, useState } from "react";

export type InfraLevel = "ok" | "warn" | "bad";
export type InfraTunnel = { port: number; host: string; card: string; name: string; lane: string; ok: boolean; fails: number; down_s: number; rebuilding: boolean; last_rebuild_at: string | null; alert: boolean; text: string; tech: string };
export type InfraServer = { name: string; night_ok: boolean; night_heartbeat_at: string | null; night_age_s: number | null; checked_at: string | null; checked_age_s: number | null; text: string };
export type InfraLocal = { id: string; label: string; ok: boolean; ms: number | null; hold?: boolean; text: string; tech: string };
export type InfraStatus = {
  at: string;
  level: InfraLevel;
  summary: string;
  watchdog: { ok: boolean; at: string | null; age_s: number | null };
  relay: { ok: boolean; checked_at: string | null; last_ok_at: string | null; down_s: number | null; text: string };
  tunnels: InfraTunnel[];
  servers: Record<string, InfraServer>;
  local: InfraLocal[];
  reconnect: string[];
  alerts: { id: string; level: string; since: string }[];
  /** r39：NETFIX 派单模式（临时由笔记本统一派图 / 正在交还 / 服务器自己派）；没有 NETFIX 状态时为 null */
  dispatch?: { override: boolean; phases: Record<string, string>; text: string } | null;
  source?: "netfix" | "watchdog";
};

const POLL_MS = 8000;
let cur: InfraStatus | null = null;
let err: string | null = null;
let dead = false;
let timer = 0;
const subs = new Set<() => void>();

function poll() {
  fetch("/api/infra/status")
    .then((r) => {
      if (r.status === 404) {
        dead = true;
        return null;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<InfraStatus>;
    })
    .then((d) => {
      if (d) {
        cur = d;
        err = null;
      }
    })
    .catch((e) => {
      err = String((e as Error).message ?? e);
    })
    .finally(() => {
      subs.forEach((f) => f());
      if (dead) stop();
    });
}
function start() {
  if (timer || dead) return;
  poll();
  timer = window.setInterval(poll, POLL_MS);
}
function stop() {
  window.clearInterval(timer);
  timer = 0;
}

/** 全站共用的连接状态（有人订阅才轮询）。返回 null = 还没读到；dead = 后端还没有这个接口 */
export function useInfra(): { data: InfraStatus | null; err: string | null; dead: boolean } {
  const [, tick] = useState(0);
  useEffect(() => {
    const f = () => tick((n) => n + 1);
    subs.add(f);
    start();
    return () => {
      subs.delete(f);
      if (!subs.size) stop();
    };
  }, []);
  return { data: cur, err, dead };
}

/** GPU 卡片“连不上”的原因（大白话）：跳板断了 / 这一条连接断了正在重连 / 暂时连不上 */
export function laneReason(d: InfraStatus | null, lane: string | null | undefined, downS?: number): string {
  if (d && !d.relay.ok) return "跳板断了，等跳板恢复后自动重连";
  const t = d?.tunnels.find((x) => x.lane === lane);
  if (t && !t.ok) return t.rebuilding ? "这条连接断了，正在自动重连" : "这条连接断了，2 分钟内自动再连";
  return downS != null ? `暂时连不上 ${downS} 秒` : "暂时连不上";
}

export const dotOf = (ok: boolean | null | undefined) => (ok == null ? "unk" : ok ? "ok" : "bad");

// 热更新时停掉旧轮询（PW-014 同类：不留多份定时器）
if (import.meta.hot) import.meta.hot.dispose(() => stop());
