// UIRSI r46 · L-114（项目方 AskUserQuestion 选“A 放映室片条”，FILMUI 稿 data/review_pages/filmui/a.html）：全剧总览的电影胶片样式。
// 只在开关打开时用（html.ui-film，见 v3/uiStyle.ts）；默认仍是现有总览。功能不删：单击一帧 = 右侧详情抽屉（同现有），双击 = 进画布这一镜，
// Ctrl / Shift 点 = 多选；悬停 = 大图放大镜（图高 420px + 片边信息：集 · 镜 · 景别 · 时长 · 实拍 / 计划镜头，D-LENS）。
// 片条按真实 35mm 比例画：片基黑、上下 KS 齿孔（竖幅横走 3 齿 / 帧）、片边暖灰小字（镜号），片头竖写 EPxx。
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { thumb } from "../../thumb";

export type FilmFrame = { key: string; src: string | null; kind?: "img" | "video"; ed?: string; empty?: string; cap?: string; dot?: "run" | "need" | "ok" | null; hoverVideo?: string | null; tag?: string | null; tagMock?: boolean };

const pad2 = (n: number) => String(n).padStart(2, "0");
/** 真实 35mm 正片几何（FILMUI r3，项目方 12:0x“不太像胶片”；参照 Wikimedia Commons 放映拷贝近照，见 docs/research/filmui/refs.md §6）。
 *  画高 H 对应 24.9 mm；片边 rail = 5.05 mm = 0.203H，其中：外侧片边 2.01 mm（0.081H，印片边字 / KeyKode）、KS 齿孔 1.98 × 2.79 mm（0.0795H × 0.112H，
 *  圆角 0.5 mm）、齿孔到画面 1.06 mm（0.043H）；齿距 4.74 mm（0.19H），竖幅横走 3 齿 / 帧。齿孔里透出背后的灯光（暖白渐变），片基深灰褐。 */
export function perf(pitch: number, rail: number, hole: string, side: "top" | "bottom") {
  const k = rail / 0.203;
  const w = Math.max(3, 0.112 * k), h = Math.max(2.2, 0.0795 * k), rx = Math.max(0.7, 0.022 * k);
  const outer = 0.081 * k;
  const y = side === "top" ? outer : rail - outer - h;
  const x = (pitch - w) / 2;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${pitch.toFixed(3)}" height="${rail}"><defs><linearGradient id="l" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${hole}"/><stop offset="1" stop-color="#9d9483"/></linearGradient></defs><rect x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${w.toFixed(2)}" height="${h.toFixed(2)}" rx="${rx.toFixed(2)}" fill="url(#l)" stroke="rgba(0,0,0,.55)" stroke-width=".7"/></svg>`;
  return `url('data:image/svg+xml,${encodeURIComponent(svg)}')`;
}
export const keykode = (n: number, shot: number) => `KN ${pad2(n)} ${String(1000 + n * 37).padStart(4, "0")} ${String(shot * 16 + 12).padStart(4, "0")}+00`;
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
  return { w: Math.ceil(x), svg: `url('data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${Math.ceil(x)}" height="${h}" fill="#d9ccb4">${bars}</svg>`)}')` };
}

