// fredw-92/EB：整集出片——集头按钮 + 小窗（阶段 / 模式 / 档位）+ 进度条（每镜三个点：首帧·尾帧·视频，在哪条道，总预计）
// 后端：POST/GET /api/episodes/{n}/produce、POST …/produce/cancel（services/api/ns_api/episode_produce.py）。
// 片段条上的小点（ProduceClipDots）读同一份进度，不另请求。
import { useEffect, useState, useSyncExternalStore } from "react";
import { useStudio } from "../store";
import { Pop } from "./widgets";
import "./produce.css";

type Stage = "first" | "last" | "video";
type StageState = "pending" | "ready" | "queued" | "running" | "review" | "done" | "skipped" | "failed" | "blocked" | "waiting" | "cancelled";
export type ProduceStage = {
  state: StageState;
  step?: "gen" | "final" | "video" | null;
  gpu?: number | null;
  lane?: string | null;
  take?: number | null;
  reason?: string | null;
  error?: string | null;
  frames?: number | null;
  locked_by?: string | null;
  eta_s?: number;
};
export type ProduceView = {
  episode: number;
  id?: string;
  state: "none" | "running" | "waiting" | "done" | "cancelled";
  mode?: "auto_lock" | "review";
  stages?: Stage[];
  eta_s: number;
  counts?: Record<string, number>;
  lanes: { gpu: number; label?: string; ok?: boolean; image_pref?: boolean; max_frames?: number; busy_with: { shot_id: string; stage: Stage; state: string; step?: string }[] }[];
  shots: { shot_id: string; eta_s: number; stages: Partial<Record<Stage, ProduceStage>> }[];
  failures?: { shot_id: string; stage: Stage; state: string; reason?: string; error?: string }[];
};

const STAGE_LABEL: Record<Stage, string> = { first: "首帧", last: "尾帧", video: "视频" };
const STATE_LABEL: Record<StageState, string> = {
  pending: "等前一步",
  ready: "待派道",
  queued: "排队",
  running: "生成中",
  review: "等你定稿",
  done: "完成",
  skipped: "已是最新，跳过",
  failed: "失败",
  blocked: "卡住",
  waiting: "等待",
  cancelled: "已取消",
};
const DOT: Record<StageState, string> = {
  pending: "gray",
  ready: "gray",
  queued: "blue",
  running: "blue",
  review: "yellow",
  done: "green",
  skipped: "green",
  failed: "red",
  blocked: "red",
  waiting: "yellow",
  cancelled: "gray",
};

// ---------------------------------------------------------------- 共享进度（集号 → 视图）
const views = new Map<number, ProduceView>();
const subs = new Set<() => void>();
const emit = () => subs.forEach((f) => f());
const subscribe = (f: () => void) => (subs.add(f), () => void subs.delete(f));
const set = (v: ProduceView) => (views.set(v.episode, v), emit());

async function call<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const b = await r.json();
      if (b?.detail) msg = typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    } catch {
      /* 非 JSON */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}
const base = (n: number) => `/api/episodes/${n}/produce`;
const active = (v?: ProduceView) => v?.state === "running" || v?.state === "waiting";

/** 轮询本集进度：在跑时 5 s 一次，否则 30 s；有阶段刚完成 → 刷新这些镜头的画布数据 */
function useProducePoll(ep: number) {
  const { refreshAfter } = useStudio();
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    let prevDone = new Set<string>();
    const tick = async () => {
      try {
        const v = await call<ProduceView>(base(ep));
        if (!alive) return;
        set(v);
        const done = new Set(v.shots.flatMap((s) => Object.entries(s.stages).filter(([, x]) => x?.state === "done").map(([k]) => `${s.shot_id}/${k}`)));
        const fresh = [...done].filter((k) => !prevDone.has(k)).map((k) => k.split("/")[0]);
        if (prevDone.size && fresh.length) void refreshAfter([...new Set(fresh)]);
        prevDone = done;
      } catch {
        /* 后端未就绪：不显示 */
      }
      if (alive) timer = window.setTimeout(tick, active(views.get(ep)) ? 5000 : 30000);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [ep, refreshAfter]);
}

export function useProduceView(ep: number): ProduceView | undefined {
  return useSyncExternalStore(subscribe, () => views.get(ep));
}

