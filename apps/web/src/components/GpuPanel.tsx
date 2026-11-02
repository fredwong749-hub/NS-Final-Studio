import { useEffect, useState } from "react";
import "../gpu.css";
import "./rendertasks.css";
import { StepBar } from "./RenderTasks";
import { fmtS, type RTRow } from "./RenderTasks.helpers";
import { cardName, cardTip, laneState, lockWord, refreshLanes, useLanes as useLaneStore, type LaneInfo } from "../v3/edit/lanes";
import { InfraPanel } from "../v3/InfraStatus";
import { laneReason, useInfra, type InfraStatus } from "../v3/InfraStatus.helpers";
import { breatheDelay } from "../v3/status";
import { useFactory } from "../v3/FactoryHealth.helpers";

/** fredw-92/UXF2（审查 #45 / #46 / #47）：去掉面板里的“按集渲染”（整集出片只留顶栏一个入口）；每张卡先一句人话，
 *  进程 / pid / ComfyUI 队列收进“技术细节”；道表接口 404 后不再轮询。
 *  GPU 实时面板（项目方：“gpu进程实时tracking”）。顶栏一个入口按钮 + 右侧抽屉；数据 GET /api/gpu3/gpus，每 5 秒轮询。
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
    const first = window.setTimeout(poll, 1800); // UIRSI r16：卡状态不抢首屏
    const t = window.setInterval(poll, POLL_MS);
    return () => {
      alive = false;
      window.clearTimeout(first);
      window.clearInterval(t);
    };
  }, [enabled]);
  return { data, err };
}

/** GPUVIEW（11-01，项目方：“实时展示gpu显卡做什么任务细节”）：GET /api/gpu/live（ns_api/gpu_live.py）——每张卡谁在做什么、
 *  进度 / 预计、队列、温度功耗（gpu36 温控守护）、最近一张出图。接口没有（API 未重启）→ null，面板照旧。 */
interface LiveItem {
  prompt_id: string;
  what: string;
  tag: { agent?: string; kind?: string; inferred?: boolean; attempt?: number; max_attempts?: number; idx?: number; total?: number };
  elapsed_s?: number | null;
  eta_s?: number | null;
  typical_s?: number | null;
  starts_in_s?: number | null;
  started?: number | null;
  progress?: { step: number; steps: number; step_left_s?: number | null; source?: string } | null;
}
interface LiveHb {
  agent: string;
  label: string;
  step?: number;
  steps?: number;
  pct?: number;
  eta_s?: number;
  started?: number;
}
interface LiveCardData {
  id: string;
  server: string;
  idx: number;
  lane: string | null;
  faulty: boolean;
  state: "busy" | "idle" | "external" | "offline" | "faulty" | "flaky";
  /** 渲染道连不上：2 分钟内是“暂时连不上（N 秒）”，超过才算离线（UIAUDIT verify_gpuview_r1 P2） */
  link?: { down_s: number; offline: boolean; text: string } | null;
  who: string;
  agent: string | null;
  running: LiveItem[];
  pending: LiveItem[];
  queue_len: number;
  queue_eta_s: number | null;
  recent: { what: string; ok: boolean; error: string | null; end: number | null }[];
  heartbeats: LiveHb[];
  other_procs: { pid: number; user: string | null; what: string; vram_mb: number | null; elapsed_s: number | null }[];
  thumb: { src: string; full: string; what: string; end: number | null; file: string } | null;
  hw: { name: string | null; util: number | null; vram_used_mb: number | null; vram_total_mb: number | null; temp_c: number | null; power_w: number | null; power_limit_w: number | null; power_default_w: number | null } | null;
  throttle: { limit_w: number; default_w: number; by_guard: boolean; text: string } | null;
  comfy: { url: string; port: number | null; reachable: boolean; error: string | null } | null;
  hw_age_s: number | null;
}
interface LiveData {
  at: string;
  cards: LiveCardData[];
  hosts: Record<string, { ok: boolean; age_s: number | null; err: string | null; guard?: { level: number; name: string } }>;
  heartbeats: LiveHb[];
}

