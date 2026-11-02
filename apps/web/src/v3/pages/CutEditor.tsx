// CUTEDIT P1（设计稿 data/review_pages/cutedit/index.html；总调度 11-02 批准：自做轻量时间线，交互参考 OpenCut classic / OpenReel，均 MIT）。
// 剪辑工程 data/renders/epNN/_final/cut_project.json（后端 services/api/ns_api/cut_project.py）：浏览器只改工程，导出在服务端用 assemble.py 合成。
// P1 最小闭环：裁头尾（拖把手 / 输入秒数）→ 集级配乐换曲、起点、音量、淡入淡出（对白处自动压低，L-118）→ 导出成片（先收下、原位进度）→ 成为定稿版本。
// P1 续（总调度 20:10）：字幕直接编辑（点字幕块 → 下方改字 / 起止；拖块移动、拖右边改长短；“加一条字幕”在播放头处）；
// 镜头拖拽换顺序（按住一段左右拖，松手落到金色插入线处）。改动原位自动保存（PUT 立即收下），导出时服务器按工程合成。
// 字幕时间存成“相对本镜在成片里的起点”，别的镜头裁切 / 换序后字幕仍跟着本镜走。不烧字幕（L-002）；界面只有正向动作（L-123）。
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
  base_trim_head_s?: number;
  base_length_s?: number | null;
}
interface Overrode {
  field: string;
  label: string;
  text: string;
  prev_rev?: number | null;
  prev_by?: string | null;
  prev_value?: unknown;
}
interface HistItem {
  id?: string;
  at: string;
  what: string;
  by?: string;
  overrode?: (Overrode | string)[];
  restored?: { at: string; by?: string; history_id: string; fields: string[] }[];
  restored_from?: string;
}
interface Sub {
  shot: number;
  text: string;
  d0: number;
  d1: number;
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
  file: string | null;
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
  history?: HistItem[];
  subtitles: Sub[];
  subtitles_edited: boolean;
}

