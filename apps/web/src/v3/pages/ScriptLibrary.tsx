// 剧本库（#/script-create，默认打开）：剧集卡片（封面 · 季 · 集数 · 状态 · 总时长）、历史剧本（只读）、写作流水线；点进一部剧是集列表
// （梗概 · 场景 · 亲密 · 版本 · 核查 · 盲评 · 版本时间线）。只读聚合：数据来自 /api/script-library。
// 动作：打开分镜 / 复制为新剧模板（预填提纲）。导出：现有接口没有，不放按钮。
import { useEffect, useState } from "react";
import { thumb } from "../../thumb";
import "./script_library.css";

type Scene = { scene_id: string; name: string; time: string | null; place_kind: string | null; privacy: string | null; scene_type?: string | null; intimate: boolean; beats: number; est_s: number; characters: string[] };
type Version = { label: string; kind: string; at: string; reason: string };
type Ep = {
  ep: number; title: string; logline: string; intimate: boolean; duration_s: number | null; scenes: Scene[]; state: string; state_text: string; version: string | null;
  versions: Version[]; cover: string | null; next_action: string | null;
  factcheck: { ok: boolean | null; deviations: number; rounds: number; items: string[] } | null;
  judge: { mean: number | null; stable: boolean | null; verdict: string | null } | null;
};
type Card = {
  run: string; title: string; season: number; episodes: number; imported: number; state: string; state_text: string; primary: boolean; paused_note: string | null;
  duration_s: number; cover: string | null; intimate_eps: number; ep_progress: number[]; ep_video_have: number[];
};
type Lib = { current: Card[]; history: Card[]; pipeline: { run: string; ep: number; state: string; text: string; note: string | null; stuck: string | null }[] };
type Detail = { card: Card; episodes: Ep[] };

const SEASON = ["", "第一季", "第二季", "第三季", "第四季"];
const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
const pad2 = (n: number) => String(n).padStart(2, "0");
const libRun = () => new URLSearchParams(location.hash.split("?")[1] ?? "").get("lib");
const goLib = (run: string | null) => {
  location.hash = run ? `#/script-create?lib=${encodeURIComponent(run)}` : "#/script-create";
};

function Pic({ src, w }: { src: string | null; w: number }) {
  return src ? <img src={thumb(src, w) ?? src} alt="" loading="lazy" decoding="async" /> : <span className="sl-none">未曝光</span>;
}

function Poster({ c, onOpen, ro }: { c: Card; onOpen: () => void; ro?: boolean }) {
  return (
    <button className={`sl-card${ro ? " ro" : ""}`} onClick={onOpen}>
      <span className="sl-pic">
        <Pic src={c.cover} w={360} />
      </span>
      <span className="sl-meta">
        <small>{SEASON[c.season] ?? `第 ${c.season} 季`}</small>
        <b>{c.title}</b>
        <span className="sl-sub">
          {c.episodes} 集 · {mmss(c.duration_s)}
        </span>
        <span className="sl-state">{c.state_text}</span>
        <span className="sl-cells" aria-hidden>
          {Array.from({ length: c.episodes }, (_, i) => {
            const f = c.ep_progress?.[i] ?? 0;
            return <i key={i} className={f >= 1 ? "full" : ""} style={{ ["--f" as string]: `${Math.round(f * 100)}%`, ["--h" as string]: `${Math.round(Math.max(f, c.ep_video_have?.[i] ?? 0) * 100)}%` }} />;
          })}
        </span>
      </span>
    </button>
  );
}

