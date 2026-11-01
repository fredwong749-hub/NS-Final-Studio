// 剧本 A/B 对比页（K-UI-030 恢复：归档前 components/ScriptAB.tsx 的功能一项不少，换成现行设计体系）。
// 项目方原话：“两个都要，看看那个写出画面更漂亮，更有短剧感觉”。
// 同集同镜并排：两版原文 + 两版各自的首帧 / 尾帧 / 视频；只记录你的选择，系统不打分。
// 后端：services/api/ns_api/script_ab.py（/api/script-ab/sources | episode | choice | choices），会话草稿读 /api/script-chat/sessions。
// 路由：#/script-ab；可带 ?sa=<会话id>&sb=<会话id>（同一提纲交给两个模型写的两份草稿）直接对比。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, LoadError, Skel, Tag } from "../../ds";
import { Lightbox } from "../../ds/MediaPlayer";
import { useMe } from "../../projects/AuthGate.helpers";
import { useHash } from "../../projects/route";
import "./pages.css";
import "./script_ab.css";

interface Renders {
  first: string | null;
  last: string | null;
  video: string | null;
}
interface Timing {
  seconds: number;
  source: string;
  frames: number;
  h3_seconds: number;
  ok: boolean;
  hint: string;
}
interface ShotV {
  id: string;
  index: number;
  duration: number;
  timing: Timing;
  img: string;
  motion: string;
  last_state: string;
  sound: string;
  sound_h3: string;
  music_cue: string;
  intimate: string;
  dialogue: { speaker: string | null; text: string; stage: string | null }[];
  voiceover: string | null;
  h3_prompt: string;
  renders: Renders;
}
interface Side {
  path: string;
  name: string;
  sha256: string;
  version: string;
  episodes: number[];
  episode: { number: number; title: string; synopsis: string; music: string; music_bgm: string; shots: ShotV[] } | null;
}
interface Choice {
  at: string;
  ep: number;
  shot: string | null;
  pick: "A" | "B";
  a: string;
  b: string;
}
type SessInfo = { id: string; title: string; episodes: Record<string, string> | number[]; episode_range?: number[] | null; validation?: { draft?: string } | null; ab?: { group: string; side: string } | null };
type K = "A" | "B";

async function getJ<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const t = await r.text();
  if (!r.ok) {
    let m = t;
    try {
      const d = JSON.parse(t).detail;
      m = typeof d === "string" ? d : JSON.stringify(d ?? t);
    } catch {
      /* 原文 */
    }
    throw new Error(m || `HTTP ${r.status}`);
  }
  return JSON.parse(t) as T;
}

const PREF = "ns.ab";
function loadPref(): { a: string; b: string; ep: number } {
  try {
    return { a: "", b: "", ep: 1, ...JSON.parse(localStorage.getItem(PREF) ?? "{}") };
  } catch {
    return { a: "", b: "", ep: 1 };
  }
}
const pad = (n: number) => String(n).padStart(2, "0");
const sessDraft = (id: string) => `data/script_chat/${id}/script.md`;
const epNums = (x: SessInfo | null) => (Array.isArray(x?.episodes) ? (x!.episodes as number[]) : Object.keys(x?.episodes ?? {}).map(Number));

