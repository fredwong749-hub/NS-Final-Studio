// fredw-92/EB：整集出片——集头按钮 + 小窗（阶段 / 模式 / 档位）+ 进度条（每镜三个点：首帧·尾帧·视频，在哪条道，总预计）
// 后端：POST/GET /api/episodes/{n}/produce、POST …/produce/cancel（services/api/ns_api/episode_produce.py）。
// 片段条上的小点（ProduceClipDots）读同一份进度，不另请求。
// fredw-92/UXF2（审查 #44 / #45）：默认“每步等我定稿”；开始前显示影响面（POST …/produce/plan：镜数 × 阶段、预计、用哪些卡、
//   被 LoRA 训练锁着的卡、长镜头、费用）；这是唯一的整集出片入口（GPU 面板里的“按集渲染”已去掉）。
// fredw-92/UXF4（审查 N1 / N6 / N9 / N7）：开始前列出没过的关口（造型待确认、G4 样片未锁定），有就把“开始”改成“仍然开始（测试）”；
//   超过所有卡单卡上限的长镜头写“无卡可出”，不计入步数和时间；预计只按现在真空闲的卡算；自动测试定稿的步数单列“待你复审”；
//   卡名一律 cardName()（技术细节悬停）。
import { useEffect, useState } from "react";
import { useStudio } from "../store";
import { Pop } from "./widgets";
import { frameState } from "./status";
import { cardName, cardTip, laneState, useLanes } from "./edit/lanes";
import { useSop } from "./sop.helpers";
import { autoFinalText, useRenderSettings } from "./edit/ImageParams.helpers";
import "./produce.css";
import { AUTO_LONG, AUTO_SHORT } from "./words";
import { errSummary } from "../components/Drawer.helpers";
import { useProduceView, views, subs, type ProduceView, type ProduceStage, type Stage, type StageState } from "./EpisodeProduce.helpers";
export type { ProduceView, ProduceStage } from "./EpisodeProduce.helpers";

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

const emit = () => subs.forEach((f) => f());
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
    // UIRSI r16（首屏）：整集出片进度接口慢（2–8 s），晚 1.5 s 再开始轮询，不占首屏的连接
    timer = window.setTimeout(tick, 1500);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [ep, refreshAfter]);
}

