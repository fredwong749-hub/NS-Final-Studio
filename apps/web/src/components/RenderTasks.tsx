// GPUVIEW（11-01）：渲染任务中心——顶栏“渲染任务”抽屉和画布底栏“任务队列”是同一份数据（GET /api/render-tasks，
// 后端 ns_api/render_tasks.py）、同一个行组件 TaskRow，不再有两套任务界面。
// 项目方原话：“顶部我需要一个rendering任务tasks,告知我现在整个系统需要rendering的任务(剧本,镜头,图片,视频等细节)
//   一个all,pending,rending状态对应的objects”；底栏：“这里uiux设计头不喜欢,展示内容也很快,你思考重构”。
// 行：人话标题 + 缩略图（可放大，全站 ZoomLayer）+ 谁 / 哪张卡 + 进度条（UIRSI 分段条的同一套样式）+ 已用时 / 第几次 + 状态；
//   哈希 id 只在悬停 / 复制；时间写“3 分钟前”（悬停看绝对时间）；报错写人话（发生了什么 / 系统已经做了什么 / 接下来），原文收进“技术详情”。
// 分组：集 → 镜头；同一镜同一类只显示最新一次，其余收进“历史 N 次”。排序：渲染中 → 等待 → 失败（未解决）→ 已完成。
// 实时：每 4 秒 + /api/events 事件来了立即重取；行内容变了柔和闪一下（useFlash）。
// 后端还没有 /api/render-tasks（API 未重启）时，用 /api/jobs 在前端拼一份（只有画布任务），界面照常可用。
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Tabs, Tag, type Tone } from "../ds";
import { useFlash } from "../v3/live";
import { type RTData, type RTFilter, type RTRow, type RTStatus, ago, countRows, filterRows, fmtS, useRenderTasks } from "./RenderTasks.helpers";
import "../ds/live.css";
import "./rendertasks.css";

const ST_LABEL: Record<RTStatus, string> = { rendering: "渲染中", pending: "等待", failed: "失败", done: "已完成" };
const ST_TONE: Record<RTStatus, Tone> = { rendering: "busy", pending: "neutral", failed: "bad", done: "ok" };
const ORDER: Record<RTStatus, number> = { rendering: 0, pending: 1, failed: 2, done: 3 };
const openGpu = () => window.dispatchEvent(new CustomEvent("ns:gpu-open"));

/** 单个任务的进度条（UIRSI 分段条的同一套样式 sp-*）：有步数按步数；只有预计时间按已用 / (已用 + 剩余)；都没有就微光 */
export function StepBar({ r }: { r: RTRow }) {
  const p = r.progress;
  let pct: number | null = null;
  let label = "";
  if (p?.steps) {
    pct = ((p.step ?? 0) / p.steps) * 100;
    label = `第 ${p.step}/${p.steps} 步`;
  } else if (p?.pct != null) {
    pct = p.pct;
    label = `${Math.round(p.pct)}%`;
  } else if (r.elapsed_s != null && r.eta_s != null && r.elapsed_s + r.eta_s > 0) {
    pct = (r.elapsed_s / (r.elapsed_s + r.eta_s)) * 100;
    label = `约 ${Math.round(pct)}%`;
  }
  const run = r.status === "rendering";
  return (
    <div className="rt-bar" title={p?.source ? `进度来自 ${p.source}` : r.eta_s != null ? "按这条道最近同类任务的耗时估算" : "还没有进度读数"}>
      <div className="sp-track">
        {pct != null && <div className="sp-fill" style={{ width: `${Math.min(100, pct)}%` }} />}
        {run && <div className="sp-run" style={{ left: `${pct != null ? Math.min(96, pct) : 0}%`, width: pct != null ? "12%" : "100%" }} />}
      </div>
      <span className="rt-bar-txt">
        {label}
        {r.eta_s != null && run ? `${label ? " · " : ""}${r.eta_s < 5 ? "已超过同类平均耗时，应快完成" : `还要约 ${fmtS(r.eta_s)}`}` : ""}
        {r.status === "pending" && r.eta_s ? `约 ${fmtS(r.eta_s)} 后开始` : ""}
        {run && pct == null && r.eta_s == null ? "进行中（这类任务还没有耗时记录）" : ""}
      </span>
    </div>
  );
}

function copy(text: string) {
  try {
    void navigator.clipboard.writeText(text);
  } catch {
    /* 无剪贴板权限 */
  }
}

