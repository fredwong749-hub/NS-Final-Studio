// UIRSI：① 新建剧本——项目方给故事提纲（P0 Brief），写作模型自动写 P1 故事线 → P2 单集大纲 → P3 剧本 → P4 剧本分镜，
// 每段系统只做格式校验（不过就自动带错误重写 ≤2 轮）；每段产物可看、可改原文、可“返修”；P4 通过后“送去导入”，
// 导入仍在 ② 由项目方勾选确认（不绕过）。后端：/api/story-runs（services/api/ns_api/story_runs.py → tools/pipeline/run_chain）。
// 系统不预填、不生成、不改写剧本内容；页面只把项目方填的字段原样组成 Brief。
import { DeleteButton, EditButton } from "../../ds/editdel";
import { EpisodeReader } from "./EpisodeReader";
import { ScriptFullRows } from "./ScriptFullRows";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button, Empty, LoadError, Seg, Skel, Tag } from "../../ds";
import { useStudio } from "../../store";
import { NODE_SHORT, RUN_LABEL, STAGE_LABEL, storyApi, StoryError, type Artifact, type Issue, type Run, type Stage } from "./story_api";
import "./story.css";
import { LiveProgress } from "../../ds/StageProgress";
import { useLiveEvent } from "../live";
import { ProducerPanel } from "../ProducerPanel";
import { AutoflowPanel, FLOW_EVENT } from "./AutoflowPanel";
import { P1Extras, canShowP1, p1Round, p1Status, useAutoflow } from "./P1Review";
import type { AFlow } from "./AutoflowPanel";

const runIdOf = () => new URLSearchParams(location.hash.split("?")[1] ?? "").get("run");
const setRunInHash = (id: string | null) => {
  const q = new URLSearchParams(location.hash.split("?")[1] ?? "");
  if (id) q.set("run", id);
  else q.delete("run");
  q.delete("tab");
  q.delete("new");
  const s = q.toString();
  history.replaceState(null, "", `${location.pathname}${location.search}#/script-create${s ? `?${s}` : ""}`);
};
const money = (x?: number | null) => (x == null ? "—" : `$${x < 0.01 && x > 0 ? x.toFixed(3) : x.toFixed(2)}`);
const ACTIVE = new Set(["queued", "running"]);
/** P5–P12：通到现有页面；知道是哪一集、且生产剧本里已有这一集时，写上这一集的真实进度（集摘要，不额外请求） */
type EpSum = { shots: number; first_frames: number; videos: number; passed: number } | undefined;
function downstream(ep: number | null, sm: EpSum): { label: string; href: string; tip: string; sub?: string; done?: boolean }[] {
  const canvas = ep ? `#ep${String(ep).padStart(2, "0")}` : "#/";
  const n = sm?.shots ?? 0;
  const f = (x: number) => (n ? `${x}/${n}` : undefined);
  return [
    { label: "资产", href: "#/assets", tip: "P5：人物表 / 场景表进资产中心，定妆是你的闸门" },
    { label: "首尾帧", href: canvas, tip: "P6：画布里出首帧 / 尾帧，你定稿", sub: sm && f(sm.first_frames), done: !!n && sm!.first_frames === n },
    { label: "视频", href: canvas, tip: "P7–P8：定稿帧出视频", sub: sm && f(sm.videos), done: !!n && sm!.videos === n },
    { label: "审片", href: canvas, tip: "P11：审片行 / 串播，用这版 / 修改", sub: sm && (n ? `通过 ${sm.passed}/${n}` : undefined), done: !!n && sm!.passed === n },
    { label: "成片", href: "#/cut", tip: "P10 / P12：成片页合成、对比，你确认交付" },
  ];
}