const fmt = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)} 小时 ${Math.round((s % 3600) / 60)} 分` : s >= 60 ? `${Math.round(s / 60)} 分钟` : `${Math.round(s)} 秒`);
const short = (id: string) => id.split("-")[1] ?? id;
const stageTitle = (st: Stage, x?: ProduceStage) =>
  !x
    ? `${STAGE_LABEL[st]}：本次不出`
    : `${STAGE_LABEL[st]}：${x.no_lane ? "无卡可出" : x.auto_review ? AUTO_LONG : STATE_LABEL[x.state]}${x.step === "final" ? "（定稿档）" : ""}${x.gpu != null ? ` · ${cardName(x.gpu)}` : ""}${x.take != null ? ` · v${x.take}` : ""}${x.locked_by === "auto" ? ` · ${AUTO_LONG}` : ""}${x.reason ? `\n${x.reason}` : ""}${x.error && x.state === "failed" ? `\n${x.error}` : ""}`;

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

/** POST …/produce/plan 的回答（开始前的影响面；fredw-92/UXF2） */
type ProducePlan = {
  shots: number;
  stages: Stage[];
  steps: Partial<Record<Stage, { run: number; skip: number; review?: number }>>;
  jobs: number;
  eta_s: number;
  work_s?: number;
  final_frames?: boolean;
  max_frames?: number;
  too_long?: { shot_id: string; frames: number }[];
  /** 现在真空闲的卡（预计按它算） */
  free_lanes?: (number | string)[];
  lanes?: { gpu: number | string; id?: string; label?: string; ok?: boolean; image_pref?: boolean; free?: boolean; train_locked?: boolean; activity?: string; load_s?: number }[];
  /** 后端还没有 /plan（旧 API）时按本页数据粗估 */
  local?: boolean;
};

/** 集头：整集出片按钮 + 进度条（全站唯一的整集出片入口；GPU 面板里不再有第二个） */
export function ProduceButton({ ep }: { ep: number }) {
  useProducePoll(ep);
  const v = useProduceView(ep);
  const { notify } = useStudio();
  const running = active(v);

  const cancel = async () => {
    try {
      // UIDEBUG #3：取消接口不收请求体——直接发不带体的 POST
      const r = await fetch(`${base(ep)}/cancel`, { method: "POST" });
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      set((await r.json()) as ProduceView);
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
      <Pop label={<>整集出片{running ? " ●" : ""}</>} btnClass="v3-btn" title="把本集按镜头分到所有可用的卡上并行出（首帧 → 尾帧 → 视频）；开始前先看镜数、预计时长和用哪些卡">
        {(close) => (
          <div className="v3-prod-dlg">
            <b>第 {ep} 集 · 整集出片</b>
            {running ? (
              <>
                <p className="v3-prod-hint">
                  正在跑（{v?.mode === "review" ? "每步等你定稿" : "自动测试定稿"}）：{doneN}/{totalN} 步完成，预计还要 {fmt(v?.eta_s ?? 0)}。
                </p>
                <button className="v3-btn" onClick={() => void cancel()}>
                  取消整集出片
                </button>
              </>
            ) : (
              <ProduceForm ep={ep} close={close} />
            )}
          </div>
        )}
      </Pop>
      {v && v.state !== "none" && <ProduceStrip v={v} />}
    </div>
  );
}

/** 开始前的设置 + 影响面（镜数 × 阶段、预计时长、用哪些卡、被 LoRA 训练锁着的卡、费用） */
function ProduceForm({ ep, close }: { ep: number; close: () => void }) {
  const st = useStudio();
  const { notify } = st;
  const [stages, setStages] = useState<Record<Stage, boolean>>({ first: true, last: true, video: true });
  // UXF2 #44：默认每步等项目方定稿（spec 7.2：每一步都是项目方点）；自动测试定稿要自己选
  const [mode, setMode] = useState<"auto_lock" | "review">("review");
  const [tier, setTier] = useState<"" | "preview" | "final">("");
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [plan, setPlan] = useState<ProducePlan | null>(null);
  const [planErr, setPlanErr] = useState<string | null>(null);
  const { lanes } = useLanes();
  const { sop } = useSop();
  const rs = useRenderSettings(); // 默认预设名 + auto_final_on_lock（按 config/render_quality.json 实际值）
  const picked = (Object.keys(stages) as Stage[]).filter((k) => stages[k]);
  const body = { stages: picked, mode, tier_first: tier || undefined, force, by: "canvas" };
  const key = JSON.stringify(body);

  useEffect(() => {
    if (!picked.length) {
      setPlan(null);
      return;
    }
    let dead = false;
    setPlanErr(null);
    call<ProducePlan>(`${base(ep)}/plan`, body).then(
      (p) => {
        if (!dead) setPlan(p);
      },
      (e: Error) => {
        if (dead) return;
        // 旧 API 没有 /plan：按本页数据粗估（镜数、已定稿跳过、默认耗时）
        if (/^40[45]|Not Found|Method Not Allowed/.test(e.message)) setPlan(localPlan(st, ep, picked, force, tier === "final" || (tier === "" && rs.autoFinal === true), lanes?.filter((l) => l.reachable).length ?? 1));
        else setPlanErr(e.message);
      },
    );
    return () => {
      dead = true;
    };
  }, [ep, key]); // eslint-disable-line react-hooks/exhaustive-deps

  const start = async () => {
    setBusy(true);
    try {
      set(await call<ProduceView>(base(ep), body));
      notify(`第 ${ep} 集整集出片已开始（${mode === "review" ? "每步等你定稿" : "自动测试定稿"}）`);
      close();
    } catch (e) {
      notify(`整集出片没开始：${/Failed to fetch|NetworkError/i.test((e as Error).message) ? "后台服务没响应（Failed to fetch），稍后重试" : (e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };

  // 用哪些卡：后端道表（plan.lanes）+ 实时道状态（在做什么、被谁锁着）
  const used = (plan?.lanes ?? []).filter((l) => l.ok !== false);
  const shown = used.length ? used : (lanes ?? []).filter((l) => l.reachable).map((l) => ({ gpu: l.gpu, id: l.id, image_pref: l.image_pref, ok: true }));
  const info = (g: number | string) => lanes?.find((l) => String(l.gpu) === String(g));
  const locked = shown.map((l) => info(l.gpu)).filter((x): x is NonNullable<typeof x> => !!x && !!x.lock);
  const skip = picked.reduce((a, k) => a + (plan?.steps[k]?.skip ?? 0), 0);
  const review = picked.reduce((a, k) => a + (plan?.steps[k]?.review ?? 0), 0);
  const nRun = plan?.jobs ?? 0;
  // UXF4（审查 N6）：本集还没过的关口（与“待你决定”同一份 SOP 数据）——只提示，不拦（项目方可以测试着出）
  const gates: string[] = [];
  const looks = (sop?.episode === ep ? sop.owner_actions : []).filter((a) => a.gate === "look" && (a.episodes ?? []).includes(ep));
  if (looks.length) gates.push(`确认造型 ×${looks.length}（${looks.map((a) => a.character_name ?? a.character).join("、")}）：造型没确认的镜头不进分镜`);
  const g4 = sop?.episode === ep ? sop.gates.find((g) => g.id === "G4") : undefined;
  const g4Ep = (g4 as { sample_episode?: number } | undefined)?.sample_episode;
  if (g4 && g4.status !== "passed" && (sop as { g4_required?: boolean } | null)?.g4_required !== false)
    gates.push(g4Ep === ep ? "G4 样片还没锁定：这一集就是样片，出完由你看片锁定" : `G4 样片（第 ${g4Ep ?? 1} 集）还没锁定：其余各集先不放量出视频`);
  const freeN = plan?.free_lanes?.length;

  return (
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
        <label title="首帧 / 尾帧出完停下，等你在画布定稿后自动接着走">
          <input type="radio" checked={mode === "review"} onChange={() => setMode("review")} /> 每步等我定稿（推荐）
        </label>
        <label title="每步出完自动定稿（记为“自动测试定稿”，你之后可以重新审）">
          <input type="radio" checked={mode === "auto_lock"} onChange={() => setMode("auto_lock")} /> 自动测试定稿
        </label>
        {mode === "auto_lock" && <small className="v3-prod-warn">系统会替你定稿首帧 / 尾帧（只算测试，之后要你复审）</small>}
      </fieldset>
      <fieldset>
        <legend>首尾帧档位</legend>
        <select value={tier} onChange={(e) => setTier(e.target.value as typeof tier)}>
          <option value="">
            按项目设置（{rs.defaultLabel ? `预览档 ${rs.defaultLabel}` : "默认预览档"}
            {rs.autoFinal == null ? "" : rs.autoFinal ? "，定稿后自动出定稿档" : "，不自动出定稿档"}）
          </option>
          <option value="preview">只出预览档{rs.defaultLabel ? ` ${rs.defaultLabel}` : ""}（快）</option>
          <option value="final">定稿档（预览 → 定稿档，慢约 4 倍）</option>
        </select>
        {tier === "" && <small className="v3-prod-hint">项目设置：{autoFinalText(rs)}</small>}
      </fieldset>
      <label title="已定稿且不过期的阶段默认跳过；勾上则重出新版本（旧版本保留）">
        <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 已是最新的也重出
      </label>

      <section className="v3-prod-sum" aria-label="开始前确认">
        <b>开始前确认</b>
        {!picked.length ? (
          <p>先勾选要出的阶段</p>
        ) : planErr ? (
          <p className="v3-prod-warn">{/Failed to fetch|NetworkError/i.test(planErr) ? "读不到影响面：后台服务没响应，稍后再打开这个窗口（Failed to fetch）" : `读不到影响面：${planErr}`}</p>
        ) : !plan ? (
          <p>计算中…</p>
        ) : (
          <>
            {gates.length > 0 && (
              <div className="v3-prod-gates" role="note">
                <b>还差 {gates.length} 个关口</b>（可以先测试着出，正式出片前要过）
                <ul>
                  {gates.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </div>
            )}
            {nRun === 0 ? (
              <p>
                <span className="k">将出</span>
                {review ? "没有要重出的" : "全部已定稿，没有要出的"}
                {skip ? `（已定稿且没过期的 ${skip} 步跳过）` : ""}
              </p>
            ) : (
              <p>
                <span className="k">将出</span>
                {picked.map((k) => `${STAGE_LABEL[k]} ${plan.steps[k]?.run ?? 0} 镜`).join(" · ")}
                <small>（本集 {plan.shots} 镜{skip ? `；已定稿且没过期的 ${skip} 步跳过` : ""}）</small>
              </p>
            )}
            {review > 0 && (
              <p className="v3-prod-warn">
                <span className="k">待复审</span>
                {review} 步是以前“自动测试定稿”的：不重出，{mode === "review" ? "等你在画布复审定稿 / 通过后接着走" : "这次按自动测试定稿照旧跳过"}
              </p>
            )}
            {nRun > 0 && (
              <p>
                <span className="k">预计</span>约 {fmt(plan.eta_s)}
                <small>
                  （
                  {plan.local
                    ? `${shown.length || 1} 张卡并行；按默认耗时粗估`
                    : freeN
                      ? `${freeN} 张空闲卡并行；按最近实际耗时`
                      : "现在没有空闲的卡：按 1 张卡算，还要等前面的活"}
                  {plan.final_frames && (stages.first || stages.last) ? "，含定稿档" : ""}
                  {mode === "review" ? "；等你定稿的时间不算" : ""}）
                </small>
              </p>
            )}
            <div>
              <span className="k">用卡</span>
              <ul className="v3-prod-lanes">
                {shown.map((l) => {
                  const x = info(l.gpu);
                  const free = (l as { free?: boolean }).free;
                  return (
                    <li key={String(l.gpu)} className={x?.lock ? "warn" : ""} title={cardTip(l.gpu)}>
                      <b>{cardName(l.gpu)}</b>
                      <small>
                        {l.image_pref ? "出图卡" : "视频优先"}
                        {x ? ` · ${laneState(x)}` : ""}
                        {free === false && !plan.local ? " · 不计入预计" : ""}
                      </small>
                    </li>
                  );
                })}
                {!shown.length && <li>道表读不到：按默认的卡出</li>}
              </ul>
            </div>
            {locked.length > 0 && (
              <p className="v3-prod-warn">
                {locked.map((l) => cardName(l.gpu)).join("、")} 正被 LoRA 训练 / 写作模型占着：不会往上派活，预计里也没算它们。
              </p>
            )}
            {!!plan.too_long?.length && (
              <p className="v3-prod-warn">
                <span className="k">无卡可出</span>
                {plan.too_long.map((t) => `${short(t.shot_id)}（${t.frames} 帧）`).join("、")}：超出单卡 {plan.max_frames} 帧，现在没有能出的卡——要拆镜或换大显存卡（不截短）；这些视频不计入步数和时间。
              </p>
            )}
            <p>
              <span className="k">费用</span>用自己的渲染卡，不调用按次收费的接口；只占卡时间。
            </p>
          </>
        )}
      </section>
      <div className="v3-prod-act">
        <button className="v3-btn" onClick={close}>
          取消
        </button>
        <button
          className={`v3-btn ${gates.length ? "" : "primary"}`}
          disabled={busy || !picked.length || !plan || nRun === 0}
          title={gates.length ? `还差：${gates.join("；")}` : undefined}
          onClick={() => void start()}
        >
          {busy ? "提交中…" : plan ? (nRun ? `${gates.length ? "仍然开始（测试）" : "开始"}（${nRun} 步，约 ${fmt(plan.eta_s)}）` : "没有要出的") : "开始"}
        </button>
      </div>
    </>
  );
}

/** 旧 API 没有 /plan 时的粗估：本页镜头摘要 + 默认耗时（出图 70 s、定稿档 280 s、视频 840 s） */
function localPlan(st: ReturnType<typeof useStudio>, ep: number, stages: Stage[], force: boolean, final: boolean, nLanes: number): ProducePlan {
  const pre = `ep${String(ep).padStart(2, "0")}-`;
  const shots = st.shots.filter((s) => s.id.startsWith(pre));
  const steps: ProducePlan["steps"] = {};
  let total = 0;
  let chain = 0;
  for (const k of stages) steps[k] = { run: 0, skip: 0 };
  for (const s of shots) {
    let sr = 0;
    for (const k of stages) {
      const fresh =
        !force && (k === "video" ? !!s.video && !s.stale?.video?.length : frameState(s, st.details[s.id], k === "first" ? "image" : "last") === "locked");
      if (fresh) steps[k]!.skip++;
      else {
        steps[k]!.run++;
        sr += k === "video" ? 840 : 70 + (final ? 280 : 0);
      }
    }
    total += sr;
    chain = Math.max(chain, sr);
  }
  return {
    shots: shots.length,
    stages,
    steps,
    jobs: Object.values(steps).reduce((a, x) => a + (x?.run ?? 0), 0),
    eta_s: Math.max(chain, total / Math.max(1, nLanes)),
    local: true,
  };
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
              <li key={String(l.gpu)} title={cardTip(l.gpu)}>
                <span>{cardName(l.gpu)}</span>
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
                            <i className={`p-${DOT[x.state]}`} /> {STAGE_LABEL[st]} {x.no_lane ? "无卡可出" : x.auto_review ? AUTO_SHORT : STATE_LABEL[x.state]}
                            {x.gpu != null && (x.state === "running" || x.state === "queued") ? ` · ${cardName(x.gpu)}` : ""}
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
                    <span title={f.error ?? f.reason ?? undefined}>{short(f.shot_id)} {STAGE_LABEL[f.stage]}：{errSummary(f.reason ?? f.error)}</span>
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