/** 一行任务（顶栏抽屉和底栏共用） */
export function TaskRow({ r, history, compact, onOpen }: { r: RTRow; history?: RTRow[]; compact?: boolean; onOpen?: (r: RTRow) => void }) {
  const flash = useFlash([r.status, r.sub, r.progress?.step, r.attempt, r.thumb]);
  const [showHist, setShowHist] = useState(false);
  const t = ago(r.at ?? r.started);
  const tech = [r.ids.job_id && `任务 ${r.ids.job_id}`, r.ids.prompt_id && `ComfyUI ${r.ids.prompt_id}`, r.ids.client_id && `client ${r.ids.client_id}`, r.ids.seed != null && r.ids.seed !== "" && `种子 ${r.ids.seed}`, `来源 ${r.source}`]
    .filter(Boolean)
    .join(" · ");
  const open = () => (onOpen ? onOpen(r) : r.link ? (location.hash = r.link) : undefined);
  return (
    <div className={`rt-row st-${r.status}${flash ? " live-flash" : ""}${compact ? " compact" : ""}`} data-rt-id={r.id}>
      <div className="rt-thumb" data-zoom-label={r.title}>
        {r.thumb ? <img src={r.thumb} data-full={r.full ?? r.thumb} alt={r.title} loading="lazy" /> : <span aria-hidden="true">{r.type.slice(0, 2)}</span>}
      </div>
      <div className="rt-main">
        <div className="rt-l1">
          {r.link ? (
            <a className="rt-title" onClick={open} title={`打开：${r.title}`}>
              {r.title}
            </a>
          ) : (
            <b className="rt-title">{r.title}</b>
          )}
          <Tag tone={r.sub === "失败后已重试成功" ? "warn" : ST_TONE[r.status]} size="s" pill>
            {r.sub === "失败后已重试成功" ? "已重试成功" : ST_LABEL[r.status]}
          </Tag>
          {r.sub && r.sub !== ST_LABEL[r.status] && r.sub !== "失败后已重试成功" && <span className="rt-sub">{r.sub}</span>}
        </div>
        <div className="rt-l2">
          {r.agent && <span title="谁在做">{r.agent}</span>}
          {r.lane && (
            <a className="rt-lane" onClick={openGpu} title="打开显卡实时状态">
              {r.lane.replace(":", "·卡")}
            </a>
          )}
          {r.elapsed_s != null && <span>{r.status === "rendering" ? "已跑" : "用时"} {fmtS(r.elapsed_s)}</span>}
          {r.stage_since != null && (r.status === "rendering" || r.status === "pending") && <span title="当前阶段已用时">本段 {fmtS(Date.now() / 1000 - r.stage_since)}</span>}
          {r.attempt != null && <span>第 {r.attempt}{r.max_attempts ? `/${r.max_attempts}` : ""} 次</span>}
          {r.batch?.idx && <span>第 {r.batch.idx}/{r.batch.total} 张</span>}
          {t.text && <span title={t.abs}>{t.text}</span>}
          <span className="grow" />
          {tech && (
            <button className="rt-id" title={`${tech}\n点击复制`} onClick={() => copy(tech)}>
              ⧉
            </button>
          )}
        </div>
        {(r.status === "rendering" || (r.status === "pending" && r.eta_s)) && <StepBar r={r} />}
        {r.error && (
          <div className={`rt-err${r.error.resolved_text ? " ok" : ""}`}>
            <span>{r.error.what}</span>
            {r.error.resolved_text ? <span className="rt-fixed">{r.error.resolved_text}</span> : r.error.next && <span className="rt-next">接下来：{r.error.next}</span>}
            {r.error.raw && (
              <details>
                <summary>技术详情</summary>
                <pre>{r.error.raw}</pre>
              </details>
            )}
          </div>
        )}
        {history && history.length > 0 && (
          <div className="rt-hist">
            <button className="rt-hist-btn" onClick={() => setShowHist((x) => !x)}>
              历史 {history.length} 次 {showHist ? "▾" : "▸"}
            </button>
            {showHist && history.map((h) => <TaskRow key={h.id} r={h} compact onOpen={onOpen} />)}
          </div>
        )}
      </div>
    </div>
  );
}

type TabKey = "all" | RTStatus;
const TAB_LABEL: [TabKey, string][] = [
  ["all", "全部"],
  ["pending", "等待"],
  ["rendering", "渲染中"],
  ["failed", "失败"],
  ["done", "已完成(最近)"],
];