export default function NewScriptPage({ onGoImport }: { onGoImport: () => void }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [, setBusy] = useState<string | null>(null);
  const [listErr, setListErr] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(runIdOf);
  const [run, setRun] = useState<Run | null>(null);
  const [runErr, setRunErr] = useState<string | null>(null);
  // UIRSI r21：默认打开最新的剧本（创作者先看到剧本），点“＋ 新建剧本”才是空表单；地址里带 new=1 时直接新建
  const [mode, setMode] = useState<"new" | "run">(runIdOf() ? "run" : new URLSearchParams(location.hash.split("?")[1] ?? "").get("new") ? "new" : "run");
  const [ep, setEp] = useState<number | null>(() => Number(new URLSearchParams(location.hash.split("?")[1] ?? "").get("ep")) || null);

  const loadList = useCallback(async () => {
    try {
      const r = await storyApi.list();
      setRuns(r.runs.filter(shownRun));
      setBusy(r.busy);
      setListErr(null);
    } catch (e) {
      setListErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void loadList();
  }, [loadList]);
  useEffect(() => {
    if (!sel && mode === "run" && runs?.length) open(runs[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs]);

  // 顶栏“＋ 新建剧本”（#/script-create?new=1）在本页上再点一次也要切到空表单
  useEffect(() => {
    const on = () => {
      const q = new URLSearchParams(location.hash.split("?")[1] ?? "");
      if (q.get("new")) (setMode("new"), setSel(null));
      else if (q.get("run")) (setSel(q.get("run")), setMode("run"));
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const loadRun = useCallback(async (id: string, e?: number | null) => {
    try {
      setRun(await storyApi.get(id, e));
      setRunErr(null);
    } catch (e) {
      setRunErr((e as Error).message);
    }
  }, []);
  useEffect(() => {
    setRun(null);
    if (sel) void loadRun(sel, ep);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, loadRun]);
  const pickEp = (e: number) => {
    // PAGEWATCH PW-007：点当前这一集什么也不做；换集只换镜头区（RunView 按运行 id 保持，不整块重建）
    if (run && run.episode === e) return;
    setEp(e);
    if (sel) void loadRun(sel, e);
  };
  // 写作中：每 2.5 s 刷新本次运行和列表
  const live = !!run && ACTIVE.has(run.status);
  useEffect(() => {
    if (!live || !sel) return;
    const t = window.setInterval(() => {
      void loadRun(sel);
      void loadList();
    }, 2500);
    return () => window.clearInterval(t);
  }, [live, sel, loadRun, loadList]);

  const open = (id: string) => {
    setEp(null);
    setSel(id);
    setMode("run");
    setRunInHash(id);
  };
  const newOne = () => {
    setMode("new");
    setSel(null);
    setRunInHash(null);
  };

  return (
    <div className="ns-page">
      <aside className="ns-side">
        <Button variant={mode === "new" ? "primary" : "secondary"} wide onClick={newOne}>
          ＋ 新建剧本
        </Button>
        <h4 className="ns-side-h">最新剧本</h4>
        {listErr && <LoadError what="写作记录" err={listErr} retry={loadList} />}
        {!runs && !listErr && (
          <div className="ns-side-sk">
            <Skel h={52} />
            <Skel h={52} />
            <Skel h={52} />
          </div>
        )}
        {runs && !runs.length && <p className="ds-small ds-muted">还没有。填好提纲点“开始自动写作”，这里会出现一条。</p>}
        {/* UIRSI r21（项目方：只留最新）：最新一份（以及正在写的）放上面；以前的实验 / 旧剧本收进折叠 */}
        <div className="ns-runs">
          {runs
            ?.filter((r, i) => i === 0 || ACTIVE.has(r.status) || (mode === "run" && sel === r.id && i === 0))
            .map((r) => (
              <RunRow key={r.id} r={r} on={mode === "run" && sel === r.id} onClick={() => open(r.id)} onDeleted={() => (void loadList(), newOne())} />
            ))}
        </div>
        {runs && runs.length > 1 && (
          <details className="ns-old" open={!!sel && runs.findIndex((r) => r.id === sel) > 0}>
            <summary>以前的稿子（{runs.filter((r, i) => i > 0 && !ACTIVE.has(r.status)).length}）</summary>
            <div className="ns-runs">
              {runs
                .filter((r, i) => i > 0 && !ACTIVE.has(r.status))
                .map((r) => (
                  <RunRow key={r.id} r={r} on={mode === "run" && sel === r.id} onClick={() => open(r.id)} onDeleted={() => (void loadList(), newOne())} />
                ))}
            </div>
          </details>
        )}
      </aside>
      <main className="ns-main">
        {mode === "new" ? (
          <BriefForm onStarted={() => void loadList()} />
        ) : runErr ? (
          <LoadError what="这次写作" err={runErr} retry={() => sel && loadRun(sel)} />
        ) : !run && listErr && !sel ? (
          /* UIRSI r35：写作记录读不到、也没指定哪一次 → 不放一直转的骨架（看起来像“还在加载”），直接说现在能做什么 */
          <div className="ns-pad">
            <Empty icon="⟳" title="写作记录暂时读不到" sub="后台恢复后左边会列出最新剧本，点一条就能看；现在也可以点“＋ 新建剧本”先填提纲。" action={<Button onClick={newOne}>＋ 新建剧本</Button>} />
          </div>
        ) : !run ? (
          <div className="ns-pad">
            <Skel h={96} />
            <Skel h={360} />
          </div>
        ) : (
          <RunView key={run.id} run={run} reload={() => (void loadRun(run.id, run.episode), void loadList())} onGoImport={onGoImport} onPickEp={pickEp} />
        )}
      </main>
    </div>
  );
}

/** 左侧列表和“写进哪部剧”不显示：已归档的剧（V1）和测试 run（drill_ / zz_ 开头） */
const shownRun = (r: { id: string; registry_status?: string | null }) => r.registry_status !== "archived" && !/^(drill_|zz_)/.test(r.id);

function RunRow({ r, on, onClick, onDeleted }: { r: Run; on: boolean; onClick: () => void; onDeleted?: () => void }) {
  const [lab0, tone0] = RUN_LABEL[r.status] ?? [r.status, "neutral"];
  const ps = p1Status((r as unknown as { autoflow?: AFlow }).autoflow);   // 和页头 / 链条 / 段标签同一个状态函数
  const lab = ps && ps.key !== "approved" ? ps.short : lab0;
  const tone = ps && ps.key !== "approved" ? "neutral" : tone0;
  return (
    <div className="ns-run-wrap">
    {!ACTIVE.has(r.status) && (
      <span className="ns-run-del">
        <DeleteButton type="story_run" id={r.id} soft label="移到回收站" size="xs" onDeleted={() => onDeleted?.()} />
      </span>
    )}
    <button className={`ns-run${on ? " on" : ""}`} onClick={onClick} title={r.outline_head}>
      <span className="ns-run-t">
        <b>{r.title || "新剧（未定名）"}</b>
        <span className="ds-muted"> · {r.series_eps?.length ? `${r.series_eps.length} 集` : r.episodes ? (r.episodes.from === r.episodes.to ? `第 ${r.episodes.from} 集` : `第 ${r.episodes.from}–${r.episodes.to} 集`) : r.episode ? `第 ${r.episode} 集` : ""}</span>
      </span>
      <Tag tone={tone} dot size="xs">
        {lab}
      </Tag>
      <small className="ds-muted">{r.created_at.replace("T", " ").slice(5, 16)}</small>
    </button>
    </div>
  );
}

// ------------------------------------------------------------------ 提纲表单（P0 Brief）
function BriefForm({ onStarted }: { onStarted: () => void }) {
  const { episodes } = useStudio();
  const [title, setTitle] = useState("");
  const [outline, setOutline] = useState("");
  const [from, setFrom] = useState(1);
  const [to, setTo] = useState(1);
  const [lines, setLines] = useState<Record<string, string>>({});
  const [secMin, setSecMin] = useState(50);
  const [secMax, setSecMax] = useState(75);
  const [shots, setShots] = useState<number | "">("");
  const [target, setTarget] = useState<string>("__new"); // 写进哪部剧的提纲：新一部 / 已有的（V2-WALK W-01：提纲只写进写作流程，不再单独起写作）
  const [targets, setTargets] = useState<{ id: string; title: string }[]>([]);
  const [continueOld, setContinueOld] = useState(false); // 续写已有剧才带旧剧人物表；新剧默认完全切割（OVERSIGHT-F P1-5）
  const [writerFree, setWriterFree] = useState<boolean | null>(null);
  const [err, setErr] = useState<{ msg: string; issues: Issue[] } | null>(null);
  const [sending, setSending] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    // 能选的剧：还没开始写的（有提纲但写作流程还没起）；顺带看写作后端，提交前显示花费
    fetch("/api/story-runs?limit=60")
      .then((r) => (r.ok ? r.json() : { runs: [] }))
      .then(async (r: { runs: { id: string; title?: string; registry_status?: string | null }[] }) => {
        const out: { id: string; title: string }[] = [];
        let free: boolean | null = null;
        for (const it of r.runs) {
          if (!shownRun(it) || !it.registry_status) continue; // 已归档 / 没登记的测试 run 不能作为写进的目标（完全切割 L-126）
          const f = await fetch(`/api/script-autoflow/${encodeURIComponent(it.id)}`).then((x) => (x.ok ? x.json() : null)).catch(() => null);
          if (f && free === null && f.writer_backend) free = f.writer_backend === "claude_agent";
          if (f && f.verdict === "not_started") out.push({ id: it.id, title: it.title || "新剧（未定名）" });
        }
        setTargets(out);
        setWriterFree(free);
      })
      .catch(() => undefined);
  }, []);
  // 剧本库“复制为新剧模板”：?tpl=<run> 把那部剧的提纲预填进表单（可改；不改原剧）
  useEffect(() => {
    const tpl = new URLSearchParams(location.hash.split("?")[1] ?? "").get("tpl");
    if (!tpl) return;
    fetch(`/api/script-library/${encodeURIComponent(tpl)}/brief`)
      .then((r) => (r.ok ? r.json() : null))
      .then((b: { title: string; outline: string; episodes: { from: number; to: number }; episode_lines: Record<string, string>; seconds_per_episode: number[]; shots_per_ep: number | null } | null) => {
        if (!b) return;
        setTitle(`${b.title}（新）`);
        setOutline(b.outline);
        setFrom(b.episodes.from);
        setTo(b.episodes.to);
        setLines(b.episode_lines ?? {});
        if (b.seconds_per_episode?.length === 2) (setSecMin(b.seconds_per_episode[0]), setSecMax(b.seconds_per_episode[1]));
        setShots(b.shots_per_ep ?? "");
      })
      .catch(() => undefined);
  }, []);
  const lo = Math.min(from, to);
  const hi = Math.max(from, to);
  const epNums = Array.from({ length: Math.min(30, hi - lo + 1) }, (_, i) => lo + i);
  const nProd = episodes?.length ?? 0;
  const why = !outline.trim()
    ? "先填故事提纲"
    : hi - lo >= 100
      ? "一次最多 100 集"
      : secMin > secMax
        ? "每集秒数下限大于上限"
        : null;

  // V2-WALK W-01：提纲写进所选剧的 Brief（POST /api/script-autoflow/{run}/brief），写作只走写作流程（/start 推进，到故事线先停下等你看）
  async function start() {
    if (why) return;
    setSending(true);
    setErr(null);
    const runId = target === "__new" ? `v2_${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}` : target;
    const call = async (path: string, body: unknown) => {
      const r = await fetch(`/api/script-autoflow/${encodeURIComponent(runId)}/${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `没成功（${r.status}）`);
      return j;
    };
    try {
      const el = Object.fromEntries(Object.entries(lines).filter(([k, v]) => v.trim() && Number(k) >= lo && Number(k) <= hi));
      await call("brief", {
        brief: { schema: "nsfs.brief/1", title: title.trim(), outline, episodes: { from: lo, to: hi }, episode_lines: el, seconds_per_episode: [secMin, secMax], shots_per_ep: shots === "" ? null : shots, registry_from: [], notes: "", source: "新建剧本页" },
        clean_cut: !continueOld,
      });
      await call("start", { episode: lo });
      window.dispatchEvent(new CustomEvent(FLOW_EVENT, { detail: runId }));
      window.scrollTo?.({ top: 0 });
      onStarted();
    } catch (e) {
      setErr({ msg: (e as Error).message, issues: [] });
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="ns-form">
      <header className="ns-h">
        <h1>新建剧本</h1>
        <p className="ds-muted">给一份故事提纲，写手依次写出故事线 → 造型表 → 各集大纲 · 剧本 · 分镜；故事线写好后先停下等你看，最后由你确认导入。</p>
      </header>
      {/* V2-WALK W-01：写作流程是唯一的写作入口（script_autoflow）；下面的提纲表单只写提纲 */}
      <AutoflowPanel />
      <ChainMap />
      <section className="ns-card">
        <div className="ns-row2">
          <label className="ns-f grow">
            <span>剧名</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="可空" />
          </label>
          <label className="ns-f">
            <span>集数范围（故事线覆盖）</span>
            <span className="ns-inl">
              第 <input type="number" min={1} value={from} onChange={(e) => setFrom(Math.max(1, Number(e.target.value) || 1))} /> –{" "}
              <input type="number" min={1} value={to} onChange={(e) => setTo(Math.max(1, Number(e.target.value) || 1))} /> 集
            </span>
          </label>
          <label className="ns-f">
            <span>写进哪部剧</span>
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              <option value="__new">新建一部剧</option>
              {targets.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
            </select>
          </label>
        </div>
        {target !== "__new" && (
        <label className="ns-chk" title="默认是全新的一部剧，不带旧剧的人物和场景；勾上才接着旧剧写">
          <input type="checkbox" checked={continueOld} onChange={(e) => setContinueOld(e.target.checked)} /> 续写已有剧（带上旧剧的人物表；不勾 = 全新的一部剧）
        </label>
        )}
        <label className="ns-f">
          <span className="ns-f-h">
            故事提纲 <small className="ds-muted">原文原样交给写手，系统不改写</small>
            <span className="ds-grow" />
            <Button size="xs" variant="ghost" onClick={() => fileRef.current?.click()}>
              上传 .md / .txt
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept=".md,.txt"
              hidden
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) setOutline(await f.text());
              }}
            />
          </span>
          <textarea className="ns-outline" value={outline} onChange={(e) => setOutline(e.target.value)} placeholder="粘贴故事提纲，或上传文件" />
          <small className="ds-muted">{outline.length} 字</small>
        </label>
        <details className="ns-more">
          <summary>逐集一句话（可选，{Object.values(lines).filter((v) => v.trim()).length}/{epNums.length}）· 写手会逐字照抄进故事线</summary>
          <div className="ns-lines">
            {epNums.map((n) => (
              <label key={n} className="ns-line">
                <span>第 {n} 集</span>
                <input value={lines[n] ?? ""} onChange={(e) => setLines({ ...lines, [n]: e.target.value })} />
              </label>
            ))}
            {hi - lo + 1 > epNums.length && <p className="ds-small ds-muted">只列前 30 集；其余集写手按提纲写。</p>}
          </div>
        </details>
        <div className="ns-row2">
          <label className="ns-f">
            <span>每集秒数</span>
            <span className="ns-inl">
              <input type="number" value={secMin} onChange={(e) => setSecMin(Number(e.target.value) || 0)} /> –{" "}
              <input type="number" value={secMax} onChange={(e) => setSecMax(Number(e.target.value) || 0)} /> 秒
            </span>
          </label>
          <label className="ns-f">
            <span>每集镜头数</span>
            <input type="number" min={1} placeholder="按规则" value={shots} onChange={(e) => setShots(e.target.value === "" ? "" : Number(e.target.value))} />
          </label>
        </div>
        {err && (
          <div className="ns-err" role="alert">
            <b>{err.msg}</b>
            {err.issues.length > 0 && <IssueList issues={err.issues} />}
          </div>
        )}
        <footer className="ns-go">
          <Button variant="primary" disabled={!!why || sending} why={why ?? "正在提交"} onClick={() => void start()}>
            {sending ? "正在提交…" : "开始写作"}
          </Button>
          <span className="ds-small ds-muted">
            {writerFree === false ? "按写作模型计费" : "花费 $0.00 · 写手直接写，不调外部接口"} · 写好故事线会先停下等你看；导入前不会动现有剧本{nProd ? `（现有 ${nProd} 集）` : ""}
          </span>
        </footer>
      </section>
    </div>
  );
}

/** P0 → P12 一条线：上游这页做，下游通到现有页面 */
function ChainMap({ stages, onPick, pick, ep, imported, overrides }: { stages?: Stage[]; onPick?: (n: string) => void; pick?: string; ep?: number | null; imported?: boolean; overrides?: Record<string, string> }) {
  const { episodes } = useStudio();
  const sm = imported && ep ? episodes?.find((e) => e.number === ep)?.summary : undefined;
  const down = downstream(ep ?? null, sm);
  const nodes = stages ?? (["P0", "P1", "P2", "P3", "P4"].map((n) => ({ node: n, label: NODE_SHORT[n], status: "pending" })) as unknown as Stage[]);
  return (
    <nav className="ns-chain" aria-label="从提纲到成片">
      {nodes.map((s) => {
        const [lab0, tone0] = STAGE_LABEL[s.status] ?? [s.status, "neutral"];
        const lab = overrides?.[s.node] ?? lab0;
        const tone = overrides?.[s.node] ? "neutral" : tone0;
        const meta = s.status === "running" ? `第 ${(s.rounds_done ?? 0) + 1} 轮` : "";
        return (
          <button key={s.node} className={`ns-node st-${s.status}${pick === s.node ? " on" : ""}`} onClick={() => onPick?.(s.node)} disabled={!onPick} aria-current={pick === s.node ? "step" : undefined}>
            <span className="ns-node-n">{s.node}</span>
            <b>{NODE_SHORT[s.node]}</b>
            {stages ? (
              <Tag tone={tone} dot size="xs">
                {lab}
                {s.blocking ? ` ${s.blocking}` : ""}
              </Tag>
            ) : (
              <small className="ds-muted">{s.node === "P0" ? "你写" : "写手"}</small>
            )}
            {meta && <small className="ds-muted">{meta}</small>}
          </button>
        );
      })}
      <span className={`ns-node gate${imported ? " st-ok" : ""}`} title="导入一律由你在 ② 导入页勾选确认">
        <span className="ns-node-n">闸</span>
        <b>导入</b>
        <small className="ds-muted">{imported ? "已送去，等你确认" : "你确认"}</small>
      </span>
      <span className="ns-down" aria-label="导入之后">
        {down.map((d) => (
          <a key={d.label} href={d.href} title={d.tip} className={d.done ? "done" : ""}>
            {d.label}
            {d.sub ? <small> {d.sub}</small> : null}
          </a>
        ))}
      </span>
    </nav>
  );
}

// ------------------------------------------------------------------ 一次写作的详情
function RunView({ run, reload, onGoImport, onPickEp }: { run: Run; reload: () => void; onGoImport: () => void; onPickEp: (ep: number) => void }) {
  // 实时：这个运行的写作产物（P0–P4、决定记录）变了 → 只重取这个运行（不整页刷新）
  useLiveEvent((e) => e.type === "stage" && (!e.run || e.run === run.id), reload, 1000);
  const firstBad = run.stages.find((s) => s.status === "needs_writer" || s.status === "budget_stop" || s.status === "running");
  const lastDone = [...run.stages].reverse().find((s) => s.status === "ok" || s.status === "unchecked");
  const [pick, setPick] = useState<string>(firstBad?.node ?? lastDone?.node ?? "P0");
  const picked = useRef(false);
  useEffect(() => {
    // 写作推进时跟着当前段走（项目方手动点过就不跟）
    if (!picked.current) setPick(firstBad?.node ?? lastDone?.node ?? "P0");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id, firstBad?.node, lastDone?.node]);
  useEffect(() => {
    picked.current = false;
  }, [run.id]);
  const [act, setAct] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad" | "warn"; text: ReactNode } | null>(null);
  const [lab0, tone0] = RUN_LABEL[run.status] ?? [run.status, "neutral"];
  const afHead = useAutoflow(run.id);
  const ps = p1Status(afHead.d);
  const lab = ps && ps.key !== "approved" ? ps.text : lab0;
  const tone = ps && ps.key !== "approved" ? "neutral" : tone0;
  const p4 = run.stages.find((s) => s.node === "P4");
  const p4ok = p4?.status === "ok";
  const live = ACTIVE.has(run.status);
  const ro = !!run.readonly;
  // UIRSI r21：画布里的正式剧本就是这一季（集数和每集标题都对得上）→ 显示“已是正式剧本”，不再给“送去导入”
  const { episodes: prodEps } = useStudio();
  const [p1Titles, setP1Titles] = useState<string[] | null>(null);
  const [p1Title, setP1Title] = useState<string>("");
  useEffect(() => {
    // 页头剧名读 P1 定的剧名（没有就用提纲里的）
    const base = `/files/pipeline/runs/${encodeURIComponent(run.id)}`;
    void fetch(`${base}/P1_storyline.json?t=${Date.now()}`).then((r) => (r.ok ? r.json() : null)).then((j) => (j?.title ? setP1Title(j.title) : null)).catch(() => undefined);
  }, [run.id]);
  const [p1ByEp, setP1ByEp] = useState<Record<number, string>>({});
  useEffect(() => {
    storyApi.artifact(run.id, "P1").then(
      (a) => {
        const eps = ((a.json as { episodes?: { episode?: number; title?: string }[] }) ?? {}).episodes ?? [];
        setP1Titles(eps.map((x) => x.title ?? ""));
        setP1ByEp(Object.fromEntries(eps.filter((x) => x.episode != null).map((x) => [x.episode as number, x.title ?? ""])));
      },
      () => undefined,
    );
  }, [run.id]);
  const isLive = !!(run.series && p1Titles && prodEps && prodEps.length === p1Titles.length && prodEps.every((e, i) => e.title === p1Titles[i]));
  // 这一集在画布里（集号对上、标题和故事线一致）就显示每镜完整一行；不要求整季都对上
  const epLive = isLive || !!(run.episode && prodEps?.some((e) => e.number === run.episode && !!e.title && e.title === p1ByEp[run.episode]));
  const canResume = !ro && !live && ["interrupted", "paused", "error", "budget_stop"].includes(run.status);
  const goImportFocus = (path?: string) => {
    if (path) location.hash = `#/script-create?tab=import&focus=${encodeURIComponent(path)}`;
    else onGoImport();
  };
  const nextUpto = !ro && run.upto !== "P4" && run.status === "ok" ? (["P1", "P2", "P3", "P4"][["P1", "P2", "P3", "P4"].indexOf(run.upto) + 1] as string) : null;

  async function doAct(name: string, f: () => Promise<unknown>, okText: ReactNode) {
    setAct(name);
    setMsg(null);
    try {
      await f();
      setMsg({ tone: "ok", text: okText });
      reload();
    } catch (e) {
      setMsg({ tone: "bad", text: (e as Error).message });
    } finally {
      setAct(null);
    }
  }
  const stage = run.stages.find((s) => s.node === pick) ?? run.stages[0];
  const [view, setView0] = useState<"full" | "read">(() => {
    try {
      return localStorage.getItem("ns.script.view") === "read" ? "read" : "full";
    } catch {
      return "full";
    }
  });
  const setView = (v: "full" | "read") => {
    setView0(v);
    try {
      localStorage.setItem("ns.script.view", v);
    } catch {
      /* 无痕模式 */
    }
  };

  return (
    <div className="ns-run-view">
      <header className="ns-rh">
        <div className="ns-rh-t">
          <h1>{p1Title || run.title || "新剧（未定名）"}</h1>
          <Tag tone={tone} dot>
            {lab}
            {live && run.current ? ` · ${NODE_SHORT[run.current.split("-")[1]] ?? run.current}` : ""}
          </Tag>
          <span className="ds-small ds-muted" title={`写作花费 ${money(run.spent_usd)}${run.budget_usd ? ` / 上限 ${money(run.budget_usd)}` : ""}${run.model ? ` · ${run.model}` : ""}`}>
            {run.series_eps?.length ? `共 ${run.series_eps.length} 集` : run.episodes ? `第 ${run.episodes.from}–${run.episodes.to} 集` : ""}
          </span>
        </div>
        <div className="ns-rh-a">
          {/* PRODUCER 11-01：项目方“人类不应该点”——这一季由制作监督自动推进时，手动按钮收进“⋯ 手动插队 / 重做”（G10 不删） */}
          {isLive && (canResume || nextUpto) ? (
            <details className="ns-rh-more">
              <summary className="ds-btn ghost sm" title="制作监督会自动推进；需要时可以手动插队 / 重做">⋯ 手动插队 / 重做</summary>
              {canResume && (
                <Button size="sm" disabled={!!act} onClick={() => void doAct("resume", () => storyApi.resume(run.id), "已继续：从没写完的那段接着写，已通过的段不重写")}>
                  {act === "resume" ? "…" : "继续写"}
                </Button>
              )}
              {nextUpto && (
                <Button size="sm" disabled={!!act} onClick={() => void doAct("resume", () => storyApi.resume(run.id, nextUpto), `接着写到 ${NODE_SHORT[nextUpto]}`)}>
                  接着写到{NODE_SHORT[nextUpto]}
                </Button>
              )}
            </details>
          ) : (
            <>
              {canResume && (
                <Button disabled={!!act} onClick={() => void doAct("resume", () => storyApi.resume(run.id), "已继续：从没写完的那段接着写，已通过的段不重写")}>
                  {act === "resume" ? "…" : "继续写"}
                </Button>
              )}
              {nextUpto && (
                <Button disabled={!!act} onClick={() => void doAct("resume", () => storyApi.resume(run.id, nextUpto), `接着写到 ${NODE_SHORT[nextUpto]}`)}>
                  接着写到{NODE_SHORT[nextUpto]}
                </Button>
              )}
            </>
          )}
          {isLive ? (
            <Tag tone="ok" dot>
              已是正式剧本 · 画布里就是这 {run.series_eps?.length ?? ""} 集
            </Tag>
          ) : run.sent_to_import ? (
            <Button variant="primary" onClick={() => goImportFocus(run.sent_to_import?.path)} title={run.sent_to_import.path}>
              去导入页确认 ›
            </Button>
          ) : (
            <Button
              variant="primary"
              disabled={!p4ok || !!act}
              why={!p4 || p4.status === "pending" ? "剧本分镜（P4）还没写出来" : "剧本分镜（P4）还没通过校验：先返修或改原文"}
              onClick={() =>
                void doAct("send", () => storyApi.sendToImport(run.id, run.series ? run.episode : null).then((r) => goImportFocus(r.draft.path)), "已存为导入候选，正在打开导入页：点“导入”即换上（导入前自动备份）")
              }
            >
              送去导入（你确认）
            </Button>
          )}
        </div>
      </header>
      {run.error && (
        <div className="ns-err" role="alert">
          <b>{run.status === "budget_stop" ? "到预算上限停下了" : run.status === "bad_brief" ? "提纲没过校验" : "写作没完成"}</b>
          <span>{run.error}</span>
          <small className="ds-muted">已通过的段都保留着；处理后点“继续写”。</small>
        </div>
      )}
      {msg && <div className={`ns-msg ${msg.tone}`}>{msg.text}</div>}
      {/* 项目方 11-01：整季分段进度（剧本 → 分镜 → 首帧 → 尾帧 → 视频 → 声音 → 成片），素材 / 任务 / 写作一有变化自动更新 */}
      {run.series_eps && run.series_eps.length > 0 && (
        <div className="ns-progress">
          <LiveProgress run={run.id} title="整季进度" />
          {/* PRODUCER 11-01：自动制作中——每集 / 每镜在等什么、在哪做、第几次、自动修复原因（/api/producer/status） */}
          <ProducerPanel run={run.id} />
        </div>
      )}
      {run.series_eps && run.series_eps.length > 0 && <SeriesStrip run={run} onPick={onPickEp} />}
      {p4?.exists && run.episode ? (
        <>
          {/* 项目方 11-01：剧本页默认“每镜一行完整视图”（首尾帧、视频、提示词、状态、操作）；阅读模式是第二视图 */}
          <div className="ns-viewsw" role="tablist" aria-label="剧本页视图">
            <button role="tab" aria-selected={view === "full"} className={view === "full" ? "on" : ""} onClick={() => setView("full")} title="每镜一行：首帧 · 尾帧 · 视频 · 剧本 / 对白 / 声音 · 提示词 · 状态与操作">
              每镜完整一行
            </button>
            <button role="tab" aria-selected={view === "read"} className={view === "read" ? "on" : ""} onClick={() => setView("read")} title="像读剧本一样从头读：画面 + 台词，配首帧大图">
              阅读模式
            </button>
          </div>
          {view === "full" && epLive ? (
            <ScriptFullRows ep={run.episode} />
          ) : (
            <>
              {view === "full" && !epLive && (
                <p className="ns-viewnote ds-small ds-muted">这份稿子还没导入画布，还没有首尾帧和视频：先按阅读模式看（每镜全部字段可展开）；导入后这里自动换成每镜完整一行。</p>
              )}
              <EpisodeReader runId={run.id} ep={run.episode} series={!!run.series} live={epLive} />
            </>
          )}
          <details className="ns-process" open={!p4ok || undefined}>
            <summary>
              写作过程与格式校验{p4ok ? "（都通过了，一般不用看）" : `（第 ${run.episode} 集分镜还有 ${p4?.blocking ?? 0} 处要改）`}
            </summary>
            <ProcessView run={run} pick={pick} setPick={(n) => ((picked.current = true), setPick(n))} stage={stage} live={live} act={act} ro={ro} reload={reload} doAct={doAct} />
          </details>
        </>
      ) : (
        <ProcessView run={run} pick={pick} setPick={(n) => ((picked.current = true), setPick(n))} stage={stage} live={live} act={act} ro={ro} reload={reload} doAct={doAct} />
      )}
    </div>
  );
}

function ProcessView({ run, pick, setPick, stage, live, act, ro, reload, doAct }: { run: Run; pick: string; setPick: (n: string) => void; stage: Stage; live: boolean; act: string | null; ro: boolean; reload: () => void; doAct: (name: string, f: () => Promise<unknown>, ok: ReactNode) => Promise<void> }) {
  const afv = useAutoflow(run.id);
  return (
    <>
      <ChainMap
        overrides={p1Status(afv.d) && p1Status(afv.d)!.key !== "approved" ? { P1: p1Status(afv.d)!.text } : undefined}
        stages={run.stages}
        ep={run.episode}
        imported={!!run.sent_to_import}
        pick={pick}
        onPick={setPick}
      />
      <StagePanel key={`${run.id}:${run.episode}:${stage.node}`} run={run} s={stage} busy={live || !!act || ro} roWhy={ro ? "这一季已是正式剧本，这里只读；要改某一集，在上面点“改这一集…”" : undefined} reload={reload} onRetry={(link) => void doAct("retry", () => storyApi.retry(run.id, link), "已开始重写这一段（旧稿留着，可以找回）")} />
    </>
  );
}

function StagePanel({ run, s, busy, roWhy, reload, onRetry }: { run: Run; s: Stage; busy: boolean; roWhy?: string; reload: () => void; onRetry: (link: string) => void }) {
  const [art, setArt] = useState<Artifact | null>(null);
  const [artErr, setArtErr] = useState<string | null>(null);
  const issues = s.issues ?? [];
  const [view, setView] = useState<"pretty" | "raw" | "issues">(issues.some((i) => i.level === "block") ? "issues" : "pretty");
  const [edit, setEdit] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveRes, setSaveRes] = useState<{ ok: boolean; text: string; issues: Issue[] } | null>(null);
  const has = s.node === "P0" ? s.status === "ok" : !!s.exists;
  const loadArt = useCallback(() => {
    if (!has) return;
    storyApi.artifact(run.id, s.node, run.series ? run.episode : null).then(
      (a) => (setArt(a), setArtErr(null)),
      (e) => setArtErr((e as Error).message),
    );
  }, [run.id, run.episode, run.series, s.node, has]);
  useEffect(loadArt, [loadArt, s.status, s.rounds]);

  async function save() {
    if (edit == null) return;
    setSaving(true);
    try {
      const r = await storyApi.save(run.id, s.node, edit);
      setSaveRes({
        ok: r.report.ok,
        text: `${r.report.ok ? "已保存，校验通过" : `已保存，但还有 ${r.report.blocking} 条格式问题`}${r.superseded.length ? `；下游 ${r.superseded.length} 个旧文件挪到 superseded/（不删）——点“继续写”让写作模型按你改的这版重写下游` : ""}`,
        issues: r.report.issues,
      });
      setEdit(null);
      reload();
    } catch (e) {
      setSaveRes({ ok: false, text: (e as Error).message, issues: (e as StoryError).issues ?? [] });
    } finally {
      setSaving(false);
    }
  }
  const [lab, tone] = STAGE_LABEL[s.status] ?? [s.status, "neutral"];
  const canEdit = s.node !== "P0" && has && !busy;
  // V2-WALK W-22：故事线走写作流程时，返修入口只留闸门的“用这版 / 修改”（下面的 P1Extras），旧的三个按钮不再出现
  const af = useAutoflow(run.id);
  const gated = s.node === "P1" && !!af.d;
  // 评审没过门槛的故事线项目方一律看不到（只给看通过的）：评审 / 返修中隐藏“看内容 / 原文 / 校验问题”
  const hideP1 = gated && !(canShowP1(af.d) || af.d?.owner_gates?.gates?.P1?.status === "approved");
  const round = af.d ? p1Round(af.d) : 1;
  const st1 = gated ? p1Status(af.d) : null;

  return (
    <section className="ns-stage">
      <header className="ns-stage-h">
        <h2>
          <span className="ns-node-n">{s.node}</span> {s.label}
        </h2>
        <Tag tone={st1 && st1.key !== "approved" ? "neutral" : tone} dot size="xs">
          {st1 && st1.key !== "approved" ? st1.text : lab}
        </Tag>
        <span className="ds-small ds-muted" title={`${s.rounds ? `写了 ${s.rounds} 轮` : ""}${s.usd ? ` · 花费 ${money(s.usd)}` : ""}`}>
          {s.blocking ? `要改 ${s.blocking} 处` : ""}
          {s.warnings ? `${s.blocking ? " · " : ""}提醒 ${s.warnings}` : ""}
          {s.edited_by === "owner" ? " · 你改过原文" : ""}
        </span>
        <span className="ds-grow" />
        {edit == null && !hideP1 && (
          <Seg
            value={view}
            onChange={setView}
            options={[
              ["pretty", "看内容"],
              ["raw", "原文"],
              ["issues", `校验问题 ${issues.length}`],
            ]}
          />
        )}
        {s.link && edit == null && has && !gated && (
          <EditButton type="script" id={`run:${run.id}/${s.node}${run.series && run.episode ? `@${run.episode}` : ""}`} size="sm" label="让模型改…" onChanged={reload} />
        )}
        {s.link && edit == null && !gated && (
          <Button size="sm" disabled={!canEdit} why={roWhy ?? (busy ? "正在写作，写完后再改" : "这一段还没有产物")} onClick={() => (setEdit(art?.text ?? ""), setSaveRes(null))}>
            改原文
          </Button>
        )}
        {s.link && edit == null && !gated && s.status !== "pending" && (
          <Button size="sm" variant={s.status === "needs_writer" || s.status === "budget_stop" ? "primary" : "ghost"} disabled={busy} why={roWhy ?? "正在写作"} onClick={() => onRetry(s.link!)} title="让写作模型重写这一段（带上一次的校验问题），下游跟着重写">
            返修这一段
          </Button>
        )}
      </header>
      {gated && <P1Extras runId={run.id} hasStory={has && s.status !== "pending"} />}
      {saveRes && (
        <div className={`ns-msg ${saveRes.ok ? "ok" : "warn"}`}>
          {saveRes.text}
          {!saveRes.ok && saveRes.issues.length > 0 && <IssueList issues={saveRes.issues} />}
        </div>
      )}
      {hideP1 ? (
        <Empty icon="…" title={`故事线在评审 / 返修中（第 ${round} 轮）`} sub="过了门槛就在这里给你看" />
      ) : edit != null ? (
        <div className="ns-edit">
          <p className="ds-small ds-muted">原样保存你写的文字，系统只重新校验格式。保存后这一段下游的旧产物会挪到 superseded/（不删）。</p>
          <textarea value={edit} onChange={(e) => setEdit(e.target.value)} spellCheck={false} />
          <footer>
            <Button variant="primary" disabled={saving} onClick={() => void save()}>
              {saving ? "保存并校验中…" : "保存并校验"}
            </Button>
            <Button variant="ghost" onClick={() => setEdit(null)}>
              取消
            </Button>
          </footer>
        </div>
      ) : s.status === "pending" ? (
        <Empty icon="…" title="还没写到这一段" sub={run.status === "running" || run.status === "queued" ? "写手正在写上游，写完自动接着写这一段" : "上游通过后点“继续写”"} />
      ) : s.status === "running" ? (
        <div className="ns-wait">
          <span className="ns-spin" aria-hidden="true" />
          <div>
            <b>写手正在写{s.label}（第 {(s.rounds_done ?? 0) + 1} 轮）</b>
            <p className="ds-small ds-muted">写完自动校验；不过就把问题带回去重写，最多 2 轮。这一页会自己刷新，可以先去别的页面。</p>
          </div>
        </div>
      ) : view === "issues" ? (
        issues.length ? <IssueList issues={issues} /> : <Empty icon="✓" title="没有校验问题" sub={s.status === "unchecked" ? "命令行记录没有校验报告" : undefined} />
      ) : artErr ? (
        <LoadError what={s.label} err={artErr} retry={loadArt} />
      ) : !art ? (
        <Skel h={240} />
      ) : view === "raw" ? (
        <pre className="ns-raw">{art.text}</pre>
      ) : (
        <Pretty node={s.node} art={art} />
      )}
    </section>
  );
}

function IssueList({ issues }: { issues: Issue[] }) {
  const blocks = issues.filter((i) => i.level === "block");
  const warns = issues.filter((i) => i.level !== "block");
  return (
    <div className="ns-issues">
      {[...blocks, ...warns].slice(0, 200).map((i, k) => (
        <div key={k} className={`ns-issue ${i.level === "block" ? "block" : "warn"}`}>
          <Tag tone={i.level === "block" ? "bad" : "warn"} size="xs">
            {i.rule}
          </Tag>
          <span>{i.message}</span>
          {i.field ? <code>{i.field}</code> : null}
        </div>
      ))}
      {issues.length > 200 && <p className="ds-small ds-muted">另有 {issues.length - 200} 条，看“原文”旁的报告文件。</p>}
    </div>
  );
}

// ------------------------------------------------------------------ 产物排版（只排版，不改字）
type J = Record<string, unknown>;
const arr = (x: unknown) => (Array.isArray(x) ? (x as J[]) : []);
const isEl = (x: unknown) => !!x && typeof x === "object" && "$$typeof" in (x as object);
const str = (x: unknown) => (x == null ? "" : typeof x === "string" ? x : Array.isArray(x) ? x.join("、") : typeof x === "object" ? JSON.stringify(x) : String(x));

function Table({ cols, rows }: { cols: [string, string][]; rows: J[] }) {
  return (
    <div className="ns-tbl-wrap">
      <table className="ns-tbl">
        <thead>
          <tr>
            {cols.map(([, l]) => (
              <th key={l}>{l}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map(([k]) => (
                <td key={k}>{isEl(r[k]) ? (r[k] as ReactNode) : str(r[k])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Reg = { chars: { id: string; name: string }[]; scenes: { id: string; name: string }[] };
let regCache: Promise<Reg> | null = null;
/** 资产中心已登记的人物 / 场景（只读；P1 表格对照用） */
function useRegistry(on: boolean): Reg | null {
  const [v, setV] = useState<Reg | null>(null);
  useEffect(() => {
    if (!on) return;
    regCache ??= Promise.all([
      fetch("/api/assets/characters").then((r) => (r.ok ? r.json() : { characters: [] })),
      fetch("/api/assets/scenes").then((r) => (r.ok ? r.json() : { scenes: [] })),
    ]).then(([c, sc]) => ({
      chars: (c.characters ?? []).map((x: { id: string; name: string }) => ({ id: x.id, name: x.name })),
      scenes: (sc.scenes ?? []).map((x: { scene_id: string; name: string }) => ({ id: x.scene_id, name: x.name })),
    }));
    regCache.then(setV, () => setV({ chars: [], scenes: [] }));
  }, [on]);
  return v;
}
function RegCell({ on, href, known }: { on: boolean; href: string; known: boolean }) {
  if (!known) return <span className="ds-muted">…</span>;
  return on ? (
    <a className="ns-reg on" href={href} title="在资产中心打开">
      已登记 ›
    </a>
  ) : (
    <span className="ns-reg" title="资产中心里还没有：剧本导入后在资产中心新建、定妆">
      新的
    </span>
  );
}
function assetCell(list: { id: string; name: string }[] | undefined, id: string, name: string, href: string) {
  const hit = list?.find((x) => x.id === id || x.name === name);
  return <RegCell on={!!hit} known={!!list} href={hit ? `${href}${encodeURIComponent(hit.id)}` : ""} />;
}

function Pretty({ node, art }: { node: string; art: Artifact }) {
  const j = (art.json ?? {}) as J;
  const reg = useRegistry(node === "P1");
  const body = useMemo(() => {
    if (art.kind !== "json") return <P4View text={art.text} />;
    if (node === "P0")
      return (
        <dl className="ns-dl">
          <dt>剧名</dt>
          <dd>{str(j.title) || "—"}</dd>
          <dt>集数</dt>
          <dd>{j.episodes ? `第 ${(j.episodes as J).from}–${(j.episodes as J).to} 集` : "—"}</dd>
          <dt>每集秒数</dt>
          <dd>{str(j.seconds_per_episode).replace("、", "–")}</dd>
          <dt>逐集一句话</dt>
          <dd>{Object.entries((j.episode_lines as Record<string, string>) ?? {}).map(([k, v]) => <div key={k}>第 {k} 集：{v}</div>)}</dd>
          <dt>提纲</dt>
          <dd className="ns-pre">{str(j.outline)}</dd>
        </dl>
      );
    if (node === "P1") {
      const chars = arr(j.characters).map((c) => ({ ...c, _asset: assetCell(reg?.chars, str(c.char_id), str(c.name), "#/assets?char=") }));
      const scenes = arr(j.scenes).map((c) => ({ ...c, _asset: assetCell(reg?.scenes, str(c.scene_id), str(c.name), "#/assets?type=scene&scene=") }));
      const newC = chars.filter((c) => !c._asset.props.on).length;
      const newS = scenes.filter((c) => !c._asset.props.on).length;
      return (
        <>
          <p className="ns-lead ds-small">
            资产中心对照（P1 → P5）：人物 {chars.length - newC}/{chars.length} 已登记、场景 {scenes.length - newS}/{scenes.length} 已登记
            {reg == null ? "（资产中心读取中…）" : newC + newS ? "。没登记的，等剧本导入后在资产中心新建并定妆（定妆是你的闸门）。" : "。"}
          </p>
          <h3>人物表 · {chars.length}</h3>
          <Table cols={[["name", "人物"], ["_asset", "资产中心"], ["char_id", "id"], ["role", "身份"], ["age", "年龄"], ["gender", "性别"], ["zh_look", "外貌"], ["en_phrase", "EN 外貌短语"], ["voice_phrase", "声线"]]} rows={chars} />
          <h3>场景表 · {scenes.length}</h3>
          <Table cols={[["scene_id", "id"], ["_asset", "资产中心"], ["name", "场景"], ["space", "空间"], ["time_of_day", "时段"], ["light", "光线"], ["fixtures", "固定陈设"]]} rows={scenes} />
          <h3>分集 · {arr(j.episodes).length}</h3>
          <Table cols={[["episode", "集"], ["title", "标题"], ["owner_line", "你的一句话"], ["logline", "展开"], ["characters", "人物"], ["scenes", "场景"]]} rows={arr(j.episodes)} />
        </>
      );
    }
    if (node === "P2")
      return (
        <>
          <p className="ns-lead">
            <b>第 {str(j.episode)} 集 · {str(j.title)}</b> · 目标 {str(j.target_duration_s)} 秒 · 节拍合计 {arr(j.beats).reduce((a, b) => a + (Number(b.est_s) || 0), 0)} 秒
          </p>
          <p className="ds-muted">{str(j.logline)}</p>
          <Table cols={[["id", "拍"], ["purpose", "作用"], ["summary", "内容"], ["scene_id", "场景"], ["characters", "人物"], ["est_s", "秒"], ["has_dialogue", "台词"]]} rows={arr(j.beats)} />
          {j.carry_out ? <p className="ds-small ds-muted">结尾状态：{str(j.carry_out)}</p> : null}
        </>
      );
    if (node === "P3")
      return (
        <>
          <p className="ns-lead">
            <b>第 {str(j.episode)} 集 · {str(j.title)}</b> · {arr(j.scenes).length} 场 · 目标 {str(j.target_duration_s)} 秒
          </p>
          {arr(j.scenes).map((sc, i) => (
            <div key={i} className="ns-scene">
              <h4>
                第 {str(sc.no)} 场 · {str(sc.scene_id)} <span className="ds-muted">· 节拍 {str(sc.beat_ids)} · {str(sc.characters)}</span>
              </h4>
              {arr(sc.lines).map((ln, k) => (
                <p key={k} className={`ns-ln k-${str(ln.kind)}`}>
                  {ln.kind === "dialogue" || ln.kind === "voiceover" ? (
                    <>
                      <b>
                        {str(ln.speaker)}
                        {ln.kind === "voiceover" ? "（独白）" : ""}
                        {ln.off_screen ? "（画外）" : ""}
                      </b>
                      {ln.tone ? <span className="ds-muted">（{str(ln.tone)}）</span> : null}：{str(ln.text)}
                    </>
                  ) : (
                    <>
                      {ln.kind === "sound" ? "♪ " : ""}
                      {str(ln.text)}
                    </>
                  )}
                </p>
              ))}
            </div>
          ))}
        </>
      );
    return <pre className="ns-raw">{art.text}</pre>;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [art, node, reg]);
  return <div className="ns-pretty">{body}</div>;
}

/** P4 剧本分镜 Markdown：按“**镜N”切成卡片（只切分显示，不改字） */
function P4View({ text }: { text: string }) {
  const parts = text.split(/\n(?=\*\*镜\s*\d+)/);
  const head = parts[0];
  const shots = parts.slice(1);
  if (!shots.length) return <pre className="ns-raw">{text}</pre>;
  return (
    <>
      <p className="ns-lead">
        <b>{shots.length} 镜</b>
      </p>
      <pre className="ns-raw sm">{head.trim()}</pre>
      <div className="ns-shots">
        {shots.map((s, i) => (
          <ShotCard key={i} text={s.trim()} />
        ))}
      </div>
    </>
  );
}

/** 一镜：“**键**：值”逐行排成 键 | 值；认不出的行原样显示（只排版，不改字） */
function ShotCard({ text }: { text: string }) {
  const lines = text.split("\n");
  const m0 = /^\*\*(镜\s*\d+)[｜|]?([^*]*)\*\*[：:]?\s*(.*)$/.exec(lines[0] ?? "");
  return (
    <article className="ns-shot">
      <header>
        <b>{m0 ? m0[1] : "镜"}</b>
        {m0?.[2] ? <span className="ds-muted"> {m0[2]}</span> : null}
      </header>
      {m0?.[3] ? <p className="ns-shot-img">{m0[3]}</p> : null}
      <dl>
        {lines.slice(m0 ? 1 : 0).map((ln, k) => {
          const m = /^\*\*([^*]{1,16})\*\*[：:]\s*(.*)$/.exec(ln);
          if (m)
            return (
              <div key={k} className="ns-kv">
                <dt>{m[1]}</dt>
                <dd>{m[2]}</dd>
              </div>
            );
          return ln.trim() ? (
            <div key={k} className="ns-kv raw">
              <dd>{ln}</dd>
            </div>
          ) : null;
        })}
      </dl>
    </article>
  );
}

/** 整季运行：每集一格（P2 大纲 · P3 剧本 · P4 分镜 三个点），点哪集看哪集 */
function SeriesStrip({ run, onPick }: { run: Run; onPick: (ep: number) => void }) {
  const eps = run.series_eps ?? [];
  const ok = eps.filter((e) => e.stages.P4 === "ok").length;
  // UIRSI r21：每集写标题（来自故事线），只在要改时打一个小标记——不再给创作者看 P2/P3/P4 三个点
  const [titles, setTitles] = useState<Record<number, string>>({});
  useEffect(() => {
    let alive = true;
    storyApi.artifact(run.id, "P1").then(
      (a) => alive && setTitles(Object.fromEntries((((a.json as { episodes?: { episode: number; title?: string }[] }) ?? {}).episodes ?? []).map((x) => [x.episode, x.title ?? ""]))),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [run.id]);
  return (
    <nav className="ns-series" aria-label="各集">
      <div className="ns-series-eps">
        {eps.map((e) => {
          const bad = Object.values(e.stages).some((v) => v === "needs_writer" || v === "budget_stop");
          const ready = e.stages.P4 === "ok";
          return (
            <button key={e.ep} className={`ns-sep${e.ep === run.episode ? " on" : ""}${bad ? " bad" : ready ? " ok" : ""}`} onClick={() => onPick(e.ep)} title={bad ? "这一集的分镜还有格式要改" : ready ? "这一集写好了" : "还在写"}>
              <span className="ns-sep-n">第 {e.ep} 集</span>
              <span className="ns-sep-t">{titles[e.ep] ?? ""}</span>
              <LiveProgress run={run.id} episode={e.ep} compact />
              {bad && <i className="ns-sep-dot" aria-label="要改" />}
            </button>
          );
        })}
      </div>
      <span className="ds-small ds-muted">{ok === eps.length ? `${eps.length} 集都写好了` : `${ok}/${eps.length} 集写好了`}</span>
    </nav>
  );
}