/** 会话参数：#/script-ab?sa=..&sb=..（也认旧地址 ?view=ab&sa=..&sb=..） */
function useSessParams(): { a: string | null; b: string | null } {
  const h = useHash();
  return useMemo(() => {
    const q = new URLSearchParams(h.split("?")[1] ?? "");
    const s = new URLSearchParams(location.search);
    return { a: q.get("sa") ?? s.get("sa"), b: q.get("sb") ?? s.get("sb") };
  }, [h]);
}
function setSessParams(a: string | null, b: string | null) {
  const [base, qs] = location.hash.split("?");
  const q = new URLSearchParams(qs ?? "");
  if (a && b) {
    q.set("sa", a);
    q.set("sb", b);
  } else {
    q.delete("sa");
    q.delete("sb");
  }
  const s = q.toString();
  history.replaceState(null, "", `${location.pathname}${base || "#/script-ab"}${s ? `?${s}` : ""}`);
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

/** 时长：剧本秒数 + 视频实际帧数档位；没写 / 超范围醒目提示 */
function Dur({ k, s, diff }: { k: K; s?: ShotV; diff: boolean }) {
  if (!s)
    return (
      <Tag tone="bad" pill>
        {k} 无此镜
      </Tag>
    );
  const t = s.timing;
  const tone = !t.ok || t.source !== "script" ? "bad" : diff ? "warn" : "neutral";
  return (
    <Tag tone={tone} pill title={`${t.source === "script" ? "剧本写明" : "剧本没写，按默认"} ${t.seconds} 秒 → 视频 ${t.frames} 帧（${t.h3_seconds} 秒）${t.hint ? `\n${t.hint}` : ""}${diff ? "\n两版时长不同" : ""}`}>
      {k} 时长 {t.seconds} 秒{t.source !== "script" ? "（默认）" : ""} · {t.frames} 帧
    </Tag>
  );
}

function Media({ r, label, onZoom }: { r: Renders; label: string; onZoom: (src: string) => void }) {
  if (!r.first && !r.last && !r.video) return <div className="sab-none">首帧 / 尾帧 / 视频：还没出（两版剧本定稿后一起出图）</div>;
  return (
    <div className="sab-media">
      {(["first", "last"] as const).map((k) => {
        const name = k === "first" ? "首帧" : "尾帧";
        const src = r[k];
        return (
          <figure key={k}>
            {src ? (
              <button type="button" className="sab-thumb" onClick={() => onZoom(src)} title={`放大看 ${label} ${name}`}>
                <img src={src} alt={`${label} ${name}`} loading="lazy" />
              </button>
            ) : (
              <div className="sab-empty">{name}还没出</div>
            )}
            <figcaption>{name}</figcaption>
          </figure>
        );
      })}
      <figure>
        {r.video ? <video src={r.video} controls muted playsInline preload="metadata" /> : <div className="sab-empty">视频还没出</div>}
        <figcaption>视频</figcaption>
      </figure>
    </div>
  );
}

function ShotText({ s }: { s: ShotV }) {
  return (
    <dl className="sab-text">
      <dt>首帧画面</dt>
      <dd>{s.img || "—"}</dd>
      <dt>运动</dt>
      <dd>{s.motion || "—"}</dd>
      <dt>尾帧状态</dt>
      <dd>{s.last_state || "—"}</dd>
      {s.dialogue.length > 0 && (
        <>
          <dt>对白</dt>
          <dd>
            {s.dialogue.map((d, i) => (
              <div key={i}>
                {d.speaker ? `（${d.speaker}）` : ""}“{d.text}”
              </div>
            ))}
          </dd>
        </>
      )}
      {s.voiceover && (
        <>
          <dt>独白</dt>
          <dd>{s.voiceover}</dd>
        </>
      )}
      <dt>声音 / 配乐</dt>
      <dd>
        {s.sound_h3 || s.sound || "—"}
        {s.music_cue && <div className="v3p-muted">配乐：{s.music_cue}</div>}
      </dd>
      <details className="sab-h3">
        <summary>视频提示词</summary>
        <pre>{s.h3_prompt || "（这一版没有视频提示词）"}</pre>
      </details>
    </dl>
  );
}

/** 整集连播：按镜顺序播放一版的视频（没有视频的镜跳过）；可随时切到另一版 */
function Reel({ rows, side, onSide, onClose }: { rows: { a?: ShotV; b?: ShotV }[]; side: K; onSide: (s: K) => void; onClose: () => void }) {
  const list = rows.map((r) => (side === "A" ? r.a : r.b)).filter((s): s is ShotV => !!s?.renders.video);
  const [i, setI] = useState(0);
  useEffect(() => setI(0), [side]);
  const cur = list[i];
  return (
    <section className="sab-reel" aria-label="整集连播">
      <header className="sab-reel-head">
        <b>连播 {side} 版</b>
        <span className="v3p-muted">{list.length ? `${i + 1} / ${list.length} · ${cur?.id}` : "这一版还没有视频"}</span>
        <span className="grow" />
        <Button size="sm" disabled={i === 0} why="已经是第一镜" onClick={() => setI((x) => Math.max(0, x - 1))}>
          ‹ 上一镜
        </Button>
        <Button size="sm" disabled={i + 1 >= list.length} why="已经是最后一镜" onClick={() => setI((x) => x + 1)}>
          下一镜 ›
        </Button>
        <Button size="sm" variant="primary" onClick={() => onSide(side === "A" ? "B" : "A")}>
          切到 {side === "A" ? "B" : "A"} 版
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          停止连播
        </Button>
      </header>
      {cur && <video key={cur.id + side} src={cur.renders.video!} autoPlay controls playsInline onEnded={() => setI((x) => (x + 1 < list.length ? x + 1 : x))} />}
    </section>
  );
}

/** 同一提纲两个模型写的会话对（剧本创作里“交给两个模型”产生） */
function SessionPairs({ cur, onPick }: { cur: { a: string | null; b: string | null }; onPick: (a: string | null, b: string | null) => void }) {
  const [list, setList] = useState<SessInfo[] | null>(null);
  useEffect(() => {
    getJ<SessInfo[]>("/api/script-chat/sessions").then(setList, () => setList([]));
  }, []);
  const pairs = useMemo(() => {
    const g = new Map<string, { a?: SessInfo; b?: SessInfo }>();
    for (const s of list ?? []) {
      if (!s.ab?.group) continue;
      const p = g.get(s.ab.group) ?? {};
      if (s.ab.side === "b" || s.ab.side === "B") p.b = s;
      else p.a = s;
      g.set(s.ab.group, p);
    }
    return [...g.entries()].filter(([, p]) => p.a && p.b) as [string, { a: SessInfo; b: SessInfo }][];
  }, [list]);
  if (!pairs.length && !(cur.a && cur.b)) return null;
  const val = cur.a && cur.b ? `${cur.a}|${cur.b}` : "";
  return (
    <label className="v3p-f sab-sess">
      <span>同一提纲 · 两个模型</span>
      <select
        value={val}
        onChange={(e) => {
          const [a, b] = e.target.value.split("|");
          onPick(a || null, b || null);
        }}
      >
        <option value="">不用（手选两份剧本）</option>
        {cur.a && cur.b && !pairs.some(([, p]) => p.a.id === cur.a && p.b.id === cur.b) && <option value={val}>当前链接里的两份草稿</option>}
        {pairs.map(([g, p]) => (
          <option key={g} value={`${p.a.id}|${p.b.id}`}>
            {p.a.title || p.a.id} ⇄ {p.b.title || p.b.id}
          </option>
        ))}
      </select>
    </label>
  );
}

export function ScriptABPage() {
  const { me } = useMe();
  const sessQ = useSessParams();
  const fromSess = !!(sessQ.a && sessQ.b);
  const init = useMemo(loadPref, []);
  const [sources, setSources] = useState<{ path: string; name: string }[] | null>(null);
  const [srcErr, setSrcErr] = useState<string | null>(null);
  const [a, setA] = useState(fromSess ? sessDraft(sessQ.a!) : init.a);
  const [b, setB] = useState(fromSess ? sessDraft(sessQ.b!) : init.b);
  const [ep, setEp] = useState(init.ep);
  const [sess, setSess] = useState<{ a: SessInfo | null; b: SessInfo | null } | null>(null);
  const [tick, setTick] = useState(0);
  const [data, setData] = useState<{ a: Side; b: Side } | null>(null);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [play, setPlay] = useState<K | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  // 登录的项目方直接点；没登录（或后台没有登录功能）时保留旧版的“我是项目方”勾选，换 A/B/集即取消
  const isOwner = me?.role === "owner";
  const [ownerTick, setOwnerTick] = useState(false);
  const canPick = isOwner || ownerTick;
  const reqId = useRef(0);

  // 会话参数变了（选了另一对 / 清掉）→ A/B 跟着换
  useEffect(() => {
    if (sessQ.a && sessQ.b) {
      setA(sessDraft(sessQ.a));
      setB(sessDraft(sessQ.b));
      setSess(null);
    }
  }, [sessQ.a, sessQ.b]);

  // 会话模式：读两个会话；草稿出现前每 15 秒再查一次
  useEffect(() => {
    if (!fromSess) return;
    let alive = true;
    const get = (id: string) => getJ<SessInfo>(`/api/script-chat/sessions/${encodeURIComponent(id)}`).catch(() => null);
    void Promise.all([get(sessQ.a!), get(sessQ.b!)]).then(([sa, sb]) => {
      if (!alive) return;
      setSess((old) => {
        if (!old) {
          const first = (x: SessInfo | null) => {
            const ks = epNums(x);
            return ks.length ? Math.min(...ks) : (x?.episode_range?.[0] ?? null);
          };
          const n = first(sa) ?? first(sb);
          if (n) setEp(n);
        }
        return { a: sa, b: sb };
      });
      if (sa?.validation?.draft) setA(sa.validation.draft);
      if (sb?.validation?.draft) setB(sb.validation.draft);
    });
    return () => {
      alive = false;
    };
  }, [fromSess, sessQ.a, sessQ.b, tick]);
  const sessWaiting = fromSess && (!epNums(sess?.a ?? null).length || !epNums(sess?.b ?? null).length);
  useEffect(() => {
    if (!sessWaiting) return;
    const t = setInterval(() => setTick((x) => x + 1), 15000);
    return () => clearInterval(t);
  }, [sessWaiting]);

  const loadSources = useCallback(() => {
    setSrcErr(null);
    getJ<{ path: string; name: string }[]>("/api/script-ab/sources").then(
      (list) => {
        setSources(list);
        // 第一次打开没选过时默认前两份；之后记住上次选择
        if (list.length >= 2 && !fromSess) {
          setA((x) => x || list[0].path);
          setB((x) => x || list[1].path);
        }
      },
      (e) => setSrcErr((e as Error).message),
    );
  }, [fromSess]);
  useEffect(loadSources, [loadSources]);

  useEffect(() => {
    if (fromSess) return; // 会话对比是一次性的，不覆盖上次手选的 A/B
    try {
      localStorage.setItem(PREF, JSON.stringify({ a, b, ep }));
    } catch {
      /* 隐私模式 */
    }
  }, [a, b, ep, fromSess]);

  const load = useCallback(async () => {
    if (!a || !b) return;
    const my = ++reqId.current; // 只采用最新一次请求的结果（旧集迟到的响应丢弃）
    setOwnerTick(false);
    setBusy(true);
    setErr(null);
    try {
      const q = new URLSearchParams({ a, b, ep: String(ep) });
      const d = await getJ<{ a: Side; b: Side }>(`/api/script-ab/episode?${q}`);
      if (my !== reqId.current) return;
      setData(d);
      const c = await getJ<Choice[]>(`/api/script-ab/choices?ep=${ep}`);
      if (my === reqId.current) setChoices(c);
    } catch (e) {
      if (my === reqId.current) setErr((e as Error).message);
    } finally {
      if (my === reqId.current) setBusy(false);
    }
  }, [a, b, ep]);
  useEffect(() => {
    if (sessWaiting) return;
    void load();
  }, [load, sessWaiting, tick]);

  const pick = async (p: K, shot: string | null) => {
    if (!canPick) return setErr("登录项目方账户（或勾选「我是项目方」）后才能记录选择");
    try {
      await getJ("/api/script-ab/choice", { ep, shot, pick: p, a, b, by: "owner" });
      setChoices(await getJ<Choice[]>(`/api/script-ab/choices?ep=${ep}`));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const latest = (shot: string | null) => [...choices].reverse().find((c) => c.shot === shot && c.a === a && c.b === b)?.pick;

  const opts = useMemo(() => {
    const list = sources ?? [];
    const extra = [a, b].filter((p) => p && !list.some((x) => x.path === p)).map((p) => ({ path: p, name: p.split("/").slice(-2).join("/") }));
    return [...extra, ...list];
  }, [sources, a, b]);

  const rows = useMemo(() => {
    const sa = data?.a.episode?.shots ?? [];
    const sb = data?.b.episode?.shots ?? [];
    return Array.from({ length: Math.max(sa.length, sb.length) }, (_, i) => ({ a: sa[i] as ShotV | undefined, b: sb[i] as ShotV | undefined }));
  }, [data]);
  const allEps = useMemo(() => [...new Set([...(data?.a.episodes ?? []), ...(data?.b.episodes ?? [])])].sort((x, y) => x - y), [data]);
  const picked = useMemo(() => {
    let A = 0;
    let B = 0;
    for (const r of rows) {
      const id = r.a?.id ?? r.b?.id;
      const g = id ? latest(id) : undefined;
      if (g === "A") A++;
      if (g === "B") B++;
    }
    return { A, B };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, choices, a, b]);

  const pickSel = (k: K, v: string, set: (x: string) => void) => (
    <label className="v3p-f sab-src">
      <span>
        <b className={`sab-k sab-k-${k.toLowerCase()}`}>{k}</b> 剧本
      </span>
      <select value={v} onChange={(e) => (fromSess && setSessParams(null, null), set(e.target.value))} title={v}>
        <option value="">选一份剧本…</option>
        {opts.map((s) => (
          <option key={s.path} value={s.path}>
            {s.name}（{s.path}）
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="v3p-page sab-page">
      <header className="v3p-head">
        <h1>剧本 A/B 对比</h1>
        <span className="v3p-muted">两份剧本并排看同一集：原文、首尾帧、视频；每一镜选你更喜欢的那版（只记录你的选择，系统不打分）</span>
      </header>

      <div className="v3p-card sab-bar">
        <div className="v3p-row">
          {pickSel("A", a, setA)}
          {pickSel("B", b, setB)}
          <label className="v3p-f narrow">
            <span>第几集</span>
            {allEps.length ? (
              <select value={ep} onChange={(e) => setEp(Number(e.target.value))}>
                {!allEps.includes(ep) && <option value={ep}>第 {ep} 集</option>}
                {allEps.map((n) => (
                  <option key={n} value={n}>
                    第 {n} 集
                  </option>
                ))}
              </select>
            ) : (
              <input type="number" min={1} max={60} value={ep} onChange={(e) => setEp(Math.max(1, Number(e.target.value) || 1))} />
            )}
          </label>
          <SessionPairs cur={sessQ} onPick={setSessParams} />
        </div>
        <div className="v3p-actions">
          <Button size="sm" disabled={!data || allEps.indexOf(ep) <= 0} why="已经是第一集" onClick={() => setEp(allEps[allEps.indexOf(ep) - 1])}>
            ‹ 上一集
          </Button>
          <Button size="sm" disabled={!data || allEps.indexOf(ep) < 0 || allEps.indexOf(ep) >= allEps.length - 1} why="已经是最后一集" onClick={() => setEp(allEps[allEps.indexOf(ep) + 1])}>
            下一集 ›
          </Button>
          <Button size="sm" variant={play ? "primary" : "secondary"} disabled={!data} why="先选两份剧本" onClick={() => setPlay(play ? null : "A")}>
            {play ? "停止连播" : "▶ 整集连播对比"}
          </Button>
          <Button size="sm" variant="ghost" disabled={!a || !b || busy} why={busy ? "正在读" : "先选两份剧本"} onClick={() => void load()}>
            刷新
          </Button>
          <span className="grow" />
          {data && rows.length > 0 && (
            <span className="v3p-muted v3p-small">
              本集已选：A {picked.A} 镜 · B {picked.B} 镜 · 未选 {rows.length - picked.A - picked.B} 镜
            </span>
          )}
          {isOwner ? (
            <Tag tone="ok" dot pill title="你已登录，点“选 A / 选 B”直接记在你名下">
              {me?.name} · 可以记录选择
            </Tag>
          ) : (
            <label className="v3p-check" title="没登录项目方账户时，勾选后才能记录（换剧本 / 换集会自动取消）">
              <input type="checkbox" checked={ownerTick} onChange={(e) => setOwnerTick(e.target.checked)} /> 我是项目方（记录选 A / B）
            </label>
          )}
          {busy && <Tag tone="busy" dot pill>正在读…</Tag>}
        </div>
      </div>

      {fromSess && (
        <div className="sab-banner">
          同一提纲两个模型：<b>A</b> = {sess?.a?.title ?? sessQ.a}，<b>B</b> = {sess?.b?.title ?? sessQ.b}
          {sessWaiting ? " · 还在写，草稿出来后自动显示（每 15 秒查一次）" : ""}
          <span className="grow" />
          <Button size="xs" variant="ghost" onClick={() => setSessParams(null, null)}>
            改回手选
          </Button>
        </div>
      )}
      {srcErr && <LoadError what="剧本列表" err={srcErr} retry={loadSources} hint="确认后台服务在运行后点重试" />}
      {err && !sessWaiting && (
        <div className="sab-err" role="alert">
          {err}
          <Button size="xs" variant="ghost" onClick={() => setErr(null)}>
            知道了
          </Button>
        </div>
      )}

      {!a || !b ? (
        <Empty
          icon="⇄"
          title="选两份剧本并排对比同一集"
          sub={
            <>
              在上方 A / B 里各选一份（例如逐镜返修版和剧本创作对话版），每一镜下面点「选 A / 选 B」记录你的选择。
              {sources && sources.length < 2 && (
                <>
                  <br />
                  现在只有 {sources.length} 份剧本可选：先在「剧本导入」存一份草稿。
                </>
              )}
            </>
          }
          action={
            sources && sources.length < 2 ? (
              <a className="v3p-link" href="#/script-create?tab=import">
                去剧本导入 →
              </a>
            ) : undefined
          }
        />
      ) : !data ? (
        busy || sessWaiting ? (
          <div className="sab-skel">
            <Skel h={96} r="var(--r-l)" />
            <Skel h={320} r="var(--r-l)" />
          </div>
        ) : null
      ) : (
        <>
          <div className="sab-pair sab-ephead">
            {(["A", "B"] as const).map((k) => {
              const side = k === "A" ? data.a : data.b;
              const on = latest(null) === k;
              return (
                <section key={k} className={`sab-col${on ? " picked" : ""}`}>
                  <div className="sab-col-head">
                    <b className={`sab-k sab-k-${k.toLowerCase()}`}>{k}</b>
                    <b className="sab-name" title={side.path}>
                      {side.name}
                    </b>
                    <span className="grow" />
                    <a className="ds-btn sm ghost" href={`/api/script-inbox/download?path=${encodeURIComponent(side.path)}`} download>
                      下载 .md
                    </a>
                  </div>
                  <div className="v3p-muted">
                    ep{pad(ep)}《{side.episode?.title ?? "这一版没有这一集"}》{side.episode ? ` · ${side.episode.shots.length} 镜` : ""}
                  </div>
                  {side.episode?.synopsis && <div>{side.episode.synopsis}</div>}
                  {side.episode?.music_bgm && <div className="v3p-muted">本集配乐：{side.episode.music_bgm}</div>}
                  <div className="v3p-actions">
                    <Button variant={on ? "primary" : "secondary"} disabled={!canPick || !side.episode} why={!side.episode ? "这一版没有这一集" : "登录项目方账户或勾选「我是项目方」"} onClick={() => pick(k, null)} aria-pressed={on}>
                      {on ? `本集已选 ${k}` : `本集选 ${k}`}
                    </Button>
                  </div>
                </section>
              );
            })}
          </div>

          {play && <Reel rows={rows} side={play} onSide={setPlay} onClose={() => setPlay(null)} />}

          {rows.length === 0 && <Empty title="两版这一集都没有镜头" sub="换一集，或换一份剧本" />}
          {rows.map((r, i) => {
            const id = r.a?.id ?? r.b?.id ?? `S${i + 1}`;
            const got = latest(id);
            const diff = !!r.a && !!r.b && r.a.duration !== r.b.duration;
            return (
              <section key={id} className="sab-shot" id={`sab-${id}`}>
                <header className="sab-shot-head">
                  <b className="mono">{id}</b>
                  <Dur k="A" s={r.a} diff={diff} />
                  <Dur k="B" s={r.b} diff={diff} />
                  {[r.a?.timing.hint, r.b?.timing.hint].filter(Boolean).map((h, j) => (
                    <span key={j} className="bad v3p-small">
                      {h}
                    </span>
                  ))}
                  <span className="grow" />
                  <span className="sab-seg" role="group" aria-label={`${id} 选哪一版`}>
                    {(["A", "B"] as const).map((k) => (
                      <Button
                        key={k}
                        size="sm"
                        variant={got === k ? "primary" : "secondary"}
                        disabled={!canPick || !(k === "A" ? r.a : r.b)}
                        why={!(k === "A" ? r.a : r.b) ? `${k} 版没有这一镜` : "登录项目方账户或勾选「我是项目方」"}
                        onClick={() => pick(k, id)}
                        aria-pressed={got === k}
                      >
                        {got === k ? `已选 ${k}` : `选 ${k}`}
                      </Button>
                    ))}
                  </span>
                </header>
                <div className="sab-pair">
                  {(["A", "B"] as const).map((k) => {
                    const s = k === "A" ? r.a : r.b;
                    return (
                      <div key={k} className={`sab-col${got === k ? " picked" : ""}`}>
                        {s ? (
                          <>
                            <Media r={s.renders} label={`${k} ${id}`} onZoom={setZoom} />
                            <ShotText s={s} />
                          </>
                        ) : (
                          <div className="sab-none">这一版没有这一镜</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </>
      )}
      {zoom && <Lightbox src={zoom} onClose={() => setZoom(null)} />}
    </div>
  );
}

export default ScriptABPage;
