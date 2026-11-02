// UX5（D1，P0）：⑤ 成片页 #/cut——以前顶栏“成片 · 可合成”点进去是旧总览，界面上没有看成片、比成片、合成的地方。
// 现在：本集全部成片版本（新的在上）· 播放 · 两版并排对比（同步播放）· “这版之后哪几镜换了定稿”· 合成新版本。
// 后端：GET /api/episodes/{n}/cuts、GET/POST /api/episodes/{n}/cut-job（services/api/ns_api/cuts.py）。
// 合成 = 起装配命令行（只用 CPU），一律另存新的对照版文件，不覆盖已有成片；要再确认一次。接口没上线时整页降级为说明。
import { p1Api } from "../assets/rev_api";
import { useEffect, useRef, useState } from "react";
import { useStudio } from "../../store";
import { Button, Empty, LoadError, Modal, Seg, Skel, Tag } from "../../ds";
import { useSop } from "../sop.helpers";
import { OwnerDecisionDialog } from "../OwnerDecision";
import type { SopOwnerAction } from "../../types";
import { DeleteButton } from "../../ds/editdel";
import { relFromUrl } from "../../ds/editdel.api";
import "./pages.css";
import "./cut.css";
import CutEditor from "./CutEditor";

interface Cut {
  name: string;
  url: string;
  size: number;
  mtime: string;
  tags: string[];
  timeline: { duration_s?: number; shots?: number; preview?: boolean; dialogue_source?: string | null; missing?: string[]; warnings?: number; warning_list?: string[]; note?: string | null } | null;
  changed: { shot_id: string; used: string; current: string; current_locked: boolean }[];
  /** UIRSI：比当前剧本导入更早的成片（旧剧本），默认不显示 */
  old_script?: boolean;
  /** CUTEDIT：剪辑器导出的当前定稿 */
  final?: boolean;
}
interface Job {
  state: "running" | "done" | "failed" | "none";
  variant?: string;
  started_at?: string;
  finished_at?: string | null;
  log_tail?: string;
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) {
    let d = "";
    try {
      d = (await r.json())?.detail ?? "";
    } catch {
      /* 非 JSON */
    }
    throw new Error(r.status === 404 && (!d || d === "Not Found") ? `404 后端未就绪（${url.split("?")[0]} 还没上线）` : `${r.status} ${d || r.statusText}`);
  }
  return r.json() as Promise<T>;
}

const DLG: Record<string, string> = { h3: "H3 原声", tts: "配音（TTS）", auto: "自动" };
const fmtS = (s?: number) => (s == null ? "—" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);

