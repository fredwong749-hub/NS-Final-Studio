import { useEffect, useMemo, useRef, useState } from "react";
import { thumb } from "../thumb";
import { useStudio, type FrameStage } from "../store";
import type { ShotDetail, Take } from "../types";
import { fmtTime, LAST_SOURCE_LABEL, segDiff, stageActive, stageTakes, usesGpu3Chain } from "../util";
import { JobBar, Score } from "./frames";
import { useFocusTrap } from "../ds/helpers";
import { LoadImg } from "../ds/LoadImg";

/** UIMASTER（UM-0531）：全屏看图是弹框——role=dialog + 焦点陷阱，关掉后焦点回到“看大图”按钮（和其它弹框同一套） */
function TrapDiv(props: React.HTMLAttributes<HTMLDivElement>) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref);
  return <div ref={ref} role="dialog" aria-modal="true" aria-label="全屏看图" tabIndex={-1} {...props} />;
}

const LABEL: Record<FrameStage, string> = { image: "首帧", last: "尾帧" };

interface Shown {
  url: string | null;
  take?: Take;
  /** 非版本来源（下一镜首帧 / 上传 / 视频抽帧） */
  srcLabel?: string;
}

// 版本链取法与镜头行版本条 / 检查器对比位共用（util.stageTakes / stageActive；gpu3 负责的镜头看 gpu3 链）
const takesOf = (d: ShotDetail | undefined, stage: FrameStage): Take[] => stageTakes(d, stage);
const activeOf = (d: ShotDetail | undefined): Partial<Record<FrameStage, number>> => ({ image: stageActive(d, "image"), last: stageActive(d, "last") });