export default function ScriptLibrary() {
  const [run, setRun] = useState<string | null>(libRun);
  useEffect(() => {
    const on = () => setRun(libRun());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return run ? <SeriesView run={run} /> : <Shelf />;
}

function Shelf() {
  const [lib, setLib] = useState<Lib | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    let alive = true;
    const load = () =>
      fetch("/api/script-library")
        .then((r) => (r.ok ? (r.json() as Promise<Lib>) : Promise.reject()))
        .then((d) => alive && (setLib(d), setErr(false)))
        .catch(() => alive && setErr(true));
    void load();
    const t = setInterval(load, 20000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  if (err && !lib) return <div className="sl-page"><p className="sl-dim">剧本库暂时读不到，稍后自动重试。</p></div>;
  if (!lib) return <div className="sl-page"><p className="sl-dim">读取中…</p></div>;
  return (
    <div className="sl-page">
      <section>
        <h2 className="sl-h">在做的剧</h2>
        <div className="sl-grid">
          {lib.current.map((c) => (
            <Poster key={c.run} c={c} onOpen={() => goLib(c.run)} />
          ))}
          <div className="sl-addcol">
            <a className="sl-card sl-add" href="#/script-create?new=1">
              <span className="sl-plus">＋</span>
              <b>新建剧本</b>
            </a>
            <a className="sl-card sl-add" href="#/script-create?tab=import">
              <span className="sl-plus">↧</span>
              <b>剧本导入</b>
            </a>
          </div>
        </div>
      </section>
      {lib.pipeline.length > 0 && (
        <section>
          <h2 className="sl-h">写作流水线</h2>
          <ul className="sl-pipe">
            {lib.pipeline.map((p) => (
              <li key={`${p.run}-${p.ep}`}>
                <a href={`#/script-create?lib=${encodeURIComponent(p.run)}`}>
                  <span className="sl-pn">{lib.current.find((c) => c.run === p.run)?.season === 2 ? "S2" : "S1"} · EP{pad2(p.ep)}</span>
                  <span className={`sl-dot ${p.stuck ? "stuck" : ""}`} />
                  <span className="sl-pt">{p.stuck ? "待处理" : p.text}</span>
                  <span className="sl-pd">{p.stuck ? "需要重写，已交写作方" : p.state === "checking" ? "事实核查中" : ""}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
      <section>
        <h2 className="sl-h">历史剧本 <small>已做完 · 只读</small></h2>
        {lib.history.length ? (
          <div className="sl-grid">
            {lib.history.map((c) => (
              <Poster key={c.run} c={c} ro onOpen={() => goLib(c.run)} />
            ))}
          </div>
        ) : (
          <p className="sl-dim">成片做完的剧会收到这里。</p>
        )}
      </section>
    </div>
  );
}

function SeriesView({ run }: { run: string }) {
  const [d, setD] = useState<Detail | null>(null);
  const [err, setErr] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => {
    let alive = true;
    setD(null);
    setErr(false);
    fetch(`/api/script-library/${encodeURIComponent(run)}`)
      .then((r) => (r.ok ? (r.json() as Promise<Detail>) : Promise.reject()))
      .then((x) => alive && setD(x))
      .catch(() => alive && setErr(true));
    return () => {
      alive = false;
    };
  }, [run]);
  if (err) return <div className="sl-page"><button className="sl-back" onClick={() => goLib(null)}>← 剧本库</button><p className="sl-dim">这部剧读不到。</p></div>;
  if (!d) return <div className="sl-page"><p className="sl-dim">读取中…</p></div>;
  const c = d.card;
  const ro = c.state === "done";
  const sbHref = (n: number) => (c.primary ? `#ep${pad2(n)}` : `#/script-create?run=${encodeURIComponent(run)}&ep=${n}`);
  return (
    <div className="sl-page">
      <button className="sl-back" onClick={() => goLib(null)}>← 剧本库</button>
      <header className="sl-head">
        <span className="sl-pic big"><Pic src={c.cover} w={480} /></span>
        <div className="sl-ht">
          <small>{SEASON[c.season] ?? `第 ${c.season} 季`}{ro ? " · 历史剧本（只读）" : ""}</small>
          <h1>{c.title}</h1>
          <div className="sl-sub">{c.episodes} 集 · {mmss(c.duration_s)} · {c.state_text}</div>
          <div className="sl-acts">
            {c.primary && <a className="sl-btn" href="#ep01">打开分镜</a>}
            <a className="sl-btn ghost" href={`#/script-create?new=1&tpl=${encodeURIComponent(run)}`}>复制为新剧模板</a>
          </div>
        </div>
      </header>
      <ol className="sl-eps">
        {d.episodes.map((e) => (
          <li key={e.ep} className={open === e.ep ? "open" : ""}>
            <div className={`sl-ep${e.cover ? "" : " nopic"}`} onClick={() => setOpen(open === e.ep ? null : e.ep)}>
              <span className="sl-epn">EP{pad2(e.ep)}</span>
              {e.cover && <span className="sl-pic sm"><Pic src={e.cover} w={120} /></span>}
              <div className="sl-eb">
                <div className="sl-et"><b>{e.title || "（未写大纲）"}</b>{e.intimate && <span className="sl-int" title="亲密戏集">亲密</span>}<span className="sl-es">{e.state_text}{e.version ? ` · ${e.version}` : ""}</span></div>
                {e.logline && <p className="sl-log">{e.logline}</p>}
                <div className="sl-sc">
                  {e.scenes.map((s) => (
                    <span key={s.scene_id}>{s.name}{s.privacy ? ` · ${s.place_kind} ${s.privacy}` : ""}{s.scene_type ? ` · ${s.scene_type}` : ""}{s.intimate ? " · 亲密戏" : ""}</span>
                  ))}
                </div>
              </div>
              <div className="sl-ev">
                {e.factcheck && <span title={e.factcheck.items.join("\n")}>核查 {e.factcheck.ok ? "通过" : `${e.factcheck.deviations} 处偏差`}</span>}
                {e.judge && e.judge.mean != null && <span>盲评 {e.judge.mean.toFixed(1)}{e.judge.stable ? " · 稳" : ""}</span>}
                {e.duration_s ? <span>{mmss(e.duration_s)}</span> : null}
              </div>
            </div>
            {open === e.ep && (
              <div className="sl-more">
                <div className="sl-tl">
                  {e.versions.length ? (
                    e.versions.map((v) => (
                      <div key={v.label + v.at} className="sl-tv">
                        <i />
                        <b>{v.label}</b>
                        <span className="sl-ta">{v.at.slice(5, 16).replace("T", " ")}</span>
                        <span className="sl-tr">{v.reason || v.kind}</span>
                      </div>
                    ))
                  ) : (
                    <p className="sl-dim">这一集没有留下改动记录。</p>
                  )}
                </div>
                <div className="sl-ma">
                  <a className="sl-btn sm" href={sbHref(e.ep)}>{c.primary ? "打开分镜" : "看分镜稿"}</a>
                  {e.next_action && <span className="sl-dim">{e.next_action}</span>}
                </div>
              </div>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