/** 列表：标签页 + 按集 / 类型筛选 + 集 → 镜头分组（同镜同类只看最新一次，其余收进“历史”）。
 *  filter / onFilter 给了就由外面管筛选（底栏标签上的数字要跟着同一个筛选走） */
export function TaskList({ data, err, defaultEp, defaultTab = "all", compact, onOpen, filter, onFilter }: { data: RTData | null; err?: string | null; defaultEp?: number | null; defaultTab?: TabKey; compact?: boolean; onOpen?: (r: RTRow) => void; filter?: RTFilter; onFilter?: (f: RTFilter) => void }) {
  const [tab, setTab] = useState<TabKey>(defaultTab);
  const [own, setOwn] = useState<RTFilter>({ ep: defaultEp ? String(defaultEp) : "", type: "" });
  const f = filter ?? own;
  const setF = onFilter ?? setOwn;
  const { ep, type } = f;
  const setEp = (v: string) => setF({ ...f, ep: v });
  const setType = (v: string) => setF({ ...f, type: v });
  const rows = useMemo(() => filterRows(data?.rows ?? [], { ep, type }), [data, ep, type]);
  const counts = useMemo(() => countRows(rows), [rows]);
  // 镜头 × 类型：最新一次 + 历史
  const groups = useMemo(() => {
    const shown = rows.filter((r) => tab === "all" || r.status === tab);
    const byKey = new Map<string, RTRow[]>();
    for (const r of shown) {
      const k = r.episode && r.shot && ["首帧", "尾帧", "视频"].includes(r.type) ? `${r.episode}|${r.shot}|${r.type}` : r.id;
      byKey.set(k, [...(byKey.get(k) ?? []), r]);
    }
    // 同镜同类显示哪一条 / 列表顺序：在跑 > 真在排队 > 没解决的失败（说明为什么还要出）> 计划中 > 已完成；同级取最新
    const rank = (r: RTRow) => (r.status === "rendering" ? 0 : r.status === "pending" && r.source !== "plan" ? 1 : r.status === "failed" ? 2 : r.status === "pending" ? 3 : 4);
    const items = [...byKey.values()].map((lst) => {
      lst.sort((a, b) => rank(a) - rank(b) || (b.at ?? 0) - (a.at ?? 0));
      return { head: lst[0], hist: lst.slice(1) };
    });
    items.sort((a, b) => rank(a.head) - rank(b.head) || (a.head.status === "done" ? (b.head.at ?? 0) - (a.head.at ?? 0) : 0));
    const eps = new Map<string, typeof items>();
    for (const it of items) {
      const k = it.head.episode != null ? String(it.head.episode) : "none";
      eps.set(k, [...(eps.get(k) ?? []), it]);
    }
    return [...eps.entries()].sort((a, b) => {
      const ra = Math.min(...a[1].map((x) => ORDER[x.head.status]));
      const rb = Math.min(...b[1].map((x) => ORDER[x.head.status]));
      return ra - rb || (a[0] === "none" ? 1 : b[0] === "none" ? -1 : Number(a[0]) - Number(b[0]));
    });
  }, [rows, tab]);
  const tabCount = (k: TabKey) => counts[k];
  return (
    <div className={`rt-list${compact ? " compact" : ""}`}>
      <div className="rt-tools">
        <Tabs value={tab} onChange={setTab} options={TAB_LABEL.map(([k, l]) => [k, l, tabCount(k)])} />
        <span className="grow" />
        <select value={ep} onChange={(e) => setEp(e.target.value)} title="按集筛选" aria-label="按集筛选">
          <option value="">全部集</option>
          {(data?.episodes ?? []).map((n) => (
            <option key={n} value={String(n)}>
              第 {n} 集
            </option>
          ))}
          <option value="none">不属于某一集（资产 / 对比）</option>
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)} title="按类型筛选" aria-label="按类型筛选">
          <option value="">全部类型</option>
          {(data?.types ?? []).map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      {data?.fallback && <div className="rt-note">只显示画布任务（API 还没更新到渲染任务中心，重启后会并入各 agent 的任务和计划中的镜头）</div>}
      {err && !data && <div className="rt-note bad">读不到渲染任务：{err}</div>}
      {!data && !err && <div className="rt-note">正在读…</div>}
      {data && !groups.length && <div className="rt-note">这里没有任务。</div>}
      {groups.map(([k, items]) => (
        <EpGroup key={k} k={k} items={items} onOpen={onOpen} compact={compact} />
      ))}
    </div>
  );
}