export default function CutPage() {
  const st = useStudio();
  const ep = st.epNum;
  const [cuts, setCuts] = useState<Cut[] | null>(null);
  const [showOld, setShowOld] = useState(false);
  const [oldN, setOldN] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [cmpWith, setCmpWith] = useState<string | null>(null);
  const [mode, setMode] = useState<"edit" | "one" | "cmp">("edit");   // CUTEDIT：默认进剪辑器
  const [ask, setAsk] = useState(false);
  const [dlg, setDlg] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [tick, setTick] = useState(0);
  // UX6（B P1 成片过期）：最新一版成片之后改过的音色（GET /api/episodes/{n}/cut/deps；没上线 → 不显示）
  const [voiceChg, setVoiceChg] = useState<{ key: string; label: string; at: string }[]>([]);
  useEffect(() => {
    let alive = true;
    setVoiceChg([]);
    p1Api.cutDeps(ep).then((d) => alive && setVoiceChg(d.voices_changed ?? []), () => undefined);
    return () => {
      alive = false;
    };
  }, [ep, tick]);

  useEffect(() => {
    let alive = true;
    setErr(null);
    void showOld;
    get<{ cuts: Cut[]; job: Job | null }>(`/api/episodes/${ep}/cuts`).then(
      (d) => {
        if (!alive) return;
        const list = showOld ? d.cuts : d.cuts.filter((c) => !c.old_script);
        setOldN(d.cuts.filter((c) => c.old_script).length);
        setCuts(list);
        setJob(d.job);
        setSel((s) => (s && list.some((c) => c.name === s) ? s : list.find((c) => !c.tags.includes("勿用"))?.name ?? list[0]?.name ?? null));
      },
      (e) => alive && (setErr(String((e as Error).message ?? e)), setCuts(null)),
    );
    return () => {
      alive = false;
    };
  }, [ep, tick, showOld]);
  // 合成进行中：10 s 刷一次状态
  useEffect(() => {
    if (job?.state !== "running") return;
    const t = window.setInterval(() => setTick((n) => n + 1), 10000);
    return () => window.clearInterval(t);
  }, [job?.state]);

  const cur = cuts?.find((c) => c.name === sel) ?? null;
  const other = cuts?.find((c) => c.name === cmpWith) ?? cuts?.find((c) => c.name !== sel) ?? null;

  async function start() {
    setBusy(true);
    try {
      const r = await fetch(`/api/episodes/${ep}/cut-job`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...(dlg ? { dialogue_source: dlg } : {}), by: "canvas" }),
      });
      if (!r.ok) throw new Error(`${r.status} ${(await r.json().catch(() => ({})))?.detail ?? r.statusText}`);
      setJob(await r.json());
      st.notify(`第 ${ep} 集开始合成新版本（另存，不覆盖）`);
      setAsk(false);
    } catch (e) {
      st.notify(`合成没开始：${String((e as Error).message ?? e)}`, "err");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="v3p-page cut-page">
      <header className="cut-head">
        <span className="ac-step">⑤</span>
        <h1>成片 · 第 {ep} 集</h1>
        {job?.state === "running" && (
          <Tag tone="busy" dot pill>
            正在合成 {job.variant}（开始于 {job.started_at?.slice(11, 16)}）
          </Tag>
        )}
        {job?.state === "failed" && (
          <Tag tone="bad" dot pill title={job.log_tail}>
            上次合成失败（{job.variant}）
          </Tag>
        )}
        {job?.state === "done" && (
          <Tag tone="ok" dot pill>
            已合成 {job.variant}
          </Tag>
        )}
        <span className="ds-grow" />
        <Seg value={mode} onChange={setMode} options={cuts && cuts.length > 1 ? [["edit", "剪辑"], ["one", "看一版"], ["cmp", "两版对比"]] : [["edit", "剪辑"], ["one", "看一版"]]} label="看法" />
        <Button variant="primary" disabled={!!err || job?.state === "running"} why={err ? "成片列表暂时读不到，后台恢复后才能合成" : "正在合成，等它跑完"} onClick={() => setAsk(true)}>
          合成新版本…
        </Button>
      </header>

      <DeliveryGate ep={ep} />
      {err && <LoadError what="成片列表" err={err} retry={() => setTick((n) => n + 1)} hint="后台恢复后这里列出全部版本、能播放和对比；已经合成好的成片不会丢。" />}
      {!cuts && !err && <Skel h={420} />}
      {cuts && !cuts.length && oldN > 0 && !showOld && (
        <Button size="sm" variant="ghost" onClick={() => setShowOld(true)}>
          显示旧剧本的成片（{oldN}）
        </Button>
      )}
      {cuts && !cuts.length && mode === "edit" && <CutEditor ep={ep} onExported={() => setTick((n) => n + 1)} />}
      {cuts && !cuts.length && mode !== "edit" && <Empty icon="▶" title={`第 ${ep} 集还没有成片`} sub={oldN > 0 ? `换剧本之前合成的 ${oldN} 版成片还在，点上面“显示旧剧本的成片”能看、能删。新剧本的视频都通过后点“合成新版本”。` : "视频都通过后点“合成新版本”。合成只用 CPU，不占显卡。"} />}

      {cuts && cuts.length > 0 && (
        <div className="cut-body">
          <aside className="cut-list" aria-label="成片版本">
            {oldN > 0 && (
              <button className="ds-btn ghost sm" onClick={() => setShowOld((v) => !v)} title="比当前剧本导入更早合成的成片（旧剧本），文件都在，默认不显示">
                {showOld ? `隐藏旧剧本的成片（${oldN}）` : `显示旧剧本的成片（${oldN}）`}
              </button>
            )}
            {cuts.map((c, i) => (
              <div key={c.name} className="cut-item-w">
              <button
                className={`cut-item${c.name === sel ? " on" : ""}${mode === "cmp" && other?.name === c.name && c.name !== sel ? " cmp" : ""}`}
                onClick={() => {
                  if (mode === "edit") setMode("one");
                  if (mode === "cmp" && c.name !== sel) setCmpWith(c.name);
                  else setSel(c.name);
                }}
                title={c.timeline?.note ?? c.name}
              >
                <span className="cut-item-t">
                  <b title={c.name}>{niceName(c.name)}</b>
                  {i === 0 && <Tag tone="accent">最新</Tag>}
                </span>
                <span className="ds-muted ds-small">
                  {c.mtime.slice(5, 16).replace("T", " ")} · {fmtS(c.timeline?.duration_s)} · {(c.size / 1048576).toFixed(1)} MB
                </span>
                <span className="ds-row" style={{ gap: 4 }}>
                  {c.tags.map((t) => (
                    <Tag key={t} tone={t === "定稿" ? "accent" : t === "勿用" ? "bad" : t === "未完成" || t === "预览" ? "warn" : "neutral"}>
                      {t}
                    </Tag>
                  ))}
                  {i === 0 && voiceChg.length > 0 && (
                    <Tag tone="stale" title={`这版成片之后改过音色：${voiceChg.map((v) => `${v.label}（${v.at.slice(5, 16).replace("T", " ")}）`).join("、")}；需要重新合成`}>
                      音色改过 {voiceChg.length}
                    </Tag>
                  )}
                  {c.changed.length > 0 && (
                    <Tag tone="stale" title={`这版成片之后，${c.changed.length} 镜换了定稿视频`}>
                      落后 {c.changed.length} 镜
                    </Tag>
                  )}
                </span>
              </button>
              <CutMore c={c} onDeleted={() => setTick((n) => n + 1)} />
              </div>
            ))}
            {mode === "cmp" && <p className="ds-muted ds-small">对比模式：先点一版当左边（蓝框），再点另一版当右边（橙框）。</p>}
          </aside>

          <section className="cut-main">
            {mode === "edit" && <CutEditor ep={ep} onExported={() => setTick((n) => n + 1)} />}
            {mode === "one" && cur && <CutView c={cur} onDeleted={() => setTick((n) => n + 1)} />}
            {mode === "cmp" && cur && other && <CutCompare a={cur} b={other} onDeleted={() => setTick((n) => n + 1)} />}
          </section>
        </div>
      )}

      {ask && (
        <Modal
          title={`合成第 ${ep} 集新版本？`}
          sub="按当前定稿把镜头视频、对白、配乐装配成一条成片。只用 CPU（不占显卡），大约几分钟到十几分钟。会另存为新文件（名字带 UI+时间），不覆盖已有成片。"
          onClose={() => setAsk(false)}
          foot={
            <>
              <Button onClick={() => setAsk(false)}>取消</Button>
              <Button variant="primary" disabled={busy} onClick={() => void start()}>
                {busy ? "正在开始…" : "确认合成"}
              </Button>
            </>
          }
        >
          <label className="ds-kv" style={{ alignItems: "center" }}>
            <dt>对白来源</dt>
            <dd>
              <select className="ds-input" value={dlg} onChange={(e) => setDlg(e.target.value)}>
                <option value="">按配置默认</option>
                <option value="h3">H3 原声（嘴型同步）</option>
                <option value="tts">配音（TTS）</option>
                <option value="auto">自动</option>
              </select>
            </dd>
          </label>
          {cur && cur.changed.length > 0 && <p className="ds-note info">和当前选中的 {cur.name} 相比，{cur.changed.length} 镜换了定稿视频，新版本会用新的定稿。</p>}
        </Modal>
      )}
    </div>
  );
}