/** 全屏看图：首帧|尾帧并排，←/→ 翻当前焦点阶段的版本；A/B 对比同阶段两个版本；设为当前一键 */
export function Viewer() {
  const st = useStudio();
  const { viewer, setViewer, details, summaryById, activate, episode, select, refreshShots } = st;
  const d = viewer ? details[viewer.shotId] : undefined;
  const s = viewer ? summaryById.get(viewer.shotId) : undefined;
  // 每阶段当前显示的版本号（pair 模式）；ab 模式 A/B
  const [pick, setPick] = useState<Partial<Record<FrameStage, number>>>({});
  const [ab, setAb] = useState<{ a: number | null; b: number | null }>({ a: null, b: null });
  const [diff, setDiff] = useState(false);
  const key = viewer ? `${viewer.shotId}|${viewer.stage}|${viewer.mode}|${viewer.b ?? ""}` : "";
  const lastKey = useRef("");

  // 封板修复：每个镜头只自动拉一次（失败不再循环重拉）
  const tried = useRef(new Set<string>());
  useEffect(() => {
    if (!viewer || details[viewer.shotId] || tried.current.has(viewer.shotId)) return;
    tried.current.add(viewer.shotId);
    void refreshShots([viewer.shotId]);
  }, [viewer, details, refreshShots]);

  const takes = useMemo(() => ({ image: takesOf(d, "image"), last: takesOf(d, "last") }), [d]);
  const active = useMemo(() => activeOf(d), [d]);
  // gpu3 的当前版本由 gpu3 决定：画布只看 / 对比
  const readOnly = usesGpu3Chain(d); // UXF1：只有出片用 gpu3 链时才只读

  // 打开 / 切镜 / 切模式时重置选择
  useEffect(() => {
    if (!viewer || !d || lastKey.current === key) return;
    lastKey.current = key;
    setPick({});
    const list = takes[viewer.stage];
    const a = active[viewer.stage] ?? list.at(-1)?.n ?? null;
    const others = list.filter((t) => t.n !== a);
    const b = viewer.b ?? others.at(-1)?.n ?? null;
    setAb({ a, b });
  }, [viewer, d, key, takes, active]);

  const order = episode?.shots.map((x) => x.id) ?? [];

  // 键盘：本组件打开时独占（主 keymap 见 viewer 就让路）
  const stateRef = useRef({ viewer, takes, pick, ab, active, d, readOnly });
  stateRef.current = { viewer, takes, pick, ab, active, d, readOnly };
  useEffect(() => {
    if (!viewer) return;
    const h = (e: KeyboardEvent) => {
      const { viewer: v, takes: tk, pick: pk, ab: AB, active: act, readOnly: ro } = stateRef.current;
      if (!v) return;
      const k = e.key;
      const step = (dir: 1 | -1) => {
        const list = tk[v.stage];
        if (!list.length) return;
        if (v.mode === "ab") {
          const others = list.filter((t) => t.n !== AB.a);
          const i = others.findIndex((t) => t.n === AB.b);
          const n = others[Math.min(others.length - 1, Math.max(0, i + dir))];
          if (n) setAb({ ...AB, b: n.n });
        } else {
          const cur = pk[v.stage] ?? act[v.stage] ?? list.at(-1)!.n;
          const i = list.findIndex((t) => t.n === cur);
          const n = list[Math.min(list.length - 1, Math.max(0, i + dir))];
          if (n) setPick({ ...pk, [v.stage]: n.n });
        }
      };
      if (k === "Escape") setViewer(null);
      else if (k === "ArrowLeft") step(-1);
      else if (k === "ArrowRight") step(1);
      else if (k === "Tab") setViewer({ ...v, stage: v.stage === "image" ? "last" : "image", b: null });
      else if (k === "c" || k === "C") setViewer({ ...v, mode: v.mode === "ab" ? "pair" : "ab", b: null });
      else if (k === "ArrowUp" || k === "ArrowDown") {
        const i = order.indexOf(v.shotId);
        const n = order[i + (k === "ArrowUp" ? -1 : 1)];
        if (n) {
          select(n);
          setViewer({ ...v, shotId: n, b: null });
        }
      } else if (k === "Enter") {
        const n = v.mode === "ab" ? AB.b : pk[v.stage];
        if (!ro && n != null && n !== act[v.stage]) void activate(v.shotId, v.stage, n);
      } else return;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [viewer, setViewer, activate, order, select]);

  if (!viewer) return null;
  const id = viewer.shotId;

  const shownPair = (stage: FrameStage): Shown => {
    const list = takes[stage];
    const n = pick[stage] ?? active[stage];
    const t = list.find((x) => x.n === n);
    if (t) return { url: t.url, take: t };
    if (stage === "image") return { url: s?.first_frame ?? null };
    return { url: s?.last_frame_target ?? null, srcLabel: s?.last_frame_source ? LAST_SOURCE_LABEL[s.last_frame_source] : undefined };
  };
  const byN = (stage: FrameStage, n: number | null): Shown => {
    const t = takes[stage].find((x) => x.n === n);
    return t ? { url: t.url, take: t } : { url: null };
  };

  const panels: { key: string; stage: FrameStage; shown: Shown; role: string; focus: boolean }[] =
    viewer.mode === "pair"
      ? (["image", "last"] as FrameStage[]).map((stage) => ({ key: stage, stage, shown: shownPair(stage), role: LABEL[stage], focus: viewer.stage === stage }))
      : [
          { key: "a", stage: viewer.stage, shown: byN(viewer.stage, ab.a), role: `A · ${LABEL[viewer.stage]}`, focus: false },
          { key: "b", stage: viewer.stage, shown: byN(viewer.stage, ab.b), role: `B · ${LABEL[viewer.stage]}`, focus: true },
        ];

  const stripStage = viewer.stage;
  const strip = takes[stripStage];
  const stripSel = viewer.mode === "ab" ? ab.b : (pick[stripStage] ?? active[stripStage]);
  const live = st.liveJob(id, stripStage);
  const pa = viewer.mode === "ab" ? panels[0].shown.take : undefined;
  const pb = viewer.mode === "ab" ? panels[1].shown.take : undefined;

  return (
    <TrapDiv className="viewer" onClick={() => setViewer(null)}>
      <div className="vw-top" onClick={(e) => e.stopPropagation()}>
        <b className="vw-id">{id}</b>
        <span className="muted">{s ? `${s.camera.size || ""} ${s.camera.move || ""}`.trim() : ""}</span>
        <div className="seg">
          <button className={viewer.mode === "pair" ? "on" : ""} onClick={() => setViewer({ ...viewer, mode: "pair", b: null })}>
            首帧 | 尾帧
          </button>
          <button className={viewer.mode === "ab" ? "on" : ""} onClick={() => setViewer({ ...viewer, mode: "ab", b: null })} disabled={takes[viewer.stage].length < 2} title="同一阶段两个版本对比（C）">
            A/B 对比{LABEL[viewer.stage]}
          </button>
        </div>
        {viewer.mode === "ab" && (
          <div className="seg">
            {(["image", "last"] as FrameStage[]).map((stg) => (
              <button key={stg} className={viewer.stage === stg ? "on" : ""} disabled={takes[stg].length < 2} onClick={() => setViewer({ ...viewer, stage: stg, b: null })}>
                {LABEL[stg]}（{takes[stg].length}）
              </button>
            ))}
          </div>
        )}
        <span className="grow" />
        {readOnly && !s?.explicit_hold && (
          <button
            className="btn"
            disabled={!!st.liveJob(id, viewer.stage) || (viewer.stage === "last" && !s?.first_frame)}
            onClick={() => st.requestGpu3(id, viewer.stage === "image" ? "image" : "last")}
            title="gpu3 负责此镜：写进 gpu3 重渲队列；新 take 到了会出现在下面的版本条（虚线格 = 等待中）"
          >
            请视频卡重出{LABEL[viewer.stage]}
          </button>
        )}
        <span className="vw-keys muted">
          <kbd>←</kbd>
          <kbd>→</kbd> 翻版本 · <kbd>Tab</kbd> 切首/尾 · <kbd>C</kbd> A/B · <kbd>Enter</kbd> 设为当前 · <kbd>↑</kbd>
          <kbd>↓</kbd> 换镜
        </span>
        <button className="btn" onClick={() => setViewer(null)}>
          关闭 Esc
        </button>
      </div>

      <div className="vw-stage" onClick={(e) => e.stopPropagation()}>
        {!d && (st.detailErr[id] ? <div className="warn">{id} 加载失败：{st.detailErr[id]}</div> : <div className="muted">加载 {id}…</div>)}
        {d &&
          panels.map((p) => {
            const t = p.shown.take;
            const isActive = t ? active[p.stage] === t.n : !!p.shown.url;
            return (
              <figure
                key={p.key}
                className={`vw-panel${p.focus ? " focus" : ""}`}
                onClick={() => viewer.mode === "pair" && setViewer({ ...viewer, stage: p.stage })}
              >
                <figcaption>
                  <b>{p.role}</b>
                  {t && <span className="chip chip-dark">#{t.n}</span>}
                  {p.shown.srcLabel && <span className="chip chip-dark">{p.shown.srcLabel}</span>}
                  {isActive ? <span className="chip chip-ok">当前</span> : t && <span className="chip chip-accent">候选</span>}
                  {/* UXF1 #6：定稿 / 坏图与审片行同一份数据（takes.json locked + take.bad） */}
                  {/* UXF4（审查 N1）：自动测试定稿单独标（查看器只看首帧 / 尾帧） */}
                  {t && (t as { locked?: boolean | null }).locked &&
                    ((d.takes as { locked_by?: Record<string, { by?: string; n?: number } | null> }).locked_by?.[p.stage]?.by === "auto" &&
                    (d.takes as { locked_by?: Record<string, { by?: string; n?: number } | null> }).locked_by?.[p.stage]?.n === t.n ? (
                      <span className="chip chip-warn" title="整集出片“自动测试定稿”出的，你还没复审：不算已定稿">自动定稿·待复审</span>
                    ) : (d.takes as { locked_by?: Record<string, { by?: string; n?: number } | null> }).locked_by?.[p.stage]?.by === "delegate" &&
                      (d.takes as { locked_by?: Record<string, { by?: string; n?: number } | null> }).locked_by?.[p.stage]?.n === t.n ? (
                      /* W18b P1-6：首帧超时代选（L-142）——不算你定稿，可改：换版本 / 解锁走原定稿入口 */
                      <span className="chip chip-warn" title="出图检测通过后你 30 分钟没定，系统按契约分代选（L-142）：不算你定稿，可改（换一版定稿或解锁）">系统代选·可改</span>
                    ) : (
                      <span className="chip chip-ok">已定稿</span>
                    ))}
                  {t?.bad && <span className="chip chip-bad" style={{ background: "var(--c-bad)", color: "#fff" }} title={t.bad}>坏图</span>}
                  <Score sc={t?.score} />
                  {t?.stale && t.stale.length > 0 && <span className="chip chip-warn" title={t.stale.join("、")}>过期</span>}
                  <span className="grow" />
                  {t && !isActive && readOnly && (
                    <span className="chip chip-src-gpu3" title="gpu3 负责此镜：当前版本由 gpu3 决定（画布设为当前的接口待 gpu3 侧提供：POST /api/shots/{id}/gpu3-activate）">
                      gpu3 版本（只读）
                    </span>
                  )}
                  {t && !isActive && !readOnly && (
                    <button
                      className="btn primary"
                      disabled={!!t.qc?.nudity || !!t.bad}
                      title={t.bad ? `${t.bad}，不能设为当前` : t.qc?.nudity ? "裸露质检未过，不能设为当前" : "Enter"}
                      onClick={(e) => {
                        e.stopPropagation();
                        void activate(id, p.stage, t.n);
                      }}
                    >
                      设为当前
                    </button>
                  )}
                </figcaption>
                <div className="vw-img">
                  {p.shown.url ? <LoadImg src={p.shown.url} alt={p.role} /> : <div className="vw-empty">{`还没有${LABEL[p.stage]}`}</div>}
                </div>
                <div className="vw-meta muted">
                  {t ? (
                    <>
                      种子 {t.seed} · {fmtTime(t.created_at)}
                      {t.seconds != null && ` · 用时 ${Math.round(t.seconds)}s`}
                      {t.source && ` · ${LAST_SOURCE_LABEL[t.source] ?? t.source}`}
                    </>
                  ) : (
                    p.shown.srcLabel && `来源：${p.shown.srcLabel}（不是生成版本）`
                  )}
                </div>
              </figure>
            );
          })}
      </div>

      <div className="vw-strip" onClick={(e) => e.stopPropagation()}>
        <span className="vw-strip-label">
          {LABEL[stripStage]}版本 {strip.length}
          {viewer.mode === "ab" ? "（点选 = B，Shift+点 = A）" : ""}
        </span>
        {strip.map((t) => (
          <button
            key={t.n}
            className={`vw-thumb${t.n === stripSel ? " on" : ""}${active[stripStage] === t.n ? " cur" : ""}${viewer.mode === "ab" && t.n === ab.a ? " a" : ""}`}
            onClick={(e) => {
              if (viewer.mode === "ab") setAb(e.shiftKey ? { ...ab, a: t.n } : { ...ab, b: t.n });
              else setPick({ ...pick, [stripStage]: t.n });
            }}
            title={`#${t.n}${active[stripStage] === t.n ? "（当前）" : ""}${t.bad ? `（${t.bad}）` : ""}`}
          >
            {t.url ? <img src={thumb(t.url, 240) ?? t.url} alt="" /> : <span>缺</span>}
            <i>#{t.n}{t.bad ? " 坏图" : ""}</i>
          </button>
        ))}
        {live && (
          <div className="vw-thumb pending">
            <JobBar live={live} compact />
          </div>
        )}
        {viewer.mode === "ab" && pa && pb && (
          <button className="btn ghost" onClick={() => setDiff((x) => !x)}>
            {diff ? "隐藏" : "看"}提示词差异
          </button>
        )}
      </div>
      {viewer.mode === "ab" && diff && pa && pb && (
        <div className="vw-diff" onClick={(e) => e.stopPropagation()}>
          {pa.prompt === pb.prompt ? (
            <span className="muted">两个版本提示词相同（只换了种子）</span>
          ) : (
            segDiff(pa.prompt, pb.prompt).map((x, i) => (
              <span key={i} className={`d-${x.op}`}>
                {x.text}
              </span>
            ))
          )}
        </div>
      )}
    </TrapDiv>
  );
}