function useGpuLive(enabled: boolean) {
  const [data, setData] = useState<LiveData | null>(null);
  const [dead, setDead] = useState(false);
  useEffect(() => {
    if (!enabled || dead) return;
    let alive = true;
    const poll = () =>
      fetch("/api/gpu/live")
        .then((r) => (r.status === 404 ? (setDead(true), null) : r.ok ? (r.json() as Promise<LiveData>) : null))
        .then((d) => {
          if (alive && d) setData(d);
        })
        .catch(() => {});
    poll();
    const t = window.setInterval(poll, 4000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, [enabled, dead]);
  return data;
}

const barRow = (progress: RTRow["progress"], eta: number | null | undefined, elapsed: number | null | undefined): RTRow =>
  ({ status: "rendering", progress, eta_s: eta ?? null, elapsed_s: elapsed ?? null }) as RTRow;

// UIAUDIT P1-2（UIRSI r43）：连接状态只认 net_status 一个口径（/api/infra/status 的 tunnels）。
// 该卡在 infra 里有对应连接 → 以它为准（连接通就不显示“连不上”）；infra 没数据才退回 gpu_live 的 link。
function linkOf(c: LiveCardData, infra: InfraStatus | null | undefined): LiveCardData["link"] {
  const t = infra?.tunnels.find((x) => x.lane === c.lane);
  if (t) return t.ok ? null : { down_s: t.down_s, offline: false, text: t.text };
  return c.link ?? null;
}

function LiveCard({ c, lane, infra, merged }: { c: LiveCardData; lane?: LaneInfo; infra?: InfraStatus | null; merged?: boolean }) {
  // UIRSI r38：“最近出图”缩略图读不到（图在服务器上、笔记本没有且连接不通）→ 写占位字，不出裂图
  const [thumbBad, setThumbBad] = useState<string | null>(null);
  const link = linkOf(c, infra);
  const r0 = c.running[0];
  const hb = c.heartbeats[0];
  const hw = c.hw;
  const state = c.faulty || c.state === "offline" ? "faulty" : c.state === "flaky" ? "warn" : c.state === "busy" || c.state === "external" ? "busy" : lane?.lock ? "warn" : "idle";
  const chip = c.faulty
    ? "坏卡 · 不用"
    : c.state === "offline"
      ? "离线"
      : link
        ? merged
          ? "连不上"
          : `暂时连不上 ${link.down_s} 秒`
        : c.state === "busy"
          ? "在跑"
          : c.state === "external"
            ? "别人在用"
            : lane?.lock ?? "空闲";
  const vtot = hw?.vram_total_mb ?? 24576;
  return (
    <section className={`gpu-row ${state} gl-card`} data-card={c.id} style={breatheDelay(c.id)}>
      <header>
        <b title={cardTip(c.lane ?? c.id)}>{cardName(c.lane ?? `${c.server}:${c.idx}`)}</b>
        <span className={`gpu-state ${state}`}>{chip}</span>
        <span className="gpu-muted">{hw?.name ?? ""}</span>
        <span className="grow" />
        {hw?.temp_c != null && <span className="gpu-muted">{Math.round(hw.temp_c)}°C</span>}
        {hw?.power_w != null && (
          <span className="gpu-muted" title={hw.power_default_w ? `默认功耗墙 ${Math.round(hw.power_default_w)} W` : ""}>
            {Math.round(hw.power_w)}/{Math.round(hw.power_limit_w ?? 0)} W
          </span>
        )}
        {!hw && <span className="gpu-muted">温度 / 显存读取中…</span>}
      </header>
      {/* UIRSI r38：连不上时说原因（跳板断了 / 只是这条连接断了、正在自动重连）；全部卡都断时面板顶部已说一次，这里不重复 */}
      {link && !c.faulty && !merged && <span className="gl-why">{laneReason(infra ?? null, c.lane, c.state === "offline" ? undefined : link.down_s)}</span>}
      {c.throttle && (
        <span className="gl-thr" title={c.throttle.text}>
          ⚠ {c.throttle.by_guard ? "温控守护限功耗" : "功耗墙"} {Math.round(c.throttle.limit_w)} W（默认 {Math.round(c.throttle.default_w)} W）
        </span>
      )}
      {!c.faulty && (
        <>
          <div className="gl-who" hidden={c.state === "idle" && !c.agent}>
            {c.who}
            {c.agent && (
              <small>
                {c.agent}
                {r0?.tag.inferred ? "（按输出推断）" : ""}
              </small>
            )}
          </div>
          {(r0 || hb || c.thumb) && (
            <div className={`gl-run${c.thumb ? "" : " nothumb"}`}>
              {c.thumb && (
                <div className="gl-thumb" data-zoom-label={`最近出图：${c.thumb.what}`}>
                  {thumbBad === c.thumb.src ? (
                    <span className="gl-thumb-none" title={`最近出图：${c.thumb.what}`}>图在服务器上，笔记本还没有</span>
                  ) : (
                    <img src={c.thumb.src} data-full={c.thumb.full} alt={`最近出图：${c.thumb.what}`} title={`最近出图：${c.thumb.what}（${c.thumb.file}）`} loading="lazy" onError={() => setThumbBad(c.thumb!.src)} />
                  )}
                </div>
              )}
              <div className="gl-card">
                {r0 && <StepBar r={barRow(r0.progress ?? null, r0.eta_s, r0.elapsed_s)} />}
                {hb && <StepBar r={barRow(hb.steps ? { step: hb.step ?? 0, steps: hb.steps } : hb.pct != null ? { pct: hb.pct } : null, hb.eta_s, hb.started ? Date.now() / 1000 - hb.started : null)} />}
                <div className="gl-meta">
                  {r0?.elapsed_s != null && <span>已跑 {fmtS(r0.elapsed_s)}</span>}
                  {r0?.typical_s != null && <span title="这条道最近同类任务耗时的中位数">同类一般 {fmtS(r0.typical_s)}</span>}
                  {r0?.tag.attempt != null && (
                    <span>
                      第 {r0.tag.attempt}
                      {r0.tag.max_attempts ? `/${r0.tag.max_attempts}` : ""} 次
                    </span>
                  )}
                  {!r0 && c.thumb && <span>最近出图：{c.thumb.what}</span>}
                </div>
              </div>
            </div>
          )}
          <div className="gl-hw">
            <div className="gpu-metric">
              <span>利用率 {hw?.util ?? "—"}%</span>
              <Bar value={hw?.util ?? 0} max={100} cls={state} />
            </div>
            <div className="gpu-metric">
              <span>
                显存 {((hw?.vram_used_mb ?? 0) / 1024).toFixed(1)}/{(vtot / 1024).toFixed(0)} GB
              </span>
              <Bar value={hw?.vram_used_mb ?? 0} max={vtot} cls="mem" />
            </div>
          </div>
          {c.pending.length > 0 && (
            <div className="gl-q">
              排队 {c.queue_len}
              {c.queue_eta_s ? ` · 全部做完约 ${fmtS(c.queue_eta_s)}` : ""}
              <ol>
                {c.pending.slice(0, 3).map((p) => (
                  <li key={p.prompt_id} title={p.what}>
                    {p.what}
                    {p.starts_in_s ? <span className="gpu-muted"> · 约 {fmtS(p.starts_in_s)} 后开始</span> : null}
                  </li>
                ))}
              </ol>
            </div>
          )}
          {c.other_procs.length > 0 && (
            <div className="gl-other">其他进程：{c.other_procs.map((o) => `${o.user ?? "?"} · ${o.what} · ${((o.vram_mb ?? 0) / 1024).toFixed(1)} GB`).join("；")}</div>
          )}
          <details className="gpu-tech">
            <summary>技术细节</summary>
            <dl className="gpu-kv">
              <dt>ComfyUI</dt>
              <dd>
                {c.comfy
                  ? `${c.comfy.url}${c.comfy.port ? ` → 远端 :${c.comfy.port}` : ""}${c.comfy.reachable === false ? `（连不上：${c.comfy.error ?? ""}）` : ""}`
                  : "这张卡没有渲染道"}
              </dd>
              {lane?.lock && (
                <>
                  <dt>占用锁</dt>
                  <dd>{lane.lock}</dd>
                </>
              )}
              {r0 && (
                <>
                  <dt>任务</dt>
                  <dd title={r0.prompt_id}>
                    {r0.prompt_id.slice(0, 8)}…{r0.progress?.source ? ` · 步数来自${r0.progress.source}` : ""}
                  </dd>
                </>
              )}
              <dt>最近完成</dt>
              <dd>
                {c.recent.length
                  ? c.recent.slice(0, 3).map((x, i) => (
                      <div key={i}>
                        {x.ok ? "✓" : "✕"} {x.what}
                      </div>
                    ))
                  : "—"}
              </dd>
              <dt>读数</dt>
              <dd>{c.hw_age_s != null ? `${Math.max(0, Math.round(c.hw_age_s))} 秒前（nvidia-smi 经 ssh，每 5 秒）` : "nvidia-smi 读不到"}</dd>
            </dl>
          </details>
        </>
      )}
    </section>
  );
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

function GpuRow({ g, lane }: { g: Gpu; lane?: LaneInfo }) {
  // fredw-92/UXF5（R2）：有道表时忙 / 闲按道表算（与顶栏“卡 x/y 忙”同一口径），硬件读数照旧
  const laneBusy = lane ? lane.reachable && lane.activity !== "idle" : g.busy;
  const state = g.faulty ? "faulty" : g.locked_idle ? "warn" : laneBusy ? "busy" : g.paused ? "paused" : "idle";
  const label = g.faulty
    ? "坏卡 · 不用"
    : lane
      ? laneState(lane)
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
        <b title={cardTip(g.id)}>{cardName(g.id)}</b>
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
          <div className="gpu-who">
            {lockWord(g.train_lock) ?? (g.paused ? g.paused : g.busy ? "在渲染 / 计算" : "没人占用")}
          </div>
          <details className="gpu-tech">
            <summary>技术细节</summary>
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
          </details>
        </>
      )}
    </section>
  );
}

