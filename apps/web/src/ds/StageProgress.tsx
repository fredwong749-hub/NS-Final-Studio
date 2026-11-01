// 分段进度条（全站一个）：剧本 → 分镜 → 首帧 → 尾帧 → 视频 → 声音 → 成片。
// 每段：已完成填充（宽度平滑过渡）+ 进行中的微光（shimmer）+ 失败红标（悬停看原因）+ “首帧 12/41”；有预计时间写“约 N 分钟”。
// 数据：GET /api/progress?run=（后端 ns_api/live.py），实时事件来了自动重取，数字变了这一条闪一下。
import { useEffect, useState } from "react";
import { useFlash, useLiveEvent } from "../v3/live";
import "./live.css";

export interface Seg {
  done: number;
  total: number;
  running: number;
  failed: number;
  reasons: string[];
  eta_s: number | null;
  /** 比之前少了（PAGEWATCH PW-012）：从多少到多少、为什么 */
  regressed?: { from: number; to: number; reason: string };
}
export interface Progress {
  run: string | null;
  labels: Record<string, string>;
  order: string[];
  episodes: { episode: number; title?: string; segs: Record<string, Seg> }[];
  total: Record<string, Seg>;
  ts: number;
}

const eta = (s: number) => (s < 90 ? `约 ${Math.round(s)} 秒` : s < 5400 ? `约 ${Math.round(s / 60)} 分钟` : `约 ${(s / 3600).toFixed(1)} 小时`);

const ORDER = ["script", "board", "first", "last", "video", "voice", "cut"];
const LABELS: Record<string, string> = { script: "剧本", board: "分镜", first: "首帧", last: "尾帧", video: "视频", voice: "声音", cut: "成片" };
const EMPTY_SEGS: Record<string, Seg> = Object.fromEntries(ORDER.map((k) => [k, { done: 0, total: 0, running: 0, failed: 0, reasons: [], eta_s: null }]));

let cache: { run: string; at: number; p: Promise<Progress | null> } | null = null;
function load(run: string | null, force = false): Promise<Progress | null> {
  const key = run ?? "";
  if (!force && cache && cache.run === key && Date.now() - cache.at < 1500) return cache.p;
  const p = fetch(`/api/progress${run ? `?run=${encodeURIComponent(run)}` : ""}`).then((r) => (r.ok ? (r.json() as Promise<Progress>) : null), () => null);
  cache = { run: key, at: Date.now(), p };
  return p;
}

/** 进度数据：首次读一次，之后任何素材 / 任务 / 写作事件来了（1.5 秒合并）重读 */
function useProgress(run: string | null): Progress | null {
  const [p, setP] = useState<Progress | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    void load(run, tick > 0).then((x) => alive && x && setP(x));
    return () => {
      alive = false;
    };
  }, [run, tick]);
  useLiveEvent((e) => e.type !== "hello", () => setTick((n) => n + 1), 800);
  return p;
}

export function StageProgress({ segs, order, labels, compact, title, placeholder }: { segs: Record<string, Seg>; order: string[]; labels: Record<string, string>; compact?: boolean; title?: string; placeholder?: boolean }) {
  const etaAll = order.reduce((a, k) => a + (segs[k]?.eta_s ?? 0), 0);
  return (
    <div className={`sp${compact ? " sp-compact" : ""}`} role="group" aria-label={title ?? "进度"}>
      {title && !compact && (
        <div className="sp-head">
          <b>{title}</b>
          {etaAll > 0 && <span className="sp-eta">{eta(etaAll)}</span>}
        </div>
      )}
      <div className="sp-row">
        {order.map((k) => (segs[k] ? <SegView key={k} k={k} s={segs[k]} label={labels[k] ?? k} compact={compact} ph={placeholder} /> : null))}
      </div>
      {compact && etaAll > 0 && <span className="sp-eta">{eta(etaAll)}</span>}
    </div>
  );
}

/** 一段：只有这一段的数字真变了才渐变提示（不整条闪） */
function SegView({ k, s, label, compact, ph }: { k: string; s: Seg; label: string; compact?: boolean; ph?: boolean }) {
  // 占位条传 null：占位 → 第一次真数据只算初始化，不提示（PAGEWATCH PW-002 复查）
  const flash = useFlash(ph ? null : [s.done, s.total, s.running, s.failed]);
  const pct = s.total ? Math.min(100, (s.done / s.total) * 100) : 0;
  const runPct = s.total ? Math.min(100 - pct, (s.running / s.total) * 100) : 0;
  const full = s.total > 0 && s.done >= s.total;
  const tip = [
    `${label}：${s.done}/${s.total}`,
    s.running ? `进行中 ${s.running}${s.eta_s ? `（${eta(s.eta_s)}）` : ""}` : "",
    s.failed ? `没成 ${s.failed}：${s.reasons.slice(0, 6).join("；")}` : "",
    s.regressed ? `比之前少了（${s.regressed.from} → ${s.regressed.to}）：${s.regressed.reason}` : "",
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <div className={`sp-seg sp-${k}${full ? " full" : ""}${s.failed ? " has-bad" : ""}${s.running ? " is-run" : ""}${s.regressed ? " is-down" : ""}${flash ? " live-flash" : ""}`} title={tip}>
      <div className="sp-track">
        <i className="sp-fill" style={{ width: `${pct}%` }} />
        {runPct > 0 && <i className="sp-run" style={{ left: `${pct}%`, width: `${Math.max(runPct, 4)}%` }} />}
        {s.failed > 0 && <i className="sp-bad" aria-label={`没成 ${s.failed}`} />}
      </div>
      {!compact && (
        <span className="sp-lbl">
          {label} {s.total ? (
            <>
              <b>{s.done}</b>/{s.total}
            </>
          ) : (
            "—"
          )}
          {s.failed ? <em className="sp-fail"> ✗{s.failed}</em> : null}
          {s.regressed ? <em className="sp-down" title={s.regressed.reason}> ↓{s.regressed.from - s.regressed.to}</em> : null}
        </span>
      )}
    </div>
  );
}

/** 某一集 / 整季的进度条（自己取数、自己刷新） */
export function LiveProgress({ run, episode, compact, title }: { run: string | null; episode?: number; compact?: boolean; title?: string }) {
  const p = useProgress(run);
  // 还没读到：用同样结构的空进度条占位（尺寸和真实内容一致，读到后不跳动——PAGEWATCH PW-003）
  if (!p) return <StageProgress segs={EMPTY_SEGS} order={ORDER} labels={LABELS} compact={compact} title={title} placeholder />;
  const segs = episode != null ? p.episodes.find((e) => e.episode === episode)?.segs : p.total;
  if (!segs) return null;
  return <StageProgress segs={segs} order={p.order} labels={p.labels} compact={compact} title={title} />;
}
