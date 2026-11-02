// UIRSI r46 · L-114（项目方 AskUserQuestion 选“A 放映室片条”，FILMUI 稿 data/review_pages/filmui/a.html）：全剧总览的电影胶片样式。
// 只在开关打开时用（html.ui-film，见 v3/uiStyle.ts）；默认仍是现有总览。功能不删：单击一帧 = 右侧详情抽屉（同现有），双击 = 进画布这一镜，
// Ctrl / Shift 点 = 多选；悬停 = 大图放大镜（图高 420px + 片边信息：集 · 镜 · 景别 · 时长 · 实拍 / 计划镜头，D-LENS）。
// 片条按真实 35mm 比例画：片基黑、上下 KS 齿孔（竖幅横走 3 齿 / 帧）、片边暖灰小字（镜号），片头竖写 EPxx。
import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { thumb } from "../../thumb";
import { filmOn } from "../uiStyle";
import { hasAudio, soundUnlocked, unlockSound, useFilmSound } from "../filmSound";

/* FILMUI r5/r6：“悬停出声”全局状态在 ../filmSound.ts（默认开、记住；任意一次手势解锁），顶栏和总览共用。 */
/** 顶栏上的“悬停出声”开关（只在电影胶片样式 html.ui-film 下显示） */
export function FilmSoundToggle() {
  const [on, set] = useFilmSound();
  const [hash, setHash] = useState(() => location.hash);
  useEffect(() => {
    const f = () => setHash(location.hash);
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  // 只在电影胶片样式的全剧总览出现（悬停出声只在这里用；单集页顶栏不再被挤压，总调度 12:5x ②）
  if (!filmOn() || !(hash === "" || hash.startsWith("#/overview"))) return null;
  return (
    <button type="button" className={`fo-tsound${on ? " on" : ""}`} aria-pressed={on} aria-label="悬停出声" onClick={() => set(!on)}
      title="悬停在片条帧上时播放这一镜的视频声音。浏览器要求先点一次才允许出声；鼠标移走就停，同一时间只播一个。">
      {on ? "🔊" : "🔈"}<span className="fo-tsound-t"> 悬停出声</span>
    </button>
  );
}

export type FilmFrame = { key: string; src: string | null; kind?: "img" | "video"; ed?: string; empty?: string; cap?: string; dot?: "run" | "need" | "ok" | null; hoverVideo?: string | null; tag?: string | null; tagMock?: boolean;
  /** FILMUI r4：片窗角上的媒体类型小图标（单色）：video = 当前视频 / 旧版 / 示意；last = 有尾帧 */
  media?: { video: "cur" | "old" | "mock" | null; last: boolean };
  /** r6：圆点的悬停说明（出图中 · 首帧 / 尾帧 / 视频 · 已用 N 秒 · 哪台） */
  dotTip?: string | null };
const fmtTc = (t: number) => `${String(Math.floor(t / 60)).padStart(2, "0")}:${(t % 60).toFixed(1).padStart(4, "0")}`;
/** 单色小图标（片窗左上角；图例在总览顶部） */
export function MediaIcons({ m }: { m: NonNullable<FilmFrame["media"]> }) {
  return (
    <span className="fs-mi" aria-hidden>
      {m.video ? (
        <svg viewBox="0 0 10 10" width="10" height="10"><path d="M2 1.2 L8.6 5 L2 8.8 Z" fill={m.video === "cur" ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1" strokeLinejoin="round" /></svg>
      ) : (
        <svg viewBox="0 0 10 10" width="10" height="10"><rect x="1" y="1.5" width="8" height="7" rx=".8" fill="none" stroke="currentColor" strokeWidth="1" /><path d="M1.8 7.6 L4.2 5 L6 6.6 L7 5.6 L8.4 7.2" fill="none" stroke="currentColor" strokeWidth=".9" /></svg>
      )}
      {m.video && <svg viewBox="0 0 10 10" width="10" height="10"><path d="M4 7.6 V2 L8 1.2 V6.8" fill="none" stroke="currentColor" strokeWidth="1" /><circle cx="3" cy="7.6" r="1.3" fill="currentColor" /><circle cx="7" cy="6.8" r="1.3" fill="currentColor" /></svg>}
      {m.last && <svg viewBox="0 0 12 10" width="12" height="10"><rect x=".8" y="1.5" width="5" height="7" rx=".6" fill="none" stroke="currentColor" strokeWidth="1" /><rect x="6.2" y="1.5" width="5" height="7" rx=".6" fill="currentColor" /></svg>}
    </span>
  );
}

const pad2 = (n: number) => String(n).padStart(2, "0");
/** 真实 35mm 正片几何（FILMUI r3，项目方 12:0x“不太像胶片”；参照 Wikimedia Commons 放映拷贝近照，见 docs/research/filmui/refs.md §6）。
 *  画高 H 对应 24.9 mm；片边 rail = 5.05 mm = 0.203H，其中：外侧片边 2.01 mm（0.081H，印片边字 / KeyKode）、KS 齿孔 1.98 × 2.79 mm（0.0795H × 0.112H，
 *  圆角 0.5 mm）、齿孔到画面 1.06 mm（0.043H）；齿距 4.74 mm（0.19H），竖幅横走 3 齿 / 帧。齿孔只透一点很弱的暖光，片基深炭黑偏暖（项目方 12:0x“胶片太亮了，暗黑调”：画面是整页最亮的东西）。 */
function perf(pitch: number, rail: number, hole: string, side: "top" | "bottom") {
  const k = rail / 0.203;
  const w = Math.max(3, 0.112 * k), h = Math.max(2.2, 0.0795 * k), rx = Math.max(0.7, 0.022 * k);
  const outer = 0.081 * k;
  const y = side === "top" ? outer : rail - outer - h;
  const x = (pitch - w) / 2;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${pitch.toFixed(3)}" height="${rail}"><defs><linearGradient id="l" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${hole}"/><stop offset="1" stop-color="#221e19"/></linearGradient></defs><rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}" rx="${rx.toFixed(2)}" fill="url(#l)" stroke="rgba(0,0,0,.7)" stroke-width=".7"/></svg>`;
  return `url('data:image/svg+xml,${encodeURIComponent(svg)}')`;
}
const keykode = (n: number, shot: number) => `KN ${pad2(n)} ${String(1000 + n * 37).padStart(4, "0")} ${String(shot * 16 + 12).padStart(4, "0")}+00`;
/** KeyKode 条码（USS-128 样式的窄 / 宽条，按文字定序，印在片边字旁边） */
function barcode(text: string, h: number) {
  let x = 0, bars = "";
  for (let i = 0; i < text.length; i++) {
    const c = text.charCodeAt(i);
    for (let b = 0; b < 3; b++) {
      const w = 0.8 + ((c >> b) & 1) * 1.1;
      if ((c + b) % 2 === 0) bars += `<rect x="${x.toFixed(1)}" y="0" width="${w.toFixed(1)}" height="${h}"/>`;
      x += w + 0.7;
    }
  }
  return { w: Math.ceil(x), svg: `url('data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${Math.ceil(x)}" height="${h}" fill="#8c7347">${bars}</svg>`)}')` };
}

export function FilmStrip({ frames, H, lead, kk, onFrame, onFrameDbl, onEnter, onMove, onLeave, thumbW = 240, sound = false }: {
  frames: FilmFrame[]; H: number; lead?: string; kk?: string; thumbW?: number; sound?: boolean;
  onFrame?: (i: number, ev: MouseEvent) => void; onFrameDbl?: (i: number) => void;
  onEnter?: (i: number, ev: MouseEvent) => void; onMove?: (ev: MouseEvent) => void; onLeave?: () => void;
}) {
  // 真实比例 rail = 0.203 × 画高；大片条（单集每格 ≥240px）时齿孔会过大抢画面 → 上限 48px（齿孔、片边字按 rail 等比缩）
  const rail = Math.round(Math.min(H * 0.203, 48));
  const k = rail / 0.203;
  const outer = 0.081 * k;
  const fw = Math.round((H * 9) / 16) + 2;
  const pitch = fw / 3;
  const leadW = lead ? Math.round(H * 0.42) : 0;
  const ed = Math.max(7.5, Math.min(10.5, outer * 0.72));
  const fl = Math.max(1.5, fw * 0.018); // 帧线：每边约 1.8% 帧宽（两帧之间合计约 3.5%，与放映拷贝近照一致）
  const rad = Math.max(1.5, fw * 0.022); // 片窗四角轻微圆角
  const bh = Math.max(3, Math.round(outer * 0.55));
  const bc = kk ? barcode(kk, bh) : null;
  const [hov, setHov] = useState<number | null>(null);
  const [tc, setTc] = useState<{ t: number; d: number } | null>(null);
  const vref = useRef<HTMLVideoElement | null>(null);
  // FILMUI r4：悬停 = 播放这一镜视频（开了“悬停出声”就带声音；浏览器拒绝出声时自动退回静音）；左右移动鼠标 = 拖时间（scrub）
  const [needTap, setNeedTap] = useState(false);
  const [aud, setAud] = useState<"none" | "track" | "on">("none");
  // 悬停开始：要出声就先试带声音播；被浏览器拒绝（还没有用户手势）→ 先静音播，帧上提示“点一下开声音”，点了立刻出声
  // UIFIX-S：ref 回调必须稳定——以前每次重渲染（播放时 timeupdate 每 ~0.25 s 一次）React 都会先 ref(null) 再 ref(v)，
  // 每次都重新 play() / 重设 muted，和“点一下开声音”、手势解锁互相打架；现在只在 <video> 挂上时跑一次，开关 / 解锁变化交给下面的 effect
  const soundRef = useRef(sound);
  soundRef.current = sound;
  const startHover = useCallback((v: HTMLVideoElement | null) => {
    if (v && vref.current === v) return;
    vref.current = v;
    if (!v) return;
    v.defaultMuted = false;
    const want = soundRef.current && soundUnlocked();
    v.muted = !want;
    v.play().then(() => { setNeedTap(soundRef.current && v.muted); console.info("[film] hover play ok", { muted: v.muted, src: v.currentSrc.split("/").pop() }); })
      .catch((err) => { console.info("[film] hover play blocked → muted", String(err)); v.muted = true; setNeedTap(soundRef.current); v.play().catch(() => undefined); });
  }, []);
  const tapSound = (ev: MouseEvent) => {
    ev.stopPropagation();
    unlockSound();
    const v = vref.current;
    if (!v) return;
    v.muted = false;
    v.play().then(() => setNeedTap(false)).catch(() => setNeedTap(true));
  };
  // 开关 / 解锁变化时，正在悬停的那一个立刻跟着变
  useEffect(() => {
    const v = vref.current;
    if (!v) return;
    if (sound && soundUnlocked() && v.muted) { v.muted = false; v.play().then(() => setNeedTap(false)).catch(() => setNeedTap(true)); }
    if (!sound && !v.muted) v.muted = true;
  });
  const scrub = (ev: MouseEvent<HTMLDivElement>) => {
    const v = vref.current;
    if (!v || !v.duration || !isFinite(v.duration)) return;
    const r = ev.currentTarget.getBoundingClientRect();
    const f = Math.min(0.999, Math.max(0, (ev.clientX - r.left) / r.width));
    if (Math.abs(v.currentTime - f * v.duration) > 0.15) v.currentTime = f * v.duration;
  };
  return (
    <div className="fs-strip" style={{ height: H + rail * 2 }}>
      <div className="fs-rail t" style={{ height: rail, backgroundImage: perf(pitch, rail, "#3b342b", "top"), backgroundPosition: `${leadW}px 0` }} />
      <div className="fs-rail b" style={{ height: rail, backgroundImage: perf(pitch, rail, "#3b342b", "bottom"), backgroundPosition: `${leadW}px 0` }} />
      {kk && <span className="fs-kk" style={{ left: leadW + pitch * 0.5, top: (outer - ed) / 2, fontSize: ed, lineHeight: `${ed}px` }}>{kk}</span>}
      {kk && bc && <span className="fs-bc" style={{ left: leadW + pitch * 0.5 + kk.length * ed * 0.62 + 10, top: (outer - bh) / 2, width: bc.w, height: bh, backgroundImage: bc.svg }} />}
      {lead && (
        <div className="fs-lead" style={{ width: leadW }}>
          <span style={{ fontSize: Math.max(9, Math.min(12, H * 0.05)) }}>{lead}</span>
        </div>
      )}
      {frames.map((f, i) => (
        <div key={f.key} className="fs-fr" style={{ width: fw }} onClick={(ev) => onFrame?.(i, ev)} onDoubleClick={() => onFrameDbl?.(i)}
          onMouseEnter={(ev) => (setHov(i), setTc(null), setNeedTap(false), setAud("none"), onEnter?.(i, ev))} onMouseMove={(ev) => (hov === i && scrub(ev), onMove?.(ev))} onMouseLeave={() => (setHov(null), setTc(null), (vref.current = null), onLeave?.())} title={f.cap}>
          <div className="fs-band" style={{ top: rail, height: H }} />
          <div className="fs-img" style={{ top: rail, height: H, left: fl, right: fl, borderRadius: rad }}>
            {f.kind === "video" && f.src ? (
              <video src={`${f.src}#t=0.3`} preload="metadata" muted playsInline />
            ) : f.src ? (
              <img src={thumb(f.src, thumbW) ?? f.src} alt="" loading="lazy" decoding="async" draggable={false} data-zoom-label={f.cap} />
            ) : (
              <div className="fs-none">{f.empty ?? ""}</div>
            )}
            {/* r46（项目方 11:3x：“预览视频也需要”）：悬停播放这一镜的视频（默认出声，r6 FEEDBACK fb-0002） */}
            {f.hoverVideo && hov === i && (
              <video className="fs-hv" src={f.hoverVideo} ref={startHover} muted loop playsInline preload="auto"
                onTimeUpdate={(ev) => { const v = ev.currentTarget; setTc({ t: v.currentTime, d: v.duration || 0 }); setAud(!hasAudio(v) ? "none" : v.muted ? "track" : "on"); }} />
            )}
            {f.hoverVideo && hov === i && tc && tc.d > 0 && (
              <>
                <span className="fs-tc">{fmtTc(tc.t)} / {fmtTc(tc.d)}{aud === "on" ? "  🔊" : aud === "track" ? "  ♪" : ""}</span>
                <span className="fs-ph" style={{ width: `${(tc.t / tc.d) * 100}%` }} />
              </>
            )}
            {f.hoverVideo && hov === i && needTap && <button type="button" className="fs-tap" onClick={tapSound}>点一下开声音</button>}
            {f.media && <MediaIcons m={f.media} />}
            {f.tag && <span className={`fs-tag${f.tagMock ? " mock" : ""}`}>{f.tag}</span>}
            {f.dot && <i className={`sea-dot d-${f.dot}${f.dot === "run" ? " is-rendering" : ""}`} title={f.dotTip ?? undefined} aria-hidden={!f.dotTip} />}
          </div>
          {f.ed && (
            <div className="fs-ed" style={{ bottom: (outer - ed) / 2, fontSize: ed, lineHeight: `${ed}px`, paddingLeft: pitch * 0.25 }}>
              {f.ed}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/** 一个字段的值 + 来源：src = "api"（接口真值）或 "mock"（示意，灰色斜体标“示意”，接口有了自动替换） */
export type Fv = { v: string | null; src: "api" | "mock" };
type OvShot = {
  id: string; index: number; img: string | null; cap: string; dot: "run" | "need" | "ok" | null;
  size: Fv; secs: Fv; lens: Fv; light: Fv; move: Fv; faces: { name: string; url: string | null }[];
  video: string | null; videoOld: string | null; videoMock?: string | null; hasLast?: boolean; dotTip?: string | null;
};
function F({ f, empty = "—" }: { f: Fv; empty?: string }) {
  if (f.src === "mock") return <span className="fo-nil">{empty}</span>; // r6（项目方 12:4x“只看最新状态”）：示意值不再显示
  return <>{f.v ?? <span className="fo-nil">{empty}</span>}</>;
}
type OvEp = { number: number; title: string; state: string; stateTip?: string; stateDot: "need" | "ok" | null; shots: OvShot[] };

/** 总览（项目方 11:3x：“一行看一个 ep 就可以，图大一点，包裹镜头细节也上去……预览视频也需要”）：
 *  一行一集、片条撑满整行，帧宽 1440 下 ≥150px、1920 下 ≥200px（9:16），放不下横向滚动（可拖动）；
 *  镜号 · 时长 · 景别印在片边（片边字），片条下面一行只放镜头 · 运镜；状态只用片窗角圆点；悬停播放视频、默认出声（FILMUI r3 去掉人物头像；r6 fb-0002 改为出声）。 */
export function FilmOverview({ eps, onOpen, onCanvas, onMulti }: { eps: OvEp[]; onOpen: (id: string) => void; onCanvas: (id: string) => void; onMulti: (id: string, ev: MouseEvent) => void }) {
  const [vw, setVw] = useState(() => window.innerWidth);
  useEffect(() => {
    const f = () => setVw(window.innerWidth);
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);
  // FILMUI r4（项目方 12:0x“胶卷图片可以再大一点”）：S / M / L 三档，记住选择；S 档 1440 宽每帧 ≥200px、1920 宽 ≥267px（9:16）
  const [size, setSize] = useState<"S" | "M" | "L">(() => (["S", "M", "L"].includes(localStorage.getItem("film.size") ?? "") ? (localStorage.getItem("film.size") as "S" | "M" | "L") : "M"));
  const [sound] = useFilmSound(); // 开关在顶栏“系统状态”面板里（默认开）
  const [proj, setProj] = useState<{ ep: OvEp; i: number } | null>(null); // 浏览器要求先有一次点击才允许出声：每次打开页面点一下开关解锁
  useEffect(() => localStorage.setItem("film.size", size), [size]);
  const fw = Math.round(Math.max(200, vw * 0.139) * { S: 1, M: 1.25, L: 1.6 }[size]);
  const hFor = (n: number) => {
    const fill = (vw - 48 - 8) / (n + 0.75) - 2;   // 撑满整行时的帧宽（片头约 0.75 帧宽）
    const w = Math.max(fw, Math.min(fill, fw * 1.15));
    return Math.round(((w - 2) * 16) / 9);
  };
  return (
    <div className="fo">
      <div className="fo-mode">
        <span className="fo-hint">一行一集 · 悬停播放、左右移动拖时间 · 单击看详情 · 双击进画布 · 片条可拖动</span>
        <span className="fo-legend fo-icons">
          <MediaIcons m={{ video: "cur", last: false }} />视频（悬停播放，有声）
          <MediaIcons m={{ video: null, last: true }} />只有图 · 已有尾帧
        </span>
        <span className="fo-seg" role="group" aria-label="帧大小">{(["S", "M", "L"] as const).map((k) => <button key={k} className={size === k ? "on" : ""} onClick={() => setSize(k)}>{k}</button>)}</span>
        <span className="fo-legend">声音开关在顶栏“🔈 悬停出声”</span>
      </div>
      {proj && <Projector ep={proj.ep} start={proj.i} sound={sound} onClose={() => setProj(null)} />}
      <div className="fo-reels big">
        {eps.map((e) => {
          const H = hFor(e.shots.length);
          const w = Math.round((H * 9) / 16) + 2;
          return (
            <section key={e.number} className="fo-reel">
              <div className="fo-h">
                <span className="no">EP {pad2(e.number)}</span>
                <span className="ti">{e.title}</span>
                <button className="fo-play" onClick={() => setProj({ ep: e, i: 0 })} title="按顺序放整集：有视频放视频，没视频的镜用首帧按时长停留；← → 换镜 · 空格暂停 · Esc 退出">▶ 连播本集</button>
                <span className="st" title={e.stateTip}>
                  {e.stateDot && <i className={`sea-dot d-${e.stateDot}`} aria-hidden />}
                  <span>{e.state}</span>
                </span>
              </div>
              <DragScroll>
                <FilmStrip
                  H={H}
                  lead={`EP${pad2(e.number)}`}
                  kk={`EASTMAN 2383  ${keykode(e.number, 0)}`}
                  thumbW={480}
                  sound={sound}
                  frames={e.shots.map((x) => ({
                    key: x.id, src: x.img, cap: x.cap, dot: x.dot, empty: "未曝光",
                    ed: [`S${pad2(x.index)}`, x.secs.src === "api" ? x.secs.v : null, x.size.src === "api" ? x.size.v : null].filter(Boolean).join("  "),
                    hoverVideo: x.video ?? null, // r6：只放当前版本；旧版 / 示意视频只在详情抽屉的过程小图里看
                    media: { video: x.video ? "cur" : null, last: !!x.hasLast },
                    dotTip: x.dotTip ?? null,
                  }))}
                  onFrame={(i, ev) => (ev.shiftKey || ev.ctrlKey || ev.metaKey ? onMulti(e.shots[i].id, ev) : onOpen(e.shots[i].id))}
                  onFrameDbl={(i) => onCanvas(e.shots[i].id)}
                />
                <div className="fo-details" style={{ paddingLeft: Math.round(H * 0.42) }}>
                  {e.shots.map((x) => (
                    <div key={x.id} className="fo-d" style={{ width: w }} title={[x.lens.v ? `镜头 ${x.lens.v}` : "", x.light.v ? `灯光 ${x.light.v}` : "", x.faces.length ? `人物 ${x.faces.map((c) => c.name).join("、")}` : ""].filter(Boolean).join("\n")}>
                      {/* FILMUI r3（项目方 12:0x）：片条下面只留重要信息，一行最多两项：镜头 · 运镜；镜号 / 时长 / 景别印在片边，人物头像去掉 */}
                      <span className="mono"><F f={{ ...x.lens, v: x.lens.v ? x.lens.v.split(" · ")[0].replace(/^实拍\s*/, "") : x.lens.v }} /></span> · <F f={x.move} />
                    </div>
                  ))}
                </div>
              </DragScroll>
            </section>
          );
        })}
      </div>
    </div>
  );
}

/** 一集连播（放映机）：片头字卡 → 逐镜放映；画面下方印镜号 · 景别 · 时长和镜头 · 运镜，底部一排镜号标出放到哪 */
function Projector({ ep, start, sound, onClose }: { ep: OvEp; start: number; sound: boolean; onClose: () => void }) {
  const [i, setI] = useState(start);
  const [title, setTitle] = useState(true);
  const [paused, setPaused] = useState(false);
  const vref = useRef<HTMLVideoElement | null>(null);
  const s = ep.shots[i];
  const vid = s ? s.video ?? null : null;
  const next = () => setI((x) => (x + 1 < ep.shots.length ? x + 1 : (onClose(), x)));
  const prev = () => setI((x) => Math.max(0, x - 1));
  useEffect(() => { const t = setTimeout(() => setTitle(false), 1500); return () => clearTimeout(t); }, []);
  useEffect(() => {
    if (title || paused || !s || vid) return;
    const t = setTimeout(next, (parseFloat(s.secs.v ?? "") || 4) * 1000);
    return () => clearTimeout(t);
  }, [i, title, paused, vid]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const k = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") onClose();
      else if (ev.key === "ArrowRight") next();
      else if (ev.key === "ArrowLeft") prev();
      else if (ev.key === " ") { ev.preventDefault(); setPaused((p) => { const v = vref.current; if (v) (p ? v.play() : v.pause()); return !p; }); }
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  const lensShort = s?.lens.v ? s.lens.v.split(" · ")[0].replace(/^实拍\s*/, "") : null;
  return (
    <div className="fo-proj" role="dialog" aria-label="连播本集">
      <button className="fo-proj-x" onClick={onClose}>Esc 退出</button>
      {title ? (
        <div className="fo-proj-title"><span>EP {pad2(ep.number)}</span><b>{ep.title}</b></div>
      ) : s ? (
        <>
          <div className="fo-proj-media">
            {vid ? (
              <video key={s.id} ref={(v) => { vref.current = v; if (v) { v.defaultMuted = false; v.muted = !sound; v.play().catch(() => { v.muted = true; v.play().catch(() => undefined); }); } }} src={vid} playsInline onEnded={next} />
            ) : s.img ? (
              <img key={s.id} src={s.img} alt="" />
            ) : (
              <div className="fs-none">未曝光</div>
            )}
          </div>
          <div className="fo-proj-cap">
            <span className="mono">S{pad2(s.index)}{s.size.src === "api" && s.size.v ? `  ${s.size.v}` : ""}{s.secs.src === "api" && s.secs.v ? `  ${s.secs.v}` : ""}</span>
            <span>{[lensShort, s.move.src === "api" ? s.move.v : null].filter(Boolean).join(" · ")}</span>
            <span className="fo-proj-k">{vid ? "视频" : "首帧（视频未出，按时长停留）"}{paused ? " · 暂停" : ""}{vid && !sound ? " · 声音已关（顶栏开关）" : ""}</span>
          </div>
        </>
      ) : null}
      <div className="fo-proj-ticks">{ep.shots.map((x, j) => <button key={x.id} className={j === i && !title ? "on" : j < i ? "past" : ""} onClick={() => (setTitle(false), setI(j))}>S{pad2(x.index)}</button>)}</div>
    </div>
  );
}

/** 片条可以按住拖动横向滚动（拖动时不触发单击） */
function DragScroll({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const st = useRef<{ x: number; l: number; moved: boolean } | null>(null);
  return (
    <div ref={ref} className="fo-scroll"
      onMouseDown={(ev) => ref.current && (st.current = { x: ev.clientX, l: ref.current.scrollLeft, moved: false })}
      onMouseMove={(ev) => {
        const s0 = st.current;
        if (!s0 || !ref.current || !(ev.buttons & 1)) return;
        const dx = ev.clientX - s0.x;
        if (Math.abs(dx) > 4) s0.moved = true;
        ref.current.scrollLeft = s0.l - dx;
      }}
      onMouseUp={() => setTimeout(() => (st.current = null), 0)}
      onMouseLeave={() => (st.current = null)}
      onClickCapture={(ev) => st.current?.moved && (ev.stopPropagation(), ev.preventDefault())}>
      {children}
    </div>
  );
}