/** fredw-92/G36：GET /api/render/lanes（全部渲染道的当前活动）；接口没有（旧 API）→ null，按钮回落旧文字
 *  fredw-92/UXF5（审查 R2 / #3）：道表改用 v3/edit/lanes.ts 的共享读数（全站一份轮询，首屏先用上次读到的道表），
 *  顶栏“卡 x/y 忙”和面板列出的卡是同一份 lanes：gpu33 一组、gpu36 一组；坏卡（gpu33·卡2）不在道表里，不计数。 */
const ACT_SHORT: Record<string, string> = { image: "出图", video: "出视频", external: "在出", idle: "空闲", train: "训练占用" };

const laneBusy = (l: LaneInfo) => l.reachable && l.activity !== "idle";

/** 顶栏入口：按钮上直接显示忙卡数；有“锁着但空闲”时变警示色 */
/** v3.1 §4.1（fredw-92/U1）：labels="cards" 时按钮写每条道在做什么；labels="short" 只写“卡 3/5 忙”；不传保持旧文字 */
export function GpuButton({ labels, className }: { labels?: "cards" | "short"; className?: string } = {}) {
  const [open, setOpen] = useState(false);
  // GPUVIEW：渲染任务中心里点卡名 → 打开这里
  useEffect(() => {
    const h = () => (refreshLanes(), setOpen(true));
    window.addEventListener("ns:gpu-open", h);
    return () => window.removeEventListener("ns:gpu-open", h);
  }, []);
  // 硬件读数（温度 / 显存 / 进程，只有 gpu33）只在面板打开或旧按钮时轮询
  const { data, err } = useGpus(open || !labels);
  const usable = data?.gpus.filter((g) => !g.faulty) ?? [];
  const busy = usable.filter((g) => g.busy).length;
  const warn = usable.some((g) => g.locked_idle);
  const { lanes, err: laneErr, stale } = useLaneStore();
  const tip = (lanes ?? []).map((l) => `${cardName(l.gpu)} · ${laneState(l)}`).join(String.fromCharCode(10));
  const drawer = open && <GpuDrawer data={data} err={err} lanes={lanes} onClose={() => setOpen(false)} />;
  const toggle = () => {
    if (!open) refreshLanes();
    setOpen((o) => !o);
  };
  const infraDead = useInfra().dead;
  const fac = useFactory().data;
  if (labels === "short") {
    // fredw-92/UXF1：顶栏只放一个短胶囊“卡 3/5 忙”，每条道在干什么放进点开的 GPU 面板（悬停也能看）
    const n = lanes?.length ?? 0;
    const up = lanes?.filter((l) => l.reachable) ?? [];
    const busyN = (lanes ?? []).filter(laneBusy).length;
    // UIRSI r38：顶栏旁边有了“连接 N/6”胶囊，这里不再重复“· N 离线”（离线几张仍在悬停提示和面板里）
    // r42（顶栏“卡 0/7 忙”误报）：:8800 刚起时道还在探测，不能当“空闲”数——探测中的道不进分母，全部在探测时写“探测中”
    const probing = (lanes ?? []).filter((l) => l.probing).length;
    const known = n - probing;
    const old = !lanes ? (laneErr ? "卡状态读不到" : null) : !n ? "卡 —" : !known ? "卡 探测中…" : `卡 ${busyN}/${known} 忙${probing ? ` · ${probing} 探测中` : ""}${up.length < known && infraDead ? ` · ${known - up.length} 离线` : ""}`;
    // r43（OVERVIEW_REDESIGN K1）：顶栏按 5 条出图道写“出图 N/5 道在出”（在跑 / 最近 60 s 出过 / 卡利用率 > 30% 都算在出；长镜头道、笔记本道在面板里单列）
    const text = fac?.total ? `出图 ${fac.busy ?? 0}/${fac.total} 道在出` : old;
    return (
      <>
        <button className={`${className ?? "gpu-btn"}${busyN ? " busy" : ""}${stale ? " stale" : ""}`} onClick={toggle}
          title={(stale ? "上次读到的状态，正在刷新…" + String.fromCharCode(10) : "") + (tip || "显卡状态")}>
          {text ?? <span className="gpu-skel" aria-label="正在读显卡状态" />}
        </button>
        {drawer}
      </>
    );
  }
  if (labels === "cards" && lanes && lanes.length) {
    // fredw-92/G36：卡不再固定“出图卡 / 视频卡”——每条渲染道（gpu33 + gpu36）显示“道名 · 正在出图 / 出视频 / 空闲”
    const anyBusy = lanes.some(laneBusy);
    const short = (l: LaneInfo) => `${cardName(l.gpu)} ${l.reachable ? ACT_SHORT[l.activity] ?? l.activity : "离线"}`;
    return (
      <>
        <button className={`${className ?? "gpu-btn"}${anyBusy ? " busy" : ""}`} onClick={toggle} title={tip}>
          {lanes.map(short).join(" · ")}
        </button>
        {drawer}
      </>
    );
  }
  if (labels === "cards") {
    const card = (id: number) => {
      const g = data?.gpus.find((x) => x.id === id);
      return !g ? "—" : g.faulty ? "故障" : g.busy ? "忙" : "空闲";
    };
    const a = card(0);
    const b = card(3);
    return (
      <>
        <button className={`${className ?? "gpu-btn"}${a === "忙" || b === "忙" ? " busy" : ""}`} onClick={toggle} title={`出图卡 = ${cardName(0)}，视频卡 = ${cardName(3)}；点开看每张卡的详情`}>
          {data ? `出图卡 ${a} · 视频卡 ${b}` : err ? "显卡状态读不到" : "显卡…"}
        </button>
        {drawer}
      </>
    );
  }
  return (
    <>
      <button className={`gpu-btn${warn ? " warn" : ""}`} onClick={toggle} title="显卡实时状态">
        GPU {data ? `${busy}/${usable.length} 忙` : err ? "连不上" : "…"}
        {warn && " · 有卡锁着闲置"}
      </button>
      {drawer}
    </>
  );
}