const fmt = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)} 小时 ${Math.round((s % 3600) / 60)} 分` : s >= 60 ? `${Math.round(s / 60)} 分钟` : `${Math.round(s)} 秒`);
const short = (id: string) => id.split("-")[1] ?? id;
const stageTitle = (st: Stage, x?: ProduceStage) =>
  !x
    ? `${STAGE_LABEL[st]}：本次不出`
    : `${STAGE_LABEL[st]}：${STATE_LABEL[x.state]}${x.step === "final" ? "（定稿档）" : ""}${x.lane ? ` · ${x.lane}` : x.gpu != null ? ` · GPU${x.gpu}` : ""}${x.take != null ? ` · v${x.take}` : ""}${x.locked_by === "auto" ? " · 自动测试定稿" : ""}${x.reason ? `\n${x.reason}` : ""}${x.error && x.state === "failed" ? `\n${x.error}` : ""}`;

/** 片段条每个镜头上的三个小点（首帧 · 尾帧 · 视频）；本集没有整集出片时不显示 */
export function ProduceClipDots({ ep, shotId }: { ep: number; shotId: string }) {
  const v = useProduceView(ep);
  const row = v && v.state !== "none" ? v.shots.find((s) => s.shot_id === shotId) : undefined;
  if (!row) return null;
  return (
    <span className="v3-prod-clip" aria-label="整集出片进度">
      {(["first", "last", "video"] as Stage[]).map((st) => (
        <i key={st} className={`p-${row.stages[st] ? DOT[row.stages[st]!.state] : "none"}${row.stages[st]?.state === "running" ? " live" : ""}`} title={stageTitle(st, row.stages[st])} />
      ))}
    </span>
  );
}

/** 集头：整集出片按钮 + 进度条 */
export function ProduceButton({ ep }: { ep: number }) {
  useProducePoll(ep);
  const v = useProduceView(ep);
  const { notify } = useStudio();
  const [stages, setStages] = useState<Record<Stage, boolean>>({ first: true, last: true, video: true });
  const [mode, setMode] = useState<"auto_lock" | "review">("auto_lock");
  const [tier, setTier] = useState<"" | "preview" | "final">("");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const running = active(v);

  const start = async (close: () => void) => {
    setBusy(true);
    try {
      const body = { stages: (Object.keys(stages) as Stage[]).filter((k) => stages[k]), mode, tier_first: tier || undefined, force, by: "canvas" };
      set(await call<ProduceView>(base(ep), body));
      notify(`第 ${ep} 集整集出片已开始：按镜头铺到所有空闲的卡`);
      close();
    } catch (e) {
      notify(`整集出片没开始：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };
  const cancel = async () => {
    try {
      set(await call<ProduceView>(`${base(ep)}/cancel`, {}));
      notify("整集出片已取消（在跑的任务已请求中断）");
    } catch (e) {
      notify(`取消失败：${(e as Error).message}`, "err");
    }
  };

  const c = v?.counts ?? {};
  const doneN = (c.done ?? 0) + (c.skipped ?? 0);
  const totalN = Object.values(c).reduce((a, b) => a + b, 0);
  return (
    <div className="v3-prod">
      <Pop label={<>整集出片{running ? " ●" : ""}</>} btnClass="v3-btn" title="把本集按镜头平均分到所有可用的卡上并行出（首帧 → 尾帧 → 视频）">
        {(close) => (
          <div className="v3-prod-dlg">
            <b>第 {ep} 集 · 整集出片</b>
            {running ? (
              <>
                <p className="v3-prod-hint">正在跑（{v?.mode === "review" ? "逐步审" : "自动测试定稿"}）：{doneN}/{totalN} 步完成，预计还要 {fmt(v?.eta_s ?? 0)}。</p>
                <button className="v3-btn" onClick={() => void cancel()}>
                  取消整集出片
                </button>
              </>
            ) : (
              <>
                <fieldset>
                  <legend>出哪些</legend>
                  {(["first", "last", "video"] as Stage[]).map((k) => (
                    <label key={k}>
                      <input type="checkbox" checked={stages[k]} onChange={(e) => setStages({ ...stages, [k]: e.target.checked })} /> {STAGE_LABEL[k]}
                    </label>
                  ))}
                </fieldset>
                <fieldset>
                  <legend>定稿方式</legend>
                  <label title="每步出完自动定稿（记为“自动测试定稿”，你之后可以重新审）">
                    <input type="radio" checked={mode === "auto_lock"} onChange={() => setMode("auto_lock")} /> 自动测试定稿
                  </label>
                  <label title="首帧 / 尾帧出完停下，等你在画布定稿后自动接着走">
                    <input type="radio" checked={mode === "review"} onChange={() => setMode("review")} /> 每步等我定稿
                  </label>
                </fieldset>
                <fieldset>
                  <legend>首尾帧档位</legend>
                  <select value={tier} onChange={(e) => setTier(e.target.value as typeof tier)}>
                    <option value="">按配置（定稿后自动出定稿档）</option>
                    <option value="preview">只出预览档（快）</option>
                    <option value="final">定稿档（预览 → 定稿档）</option>
                  </select>
                </fieldset>
                <label title="已定稿且不过期的阶段默认跳过；勾上则重出新版本（旧版本保留）">
                  <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 已是最新的也重出
                </label>
                <button className="v3-btn primary" disabled={busy || !Object.values(stages).some(Boolean)} onClick={() => void start(close)}>
                  开始
                </button>
                <p className="v3-prod-hint">超过显存上限的长镜头会等待（不截短）。</p>
              </>
            )}
          </div>
        )}
      </Pop>
      {v && v.state !== "none" && <ProduceStrip v={v} />}
    </div>
  );
}

