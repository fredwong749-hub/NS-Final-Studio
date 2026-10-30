import { useEffect, useState } from "react";
import "../gpu.css";
import { useStudio } from "../store";
import { OwnerRunPanel } from "./OwnerRunPanel";

/** GPU 实时面板（项目方：“gpu进程实时tracking”）。顶栏一个入口按钮 + 右侧抽屉；数据 GET /api/gpu3/gpus，每 5 秒轮询。
 *  只读：显示忙闲、显存、温度功耗、进程、锁 / lend 归属、Qwen 信箱任务；锁着但空闲 ≥ 10 分钟用警示色。 */

interface Proc {
  pid: number | null;
  vram_mb: number | null;
  cmd: string | null;
  cmdline: string | null;
}
interface Gpu {
  id: number;
  name: string | null;
  faulty: boolean;
  util: number | null;
  vram_used_mb: number | null;
  vram_total_mb: number | null;
  temp_c: number | null;
  power_w: number | null;
  power_limit_w: number | null;
  processes: Proc[];
  train_lock: string | null;
  gpu_lock: string | null;
  lend: string | null;
  comfy: { url: string; running: number; pending: number } | null;
  busy: boolean;
  idle_s: number;
  locked_idle: boolean;
  /** 锁被临时改名暂停（如“为 ep01 渲染暂停 Qwen”） */
  paused: string | null;
}
interface GpuData {
  at: string;
  age_s: number;
  gpus: Gpu[];
  qwen: { reachable: boolean; running: number | null; queued: number | null; tasks: { id: string; from: string; status: string; created_at: string }[] };
  sources: { bridge: boolean; ssh: boolean; qwen_mailbox: boolean };
  idle_warn_s: number;
}

const POLL_MS = 5000;

function useGpus(enabled: boolean) {
  const [data, setData] = useState<GpuData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    const poll = () =>
      fetch("/api/gpu3/gpus")
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((d: GpuData) => alive && (setData(d), setErr(null)))
        .catch((e: Error) => alive && setErr(e.message));
    poll();
    const t = window.setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [enabled]);
  return { data, err };
}