/** CUTEDIT（总调度 11-02，L-123）：删除只放在每一版的“⋯”菜单里，动作是移到回收区（EDITDEL 回收站，可还原） */
function CutMore({ c, onDeleted }: { c: Cut; onDeleted?: () => void }) {
  const rel = relFromUrl(c.url);
  if (!rel) return null;
  return (
    <details className="cut-more">
      <summary title="更多">⋯</summary>
      <div className="cut-more-pop">
        <DeleteButton type="cut" id={rel} size="sm" label="移到回收区" onDeleted={() => onDeleted?.()} />
      </div>
    </details>
  );
}

function CutInfo({ c, onDeleted }: { c: Cut; onDeleted?: () => void }) {
  const tl = c.timeline;
  void onDeleted;
  return (
    <div className="cut-info">
      <dl className="ds-kv">
        <dt>时长</dt>
        <dd>{fmtS(tl?.duration_s)}（{tl?.shots ?? "—"} 镜）</dd>
        <dt>对白</dt>
        <dd>{tl?.dialogue_source ? DLG[tl.dialogue_source] ?? tl.dialogue_source : "—"}</dd>
        <dt>状态</dt>
        <dd>{tl ? (tl.preview ? "预览（还有没完成的部分）" : "正式") : "没有时间线文件"}</dd>
        {!!tl?.missing?.length && (
          <>
            <dt>缺镜头</dt>
            <dd className="ac-miss">{tl.missing.join("、")}（用静帧占位）</dd>
          </>
        )}
      </dl>
      {c.changed.length > 0 && (
        <div className="cut-changed">
          <b>这版之后换了定稿的镜头（{c.changed.length}）</b>
          <div className="mt-shots">
            {c.changed.map((x) => (
              <a key={x.shot_id} className="ac-shot" href={`#${x.shot_id}`} title={`成片里用的：${x.used}\n现在${x.current_locked ? "定稿" : "当前"}：${x.current}`}>
                {x.shot_id.split("-")[1]}
              </a>
            ))}
          </div>
        </div>
      )}
      {!!tl?.warnings && (
        <details className="cut-warn">
          <summary>装配提示 {tl.warnings} 条</summary>
          <ul>
            {(tl.warning_list ?? []).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
      {tl?.note && <p className="ds-muted ds-small">{tl.note}</p>}
    </div>
  );
}

function CutView({ c, onDeleted }: { c: Cut; onDeleted?: () => void }) {
  return (
    <div className="cut-one">
      <video key={c.url} className="cut-video" src={`${c.url}#t=0.1`} controls preload="metadata" />
      <CutInfo c={c} onDeleted={onDeleted} />
    </div>
  );
}

/** 两版并排，同步播放 / 暂停 / 拖动（以左边为准） */
function CutCompare({ a, b, onDeleted }: { a: Cut; b: Cut; onDeleted?: () => void }) {
  const la = useRef<HTMLVideoElement>(null);
  const lb = useRef<HTMLVideoElement>(null);
  const sync = (ev: "play" | "pause" | "seeked") => {
    const x = la.current;
    const y = lb.current;
    if (!x || !y) return;
    if (ev === "play") void y.play().catch(() => undefined);
    if (ev === "pause") y.pause();
    if (Math.abs(y.currentTime - x.currentTime) > 0.2) y.currentTime = x.currentTime;
  };
  return (
    <div className="cut-cmp">
      {[a, b].map((c, i) => (
        <figure key={c.name} className={i ? "r" : "l"}>
          <figcaption>
            <b>{i ? "右" : "左"}</b> {niceName(c.name)}
          </figcaption>
          <video ref={i ? lb : la} className="cut-video" src={`${c.url}#t=0.1`} controls={!i} muted={!!i} preload="metadata" onPlay={() => !i && sync("play")} onPause={() => !i && sync("pause")} onSeeked={() => !i && sync("seeked")} />
          <CutInfo c={c} onDeleted={onDeleted} />
        </figure>
      ))}
    </div>
  );
}

/** UIRSI r3（P11 → P12）：成片交付闸门就放在成片页——和画布“待你决定”是同一个确认框（POST /api/sop/owner-decision gate=G5，
 *  登录的项目方一个按钮确认（2026-10-31 起不再勾选本人、不再填原话）；记录逻辑 = tools/sop_owner.py g5）。还不能确认时写明在等什么。 */
function DeliveryGate({ ep }: { ep: number }) {
  const { sop } = useSop();
  const [open, setOpen] = useState<SopOwnerAction | null>(null);
  if (!sop || sop.episode !== ep) return null;
  const gate = sop.gates.find((g) => g.id === "G5");
  const act = sop.owner_actions.find((a) => a.gate === "G5");
  const passed = gate?.status === "passed";
  const tone = passed ? "ok" : act?.actionable ? "accent" : "neutral";
  return (
    <section className={`cut-gate ${tone}`} aria-label="成片交付闸门">
      <span className="cut-gate-n">闸</span>
      <div className="cut-gate-t">
        <b>成片交付{passed ? " · 已确认" : act?.actionable ? " · 等你确认" : " · 还不能确认"}</b>
        <small className="ds-muted">
          {passed
            ? gate?.detail || "这一集的成片已由你确认"
            : act?.actionable
              ? "看完最新一版没问题就确认交付；不满意就选“返工”并写清哪几镜"
              : act?.waiting_on?.length
                ? `在等：${act.waiting_on.join("；")}`
                : `${gate?.detail ? `${gate.detail} · ` : ""}先过前面的关口：${sop.gates.filter((g) => g.id !== "G5" && (g.status === "blocked" || g.status === "pending")).map((g) => g.label).join("、") || "前面的步骤"}（画布顶部“待你决定”）`}
        </small>
      </div>
      {act && (
        <Button variant={act.actionable && !passed ? "primary" : "secondary"} size="sm" disabled={!act.actionable} why={`还不能确认：${act.waiting_on.join("；") || "前面的步骤还没走完"}`} onClick={() => setOpen(act)}>
          {passed ? "改判 / 返工…" : "确认交付 / 返工…"}
        </Button>
      )}
      {open && <OwnerDecisionDialog a={open} onClose={() => setOpen(null)} />}
    </section>
  );
}

/** UIRSI r14（看不懂的字）：文件名 → 人话。ep02_v2a.mp4 → “v2a”；预览 / 未完成 / 勿用 / H3 原声 这些已经是标签，名字里去掉 */
function niceName(name: string): string {
  const plan = /^方案 ([A-Z]) · /.exec(name);
  let n = name.replace(/^方案 [A-Z] · /, "").replace(/\.mp4$/, "").replace(/^ep\d{2}[_·\s-]*/i, "");
  n = n.replace(/PREVIEW|预览|未完成|勿用|H3原声|[_·•]+/g, " ").replace(/\s+/g, " ").trim();
  return `${plan ? `方案 ${plan[1]} · ` : ""}${n || "预览版"}`;
}