function ProduceStrip({ v }: { v: ProduceView }) {
  const running = active(v);
  const lanes = v.lanes.filter((l) => l.ok !== false);
  return (
    <Pop
      label={
        <span className="v3-prod-strip">
          {v.shots.map((s) => (
            <span key={s.shot_id} className="v3-prod-shot" title={`${short(s.shot_id)}\n${(["first", "last", "video"] as Stage[]).map((st) => stageTitle(st, s.stages[st])).join("\n")}`}>
              {(["first", "last", "video"] as Stage[]).map((st) => (s.stages[st] ? <i key={st} className={`p-${DOT[s.stages[st]!.state]}${s.stages[st]!.state === "running" ? " live" : ""}`} /> : null))}
            </span>
          ))}
          <small>{running ? `约 ${fmt(v.eta_s)}` : v.state === "done" ? "完成" : v.state === "cancelled" ? "已取消" : ""}</small>
        </span>
      }
      btnClass="v3-prod-stripbtn"
      title="整集出片进度：每镜三个点 = 首帧 · 尾帧 · 视频；点开看每条道在跑什么"
    >
      {() => (
        <div className="v3-prod-detail">
          <b>
            整集出片 · {v.state === "running" ? "进行中" : v.state === "waiting" ? "等待中" : v.state === "done" ? "已完成" : "已取消"}
            {running ? ` · 预计还要 ${fmt(v.eta_s)}` : ""}
          </b>
          <h4>渲染道</h4>
          <ul>
            {lanes.map((l) => (
              <li key={l.gpu}>
                <span>{l.label ?? `GPU${l.gpu}`}</span>
                <small>{l.busy_with.length ? l.busy_with.map((b) => `${short(b.shot_id)} ${STAGE_LABEL[b.stage]}${b.step === "final" ? "（定稿档）" : ""} ${b.state === "running" ? "生成中" : "排队"}`).join("，") : "空闲"}</small>
              </li>
            ))}
          </ul>
          <h4>镜头</h4>
          <table>
            <tbody>
              {v.shots.map((s) => (
                <tr key={s.shot_id}>
                  <th>{short(s.shot_id)}</th>
                  {(["first", "last", "video"] as Stage[]).map((st) => {
                    const x = s.stages[st];
                    return (
                      <td key={st} title={stageTitle(st, x)}>
                        {x ? (
                          <>
                            <i className={`p-${DOT[x.state]}`} /> {STAGE_LABEL[st]} {STATE_LABEL[x.state]}
                            {x.gpu != null && (x.state === "running" || x.state === "queued") ? ` · GPU${x.gpu}` : ""}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {!!v.failures?.length && (
            <>
              <h4>失败 / 等待</h4>
              <ul>
                {v.failures.map((f) => (
                  <li key={`${f.shot_id}/${f.stage}`}>
                    {short(f.shot_id)} {STAGE_LABEL[f.stage]}：{f.reason ?? f.error}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </Pop>
  );
}
