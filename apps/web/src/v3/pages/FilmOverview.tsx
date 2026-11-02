// UIRSI r46 · L-114（项目方 AskUserQuestion 选“A 放映室片条”，FILMUI 稿 data/review_pages/filmui/a.html）：全剧总览的电影胶片样式。
// 只在开关打开时用（html.ui-film，见 v3/uiStyle.ts）；默认仍是现有总览。功能不删：单击一帧 = 右侧详情抽屉（同现有），双击 = 进画布这一镜，
// Ctrl / Shift 点 = 多选；悬停 = 大图放大镜（图高 420px + 片边信息：集 · 镜 · 景别 · 时长 · 实拍 / 计划镜头，D-LENS）。
// 片条按真实 35mm 比例画：片基黑、上下 KS 齿孔（竖幅横走 3 齿 / 帧）、片边暖灰小字（镜号），片头竖写 EPxx。
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { thumb } from "../../thumb";

export type FilmFrame = { key: string; src: string | null; kind?: "img" | "video"; ed?: string; empty?: string; cap?: string; dot?: "run" | "need" | "ok" | null };

const pad2 = (n: number) => String(n).padStart(2, "0");
/** 齿孔（与 FILMUI film_common.js perf() 同一套比例） */
export function perf(pitch: number, rail: number, hole: string, side: "top" | "bottom") {
  const H = rail / 0.203;
  const w = Math.max(3, 0.112 * H), h = Math.max(2.2, 0.0795 * H), rx = Math.max(0.6, 0.02 * H);
  const y = side === "top" ? rail - h - 0.03 * H : 0.03 * H;
  const x = (pitch - w) / 2;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${pitch}" height="${rail}"><rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}" rx="${rx.toFixed(2)}" fill="${hole}"/></svg>`;
  return `url('data:image/svg+xml,${encodeURIComponent(svg)}')`;
}
export const keykode = (n: number, shot: number) => `KN ${pad2(n)} ${String(1000 + n * 37).padStart(4, "0")} ${String(shot * 16 + 12).padStart(4, "0")}+00`;

export function FilmStrip({ frames, H, lead, kk, onFrame, onFrameDbl, onEnter, onMove, onLeave, thumbW = 240 }: {
  frames: FilmFrame[]; H: number; lead?: string; kk?: string; thumbW?: number;
  onFrame?: (i: number, ev: MouseEvent) => void; onFrameDbl?: (i: number) => void;
  onEnter?: (i: number, ev: MouseEvent) => void; onMove?: (ev: MouseEvent) => void; onLeave?: () => void;
}) {
  // 真实比例 rail = 0.203 × 画高；大片条（单集每格 ≥240px）时齿孔会过大抢画面 → 上限 44px（齿孔按 rail 等比缩）
  const rail = Math.round(Math.min(H * 0.203, 44));
  const fw = Math.round((H * 9) / 16) + 2;
  const pitch = fw / 3;
  const leadW = lead ? Math.round(H * 0.42) : 0;
  const ed = Math.max(8.5, Math.min(10, H * 0.06));
  const hole = H > 200 ? "#1e1c1a" : "#2b2825";
  return (
    <div className="fs-strip" style={{ height: H + rail * 2 }}>
      <div className="fs-rail t" style={{ height: rail, backgroundImage: perf(pitch, rail, hole, "top"), backgroundPosition: `${leadW}px 0` }} />
      <div className="fs-rail b" style={{ height: rail, backgroundImage: perf(pitch, rail, hole, "bottom"), backgroundPosition: `${leadW}px 0` }} />
      {kk && <span className="fs-kk" style={{ left: leadW + 6, top: Math.max(1, rail * 0.12), fontSize: ed - 1 }}>{kk}</span>}
      {lead && (
        <div className="fs-lead" style={{ width: leadW }}>
          <span>{lead}</span>
        </div>
      )}
      {frames.map((f, i) => (
        <div key={f.key} className="fs-fr" style={{ width: fw }} onClick={(ev) => onFrame?.(i, ev)} onDoubleClick={() => onFrameDbl?.(i)}
          onMouseEnter={(ev) => onEnter?.(i, ev)} onMouseMove={onMove} onMouseLeave={onLeave} title={f.cap}>
          <div className="fs-img" style={{ top: rail, height: H }}>
            {f.kind === "video" && f.src ? (
              <video src={`${f.src}#t=0.3`} preload="metadata" muted playsInline />
            ) : f.src ? (
              <img src={thumb(f.src, thumbW) ?? f.src} alt="" loading="lazy" decoding="async" draggable={false} data-zoom-label={f.cap} />
            ) : (
              <div className="fs-none">{f.empty ?? ""}</div>
            )}
            {f.dot && <i className={`sea-dot d-${f.dot}${f.dot === "run" ? " is-rendering" : ""}`} aria-hidden />}
          </div>
          {f.ed && (
            <div className="fs-ed" style={{ bottom: Math.max(1, rail * 0.12), fontSize: ed }}>
              {f.ed}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

type OvShot = { id: string; index: number; img: string | null; cap: string; dot: "run" | "need" | "ok" | null };
type OvEp = { number: number; title: string; state: string; stateTip?: string; stateDot: "need" | "ok" | null; shots: OvShot[] };

/** 总览：一屏（两列 × 五行，每集一条片）/ 大图（一列）；悬停放大镜 */
export function FilmOverview({ eps, onOpen, onCanvas, onMulti }: { eps: OvEp[]; onOpen: (id: string) => void; onCanvas: (id: string) => void; onMulti: (id: string, ev: MouseEvent) => void }) {
  const [big, setBig] = useState(() => {
    try {
      return localStorage.getItem("film.big") === "1";
    } catch {
      return false;
    }
  });
  const [vw, setVw] = useState(() => window.innerWidth);
  const [loupe, setLoupe] = useState<{ src: string; cap: string } | null>(null);
  const L = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const f = () => setVw(window.innerWidth);
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);
  // r46 亲审：片条按列宽自适应帧大小（每集按自己的镜数算，撑满列宽）；一屏模式再受屏高限制（五行放得下）
  const hFor = (n: number) => {
    const N = Math.max(n, 6);
    const colW = big ? vw - 48 - 8 : (vw - 48 - 32 - 8) / 2;
    const byW = (colW - 2 * N) / (0.42 + N * 0.5625);
    return Math.floor(big ? Math.min(260, byW) : Math.max(70, byW));   // 总调度亲审：按列宽撑满（屏高放不下五行时页面滚动）
  };
  const move = (ev: MouseEvent) => {
    const el = L.current;
    if (!el) return;
    const w = el.offsetWidth || 250, h = el.offsetHeight || 460;
    let x = ev.clientX + 24;
    if (x + w > window.innerWidth - 12) x = ev.clientX - w - 24;
    const y = Math.max(56, Math.min(window.innerHeight - h - 12, ev.clientY - h / 2));
    el.style.left = `${x}px`;
    el.style.top = `${y}px`;
  };
  return (
    <div className="fo">
      <div className="fo-mode">
        <span className="fo-hint">悬停看大图 · 单击看详情 · 双击进画布</span>
        <button type="button" className={big ? "" : "on"} onClick={() => (setBig(false), localStorage.setItem("film.big", "0"))}>一屏</button>
        <button type="button" className={big ? "on" : ""} onClick={() => (setBig(true), localStorage.setItem("film.big", "1"))}>大图</button>
      </div>
      <div className={`fo-reels${big ? " big" : ""}`}>
        {eps.map((e) => (
          <section key={e.number} className="fo-reel">
            <div className="fo-h">
              <span className="no">EP {pad2(e.number)}</span>
              <span className="ti">{e.title}</span>
              <span className="st" title={e.stateTip}>
                {e.stateDot && <i className={`sea-dot d-${e.stateDot}`} aria-hidden />}
                <span>{e.state}</span>
              </span>
            </div>
            <div className="fo-scroll">
              <FilmStrip
                H={hFor(e.shots.length)}
                lead={`EP${pad2(e.number)}`}
                thumbW={big ? 240 : 160}
                frames={e.shots.map((s) => ({ key: s.id, src: s.img, ed: pad2(s.index), cap: s.cap, dot: s.dot, empty: "未曝光" }))}
                onFrame={(i, ev) => (ev.shiftKey || ev.ctrlKey || ev.metaKey ? onMulti(e.shots[i].id, ev) : onOpen(e.shots[i].id))}
                onFrameDbl={(i) => onCanvas(e.shots[i].id)}
                onEnter={(i, ev) => {
                  const s = e.shots[i];
                  if (!s.img) return setLoupe(null);
                  setLoupe({ src: s.img, cap: s.cap });
                  requestAnimationFrame(() => move(ev));
                }}
                onMove={move}
                onLeave={() => setLoupe(null)}
              />
            </div>
          </section>
        ))}
      </div>
      <div ref={L} className="fo-loupe" style={{ display: loupe ? "block" : "none" }} aria-hidden>
        {loupe && <img src={thumb(loupe.src, 480) ?? loupe.src} alt="" />}
        <div className="cap">{loupe?.cap}</div>
      </div>
    </div>
  );
}
