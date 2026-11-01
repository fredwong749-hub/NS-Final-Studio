// 实时刷新的公共机制（UIRSI 11-01，总调度任务；项目方：“这个页面应该自动刷新……用 flash 渐变来代表该区域更新了”）。
// 一条 SSE（/api/events，后端 ns_api/live.py）+ 事件总线；断线自动退回每 10 秒轮询（发 type:"tick"）。
// 用法：
//   useLiveEvent((e) => e.type === "frame" && e.episode === 2, () => reload());     // 只刷自己这一块
//   const [ref, flashing] = useFlash(value);  <div ref={ref} className={flashing ? "live-flash" : ""}>  // 值真变了才闪
//   useLiveStatus() → "live" | "poll" | "connecting"
import { useEffect, useRef, useState } from "react";

export type LiveType = "frame" | "lastframe" | "video" | "voice" | "asset" | "stage" | "job" | "cut" | "tick" | "hello" | "ping";
export interface LiveEvent {
  type: LiveType;
  run?: string | null;
  episode?: number | null;
  shot?: string | null;
  field?: string | null;
  stage?: string | null;
  ts?: number;
  seq?: number;
  boot?: string;
}
export type LiveStatus = "connecting" | "live" | "poll" | "reconnecting";

const subs = new Set<(e: LiveEvent) => void>();
const statusSubs = new Set<(s: LiveStatus) => void>();
let status: LiveStatus = "connecting";
let es: EventSource | null = null;
let pollTimer: number | null = null;
let errors = 0;
let started = false;

function setStatus(s: LiveStatus) {
  if (s === status) return;
  status = s;
  statusSubs.forEach((f) => f(s));
}
function emit(e: LiveEvent) {
  // 验收 / 排错用：最近 20 条事件挂在 window.__live（不影响功能）
  try {
    const w = window as unknown as { __live?: LiveEvent[] };
    (w.__live ??= []).push(e);
    if (w.__live.length > 20) w.__live.shift();
  } catch {
    /* 无 window */
  }
  subs.forEach((f) => {
    try {
      f(e);
    } catch {
      /* 某一块处理出错不影响别的块 */
    }
  });
}
function startPoll() {
  if (pollTimer != null) return;
  setStatus("poll");
  pollTimer = window.setInterval(() => emit({ type: "tick", ts: Date.now() / 1000 }), 10000);
}
function stopPoll() {
  if (pollTimer != null) window.clearInterval(pollTimer);
  pollTimer = null;
}

/** 第一次有人订阅时才连（截图 / 测试页不订阅就不连）。
 *  看门狗（PAGEWATCH PW-008）：后端每 10 秒发 {type:"ping", boot, seq}；25 秒什么都没收到（代理把连接挂着、后端已重启，
 *  浏览器收不到 error）或 boot 变了（后端重启过）→ 关掉重连，徽标显示“重连中”，连上后补发一次 tick 让各块全量重取。 */
function start() {
  if (started || typeof window === "undefined") return;
  started = true;
  if (typeof EventSource === "undefined") return startPoll();
  let lastMsg = Date.now();
  let boot: string | null = null;
  let resync = false;
  let retryTimer: number | null = null;
  const seen = (b?: string) => {
    lastMsg = Date.now();
    if (!b) return;
    if (boot && b !== boot) {
      boot = b;
      reopen(0); // 后端重启过：换一条新连接（旧连接可能已是僵尸），连上后全量重取
      return;
    }
    boot = b;
    if (resync) {
      resync = false;
      emit({ type: "tick", ts: Date.now() / 1000 });
    }
  };
  const reopen = (delay: number) => {
    es?.close();
    es = null;
    resync = true;
    setStatus("reconnecting");
    if (retryTimer != null) window.clearTimeout(retryTimer);
    retryTimer = window.setTimeout(() => {
      retryTimer = null;
      open();
    }, delay);
  };
  const open = () => {
    lastMsg = Date.now();
    es = new EventSource("/api/events");
    es.onopen = () => {
      errors = 0;
      lastMsg = Date.now();
      stopPoll();
      setStatus("live");
    };
    es.addEventListener("hello", (m) => {
      try {
        seen((JSON.parse((m as MessageEvent).data) as LiveEvent).boot);
      } catch {
        seen();
      }
    });
    es.onmessage = (m) => {
      try {
        const e = JSON.parse(m.data) as LiveEvent;
        seen(e.boot);
        if (e.type !== "ping") emit(e);
      } catch {
        seen();
      }
    };
    es.onerror = () => {
      errors += 1;
      // 浏览器会自己按 retry 重连；连不上（或接口还没启用 404 → CLOSED）就先退回轮询，几秒后再试 SSE
      if (errors >= 2 || es?.readyState === EventSource.CLOSED) {
        startPoll();
        if (es?.readyState === EventSource.CLOSED) reopen(errors > 5 ? 30000 : 3000);
      }
    };
  };
  dogTimer = window.setInterval(() => {
    if (es && Date.now() - lastMsg > 25000) reopen(0);
  }, 5000);
  closeAll = () => {
    if (retryTimer != null) window.clearTimeout(retryTimer);
    retryTimer = null;
  };
  open();
}

