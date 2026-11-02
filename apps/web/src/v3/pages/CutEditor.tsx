// CUTEDIT P1（设计稿 data/review_pages/cutedit/index.html；总调度 11-02 批准：自做轻量时间线，交互参考 OpenCut classic / OpenReel，均 MIT）。
// 剪辑工程 data/renders/epNN/_final/cut_project.json（后端 services/api/ns_api/cut_project.py）：浏览器只改工程，导出在服务端用 assemble.py 合成。
// P1 最小闭环：裁头尾（拖把手 / 输入秒数）→ 集级配乐换曲、起点、音量、淡入淡出（对白处自动压低，L-118）→ 导出成片（先收下、原位进度）→ 成为定稿版本。
// 字幕编辑、拖动换顺序排在后面（字幕轨现在只显示）。不烧字幕（L-002）；界面只有正向动作（L-123）。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useStudio } from "../../store";
import "./cutedit.css";

interface Seg {
  shot: string;
  index: number;
  kind: "video" | "still" | "black";
  file: string | null;
  url: string | null;
  origin?: string | null;
  source_duration_s?: number | null;
  still_s?: number | null;
  trim_head_s: number;
  trim_tail_s: number;
  trim_by: "auto" | "owner";
  replaced_from?: string | null;
  trim_adjusted?: boolean;
}
interface Speech {
  kind: "dialogue" | "voiceover" | string;
  shot: number;
  speaker?: string;
  text: string;
  start_s: number;
  end_s: number;
  urls?: (string | null)[];
  source?: string | null;
}
interface Bgm {
  file: string;
  offset_s: number;
  gain_db: number;
  fade_in_s: number;
  fade_out_s: number;
}
interface Job {
  state: "queued" | "picture" | "sound" | "final" | "done" | "failed" | "none";
  stage?: string;
  pct?: number;
  eta_s?: number;
  started_at?: string;
  output?: string | null;
  url?: string | null;
  error?: string | null;
}
interface Proj {
  episode: number;
  rev: number;
  updated_at: string;
  segments: Seg[];
  speech: Speech[];
  bgm: Bgm;
  bgm_url: string | null;
  music_choices: { file: string; url: string | null; name: string; duration_s?: number | null; bpm?: number | null; mine: boolean }[];
  final: { file: string; rev: number; at: string } | null;
  job: Job | null;
  history?: { at: string; what: string; by?: string }[];
}

