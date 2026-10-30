import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "../ab.css";

/** 剧本 A/B 对比（项目方：“两个都要，看看那个写出画面更漂亮，更有短剧感觉”）。
 *  同集同镜并排显示两版原文与两版各自的首帧 / 尾帧 / 视频；只记录项目方的选择，系统不打分。 */

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

async function getJ<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const t = await r.text();
  if (!r.ok) {
    let m = t;
    try {
      m = JSON.parse(t).detail ?? t;
    } catch {
      /* 原文 */
    }
    throw new Error(m);
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

/** 时长：剧本秒数 + H3 实际帧数档位；没写 / 超范围醒目提示 */
function Dur({ k, s, diff }: { k: "A" | "B"; s?: ShotV; diff: boolean }) {
  if (!s) return <span className="ab-dur bad">{k} 无此镜</span>;
  const t = s.timing;
  const cls = !t.ok || t.source !== "script" ? " bad" : diff ? " diff" : "";
  return (
    <span className={`ab-dur${cls}`} title={`${t.source === "script" ? "剧本写明" : "剧本没写，默认"} ${t.seconds} 秒 → H3 ${t.frames} 帧（${t.h3_seconds} 秒）${t.hint ? `\n${t.hint}` : ""}`}>
      {k} 时长 {t.seconds} 秒{t.source !== "script" ? "（默认）" : ""} · {t.frames} 帧
    </span>
  );
}

function Media({ r, label }: { r: Renders; label: string }) {
  if (!r.first && !r.last && !r.video)
    return <div className="ab-none">首帧 / 尾帧 / 视频：未出（两版剧本定稿后一起渲染）</div>;
  return (
    <div className="ab-media">
      {(["first", "last"] as const).map((k) => (
        <figure key={k}>
          {r[k] ? <img src={r[k]!} alt={`${label} ${k === "first" ? "首帧" : "尾帧"}`} loading="lazy" /> : <div className="ab-empty">{k === "first" ? "首帧" : "尾帧"}未出</div>}
          <figcaption>{k === "first" ? "首帧" : "尾帧"}</figcaption>
        </figure>
      ))}
      <figure>
        {r.video ? <video src={r.video} controls muted playsInline preload="metadata" /> : <div className="ab-empty">视频未出</div>}
        <figcaption>视频</figcaption>
      </figure>
    </div>
  );
}

function ShotText({ s }: { s: ShotV }) {
  return (
    <div className="ab-text">
      <div className="ab-k">首帧（img）</div>
      <div>{s.img || "—"}</div>
      <div className="ab-k">运动（motion）</div>
      <div>{s.motion || "—"}</div>
      <div className="ab-k">尾帧状态</div>
      <div>{s.last_state || "—"}</div>
      {s.dialogue.length > 0 && (
        <>
          <div className="ab-k">对白</div>
          <div>
            {s.dialogue.map((d, i) => (
              <div key={i}>
                {d.speaker ? `（${d.speaker}）` : ""}“{d.text}”
              </div>
            ))}
          </div>
        </>
      )}
      {s.voiceover && (
        <>
          <div className="ab-k">独白</div>
          <div>{s.voiceover}</div>
        </>
      )}
      <div className="ab-k">声音 / 配乐</div>
      <div>
        {s.sound_h3 || s.sound || "—"}
        {s.music_cue && <div className="ab-sub">配乐：{s.music_cue}</div>}
      </div>
      <details>
        <summary>H3 提示词</summary>
        <pre>{s.h3_prompt || "（这一版没有 H3提示词）"}</pre>
      </details>
    </div>
  );
}

/** fredw-92/W4c：?view=ab&sa=<会话id>&sb=<会话id>（剧本创作页“同一提纲交给两个模型”）→ 直接对比这两个会话的草稿 */
const AB_Q = new URLSearchParams(location.search);
const SESS = { a: AB_Q.get("sa"), b: AB_Q.get("sb") };
const sessDraft = (id: string) => `data/script_chat/${id}/script.md`;
type SessInfo = { id: string; title: string; episodes: Record<string, string>; episode_range?: number[] | null; validation?: { draft?: string } | null };

export function ScriptAB() {
  const init = loadPref();
  const fromSess = !!(SESS.a && SESS.b);
  const [sources, setSources] = useState<{ path: string; name: string }[]>([]);
  const [a, setA] = useState(fromSess ? sessDraft(SESS.a!) : init.a);
  const [b, setB] = useState(fromSess ? sessDraft(SESS.b!) : init.b);
  const [ep, setEp] = useState(init.ep);
  const [sess, setSess] = useState<{ a: SessInfo | null; b: SessInfo | null } | null>(null);
  const [tick, setTick] = useState(0);

  // 会话模式：读两个会话；草稿（script.md）出现前每 15 秒再查一次
  useEffect(() => {
    if (!fromSess) return;
    let alive = true;
    const get = (id: string) => getJ<SessInfo>(`/api/script-chat/sessions/${encodeURIComponent(id)}`).catch(() => null);
    void Promise.all([get(SESS.a!), get(SESS.b!)]).then(([sa, sb]) => {
      if (!alive) return;
      setSess((old) => {
        if (!old) {
          const first = (x: SessInfo | null) => {
            const ks = Object.keys(x?.episodes ?? {}).map(Number);
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
  }, [fromSess, tick]);
  const sessWaiting = fromSess && (!Object.keys(sess?.a?.episodes ?? {}).length || !Object.keys(sess?.b?.episodes ?? {}).length);
  useEffect(() => {
    if (!sessWaiting) return;
    const t = setInterval(() => setTick((x) => x + 1), 15000);
    return () => clearInterval(t);
  }, [sessWaiting]);
  const [data, setData] = useState<{ a: Side; b: Side } | null>(null);
  const [choices, setChoices] = useState<Choice[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [play, setPlay] = useState<"A" | "B" | null>(null);
  // 封板修复：选择以项目方名义记录，须勾选；换 A/B/集即取消勾选
  const [owner, setOwner] = useState(false);
  const reqId = useRef(0);

  useEffect(() => {
    getJ<{ path: string; name: string }[]>("/api/script-ab/sources").then((list) => {
      setSources(list);
      // fredw-b3：第一次打开没选过时默认前两份，少两次下拉；之后记住上次选择
      if (list.length >= 2 && !fromSess) {
        setA((x) => x || list[0].path);
        setB((x) => x || list[1].path);
      }
    }, (e) => setErr(`读不到剧本列表：${(e as Error).message}。确认 API（:8800）在运行后刷新页面。`));
  }, []);
  useEffect(() => {
    if (fromSess) return; // 会话对比是一次性的，不覆盖上次手选的 A/B
    try {
      localStorage.setItem(PREF, JSON.stringify({ a, b, ep }));
    } catch {
      /* 隐私模式 */
    }
  }, [a, b, ep]);

  const load = useCallback(async () => {
    if (!a || !b) return;
    // 封板修复：只采用最新一次请求的结果（旧集迟到的响应丢弃）
    const my = ++reqId.current;
    setOwner(false);
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
  }, [a, b, ep, fromSess]);
  useEffect(() => {
    if (sessWaiting) return;
    void load();
  }, [load, sessWaiting, tick]);

  const pick = async (p: "A" | "B", shot: string | null) => {
    if (!owner) return setErr("先勾选「我是项目方」再记录选择");
    try {
      await getJ("/api/script-ab/choice", { ep, shot, pick: p, a, b, by: "owner" });
      setChoices(await getJ(`/api/script-ab/choices?ep=${ep}`));
    } catch (e) {
      setErr((e as Error).message);
    }
  };
  const latest = (shot: string | null) => [...choices].reverse().find((c) => c.shot === shot && c.a === a && c.b === b)?.pick;

  const opts = useMemo(() => {
    const extra = [a, b].filter((p) => p && !sources.some((x) => x.path === p)).map((p) => ({ path: p, name: p.split("/").slice(-2).join("/") }));
    return [...extra, ...sources];
  }, [sources, a, b]);

  const rows = useMemo(() => {
    const sa = data?.a.episode?.shots ?? [];
    const sb = data?.b.episode?.shots ?? [];
    const n = Math.max(sa.length, sb.length);
    return Array.from({ length: n }, (_, i) => ({ a: sa[i], b: sb[i] }));
  }, [data]);

  return (
    <div className="ab-view">
      <header className="ab-head">
        <h2>剧本 A/B 对比</h2>
        <label className="ab-pick-a">
          <b>A</b>
          <select value={a} onChange={(e) => setA(e.target.value)} title={a}>
            <option value="">选一份剧本…</option>
            {opts.map((s) => (
              <option key={s.path} value={s.path}>
                {s.name}（{s.path}）
              </option>
            ))}
          </select>
        </label>
        <label className="ab-pick-b">
          <b>B</b>
          <select value={b} onChange={(e) => setB(e.target.value)} title={b}>
            <option value="">选一份剧本…</option>
            {opts.map((s) => (
              <option key={s.path} value={s.path}>
                {s.name}（{s.path}）
              </option>
            ))}
          </select>
        </label>
        <label>
          第
          <input type="number" min={1} max={60} value={ep} onChange={(e) => setEp(Math.max(1, Number(e.target.value) || 1))} />
          集
        </label>
        <span className="grow" />
        <button className="btn-mini" onClick={() => setPlay(play ? null : "A")} disabled={!data}>
          {play ? "停止连播" : "整集连播对比"}
        </button>
        <label className="ab-muted">
          <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} /> 我是项目方（记录选 A/B）
        </label>
        {busy && <span className="ab-muted">读取中…</span>}
      </header>
      {fromSess && (
        <div className="banner ok">
          同一提纲两个模型：A = {sess?.a?.title ?? SESS.a}，B = {sess?.b?.title ?? SESS.b}
          {sessWaiting ? " · 还在写，草稿出来后自动显示（每 15 秒查一次）" : ""}{" "}
          <a href={`/#/script-chat/${SESS.a}`}>A 会话</a> · <a href={`/#/script-chat/${SESS.b}`}>B 会话</a>
        </div>
      )}
      {err && !sessWaiting && <div className="banner bad">{err}</div>}
      {!a || !b ? (
        <div className="ab-emptybox">
          <b>选两份剧本并排对比同一集</b>
          <span>在上方 A / B 里各选一份（例如 Qwen 返修版 和 剧本创作对话版），每一镜下面点「选 A / 选 B」记录你的选择。</span>
          {sources.length < 2 && <span className="ab-muted">现在只有 {sources.length} 份剧本可选：先在「剧本 → 输入 / 导入」存一份草稿。</span>}
        </div>
      ) : (
        data && (
          <>
            <div className="ab-ep">
              {(["A", "B"] as const).map((k) => {
                const side = k === "A" ? data.a : data.b;
                return (
                  <div key={k} className={`ab-col${latest(null) === k ? " picked" : ""}`}>
                    <div className="ab-col-head">
                      <b>{k}</b> {side.name}
                      <span className="ab-muted"> · ep{String(ep).padStart(2, "0")}《{side.episode?.title ?? "这一版没有这一集"}》</span>{" "}
                      <a className="btn-mini" href={`/api/script-inbox/download?path=${encodeURIComponent(side.path)}`} download>
                        下载 .md
                      </a>
                    </div>
                    {side.episode && <div className="ab-sub">{side.episode.synopsis}</div>}
                    {side.episode?.music_bgm && <div className="ab-sub">本集配乐：{side.episode.music_bgm}</div>}
                    <button className="btn" disabled={!owner} onClick={() => pick(k, null)}>
                      本集选 {k}
                    </button>
                  </div>
                );
              })}
            </div>
            {play && <Reel rows={rows} side={play} onSide={setPlay} />}
            {rows.map((r, i) => {
              const id = r.a?.id ?? r.b?.id ?? `S${i + 1}`;
              const got = latest(id);
              return (
                <section key={id} className="ab-shot">
                  <div className="ab-shot-head">
                    <b>{id}</b>
                    <Dur k="A" s={r.a} diff={!!r.a && !!r.b && r.a.duration !== r.b.duration} />
                    <Dur k="B" s={r.b} diff={!!r.a && !!r.b && r.a.duration !== r.b.duration} />
                    {[r.a?.timing.hint, r.b?.timing.hint].filter(Boolean).map((h, j) => (
                      <span key={j} className="ab-err">{h}</span>
                    ))}
                    <span className="grow" />
                    <span className="ab-seg" role="group" aria-label={`${id} 选哪一版`}>
                      {(["A", "B"] as const).map((k) => (
                        <button key={k} className={got === k ? "on" : ""} disabled={!owner || !(k === "A" ? r.a : r.b)} onClick={() => pick(k, id)} aria-pressed={got === k}>
                          {got === k ? `已选 ${k}` : `选 ${k}`}
                        </button>
                      ))}
                    </span>
                  </div>
                  <div className="ab-pair">
                    {(["A", "B"] as const).map((k) => {
                      const s = k === "A" ? r.a : r.b;
                      return (
                        <div key={k} className={`ab-col${got === k ? " picked" : ""}`}>
                          {s ? (
                            <>
                              <Media r={s.renders} label={k} />
                              <ShotText s={s} />
                            </>
                          ) : (
                            <div className="ab-empty">这一版没有这一镜</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </>
        )
      )}
    </div>
  );
}

/** 整集连播：按镜顺序播放一版的视频（没有视频的镜跳过）；可随时切到另一版 */
function Reel({ rows, side, onSide }: { rows: { a?: ShotV; b?: ShotV }[]; side: "A" | "B"; onSide: (s: "A" | "B") => void }) {
  const list = rows.map((r) => (side === "A" ? r.a : r.b)).filter((s): s is ShotV => !!s?.renders.video);
  const [i, setI] = useState(0);
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => setI(0), [side]);
  const cur = list[i];
  return (
    <div className="ab-reel">
      <div className="ab-reel-head">
        连播 {side} 版 · {list.length ? `${i + 1}/${list.length} ${cur?.id}` : "这一版还没有视频"}
        <button className="btn-mini" onClick={() => onSide(side === "A" ? "B" : "A")}>
          切到 {side === "A" ? "B" : "A"} 版
        </button>
      </div>
      {cur && <video ref={ref} key={cur.id + side} src={cur.renders.video!} autoPlay controls playsInline onEnded={() => setI((x) => (x + 1 < list.length ? x + 1 : x))} />}
    </div>
  );
}

export default ScriptAB;