/** 一条渲染道（gpu36 等读不到硬件的机器只写在做什么，硬件读数写“读不到”） */
function LaneRow({ l, g }: { l: LaneInfo; g: Gpu | null }) {
  if (g) {
    return (
      <div className="gpu-lane">
        <GpuRow g={g} lane={l} />
      </div>
    );
  }
  const state = !l.reachable ? "faulty" : l.lock ? "warn" : laneBusy(l) ? "busy" : "idle";
  return (
    <section className={`gpu-row ${state}`}>
      <header>
        <b title={cardTip(l.gpu)}>{cardName(l.gpu)}</b>
        <span className={`gpu-state ${state}`}>{laneState(l)}</span>
        <span className="grow" />
        <span className="gpu-muted">温度 / 显存读不到</span>
      </header>
      <div className="gpu-who">
        {!l.reachable ? "连不上这张卡" : l.lock ?? (l.activity === "idle" ? "没人占用" : `${ACT_SHORT[l.activity] ?? "在跑"}${l.queued > 1 ? ` · 队列 ${l.queued}` : ""}`)}
      </div>
    </section>
  );
}

function GpuDrawer({ data, err, lanes, onClose }: { data: GpuData | null; err: string | null; lanes: LaneInfo[] | null; onClose: () => void }) {
  const live = useGpuLive(true);
  // UIRSI r38（项目方：“uiux加个实时连接状态”）：面板顶部一块连接状态；卡片“连不上”带原因；全部卡都连不上时只在顶部说一次
  const { data: infra } = useInfra();
  const usableCards = live?.cards.filter((c) => !c.faulty) ?? [];
  const allDown = usableCards.length > 0 && usableCards.every((c) => { const k = linkOf(c, infra); return !!k && !k.offline; });
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  // 按机器分组；gpu33 的道配上硬件读数（同编号的卡）
  const groups = new Map<string, LaneInfo[]>();
  for (const l of lanes ?? []) {
    const m = /^([a-z]+\d+):/i.exec(l.id);
    const k = l.server || (m ? m[1] : "其他");
    groups.set(k, [...(groups.get(k) ?? []), l]);
  }
  const hw = (l: LaneInfo): Gpu | null =>
    (l.server === "gpu33" || l.server === "gpu3" || !l.server) && typeof l.gpu === "number" ? data?.gpus.find((g) => g.id === l.gpu && !g.faulty) ?? null : null;
  const faulty = data?.gpus.filter((g) => g.faulty) ?? [];
  const total = lanes?.length ?? 0;
  const busyN = (lanes ?? []).filter(laneBusy).length;
  return (
    <aside className="gpu-drawer" role="dialog" aria-label="GPU 实时状态">
      <header className="gpu-drawer-head">
        <b>显卡实时状态</b>
        <span className="gpu-muted">{lanes ? `${total} 张卡 · ${busyN} 张忙` : ""}{data ? ` · 更新于 ${data.at.slice(11)}` : ""}</span>
        <span className="grow" />
        <button className="btn-mini" onClick={onClose}>
          关闭 Esc
        </button>
      </header>
      {infra && <InfraPanel d={infra} compact />}
      {allDown && (
        <div className="gpu-err">
          全部卡都连不上：{infra ? (infra.relay.ok ? "到服务器的连接断了，正在自动重连" : "跳板断了，等跳板恢复后自动重连") : `已 ${Math.max(...usableCards.map((c) => linkOf(c, infra)?.down_s ?? 0))} 秒`}（下面每张卡不再逐张重复）
        </div>
      )}
      {err && <div className="gpu-err">温度 / 显存读取失败：{err}</div>}
      {data && !live && (!data.sources.bridge || !data.sources.ssh) && (
        <div className="gpu-err">
          {!data.sources.bridge && "渲染机连不上；"}
          {!data.sources.ssh && "温度 / 进程读不到；"}部分数据缺失
        </div>
      )}
      {live && live.cards.length ? (
        [...new Set(live.cards.map((c) => c.server))].map((srv) => {
          const cs = live.cards.filter((c) => c.server === srv);
          const h = live.hosts[srv];
          const bad = cs.filter((c) => c.faulty).length;
          return (
            <div key={srv} className="gpu-group">
              <div className="gpu-group-head">
                {srv} · {cs.length - bad} 张卡{bad ? ` + ${bad} 张坏卡` : ""}{" "}
                {h?.guard && h.guard.level >= 1 ? (
                  <span className="gl-thr" title="gpu36 内存温度守护：内存温度 ≥70 ℃ 时把 GPU 功耗墙压到 200 W（≥78 ℃ 压到 100 W），降温 10 分钟后恢复">
                    温控守护：{h.guard.name}
                  </span>
                ) : null}
                {h && !h.ok ? <span className="gpu-muted">（温度 / 显存读不到：{h.err ?? "连接中"}）</span> : null}
              </div>
              {cs.map((c) => (
                <LiveCard key={c.id} c={c} lane={(lanes ?? []).find((l) => l.id === c.lane)} infra={infra} merged={allDown} />
              ))}
            </div>
          );
        })
      ) : lanes
        ? [...groups.entries()].map(([server, ls]) => (
            <div key={server} className="gpu-group">
              <div className="gpu-group-head">
                {server} · {ls.length} 张卡
              </div>
              {ls.map((l) => (
                <LaneRow key={l.id} l={l} g={hw(l)} />
              ))}
            </div>
          ))
        : data?.gpus.filter((g) => !g.faulty).map((g) => <GpuRow key={g.id} g={g} />)}
      {live && live.heartbeats.length > 0 && (
        <section className="gpu-row busy">
          <header>
            <b>其他 GPU 任务（心跳）</b>
          </header>
          {live.heartbeats.map((b, i) => (
            <div key={i} className="gpu-task">
              {b.agent} · {b.label}
            </div>
          ))}
        </section>
      )}
      {faulty.length > 0 && !live && <div className="gpu-muted">不计入：{faulty.map((g) => cardName(g.id)).join("、")}（坏卡，不派活）</div>}
      {data && (
        <section className="gpu-row">
          <header>
            <b>写作信箱</b>
            <span className="gpu-muted">{data.qwen.reachable ? `运行 ${data.qwen.running} · 排队 ${data.qwen.queued}` : "连不上"}</span>
          </header>
          {data.qwen.tasks.map((t) => (
            <div key={t.id} className="gpu-task">
              <span className={`gpu-state ${t.status === "running" ? "busy" : "idle"}`}>{t.status === "running" ? "运行" : "排队"}</span> {t.id}
              <span className="gpu-muted"> · {t.from}</span>
            </div>
          ))}
        </section>
      )}
      <div className="gpu-note">整集出片请用顶栏的「整集出片」：开始前会显示镜数、预计时长和用哪些卡。</div>
    </aside>
  );
}

export default GpuButton;