const MIN_KEEP = 0.2;
const DUCK_DL = -12; // L-118：对白处压 12 dB
const DUCK_VO = -9; // 独白处压 9 dB
const LANE_LABEL = 72;
const fileUrl = (rel?: string | null) => (rel && rel.startsWith("data/") ? `/files/${rel.slice(5)}` : null);
const segLen = (s: Seg) => (s.kind === "video" && s.source_duration_s ? Math.max(MIN_KEEP, s.source_duration_s - s.trim_head_s - s.trim_tail_s) : s.still_s ?? 4);
const fmt = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, "0")}`;
const r3 = (x: number) => Math.round(x * 1000) / 1000;

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let d = "";
    try {
      d = (await r.json())?.detail ?? "";
    } catch {
      /* 非 JSON */
    }
    throw new Error(`${r.status} ${d || r.statusText}`);
  }
  return r.json() as Promise<T>;
}

/** 镜头段起点（按当前草稿裁切） */
function layout(segs: Seg[]) {
  let t = 0;
  return segs.map((s) => {
    const a = t;
    t += segLen(s);
    return { s, start: a, end: t };
  });
}

/** 对白 / 独白跟着裁切挪：画内对白随画面（裁头会把它往前带），独白只跟段起点 */
function shiftSpeech(speech: Speech[], base: Seg[], now: Seg[]) {
  const b = layout(base);
  const n = layout(now);
  return speech.map((x) => {
    const i = now.findIndex((s) => s.index === x.shot);
    if (i < 0) return x;
    let d = n[i].start - b[i].start;
    if (x.kind === "dialogue" && now[i].kind === "video") d -= now[i].trim_head_s - base[i].trim_head_s;
    return { ...x, start_s: x.start_s + d, end_s: x.end_s + d };
  });
}

/** 配乐音量（线性 0..∞）：整体 dB × 淡入淡出 × 对白避让 */
function bgmGain(t: number, total: number, b: Bgm, speech: Speech[]) {
  let g = Math.pow(10, b.gain_db / 20);
  if (b.fade_in_s > 0 && t < b.fade_in_s) g *= Math.max(0, t / b.fade_in_s);
  if (b.fade_out_s > 0 && t > total - b.fade_out_s) g *= Math.max(0, (total - t) / b.fade_out_s);
  let duck = 0;
  for (const x of speech) if (t >= x.start_s - 0.12 && t <= x.end_s + 0.12) duck = Math.min(duck, x.kind === "dialogue" ? DUCK_DL : DUCK_VO);
  return g * Math.pow(10, duck / 20);
}

export default function CutEditor({ ep, onExported }: { ep: number; onExported?: () => void }) {
  const st = useStudio();
  const [proj, setProj] = useState<Proj | null>(null);
  const [segs, setSegs] = useState<Seg[]>([]);
  const [bgm, setBgm] = useState<Bgm | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [save, setSave] = useState<"idle" | "dirty" | "saving" | "saved">("idle");
  const [job, setJob] = useState<Job | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const laneRef = useRef<HTMLDivElement>(null);
  const [laneW, setLaneW] = useState(1000);

  const load = useCallback(() => {
    setErr(null);
    api<Proj>(`/api/episodes/${ep}/cut-project`).then(
      (p) => {
        setProj(p);
        setSegs(p.segments);
        setBgm(p.bgm);
        setJob(p.job);
        setSave("idle");
        setSel((s) => s ?? p.segments.find((x) => x.kind === "video")?.index ?? null);
      },
      (e) => setErr(String((e as Error).message ?? e)),
    );
  }, [ep]);
  useEffect(load, [load]);

  useEffect(() => {
    const el = laneRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setLaneW(el.clientWidth || 1000));
    ro.observe(el);
    return () => ro.disconnect();
  }, [proj]);

  const lay = useMemo(() => layout(segs), [segs]);
  const total = lay.length ? lay[lay.length - 1].end : 0;
  const pps = total ? laneW / total : 20;
  const speech = useMemo(() => (proj ? shiftSpeech(proj.speech, proj.segments, segs) : []), [proj, segs]);

  // ---------- 保存（停手 700 ms 自动存；rev 冲突 → 重新读）
  const saveTimer = useRef<number | null>(null);
  const pending = useRef<{ segs: Seg[]; bgm: Bgm | null } | null>(null);
  const flush = useCallback(async () => {
    if (!proj || !pending.current) return proj;
    const body = { rev: proj.rev, by: "owner", segments: pending.current.segs.filter((s) => s.kind === "video").map((s) => ({ index: s.index, trim_head_s: s.trim_head_s, trim_tail_s: s.trim_tail_s })), bgm: pending.current.bgm };
    pending.current = null;
    setSave("saving");
    try {
      const p = await api<Proj>(`/api/episodes/${ep}/cut-project`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      setProj(p);
      setSave("saved");
      return p;
    } catch (e) {
      const m = String((e as Error).message ?? e);
      st.notify(m.startsWith("409") ? "工程刚被更新（镜头换了新片），已重新读取" : `没存上：${m}`, m.startsWith("409") ? "ok" : "err");
      load();
      return null;
    }
  }, [proj, ep, st, load]);
  const schedule = (nextSegs: Seg[], nextBgm: Bgm | null) => {
    pending.current = { segs: nextSegs, bgm: nextBgm };
    setSave("dirty");
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => void flush(), 700);
  };
  const drag = useRef<{ index: number; side: "l" | "r"; x0: number; h0: number; t0: number } | null>(null);
  const segsRef = useRef<Seg[]>(segs);   // 拖动松手时可能还没重绘：存最新一次计算结果
  segsRef.current = drag.current ? segsRef.current : segs;
  const setTrim = (index: number, head: number, tail: number, commit = true) => {
    const next = segsRef.current.map((s) => {
      if (s.index !== index || s.kind !== "video" || !s.source_duration_s) return s;
      const src = s.source_duration_s;
      const h = Math.min(Math.max(0, head), src - MIN_KEEP);
      const tl = Math.min(Math.max(0, tail), src - h - MIN_KEEP);
      return { ...s, trim_head_s: r3(h), trim_tail_s: r3(tl), trim_by: "owner" as const };
    });
    segsRef.current = next;
    setSegs(next);
    if (commit) schedule(next, bgm);
  };
  const setBgmF = (patch: Partial<Bgm>) => {
    if (!bgm) return;
    const nb = { ...bgm, ...patch };
    setBgm(nb);
    schedule(segs, nb);
  };

  // ---------- 拖把手裁头尾
  const onHandleDown = (e: React.PointerEvent, s: Seg, side: "l" | "r") => {
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = { index: s.index, side, x0: e.clientX, h0: s.trim_head_s, t0: s.trim_tail_s };
    setSel(s.index);
  };
  const onHandleMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dt = (e.clientX - d.x0) / pps;
    if (d.side === "l") setTrim(d.index, d.h0 + dt, d.t0, false);
    else setTrim(d.index, d.h0, d.t0 - dt, false);
  };
  const onHandleUp = () => {
    if (!drag.current) return;
    drag.current = null;
    schedule(segsRef.current, bgm);
  };

  // ---------- 预览播放（逐段播源片、按入出点跳；配乐 Web 音量包络；独白 TTS 按时间点起播）
  const vidRef = useRef<HTMLVideoElement>(null);
  const bgmRef = useRef<HTMLAudioElement>(null);
  const voRefs = useRef<Map<string, HTMLAudioElement>>(new Map());
  const clock = useRef<{ wall: number; t: number } | null>(null);
  const curSeg = lay.find((x) => t >= x.start && t < x.end) ?? lay[lay.length - 1];
  const raf = useRef<number | null>(null);
  const stopAll = () => {
    vidRef.current?.pause();
    bgmRef.current?.pause();
    voRefs.current.forEach((a) => a.pause());
  };
  const seek = (nt: number) => {
    const c = Math.max(0, Math.min(total - 0.01, nt));
    setT(c);
    clock.current = { wall: performance.now(), t: c };
    const x = lay.find((y) => c >= y.start && c < y.end);
    const v = vidRef.current;
    if (x && v && x.s.kind === "video" && x.s.url) {
      if (!v.src.endsWith(x.s.url)) v.src = x.s.url;
      v.currentTime = x.s.trim_head_s + (c - x.start);
    }
    if (bgmRef.current) bgmRef.current.currentTime = (bgm?.offset_s ?? 0) + c;
    voRefs.current.forEach((a) => a.pause());
  };
  useEffect(() => {
    if (!playing) {
      stopAll();
      if (raf.current) cancelAnimationFrame(raf.current);
      return;
    }
    clock.current = { wall: performance.now(), t };
    if (bgmRef.current && bgm) {
      bgmRef.current.currentTime = bgm.offset_s + t;
      void bgmRef.current.play().catch(() => undefined);
    }
    let lastIdx = -1;
    const tick = () => {
      const ck = clock.current!;
      const now = ck.t + (performance.now() - ck.wall) / 1000;
      if (now >= total) {
        setPlaying(false);
        setT(0);
        return;
      }
      const x = lay.find((y) => now >= y.start && now < y.end);
      const v = vidRef.current;
      if (x && v) {
        if (x.s.index !== lastIdx) {
          lastIdx = x.s.index;
          if (x.s.kind === "video" && x.s.url) {
            if (!v.src.endsWith(x.s.url)) v.src = x.s.url;
            v.currentTime = x.s.trim_head_s + (now - x.start);
            void v.play().catch(() => undefined);
          } else v.pause();
        } else if (x.s.kind === "video" && Math.abs(v.currentTime - (x.s.trim_head_s + now - x.start)) > 0.25) {
          v.currentTime = x.s.trim_head_s + (now - x.start);
        }
      }
      if (bgmRef.current && bgm) bgmRef.current.volume = Math.max(0, Math.min(1, bgmGain(now, total, bgm, speech)));
      speech.forEach((sp, i) => {
        const u = sp.kind === "voiceover" ? sp.urls?.[0] : null;
        if (!u) return;
        const key = `${i}`;
        let a = voRefs.current.get(key);
        if (now >= sp.start_s && now < sp.end_s) {
          if (!a) {
            a = new Audio(u);
            voRefs.current.set(key, a);
          }
          if (a.paused) {
            a.currentTime = now - sp.start_s;
            void a.play().catch(() => undefined);
          }
        } else if (a && !a.paused) a.pause();
      });
      setT(now);
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      stopAll();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest?.("input,select,textarea")) return;
      if (e.code === "Space" && document.querySelector(".ce-root")) {
        e.preventDefault();
        setPlaying((p) => !p);
      }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  // ---------- 导出（先收下，原位显示进度）
  const running = !!job && !["done", "failed", "none"].includes(job.state);
  useEffect(() => {
    if (!running) return;
    const iv = window.setInterval(() => {
      api<Job>(`/api/episodes/${ep}/cut-project/export`).then((j) => {
        setJob(j);
        if (j.state === "done") {
          st.notify(`第 ${ep} 集定稿已导出`);
          onExported?.();
          load();
        }
        if (j.state === "failed") st.notify(`导出没成功：${j.error ?? ""}`, "err");
      }, () => undefined);
    }, 2000);
    return () => window.clearInterval(iv);
  }, [running, ep, st, onExported, load]);
  const exportNow = async () => {
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    if (pending.current) {
      const p = await flush();
      if (!p) return;
    }
    try {
      setJob(await api<Job>(`/api/episodes/${ep}/cut-project/export`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ by: "owner" }) }));
    } catch (e) {
      st.notify(`导出没开始：${String((e as Error).message ?? e)}`, "err");
    }
  };

  if (err) return <div className="ce-root ce-err">剪辑工程读不到：{err}</div>;
  if (!proj || !bgm) return <div className="ce-root ce-skel" />;
  const selSeg = segs.find((s) => s.index === sel) ?? null;
  const selLay = lay.find((x) => x.s.index === sel);
  const subNow = speech.find((x) => t >= x.start_s && t <= x.end_s);
  const music = proj.music_choices.find((m) => m.file === bgm.file);
  const envPts = (() => {
    const pts: [number, number][] = [];
    const N = 240;
    for (let i = 0; i <= N; i++) {
      const tt = (total * i) / N;
      const g = bgmGain(tt, total, bgm, speech);
      const db = g > 0 ? 20 * Math.log10(g) : -60;
      pts.push([(tt / total) * 1000, Math.min(96, Math.max(4, 16 + (-db * 70) / 30))]);
    }
    return pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  })();
  const steps: [string, Job["state"][]][] = [
    ["收下", ["queued"]],
    ["合成画面", ["picture"]],
    ["混音 + 响度", ["sound"]],
    ["定稿", ["final"]],
  ];
  const stepIdx = job ? (job.state === "done" ? 4 : steps.findIndex(([, ss]) => ss.includes(job.state))) : -1;

  return (
    <div className="ce-root">
      <div className="ce-bar">
        <span className="ce-ep">EP{String(ep).padStart(2, "0")} · {fmt(total)} · {segs.length} 镜</span>
        <span className={`ce-save s-${save}`}>{save === "saving" ? "正在保存…" : save === "dirty" ? "有改动，马上自动保存" : `工程第 ${proj.rev} 版 · 已保存`}</span>
        {proj.final && (
          <span className="ce-final">
            定稿 · 第 {proj.final.rev} 版工程 · {proj.final.at.slice(5, 16).replace("T", " ")}
            {proj.final.rev < proj.rev ? " · 之后的改动导出后才进定稿" : ""}
          </span>
        )}
        <span className="ce-grow" />
        {running && (
          <span className="ce-busy">
            <i className="is-rendering" />
            {job?.stage ?? "正在导出"} · 约 {Math.max(1, Math.round((job?.eta_s ?? 60) / 60))} 分钟
          </span>
        )}
        <button className="ce-btn pri" disabled={running} title={running ? "正在导出，完成后会出现在左侧版本列表并标“定稿”" : "在服务器上合成成片（只用 CPU），完成后成为这一集的定稿版本"} onClick={() => void exportNow()}>
          {running ? "正在导出…" : "导出成片"}
        </button>
      </div>

      {job && running && (
        <div className="ce-steps" aria-label="导出进度">
          {steps.map(([lab], i) => (
            <div key={lab} className={`ce-step${i < stepIdx ? " done" : i === stepIdx ? " on" : ""}`}>
              <span className="n">{String(i + 1).padStart(2, "0")}</span>
              <span className="l">
                {i === stepIdx && running && <i className="is-rendering" />}
                {lab}
              </span>
              <span className="bar">
                <b style={{ width: i < stepIdx ? "100%" : i === stepIdx ? `${Math.min(100, Math.max(8, (((job.pct ?? 0) - [0, 8, 60, 90][i]) / ([8, 52, 30, 10][i] || 1)) * 100))}%` : "0" }} />
              </span>
            </div>
          ))}
        </div>
      )}
      {job?.state === "done" && job.url && (
        <div className="ce-steps">
          <a className="ce-done" href={job.url} target="_blank" rel="noreferrer">
            定稿已出：{job.output?.split("/").pop()}（已进左侧版本列表）
          </a>
        </div>
      )}
      {job?.state === "failed" && (
        <div className="ce-steps">
          <span className="ce-fail">上次导出没成功：{job.error}（改好后再点“导出成片”）</span>
        </div>
      )}

      <div className="ce-main">
        <div className="ce-stage">
          <div className="ce-player">
            <video ref={vidRef} muted={false} playsInline preload="auto" style={{ visibility: curSeg?.s.kind === "video" ? "visible" : "hidden" }} />
            {curSeg && curSeg.s.kind !== "video" && (curSeg.s.url ? <img src={curSeg.s.url} alt="" /> : <div className="ce-black">黑场</div>)}
            <span className="ce-tag">PREVIEW · 字幕外挂</span>
            {subNow && <div className="ce-sub">{subNow.text}</div>}
          </div>
          <audio ref={bgmRef} src={fileUrl(bgm.file) ?? undefined} preload="auto" />
          <div className="ce-transport">
            <button onClick={() => seek((curSeg?.start ?? 0) - 0.05)} title="上一镜">⏮</button>
            <button className="p" onClick={() => setPlaying((p) => !p)} title="播放 / 暂停（空格）">{playing ? "❚❚" : "▶"}</button>
            <button onClick={() => seek(curSeg?.end ?? 0)} title="下一镜">⏭</button>
            <span>{fmt(t)} / {fmt(total)}</span>
          </div>
        </div>

        <aside className="ce-insp">
          {selSeg && selLay ? (
            <>
              <div className="ce-insp-h">
                {selSeg.url && <img src={selSeg.kind === "video" ? `/api/cut-frame?src=${encodeURIComponent(selSeg.url)}&t=${(selSeg.trim_head_s + segLen(selSeg) / 2).toFixed(2)}&w=120` : selSeg.url} alt="" />}
                <div>
                  <b>S{selSeg.index}</b>
                  <div className="ce-dim">{selSeg.kind === "video" ? (selSeg.origin ?? "").replace(/^ep\d+-S\d+\s*/, "") : selSeg.kind === "still" ? "静帧占位（视频还没出）" : "黑场"}</div>
                  {selSeg.replaced_from && <div className="ce-note">新片已换上{selSeg.trim_by === "owner" ? "，裁切沿用" : ""}{selSeg.trim_adjusted ? "（新片更短，已收到片尾，看一眼）" : ""}</div>}
                </div>
              </div>
              {selSeg.kind === "video" && selSeg.source_duration_s ? (
                <>
                  <div className="ce-src">
                    {[0, 1, 2, 3, 4, 5].map((k) => (
                      <img key={k} src={`/api/cut-frame?src=${encodeURIComponent(selSeg.url!)}&t=${((selSeg.source_duration_s! * (k + 0.5)) / 6).toFixed(2)}&w=90`} alt="" />
                    ))}
                    <span className="dim" style={{ left: 0, width: `${(selSeg.trim_head_s / selSeg.source_duration_s) * 100}%` }} />
                    <span className="dim" style={{ right: 0, width: `${(selSeg.trim_tail_s / selSeg.source_duration_s) * 100}%` }} />
                    <span className="edge" style={{ left: `${(selSeg.trim_head_s / selSeg.source_duration_s) * 100}%` }} />
                    <span className="edge" style={{ left: `${(1 - selSeg.trim_tail_s / selSeg.source_duration_s) * 100}%` }} />
                  </div>
                  <dl className="ce-kv">
                    <dt>入点</dt>
                    <dd>
                      <input type="number" step={0.04} min={0} value={selSeg.trim_head_s} onChange={(e) => setTrim(selSeg.index, Number(e.target.value), selSeg.trim_tail_s)} /> s
                    </dd>
                    <dt>出点</dt>
                    <dd>
                      <input type="number" step={0.04} min={0} value={r3(selSeg.source_duration_s - selSeg.trim_tail_s)} onChange={(e) => setTrim(selSeg.index, selSeg.trim_head_s, selSeg.source_duration_s! - Number(e.target.value))} /> s
                    </dd>
                    <dt>源长</dt>
                    <dd>{selSeg.source_duration_s.toFixed(3)} s</dd>
                    <dt>成片长</dt>
                    <dd>{segLen(selSeg).toFixed(3)} s</dd>
                    <dt>裁切</dt>
                    <dd>{selSeg.trim_by === "owner" ? "你定的（导出时以它为准）" : "装配自动定的"}</dd>
                  </dl>
                </>
              ) : (
                <p className="ce-dim">{selSeg.kind === "still" ? "这一镜视频出来后会自动换上。" : ""}</p>
              )}
              <div className="ce-dim">换镜头 → 去画布“修改”；新片回来自动替换这一段，裁切沿用。</div>
            </>
          ) : (
            <p className="ce-dim">点时间线上的一段镜头</p>
          )}

          <div className="ce-bgm">
            <b>集级配乐</b>
            <label>
              <span>曲目</span>
              <select value={bgm.file} onChange={(e) => setBgmF({ file: e.target.value })}>
                {proj.music_choices.map((m) => (
                  <option key={m.file} value={m.file}>
                    {m.name}
                    {m.mine ? "（本集）" : ""}
                    {m.duration_s ? ` · ${Math.round(m.duration_s)} s` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>从曲中</span>
              <input type="number" step={0.5} min={0} value={bgm.offset_s} onChange={(e) => setBgmF({ offset_s: Math.max(0, Number(e.target.value)) })} /> s 开始
            </label>
            <label>
              <span>整体</span>
              <input type="range" min={-30} max={6} step={0.5} value={bgm.gain_db} onChange={(e) => setBgmF({ gain_db: Number(e.target.value) })} />
              <em>{bgm.gain_db > 0 ? "+" : ""}{bgm.gain_db} dB</em>
            </label>
            <label>
              <span>淡入</span>
              <input type="number" step={0.5} min={0} max={10} value={bgm.fade_in_s} onChange={(e) => setBgmF({ fade_in_s: Number(e.target.value) })} /> s
            </label>
            <label>
              <span>淡出</span>
              <input type="number" step={0.5} min={0} max={10} value={bgm.fade_out_s} onChange={(e) => setBgmF({ fade_out_s: Number(e.target.value) })} /> s
            </label>
            <div className="ce-dim">对白处自动压低 12 dB、独白 9 dB；成片响度 −14 LUFS。{music?.duration_s && music.duration_s - bgm.offset_s < total ? " 这条从这里起不够整集长，导出时会循环。" : ""}</div>
          </div>
        </aside>
      </div>

      <div className="ce-tl" onPointerMove={onHandleMove} onPointerUp={onHandleUp}>
        <div className="ce-ruler" style={{ marginLeft: LANE_LABEL }} onClick={(e) => seek((e.clientX - e.currentTarget.getBoundingClientRect().left) / pps)}>
          {Array.from({ length: Math.floor(total / 4) + 1 }, (_, k) => k * 4).map((s) => (
            <span key={s} style={{ left: s * pps }}>
              {fmt(s).slice(0, -3)}
            </span>
          ))}
        </div>
        <div className="ce-track">
          <div className="ce-lab">V1 镜头</div>
          <div className="ce-lane v" ref={laneRef}>
            {lay.map(({ s, start, end }) => {
              const w = (end - start) * pps;
              const n = Math.max(1, Math.round(w / 40));
              return (
                <div key={s.index} className={`ce-clip${s.kind !== "video" ? " still" : ""}${s.index === sel ? " sel" : ""}${s.trim_by === "owner" ? " own" : ""}`} style={{ left: start * pps, width: w }} onClick={() => setSel(s.index)} onDoubleClick={() => seek(start)} title={`S${s.index} · ${(end - start).toFixed(2)} s`}>
                  {s.url &&
                    Array.from({ length: n }, (_, k) => (
                      <img key={k} loading="lazy" src={s.kind === "video" ? `/api/cut-frame?src=${encodeURIComponent(s.url!)}&t=${(s.trim_head_s + ((end - start) * (k + 0.5)) / n).toFixed(1)}&w=60` : `/api/cut-frame?src=${encodeURIComponent(s.url!)}&w=60`} alt="" />
                    ))}
                  <span className="no">S{s.index}</span>
                  {s.kind === "still" && <span className="ph">静帧占位</span>}
                  {s.replaced_from && <span className="nw">新片</span>}
                  {s.index === sel && s.kind === "video" && (
                    <>
                      <span className="hdl l" onPointerDown={(e) => onHandleDown(e, s, "l")} title="拖动裁开头" />
                      <span className="hdl r" onPointerDown={(e) => onHandleDown(e, s, "r")} title="拖动裁结尾" />
                    </>
                  )}
                </div>
              );
            })}
          </div>
        </div>
        <div className="ce-track">
          <div className="ce-lab">A1 对白</div>
          <div className="ce-lane a">
            {speech.map((x, i) => (
              <div key={i} className={`ce-blk ${x.kind === "dialogue" ? "dl" : "vo"}`} style={{ left: x.start_s * pps, width: Math.max(4, (x.end_s - x.start_s) * pps) }} title={`${x.speaker ?? ""} · ${x.text}`}>
                {x.speaker} · {x.text}
              </div>
            ))}
          </div>
        </div>
        <div className="ce-track">
          <div className="ce-lab">A2 配乐</div>
          <div className="ce-lane m">
            <span className="ce-mname">{music?.name ?? bgm.file.split("/").pop()}{bgm.offset_s ? ` · 从 ${bgm.offset_s}s` : ""}</span>
            <svg viewBox="0 0 1000 100" preserveAspectRatio="none">
              <polyline points={envPts} fill="none" stroke="#e9e6e0" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            </svg>
          </div>
        </div>
        <div className="ce-track">
          <div className="ce-lab">SUB 字幕</div>
          <div className="ce-lane s">
            {speech.map((x, i) => (
              <div key={i} className="ce-blk sb" style={{ left: x.start_s * pps, width: Math.max(4, (x.end_s - x.start_s) * pps) }} title={x.text}>
                {x.text}
              </div>
            ))}
          </div>
        </div>
        <div className="ce-head" style={{ left: `calc(${LANE_LABEL}px + ${t * pps}px)` }} />
      </div>
      <p className="ce-hint">点选一段 → 拖两头金色把手裁头尾 · 双击一段从那里播 · 点刻度尺跳转 · 空格播放 · 白线 = 配乐音量（淡入、对白处压低、淡出）· 改动自动保存成工程，导出时服务器按工程合成</p>
    </div>
  );
}