function EpGroup({ k, items, onOpen, compact }: { k: string; items: { head: RTRow; hist: RTRow[] }[]; onOpen?: (r: RTRow) => void; compact?: boolean }) {
  const hot = items.some((x) => x.head.status === "rendering" || x.head.status === "failed");
  const [open, setOpen] = useState(hot || items.length <= 12);
  // 与标签页同一口径：按条数（含收进“历史”的）
  const n = (s: RTStatus) => items.reduce((a, x) => a + [x.head, ...x.hist].filter((r) => r.status === s).length, 0);
  const LIMIT = 40;
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, LIMIT);
  return (
    <section className="rt-ep">
      <button className="rt-ep-h" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <b>{k === "none" ? "资产 / 对比 / 其他" : `第 ${k} 集`}</b>
        <span className="rt-ep-n">
          {n("rendering") ? <em className="busy">渲染中 {n("rendering")}</em> : null}
          {n("pending") ? <em>等待 {n("pending")}</em> : null}
          {n("failed") ? <em className="bad">失败 {n("failed")}</em> : null}
          {n("done") ? <em className="ok">完成 {n("done")}</em> : null}
        </span>
        <span className="grow" />
        <i aria-hidden="true">{open ? "▾" : "▸"}</i>
      </button>
      {open && (
        <div className="rt-rows">
          {shown.map((x) => (
            <TaskRow key={x.head.id} r={x.head} history={x.hist} onOpen={onOpen} compact={compact} />
          ))}
          {items.length > LIMIT && !all && (
            <button className="rt-more" onClick={() => setAll(true)}>
              还有 {items.length - LIMIT} 条，展开
            </button>
          )}
        </div>
      )}
    </section>
  );
}

/** 顶栏入口：替换原“● 生成中 · 排队 · 失败”胶囊；点开右侧抽屉。旧的任务队列页仍可从抽屉头部进入 */
export function RenderTasksButton({ className, onOpenJobsPage, extra, extraTitle, alert }: { className?: string; onOpenJobsPage?: () => void; extra?: ReactNode; extraTitle?: string; alert?: boolean }) {
  const [open, setOpen] = useState(false);
  const { data, err } = useRenderTasks();
  const c = data?.counts;
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open]);
  const flash = useFlash(c ? [c.rendering, c.pending, c.failed] : null);
  const tone = c?.failed || alert ? "bad" : c?.rendering ? "busy" : "ok";
  const tip = c ? `渲染任务：全部 ${c.all} = 等待 ${c.pending} + 渲染中 ${c.rendering} + 失败 ${c.failed} + 已完成 ${c.done}\n点击查看每个任务（剧本 / 分镜 / 首帧 / 尾帧 / 视频 / 音色 / 资产图）` : err ? `读不到：${err}` : "正在读渲染任务";
  return (
    <>
      <button className={`${className ?? ""} rt-btn q-${tone}${flash ? " live-flash" : ""}`} onClick={() => setOpen((o) => !o)}
        title={[extraTitle, tip].filter(Boolean).join("\n")}>
        <i />
        渲染任务
        {c ? (
          <span className="rt-btn-n">
            {" "}
            {c.rendering} 渲染 · {c.pending} 等待
            {c.failed ? <b> · {c.failed} 失败</b> : null}
          </span>
        ) : null}
        {extra}
      </button>
      {open && (
        <aside className="rt-drawer" role="dialog" aria-label="渲染任务">
          <header className="rt-drawer-h">
            <b>渲染任务</b>
            <span className="gpu-muted">
              {c ? `全部 ${c.all} · 更新于 ${(data?.at ?? "").slice(11, 19)}` : ""}
            </span>
            <span className="grow" />
            <button className="btn-mini" onClick={openGpu} title="每张卡在做什么、温度、显存">
              显卡状态
            </button>
            {onOpenJobsPage && (
              <button className="btn-mini" onClick={() => (setOpen(false), onOpenJobsPage())} title="原来的任务队列页（取消 / 重试）">
                任务队列页
              </button>
            )}
            <button className="btn-mini" onClick={() => setOpen(false)}>
              关闭 Esc
            </button>
          </header>
          <TaskList data={data} err={err} defaultEp={null} onOpen={(r) => r.link && (location.hash = r.link)} />
        </aside>
      )}
    </>
  );
}