// 热更新 / 重复加载时把旧模块的连接、看门狗、定时器全部收掉（PAGEWATCH PW-014：每次热更新多留一条 /api/events，占满浏览器 6 条连接）
let dogTimer: number | null = null;
let closeAll: () => void = () => undefined;
function disposeLive() {
  es?.close();
  es = null;
  stopPoll();
  if (dogTimer != null) window.clearInterval(dogTimer);
  dogTimer = null;
  closeAll();
  started = false;
}
if (typeof window !== "undefined") {
  const w = window as unknown as { __liveDispose?: () => void };
  w.__liveDispose?.(); // 上一份模块（热更新前）留下的连接
  w.__liveDispose = disposeLive;
}
if (import.meta.hot) import.meta.hot.dispose(disposeLive);

export function onLive(f: (e: LiveEvent) => void): () => void {
  start();
  subs.add(f);
  return () => void subs.delete(f);
}

export function useLiveStatus(): LiveStatus {
  const [s, setS] = useState(status);
  useEffect(() => {
    start();
    statusSubs.add(setS);
    setS(status);
    return () => void statusSubs.delete(setS);
  }, []);
  return s;
}

/** 匹配的事件来了就调 cb（同一块 delayMs 内多条只刷一次）；轮询兜底的 tick 也会触发 */
export function useLiveEvent(match: (e: LiveEvent) => boolean, cb: () => void, delayMs = 500) {
  const m = useRef(match);
  const c = useRef(cb);
  m.current = match;
  c.current = cb;
  useEffect(() => {
    let t: number | null = null;
    const off = onLive((e) => {
      if (e.type === "hello") return;
      if (e.type !== "tick" && !m.current(e)) return;
      if (t != null) return;
      t = window.setTimeout(() => {
        t = null;
        c.current();
      }, delayMs);
    });
    return () => {
      off();
      if (t != null) window.clearTimeout(t);
    };
  }, [delayMs]);
}

/** 值真的变了才提示（第一次渲染、内容一样都不提示）；同一块 3 秒内连变几次只放一次渐变。返回 true 的约 2.2 秒里给这一块加 live-flash */
export function useFlash(value: unknown, ms = 2300): boolean {
  const prev = useRef<string | null>(null);
  const lastAt = useRef(0);
  const timer = useRef<number | null>(null);
  const [on, setOn] = useState(false);
  useEffect(() => () => void (timer.current != null && window.clearTimeout(timer.current)), []);
  const sig = JSON.stringify(value ?? null);
  useEffect(() => {
    // 第一次、或之前还没有数据（null → 首次到数据）都只记录不提示（PAGEWATCH PW-002）
    if (prev.current === null || prev.current === "null") {
      prev.current = sig;
      return;
    }
    if (prev.current === sig) return;
    prev.current = sig;
    const now = Date.now();
    if (now - lastAt.current < 3000) return; // 合并：3 秒内已经在提示了
    lastAt.current = now;
    setOn(true);
    if (timer.current != null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      timer.current = null;
      setOn(false);
    }, ms);
  }, [sig, ms]);
  return on;
}