export function FilmStrip({ frames, H, lead, kk, onFrame, onFrameDbl, onEnter, onMove, onLeave, thumbW = 240 }: {
  frames: FilmFrame[]; H: number; lead?: string; kk?: string; thumbW?: number;
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
  return (
    <div className="fs-strip" style={{ height: H + rail * 2 }}>
      <div className="fs-rail t" style={{ height: rail, backgroundImage: perf(pitch, rail, "#e4dccb", "top"), backgroundPosition: `${leadW}px 0` }} />
      <div className="fs-rail b" style={{ height: rail, backgroundImage: perf(pitch, rail, "#e4dccb", "bottom"), backgroundPosition: `${leadW}px 0` }} />
      {kk && <span className="fs-kk" style={{ left: leadW + pitch * 0.5, top: (outer - ed) / 2, fontSize: ed, lineHeight: `${ed}px` }}>{kk}</span>}
      {kk && bc && <span className="fs-bc" style={{ left: leadW + pitch * 0.5 + kk.length * ed * 0.62 + 10, top: (outer - bh) / 2, width: bc.w, height: bh, backgroundImage: bc.svg }} />}
      {lead && (
        <div className="fs-lead" style={{ width: leadW }}>
          <span style={{ fontSize: Math.max(9, Math.min(12, H * 0.05)) }}>{lead}</span>
        </div>
      )}
      {frames.map((f, i) => (
        <div key={f.key} className="fs-fr" style={{ width: fw }} onClick={(ev) => onFrame?.(i, ev)} onDoubleClick={() => onFrameDbl?.(i)}
          onMouseEnter={(ev) => (setHov(i), onEnter?.(i, ev))} onMouseMove={onMove} onMouseLeave={() => (setHov(null), onLeave?.())} title={f.cap}>
          <div className="fs-band" style={{ top: rail, height: H }} />
          <div className="fs-img" style={{ top: rail, height: H, left: fl, right: fl, borderRadius: rad }}>
            {f.kind === "video" && f.src ? (
              <video src={`${f.src}#t=0.3`} preload="metadata" muted playsInline />
            ) : f.src ? (
              <img src={thumb(f.src, thumbW) ?? f.src} alt="" loading="lazy" decoding="async" draggable={false} data-zoom-label={f.cap} />
            ) : (
              <div className="fs-none">{f.empty ?? ""}</div>
            )}
            {/* r46（项目方 11:3x：“预览视频也需要”）：悬停静音循环播放这一镜的视频 */}
            {f.hoverVideo && hov === i && <video className="fs-hv" src={f.hoverVideo} autoPlay muted loop playsInline />}
            {f.tag && <span className={`fs-tag${f.tagMock ? " mock" : ""}`}>{f.tag}</span>}
            {f.dot && <i className={`sea-dot d-${f.dot}${f.dot === "run" ? " is-rendering" : ""}`} aria-hidden />}
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
  video: string | null; videoOld: string | null; videoMock?: string | null;
};
function F({ f, empty = "—" }: { f: Fv; empty?: string }) {
  if (f.src === "mock") return <em className="fo-mock" title="示意值（mock）：接口还没有这个字段，有了会自动替换">示意 · {f.v ?? empty}</em>;
  return <>{f.v ?? <span className="fo-nil">{empty}</span>}</>;
}
type OvEp = { number: number; title: string; state: string; stateTip?: string; stateDot: "need" | "ok" | null; shots: OvShot[] };

/** 总览（项目方 11:3x：“一行看一个 ep 就可以，图大一点，包裹镜头细节也上去……预览视频也需要”）：
 *  一行一集、片条撑满整行，帧宽 1440 下 ≥150px、1920 下 ≥200px（9:16），放不下横向滚动（可拖动）；
 *  镜号 · 时长 · 景别印在片边（片边字），片条下面一行只放镜头 · 运镜；状态只用片窗角圆点；悬停静音循环播放视频（FILMUI r3 去掉人物头像）。 */
export function FilmOverview({ eps, onOpen, onCanvas, onMulti }: { eps: OvEp[]; onOpen: (id: string) => void; onCanvas: (id: string) => void; onMulti: (id: string, ev: MouseEvent) => void }) {
  const [vw, setVw] = useState(() => window.innerWidth);
  useEffect(() => {
    const f = () => setVw(window.innerWidth);
    window.addEventListener("resize", f);
    return () => window.removeEventListener("resize", f);
  }, []);
  const fw = Math.max(150, Math.round(vw * 0.1042));            // 1440 → 150、1920 → 200
  const hFor = (n: number) => {
    const fill = (vw - 48 - 8) / (n + 0.75) - 2;   // 撑满整行时的帧宽（片头约 0.75 帧宽）
    const w = Math.max(fw, Math.min(fill, fw * 1.6));
    return Math.round(((w - 2) * 16) / 9);
  };
  return (
    <div className="fo">
      <div className="fo-mode">
        <span className="fo-hint">一行一集 · 悬停播放视频 · 单击看详情 · 双击进画布 · 片条可左右拖动</span>
        <span className="fo-legend"><em className="fo-mock">示意</em> = 接口还没有的字段（mock），有了自动替换</span>
      </div>
      <div className="fo-reels big">
        {eps.map((e) => {
          const H = hFor(e.shots.length);
          const w = Math.round((H * 9) / 16) + 2;
          return (
            <section key={e.number} className="fo-reel">
              <div className="fo-h">
                <span className="no">EP {pad2(e.number)}</span>
                <span className="ti">{e.title}</span>
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
                  frames={e.shots.map((x) => ({
                    key: x.id, src: x.img, cap: x.cap, dot: x.dot, empty: "未曝光",
                    ed: [`S${pad2(x.index)}`, x.secs.src === "api" ? x.secs.v : null, x.size.src === "api" ? x.size.v : null].filter(Boolean).join("  "),
                    hoverVideo: x.video ?? x.videoOld ?? x.videoMock ?? null,
                    tag: x.video ? null : x.videoOld ? "旧版视频" : x.videoMock ? "示意视频" : null,
                    tagMock: !x.video && !x.videoOld && !!x.videoMock,
                  }))}
                  onFrame={(i, ev) => (ev.shiftKey || ev.ctrlKey || ev.metaKey ? onMulti(e.shots[i].id, ev) : onOpen(e.shots[i].id))}
                  onFrameDbl={(i) => onCanvas(e.shots[i].id)}
                />
                <div className="fo-details" style={{ paddingLeft: Math.round(H * 0.42) }}>
                  {e.shots.map((x) => (
                    <div key={x.id} className="fo-d" style={{ width: w }} title={[x.light.v ? `灯光 ${x.light.v}` : "", x.faces.length ? `人物 ${x.faces.map((c) => c.name).join("、")}` : ""].filter(Boolean).join("\n")}>
                      {/* FILMUI r3（项目方 12:0x）：片条下面只留重要信息，一行最多两项：镜头 · 运镜；镜号 / 时长 / 景别印在片边，人物头像去掉 */}
                      <span className="mono"><F f={x.lens} /></span> · <F f={x.move} />
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