const mins = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)} 小时 ${Math.round((s % 3600) / 60)} 分` : `${Math.round(s / 60)} 分`);

function Bar({ value, max, cls }: { value: number; max: number; cls: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="gpu-bar" title={`${pct}%`}>
      <i className={cls} style={{ width: `${pct}%` }} />
    </div>
  );
}

function GpuRow({ g }: { g: Gpu }) {
  const state = g.faulty ? "faulty" : g.locked_idle ? "warn" : g.busy ? "busy" : g.paused ? "paused" : "idle";
  const label = g.faulty
    ? "坏卡 · 不用"
    : g.locked_idle
      ? `锁着但空闲 ${mins(g.idle_s)}`
      : g.busy
        ? `忙${g.paused ? ` · ${g.paused}` : ""}`
        : g.paused ?? "闲";
  const vram = g.vram_used_mb ?? 0;
  const vtot = g.vram_total_mb ?? 24576;
  return (
    <section className={`gpu-row ${state}`}>
      <header>
        <b>GPU{g.id}</b>
        <span className={`gpu-state ${state}`}>{label}</span>
        <span className="gpu-muted">{g.name ?? ""}</span>
        <span className="grow" />
        {g.temp_c != null && <span className="gpu-muted">{Math.round(g.temp_c)}°C</span>}
        {g.power_w != null && (
          <span className="gpu-muted">
            {Math.round(g.power_w)}
            {g.power_limit_w ? `/${Math.round(g.power_limit_w)}` : ""} W
          </span>
        )}
      </header>
      {!g.faulty && (
        <>
          <div className="gpu-metric">
            <span>利用率 {g.util ?? "—"}%</span>
            <Bar value={g.util ?? 0} max={100} cls={state} />
          </div>
          <div className="gpu-metric">
            <span>
              显存 {(vram / 1024).toFixed(1)}/{(vtot / 1024).toFixed(0)} GB
            </span>
            <Bar value={vram} max={vtot} cls="mem" />
          </div>
          <dl className="gpu-kv">
            <dt>占用锁</dt>
            <dd>{g.train_lock ?? g.gpu_lock ?? (g.paused ? `无（${g.paused}）` : "无")}</dd>
            {g.lend && (
              <>
                <dt>lend</dt>
                <dd>{g.lend}</dd>
              </>
            )}
            {g.comfy && (
              <>
                <dt>ComfyUI</dt>
                <dd>
                  运行 {g.comfy.running} · 排队 {g.comfy.pending}
                </dd>
              </>
            )}
            <dt>正在跑</dt>
            <dd>
              {g.processes.length === 0
                ? "无进程"
                : g.processes.map((p) => (
                    <div key={`${p.pid}`} title={p.cmdline ?? ""}>
                      {p.cmd || "?"} <span className="gpu-muted">pid {p.pid} · {((p.vram_mb ?? 0) / 1024).toFixed(1)} GB</span>
                    </div>
                  ))}
            </dd>
          </dl>
        </>
      )}
    </section>
  );
}

/** 顶栏入口：按钮上直接显示忙卡数；有“锁着但空闲”时变警示色 */
/** v3.1 §4.1（fredw-92/U1）：labels="cards" 时按钮写“出图卡 空闲|忙 · 视频卡 空闲|忙”（出图卡 = GPU0，视频卡 = GPU3），详情点开看；不传保持旧文字 */
export function GpuButton({ labels, className }: { labels?: "cards"; className?: string } = {}) {
  const [open, setOpen] = useState(false);
  // 抽屉关着时也低频取一次概况给按钮用（同一接口，后端快照不额外耗时）
  const { data, err } = useGpus(true);
  const usable = data?.gpus.filter((g) => !g.faulty) ?? [];
  const busy = usable.filter((g) => g.busy).length;
  const warn = usable.some((g) => g.locked_idle);
  if (labels === "cards") {
    const card = (id: number) => {
      const g = data?.gpus.find((x) => x.id === id);
      return !g ? "—" : g.faulty ? "故障" : g.busy ? "忙" : "空闲";
    };
    const a = card(0);
    const b = card(3);
    return (
      <>
        <button className={`${className ?? "gpu-btn"}${a === "忙" || b === "忙" ? " busy" : ""}`} onClick={() => setOpen((o) => !o)} title="出图卡 = GPU0，视频卡 = GPU3；点开看每张卡的详情">
          {data ? `出图卡 ${a} · 视频卡 ${b}` : err ? "显卡状态读不到" : "显卡…"}
        </button>
        {open && <GpuDrawer data={data} err={err} onClose={() => setOpen(false)} />}
      </>
    );
  }
  return (
    <>
      <button className={`gpu-btn${warn ? " warn" : ""}`} onClick={() => setOpen((o) => !o)} title="gpu3 GPU 实时状态">
        GPU {data ? `${busy}/${usable.length} 忙` : err ? "连不上" : "…"}
        {warn && " · 有卡锁着闲置"}
      </button>
      {open && <GpuDrawer data={data} err={err} onClose={() => setOpen(false)} />}
    </>
  );
}

function GpuDrawer({ data, err, onClose }: { data: GpuData | null; err: string | null; onClose: () => void }) {
  const { epNum } = useStudio();
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <aside className="gpu-drawer" role="dialog" aria-label="GPU 实时状态">
      <header className="gpu-drawer-head">
        <b>gpu3 GPU 实时状态</b>
        <span className="gpu-muted">{data ? `更新于 ${data.at.slice(11)}（${data.age_s}s 前）· 每 5 秒刷新` : ""}</span>
        <span className="grow" />
        <button className="btn-mini" onClick={onClose}>
          关闭 Esc
        </button>
      </header>
      {err && <div className="gpu-err">读取失败：{err}（API 需重启才有此接口）</div>}
      {data && (
        <>
          {(!data.sources.bridge || !data.sources.ssh) && (
            <div className="gpu-err">
              {!data.sources.bridge && "gpu3 桥连不上（隧道 15180）；"}
              {!data.sources.ssh && "ssh 取温度 / 进程失败；"}部分数据缺失
            </div>
          )}
          {data.gpus.map((g) => (
            <GpuRow key={g.id} g={g} />
          ))}
          <section className="gpu-row">
            <header>
              <b>Qwen 信箱</b>
              <span className="gpu-muted">{data.qwen.reachable ? `运行 ${data.qwen.running} · 排队 ${data.qwen.queued}` : "连不上（隧道 18099）"}</span>
            </header>
            {data.qwen.tasks.map((t) => (
              <div key={t.id} className="gpu-task">
                <span className={`gpu-state ${t.status === "running" ? "busy" : "idle"}`}>{t.status === "running" ? "运行" : "排队"}</span> {t.id}
                <span className="gpu-muted"> · {t.from}</span>
              </div>
            ))}
          </section>
        </>
      )}
      <OwnerRunPanel defaultEp={epNum} />
    </aside>
  );
}

export default GpuButton;
