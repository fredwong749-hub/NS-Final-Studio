// FILMUI · 图像工坊 P1（项目方 11-02 12:5x：“为什么没有 UI，做了一半也没做完？”；总调度 13:0x 授权，架构见 docs/master/EDITOR_INTEGRATION.md）。
// 路由 #/image-edit?shot=epNN-SN（以后 ?session=… 由 UIRSI2 的 edit_session 带入；接口没上线时退回 ?shot=）。
// 真能用、不做假：
//   · 基座列表 GET /api/image-workshop/bases（IMGLAB bases_api 的就绪状态）；只有接通出图路径（submit）的基座能点“出图”
//   · Qwen-Image 2.1（S★ R0）出图 = 现有 POST /api/shots/{id}/frame-jobs {scope:"ab", experiment:"workshop"}：
//     用本镜编译好的提示词和参考图（身份脸 / 设定图 / 场景），结果只进 data/ab/workshop/，不写镜头账本、不设当前
//   · 历史 GET /api/image-workshop/history + 本镜现有版本（GET /api/shots/{id} 的 takes）；质检 = 出图时的 postflight 契约
//   · “采用到镜头 / 采用为资产”等结构问题 #16（一本账，sv-11）上线前禁用；“设为候选”只是本机标记
// 设计稿：data/review_pages/filmui/image_edit.html（风格 A）。
// NAVFLOW-F 11-03（L-146，项目方：“image editor 在 V1 你做了半成品，在 V2 直接没有了”）：挂回 ②资产（资产中心左栏）和 ④出图（出图页抽屉“到图像编辑器里改”）；
//   “修改”= 全站同一个口语化一句话入口（Verdict → EditBox → /api/shots/{id}/frame-edit → prompt_rewrite → Qwen-Image-Edit，L-119 / L-120），不另写；
//   界面文字去掉技术词；后端 /api/shots、/api/image-workshop 都按当前剧取路径，不需要别的参数。
import { useCallback, useEffect, useMemo, useState, type MouseEvent } from "react";
import { FilmStrip, type FilmFrame } from "./FilmOverview";
import { Verdict } from "../Verdict";
import "../imageedit.css";

type Base = { id: string; name: string; license: string; state: string; state_detail: string; presets: { id: string; label: string }[]; submit: string | null; size: number[]; max_refs: number; mode?: string | null };
type Check = { id: string; title: string; status: string; detail?: string };
type Item = { key: string; src: string | null; label: string; seed?: number | null; origin: "shot" | "workshop"; n?: number; active?: boolean; prompt?: string; refs?: unknown; checks?: Check[]; created?: string; seconds?: number | null; pending?: string; jobId?: string };
type RefImg = { file: string; label: string; kind: string; character?: string };

const q = () => new URLSearchParams(location.hash.split("?")[1] ?? "");
const files = (rel?: string | null) => (rel ? (rel.startsWith("/") ? rel : `/files/${rel.replace(/^data\//, "")}`) : null);
const DOT = (s: string) => (s === "pass" ? "ok" : s === "fail" ? "need" : null);

async function getJson<T>(url: string): Promise<T | null> {
  try {
    const r = await fetch(url);
    return r.ok ? ((await r.json()) as T) : null;
  } catch {
    return null;
  }
}