const MIN_KEEP = 0.2;
/** 这个窗口的标识：同一窗口自己的连改 / 重发，服务器不记成“覆盖” */
const CLIENT = Math.random().toString(36).slice(2, 10);
const DUCK_DL = -12; // L-118：对白处压 12 dB
const DUCK_VO = -9; // 独白处压 9 dB
const LANE_LABEL = 72;
const fileUrl = (rel?: string | null) => (rel && rel.startsWith("data/") ? `/files/${rel.slice(5)}` : null);
const segLen = (s: Seg) => (s.kind === "video" && s.source_duration_s ? Math.max(MIN_KEEP, s.source_duration_s - s.trim_head_s - s.trim_tail_s) : s.still_s ?? 4);
const fmt = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, "0")}`;
const r3 = (x: number) => Math.round(x * 1000) / 1000;
/** 拖动时捕获指针（拿不到捕获也照常拖：时间线容器统一收 pointermove / pointerup） */
const capture = (el: EventTarget, id: number) => {
  try {
    (el as HTMLElement).setPointerCapture(id);
  } catch {
    /* 合成事件 / 已松手：不影响拖动 */
  }
};

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

/** 对白 / 独白跟着裁切和换序挪：基准 = 建工程时的时间线（镜号顺序 + 自动裁切）；画内对白随画面（裁头会把它往前带），独白只跟段起点 */
function shiftSpeech(speech: Speech[], now: Seg[]) {
  const bStart = new Map<number, number>();
  let bt = 0;
  for (const s of [...now].sort((a, b) => a.index - b.index)) {
    bStart.set(s.index, bt);
    bt += s.base_length_s ?? segLen(s);
  }
  const n = layout(now);
  return speech.map((x) => {
    const i = now.findIndex((s) => s.index === x.shot);
    if (i < 0) return x;
    let d = n[i].start - (bStart.get(x.shot) ?? 0);
    if (x.kind === "dialogue" && now[i].kind === "video") d -= now[i].trim_head_s - (now[i].base_trim_head_s ?? now[i].trim_head_s);
    return { ...x, start_s: x.start_s + d, end_s: x.end_s + d };
  });
}

/** 字幕绝对时间（成片时间轴）= 本镜起点 + 相对秒数 */
function subAbs(subs: Sub[], lay: { s: Seg; start: number }[]) {
  const st = new Map(lay.map((x) => [x.s.index, x.start] as const));
  return subs.map((x, i) => ({ ...x, i, a: (st.get(x.shot) ?? 0) + x.d0, b: (st.get(x.shot) ?? 0) + x.d1 }));
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
  const [subs, setSubs] = useState<Sub[]>([]);
  const [subsEdited, setSubsEdited] = useState(false);
  const [selSub, setSelSub] = useState<number | null>(null);
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
        setSubs(p.subtitles ?? []);
        setSubsEdited(!!p.subtitles_edited);
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
  const speech = useMemo(() => (proj ? shiftSpeech(proj.speech, segs) : []), [proj, segs]);
  const subsA = useMemo(() => subAbs(subs, lay), [subs, lay]);

  // ---------- 保存（停手 700 ms 自动存；rev 冲突 → 重新读）
  const saveTimer = useRef<number | null>(null);
  const pending = useRef<{ segs: Seg[]; bgm: Bgm | null; subs: Sub[] | null } | null>(null);
  // 三方合并（OVERSIGHT-F r7）：基线 = 最近一次从服务器拿到的工程；保存时只发和基线不同的字段，别的窗口刚改的不会被这里的旧值盖回去
  const baseRef = useRef<Proj | null>(null);
  baseRef.current = baseRef.current && proj && baseRef.current.rev > proj.rev ? baseRef.current : proj;
  const flush = useCallback(async () => {
    const base = baseRef.current;
    if (!base || !pending.current) return base;
    const pd = pending.current;
    const bIdx = new Map(base.segments.map((x) => [x.index, x] as const));
    const segDiff = pd.segs
      .filter((x) => x.kind === "video")
      .filter((x) => {
        const b = bIdx.get(x.index);
        return !b || b.trim_head_s !== x.trim_head_s || b.trim_tail_s !== x.trim_tail_s;
      })
      .map((x) => ({ index: x.index, trim_head_s: x.trim_head_s, trim_tail_s: x.trim_tail_s }));
    const order = pd.segs.map((x) => x.index);
    const orderChanged = order.join() !== base.segments.map((x) => x.index).join();
    const bgmDiff: Partial<Bgm> = {};
    if (pd.bgm) for (const k of ["file", "offset_s", "gain_db", "fade_in_s", "fade_out_s"] as const) if (pd.bgm[k] !== base.bgm?.[k]) (bgmDiff as Record<string, unknown>)[k] = pd.bgm[k];
    const subsChanged = !!pd.subs && (!base.subtitles_edited || JSON.stringify(pd.subs) !== JSON.stringify(base.subtitles));
    pending.current = null;
    if (!segDiff.length && !orderChanged && !Object.keys(bgmDiff).length && !subsChanged) {
      setSave("saved");
      return base;
    }
    const body = {
      rev: base.rev,
      by: "owner",
      client: CLIENT,
      ...(segDiff.length ? { segments: segDiff } : {}),
      ...(orderChanged ? { order } : {}),
      ...(Object.keys(bgmDiff).length ? { bgm: bgmDiff } : {}),
      ...(subsChanged ? { subtitles: pd.subs } : {}),
    };
    setSave("saving");
    try {
      const p = await api<Proj>(`/api/episodes/${ep}/cut-project`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      baseRef.current = p;
      setProj(p);
      if (!pending.current) {
        // 保存期间没再改：把合并后的结果（可能含别的窗口的改动）整体带回来
        segsRef.current = p.segments;
        setSegs(p.segments);
        setBgm(p.bgm);
        setSubs(p.subtitles ?? []);
        setSubsEdited(!!p.subtitles_edited);
      } else if (!p.subtitles_edited) setSubs(p.subtitles ?? []);
      setSave("saved");
      return p;
    } catch (e) {
      st.notify(`没存上：${String((e as Error).message ?? e)}（改动还在页面上，稍后会再存）`, "err");
      pending.current = pending.current ?? pd;   // 不丢：留着，3 秒后自动再发
      setSave("dirty");
      if (saveTimer.current) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => void flush(), 3000);
      return null;
    }
  }, [ep, st]);
  const schedule = (nextSegs: Seg[], nextBgm: Bgm | null, nextSubs?: Sub[] | null) => {
    pending.current = { segs: nextSegs, bgm: nextBgm, subs: nextSubs !== undefined ? nextSubs : pending.current?.subs ?? (subsEdited ? subs : null) };
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

  // ---------- 被覆盖的改动：一键找回（POST …/restore，202 收下，恢复也记成一次新改动）
  const [restoring, setRestoring] = useState<string | null>(null);
  const restore = async (hid: string, field?: string) => {
    setRestoring(`${hid}:${field ?? ""}`);
    try {
      const p = await api<Proj>(`/api/episodes/${ep}/cut-project/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ history_id: hid, field, by: "owner", client: CLIENT }) });
      baseRef.current = p;
      setProj(p);
      segsRef.current = p.segments;
      setSegs(p.segments);
      setBgm(p.bgm);
      setSubs(p.subtitles ?? []);
      setSubsEdited(!!p.subtitles_edited);
      st.notify("被覆盖的改动已找回");
    } catch (e) {
      st.notify(`没找回：${String((e as Error).message ?? e)}`, "err");
    } finally {
      setRestoring(null);
    }
  };

  // ---------- 拖把手裁头尾
  const onHandleDown = (e: React.PointerEvent, s: Seg, side: "l" | "r") => {
    e.stopPropagation();
    capture(e.target, e.pointerId);
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
    if (subDrag.current) {
      const moved = subDrag.current.moved;
      subDrag.current = null;
      if (moved) schedule(segsRef.current, bgm, subsRef.current);   // 只是点选不保存
      return;
    }
    if (move.current) {
      const m = move.current;
      move.current = null;
      setMoveTo(null);
      if (m.active && m.to !== null) reorder(m.index, m.to);
      return;
    }
    if (!drag.current) return;
    drag.current = null;
    schedule(segsRef.current, bgm);
  };

  // ---------- 镜头拖拽换顺序：按住一段左右拖（超过 6 px 才算拖），金色插入线 = 松手后落的位置
  const move = useRef<{ index: number; x0: number; active: boolean; to: number | null } | null>(null);
  const [moveTo, setMoveTo] = useState<{ index: number; to: number } | null>(null);
  const onClipDown = (e: React.PointerEvent, s: Seg) => {
    if ((e.target as HTMLElement).classList.contains("hdl")) return;
    capture(e.currentTarget, e.pointerId);
    move.current = { index: s.index, x0: e.clientX, active: false, to: null };
  };
  const insertAt = (clientX: number) => {
    const el = laneRef.current;
    if (!el) return 0;
    const x = (clientX - el.getBoundingClientRect().left) / pps;
    const k = lay.findIndex((y) => x < (y.start + y.end) / 2);
    return k < 0 ? lay.length : k;   // 插到第 k 段之前
  };
  const onLaneMove = (e: React.PointerEvent) => {
    const m = move.current;
    if (m) {
      if (!m.active && Math.abs(e.clientX - m.x0) > 6) m.active = true;
      if (m.active) {
        m.to = insertAt(e.clientX);
        setMoveTo({ index: m.index, to: m.to });
      }
      return;
    }
    if (subDrag.current) return onSubMove(e);
    onHandleMove(e);
  };
  const reorder = (index: number, to: number) => {
    const from = segs.findIndex((s) => s.index === index);
    if (from < 0) return;
    const next = [...segs];
    const [it] = next.splice(from, 1);
    next.splice(to > from ? to - 1 : to, 0, it);
    if (next.map((s) => s.index).join() === segs.map((s) => s.index).join()) return;
    segsRef.current = next;
    setSegs(next);
    setSel(index);
    schedule(next, bgm);
  };

  // ---------- 字幕：点选 → 下方改字 / 起止；拖块移动、拖右边改长短；“加一条字幕”
  const subsRef = useRef<Sub[]>(subs);
  const subDrag = useRef<{ i: number; mode: "move" | "end"; x0: number; d0: number; d1: number; moved: boolean } | null>(null);
  subsRef.current = subDrag.current ? subsRef.current : subs;
  const commitSubs = (next: Sub[], save = true) => {
    subsRef.current = next;
    setSubs(next);
    setSubsEdited(true);
    if (save) schedule(segsRef.current, bgm, next);
  };
  const setSubAbs = (i: number, patch: { text?: string; a?: number; b?: number }) => {
    const x = subsA[i];
    if (!x) return;
    const segStart = x.a - x.d0;
    const next = subs.map((s, k) => {
      if (k !== i) return s;
      const d0 = patch.a !== undefined ? Math.max(0, r3(patch.a - segStart)) : s.d0;
      const d1 = patch.b !== undefined ? Math.max(d0 + 0.2, r3(patch.b - segStart)) : Math.max(d0 + 0.2, s.d1);
      return { ...s, text: patch.text ?? s.text, d0, d1 };
    });
    commitSubs(next);
  };
  const onSubDown = (e: React.PointerEvent, i: number, mode: "move" | "end") => {
    e.stopPropagation();
    capture(e.currentTarget, e.pointerId);
    setSelSub(i);
    subDrag.current = { i, mode, x0: e.clientX, d0: subs[i].d0, d1: subs[i].d1, moved: false };
  };
  const onSubMove = (e: React.PointerEvent) => {
    const d = subDrag.current;
    if (!d) return;
    if (!d.moved && Math.abs(e.clientX - d.x0) < 3) return;
    d.moved = true;
    const dt = (e.clientX - d.x0) / pps;
    const next = subsRef.current.map((s, k) => {
      if (k !== d.i) return s;
      if (d.mode === "end") return { ...s, d1: r3(Math.max(s.d0 + 0.2, d.d1 + dt)) };
      const nd0 = Math.max(0, d.d0 + dt);
      return { ...s, d0: r3(nd0), d1: r3(nd0 + (d.d1 - d.d0)) };
    });
    commitSubs(next, false);
  };
  const addSub = () => {
    const x = lay.find((y) => t >= y.start && t < y.end) ?? lay[0];
    if (!x) return;
    const d0 = r3(t - x.start);
    const next = [...subs, { shot: x.s.index, text: "新字幕", d0, d1: r3(d0 + 1.5) }];
    commitSubs(next);
    setSelSub(next.length - 1);
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
  // 打开就显示播放头处那一帧（不用先点播放）；换序 / 裁切后也跟着刷新
  useEffect(() => {
    if (!playing && lay.length) seek(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lay]);
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
  const subNow = subsA.find((x) => x.text.trim() && t >= x.a && t <= x.b);
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
              <select value={bgm.file ?? ""} onChange={(e) => setBgmF({ file: e.target.value })}>
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

      <div className="ce-tl" onPointerMove={onLaneMove} onPointerUp={onHandleUp}>
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
                <div key={s.index} className={`ce-clip${s.kind !== "video" ? " still" : ""}${s.index === sel ? " sel" : ""}${s.trim_by === "owner" ? " own" : ""}${moveTo?.index === s.index ? " moving" : ""}`} style={{ left: start * pps, width: w }} onPointerDown={(e) => onClipDown(e, s)} onClick={() => setSel(s.index)} onDoubleClick={() => seek(start)} title={`S${s.index} · ${(end - start).toFixed(2)} s`}>
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
            {moveTo && <span className="ce-ins" style={{ left: (moveTo.to < lay.length ? lay[moveTo.to].start : total) * pps }} />}
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
            <span className="ce-mname">{bgm.file ? `${music?.name ?? bgm.file.split("/").pop()}${bgm.offset_s ? ` · 从 ${bgm.offset_s}s` : ""}` : "这一集还没有配乐"}</span>
            <svg viewBox="0 0 1000 100" preserveAspectRatio="none">
              <polyline points={envPts} fill="none" stroke="#e9e6e0" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
            </svg>
          </div>
        </div>
        <div className="ce-track">
          <div className="ce-lab">SUB 字幕</div>
          <div className="ce-lane s">
            {subsA.map((x) => (
              <div
                key={x.i}
                className={`ce-blk sb${x.i === selSub ? " on" : ""}${x.text.trim() ? "" : " empty"}`}
                style={{ left: x.a * pps, width: Math.max(6, (x.b - x.a) * pps) }}
                title={`${x.text || "（空，导出时不出这条）"} · 挂在 S${x.shot}`}
                onPointerDown={(e) => onSubDown(e, x.i, "move")}
                onDoubleClick={() => seek(x.a)}
              >
                {x.text || "（空）"}
                <span className="end" onPointerDown={(e) => onSubDown(e, x.i, "end")} />
              </div>
            ))}
          </div>
        </div>
        <div className="ce-head" style={{ left: `calc(${LANE_LABEL}px + ${t * pps}px)` }} />
      </div>
      <div className="ce-subbar">
        {selSub !== null && subsA[selSub] ? (
          <>
            <b>字幕 · S{subsA[selSub].shot}</b>
            <input className="ce-subtext" value={subsA[selSub].text} placeholder="留空 = 导出时不出这条" onChange={(e) => setSubAbs(selSub, { text: e.target.value })} />
            <label>
              起 <input type="number" step={0.04} value={r3(subsA[selSub].a)} onChange={(e) => setSubAbs(selSub, { a: Number(e.target.value), b: Number(e.target.value) + (subsA[selSub].b - subsA[selSub].a) })} /> s
            </label>
            <label>
              止 <input type="number" step={0.04} value={r3(subsA[selSub].b)} onChange={(e) => setSubAbs(selSub, { b: Number(e.target.value) })} /> s
            </label>
          </>
        ) : (
          <span className="ce-dim">点字幕轨上的一条来改字和时间；拖动一条整体挪，拖它右边改长短</span>
        )}
        <span className="ce-grow" />
        <span className="ce-dim">{subsEdited ? "字幕是你改过的版本（外挂 .srt，不烧进画面）" : "字幕按对白自动生成（外挂 .srt）"}</span>
        <button className="ce-btn" onClick={addSub} title="在播放头的位置加一条字幕">
          在播放头处加一条字幕
        </button>
      </div>
      {!!proj.history?.length && (
        <details className="ce-hist" open={proj.history.slice(-8).some((h) => (h.overrode ?? []).some((o) => typeof o !== "string" && o.prev_value !== undefined) && !h.restored?.length)}>
          <summary>改动记录（最近 {Math.min(8, proj.history.length)} 条）</summary>
          <ul>
            {[...proj.history].slice(-8).reverse().map((h, k) => (
              <li key={h.id ?? k}>
                <span className="t">{h.at.slice(11, 16)}</span>
                <span className="w">{h.what}</span>
                {(h.overrode ?? []).map((o, j) =>
                  typeof o === "string" ? (
                    <div key={j} className="ov">{o}</div>
                  ) : (
                    <div key={j} className="ov">
                      {o.text}
                      {h.id && o.prev_value !== undefined && (
                        h.restored?.some((r) => r.fields.includes(o.field)) ? (
                          <em className="done">已恢复</em>
                        ) : (
                          <button className="ce-btn sm" disabled={restoring === `${h.id}:${o.field}`} onClick={() => void restore(h.id!, o.field)} title="把被覆盖的这一项原样找回（会记成一次新改动，之后还能再换回来）">
                            {restoring === `${h.id}:${o.field}` ? "正在恢复…" : "恢复这条"}
                          </button>
                        )
                      )}
                    </div>
                  ),
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="ce-hint">点选一段 → 拖两头金色把手裁头尾 · 按住一段左右拖换顺序（金色竖线 = 落点）· 双击一段从那里播 · 点刻度尺跳转 · 空格播放 · 白线 = 配乐音量 · 改动自动保存成工程，导出时服务器按工程合成</p>
    </div>
  );
}