export default function ImageEditPage() {
  const [shot, setShot] = useState(() => q().get("shot") ?? "ep01-S1");
  const session = q().get("session");
  const stage: "first" | "last" = q().get("stage") === "last" ? "last" : "first"; // 从出图页抽屉带进来：首帧 / 尾帧
  const [bases, setBases] = useState<Base[] | null>(null);
  const [baseErr, setBaseErr] = useState<string | null>(null);
  const [base, setBase] = useState("qwen21");
  const [count, setCount] = useState(4);
  const [seed, setSeed] = useState<string>("");
  const [lock, setLock] = useState(false);
  const [shotData, setShotData] = useState<{ prompt: string; items: Item[]; refs: RefImg[]; active: number | null } | null>(null);
  const [ws, setWs] = useState<Item[]>([]);
  const [pend, setPend] = useState<Item[]>(() => JSON.parse(localStorage.getItem(`ie.pend.${shot}`) ?? "[]"));
  const [a, setA] = useState<string | null>(null);
  const [b, setB] = useState<string | null>(null);
  const [tab, setTab] = useState<"ref" | "qc" | "meta" | "tree">("ref");
  const [cand, setCand] = useState<string[]>(() => JSON.parse(localStorage.getItem(`ie.cand.${shot}`) ?? "[]"));
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const toast = (t: string) => { setMsg(t); window.setTimeout(() => setMsg(null), 3200); };
  useEffect(() => localStorage.setItem(`ie.pend.${shot}`, JSON.stringify(pend)), [pend, shot]);
  useEffect(() => localStorage.setItem(`ie.cand.${shot}`, JSON.stringify(cand)), [cand, shot]);

  // 基座
  useEffect(() => {
    getJson<{ bases: Base[] }>("/api/image-workshop/bases").then((d) => (d ? setBases(d.bases) : (setBaseErr("出图模型列表还没读到（后台重启后出现）；现在用默认模型出图"), setBases(null))));
  }, []);
  // 本镜上下文：编译提示词、现有版本、参考图
  const loadShot = useCallback(async () => {
    const [d, r, h] = await Promise.all([
      getJson<{ compiled?: { image_prompt?: string }; script?: { img_prompt?: string }; takes?: { active?: { image?: number }; takes?: { n: number; stage: string; file: string; seed?: number; prompt?: string; created_at?: string; seconds?: number; postflight?: { items?: Check[] } }[] } }>(`/api/shots/${shot}`),
      getJson<{ characters?: { effective?: { images?: RefImg[] } }[]; scene?: { images?: RefImg[] } }>(`/api/shots/${shot}/refs`),
      getJson<{ items: { id: string; seed: number; url: string; created_at: string; seconds: number; prompt: string; refs: unknown; postflight?: { items?: Check[] } }[] }>(`/api/image-workshop/history?shot=${shot}`),
    ]);
    const active = d?.takes?.active?.image ?? null;
    const items: Item[] = (d?.takes?.takes ?? []).filter((t) => t.stage === "image").map((t) => ({
      key: `t${t.n}`, src: files(t.file), label: `v${t.n}${t.n === active ? " 当前" : ""}`, seed: t.seed, origin: "shot" as const, n: t.n, active: t.n === active,
      prompt: t.prompt, checks: t.postflight?.items, created: t.created_at, seconds: t.seconds,
    })).slice(-8);
    const refs: RefImg[] = [...(r?.characters ?? []).flatMap((c) => c.effective?.images ?? []), ...(r?.scene?.images ?? [])];
    setShotData({ prompt: d?.compiled?.image_prompt ?? d?.script?.img_prompt ?? "", items, refs, active });
    setWs((h?.items ?? []).map((x) => ({ key: `w${x.id}`, src: x.url, label: `试出 s${String(x.seed).slice(-4)}`, seed: x.seed, origin: "workshop" as const, prompt: x.prompt, refs: x.refs, checks: x.postflight?.items, created: x.created_at, seconds: x.seconds })));
  }, [shot]);
  useEffect(() => { loadShot(); }, [loadShot]);
  useEffect(() => { if (!a && shotData) setA(shotData.items.find((x) => x.active)?.key ?? shotData.items[shotData.items.length - 1]?.key ?? null); }, [shotData, a]);

  // 轮询排队中的任务
  useEffect(() => {
    if (!pend.length) return;
    const t = window.setInterval(async () => {
      const next: Item[] = [];
      let done = false;
      for (const p of pend) {
        const j = await getJson<{ state: string; error?: string; started_at?: string; take?: { id: string; file: string; seed: number } }>(`/api/jobs/${p.jobId}`);
        if (!j) { next.push(p); continue; }
        if (j.state === "done" && j.take) { done = true; continue; }
        if (j.state === "failed" || j.state === "cancelled") { toast(`出图失败：${(j.error ?? j.state).slice(0, 80)}`); continue; }
        const secs = j.started_at ? Math.round((Date.now() - Date.parse(j.started_at)) / 1000) : null;
        next.push({ ...p, pending: j.state === "running" ? `出图中 ${secs ?? ""}s` : "排队中" });
      }
      setPend(next);
      if (done) { loadShot(); toast("新图出来了：已放进历史片条"); }
    }, 4000);
    return () => window.clearInterval(t);
  }, [pend, loadShot]);

  const all: Item[] = useMemo(() => [...pend, ...ws, ...(shotData?.items ?? []).slice().reverse()], [pend, ws, shotData]);
  const A = all.find((x) => x.key === a) ?? null;
  const B = all.find((x) => x.key === b) ?? null;
  const cur = bases?.find((x) => x.id === base);
  const canSubmit = base === "qwen21" && (!bases || cur?.submit === "frame_jobs_ab");

  const generate = async () => {
    if (!canSubmit) return toast(cur ? `${cur.name}：${cur.state === "ready" ? "出图接口还没接上（P3）" : "准备中"}` : "这个基座还不能出图");
    setBusy(true);
    const s0 = seed && /^\d+$/.test(seed) ? Number(seed) : Math.floor(Math.random() * 2 ** 40);
    const made: Item[] = [];
    for (let i = 0; i < count; i++) {
      try {
        const r = await fetch(`/api/shots/${shot}/frame-jobs`, {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ stage: "first", mode: "regen", tier: "preview", scope: "ab", experiment: "workshop", ab_tier: "w1", seed: s0 + i, yield_lane: false }),
        });
        const j = await r.json();
        if (!r.ok) { toast(`没交上：${String(j.detail ?? r.status).slice(0, 90)}`); break; }
        made.push({ key: `p${j.job_id}`, jobId: j.job_id, src: null, label: `排队 s${String(s0 + i).slice(-4)}`, seed: s0 + i, origin: "workshop", pending: "排队中" });
      } catch (e) { toast(`没交上：${String(e).slice(0, 80)}`); break; }
    }
    if (made.length) { setPend((p) => [...made, ...p]); toast(`已交 ${made.length} 张（Qwen-Image 2.1 · 本镜编译提示词 + 参考图）`); }
    if (!lock) setSeed("");
    setBusy(false);
  };

  const frames: FilmFrame[] = all.map((x) => ({ key: x.key, src: x.pending ? null : x.src, empty: x.pending ?? "未曝光", ed: `${cand.includes(x.key) ? "★ " : ""}${x.label}`, cap: x.label, dot: x.checks?.length ? (x.checks.some((c) => c.status === "fail") ? "need" : "ok") : x.pending ? "run" : null }));
  const pick = (i: number, ev: MouseEvent) => { const k = all[i]?.key; if (!k || all[i].pending) return; if (ev.shiftKey) setB(k); else setA(k); };

  return (
    <div className="ie">
      <div className="ie-hd">
        <h1>图像编辑器</h1>
        <label className="ie-shot">镜头 <input value={shot} onChange={(e) => setShot(e.target.value.trim())} onKeyDown={(e) => e.key === "Enter" && (location.hash = `#/image-edit?shot=${shot}&stage=${stage}`, setA(null), loadShot())} /></label>
        <span className="ie-src">{session ? "从会话打开：按这一镜的上下文显示" : `这一镜的${stage === "last" ? "尾帧" : "首帧"}：提示词、参考图都是系统为它准备的`}</span>
        <span className="ie-sp" />
        {/* L-123：只有“用这张 / 修改”两个动作——和出图页、画布同一个入口（一句话 → 系统改写提示词 → 出修改版，失败就不出图） */}
        {A && A.origin === "shot" && A.n != null ? (
          <span className="ie-verdict" onClick={() => window.setTimeout(loadShot, 1200)}>
            <Verdict shot={shot} stage={stage} n={A.n} size="md" />
          </span>
        ) : (
          <span className="ie-note">在下面片条里点一张镜头版本，就能“用这张”或“修改”</span>
        )}
        <button className="ie-btn" disabled title="编辑器里试出的图直接设为镜头当前版——这一步还在接通中，先用“修改”出改好的版本">采用到镜头（接通中）</button>
        <button className="ie-btn" disabled title="把试出的图登记为资产（设定图 / 单品）——这一步还在接通中">采用为资产（接通中）</button>
      </div>
      <div className="ie-ws">
        <aside className="ie-l">
          <h4>出图模型<span>亮绿点的能用</span></h4>
          {baseErr && <p className="ie-note">{baseErr}</p>}
          {(bases ?? [{ id: "qwen21", name: "Qwen-Image 2.1（S★ R0）", state: "ready", state_detail: "生产在用", submit: "frame_jobs_ab", license: "", presets: [], size: [768, 1344], max_refs: 10 } as Base]).map((x) => {
            const ok = x.state === "ready";
            return (
              <button key={x.id} className={`ie-base${base === x.id ? " on" : ""}`} disabled={!ok} onClick={() => setBase(x.id)} title={`${x.license}\n${x.state_detail}`}>
                <i className="rd" />
                <span className="nm">{x.name}</span>
                <span className="ds"><i className={`sea-dot d-${ok ? (x.submit ? "ok" : "need") : "none"}`} />{!ok ? "准备中" : x.submit ? "就绪" : "就绪 · 出图接口待接"}{x.mode === "t2i_no_identity" ? " · 文生图（无身份参考）" : ""}</span>
              </button>
            );
          })}
          <h4>生成</h4>
          <div className="ie-row"><span>张数</span><span className="ie-seg">{[1, 2, 4].map((n) => <button key={n} className={count === n ? "on" : ""} onClick={() => setCount(n)}>{n}</button>)}</span></div>
          <div className="ie-row"><span>种子</span><input className="ie-in" placeholder="随机" value={seed} onChange={(e) => setSeed(e.target.value.replace(/\D/g, ""))} /><label className="ie-chk"><input type="checkbox" checked={lock} onChange={(e) => setLock(e.target.checked)} />锁定</label></div>
          <div className="ie-row"><span>预设</span><span className="ie-v">{cur?.presets?.[0]?.label ?? "默认"} · 预览档</span></div>
          <p className="ie-note">这里出的图先放在“试出”区，不改镜头的当前版本；要改当前版本，用上面的“修改”写一句话。</p>
        </aside>
        <section className="ie-mid">
          <div className="ie-stage">
            {[A, B].filter(Boolean).map((x, i) => (
              <figure key={x!.key} className="ie-pane">
                {x!.src ? <img src={x!.src} alt="" /> : <div className="ie-none">{x!.pending ?? "未曝光"}</div>}
                <figcaption><b>{B ? (i ? "B" : "A") : ""}</b> {x!.label}{x!.seed ? ` · seed ${x!.seed}` : ""}{cand.includes(x!.key) ? " · ★ 候选" : ""}</figcaption>
              </figure>
            ))}
            {!A && <div className="ie-none">在下面片条里点一张</div>}
          </div>
          <div className="ie-bar">
            <span>点片条 = 放上图台 · Shift + 点 = 并排对比</span>
            {B && <button className="ie-lnk" onClick={() => setB(null)}>关掉对比</button>}
            <span className="ie-sp" />
            {A && !A.pending && <button className="ie-lnk" onClick={() => setCand((c) => (c.includes(A.key) ? c.filter((k) => k !== A.key) : [...c, A.key]))}>{cand.includes(A.key) ? "取消候选" : "★ 设为候选"}</button>}
          </div>
          <div className="ie-prompt">
            <div className="ie-pt"><b>提示词</b><span>系统为 {shot} 写好的（只读；要改画面，用“修改”写一句话，系统会改写提示词）</span></div>
            <textarea readOnly value={shotData?.prompt ?? ""} />
            <button className="ie-go" disabled={busy || !canSubmit} onClick={generate}><b>出图</b><span>{cur?.name ?? "Qwen-Image 2.1"} · {count} 张</span></button>
          </div>
          <div className="ie-hist">
            <div className="ie-ht"><span>出图历史 · 试出的图在左，镜头版本在右</span><span>{pend.length ? `${pend.length} 张在路上` : ""}</span></div>
            <div className="ie-scroll"><FilmStrip frames={frames} H={92} thumbW={240} onFrame={pick} /></div>
          </div>
        </section>
        <aside className="ie-r">
          <nav className="ie-tabs">{([["ref", "参考图"], ["qc", "质检"], ["meta", "元数据"], ["tree", "版本"]] as const).map(([k, t]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{t}</button>)}</nav>
          {tab === "ref" && (
            <div className="ie-refs">
              <p className="ie-note">系统给这一镜准备的参考图（身份脸 / 设定图 / 单品 / 场景）。要换参考，到资产中心改人物的造型和单品。</p>
              {(shotData?.refs ?? []).map((r) => (
                <figure key={r.file}><img src={files(r.file) ?? ""} alt="" /><figcaption>{r.label}</figcaption></figure>
              ))}
            </div>
          )}
          {tab === "qc" && (
            <div className="ie-qc">
              {A?.checks?.length ? A.checks.map((c) => <div key={c.id} className="ie-ck"><i className={`sea-dot d-${DOT(c.status) ?? "none"}`} /><b>{c.id}</b><span>{c.title}　{c.detail}</span></div>) : <p className="ie-note">{A ? "这一版没有契约记录" : "先选一张"}</p>}
            </div>
          )}
          {tab === "meta" && A && (
            <dl className="ie-meta">
              <dt>来源</dt><dd>{A.origin === "shot" ? "镜头版本" : "编辑器试出的图"}</dd>
              <dt>种子</dt><dd className="mono">{A.seed ?? "—"}</dd>
              <dt>时间</dt><dd className="mono">{A.created?.replace("T", " ") ?? "—"}</dd>
              <dt>用时</dt><dd className="mono">{A.seconds ? `${A.seconds} s` : "—"}</dd>
              <dt>提示词</dt><dd><pre>{A.prompt || "—"}</pre></dd>
            </dl>
          )}
          {tab === "tree" && (
            <div className="ie-tree">
              {(shotData?.items ?? []).map((x) => (
                <button key={x.key} className={`ie-nd${a === x.key ? " on" : ""}`} onClick={() => setA(x.key)}>{x.src && <img src={x.src} alt="" />}<span>{x.label}</span></button>
              ))}
              {ws.length > 0 && <div className="ie-branch">└ 编辑器试出的图（从当前版 v{shotData?.active ?? "?"} 的提示词和参考出）</div>}
              {ws.map((x) => (
                <button key={x.key} className={`ie-nd sub${a === x.key ? " on" : ""}`} onClick={() => setA(x.key)}>{x.src && <img src={x.src} alt="" />}<span>{x.label}{cand.includes(x.key) ? " ★" : ""}</span></button>
              ))}
              <p className="ie-note">按时间先后排列。</p>
            </div>
          )}
        </aside>
      </div>
      {msg && <div className="ie-toast">{msg}</div>}
    </div>
  );
}
