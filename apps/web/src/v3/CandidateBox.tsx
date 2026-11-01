// UIRSI（BE-5 配套）：候选版本看图器——大图 + 全部版本缩略图 + 一键“用这张”（10 秒撤销）+ 新旧对比（并排 / 滑块）。
// 旧配方 / 新配方各一版时默认就是对比；暂定、规则过期只做角标。
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { MediaCompare } from "../ds/MediaPlayer";
import { thumb } from "../thumb";
import { useStudio } from "../store";
import { candLabel, passed, pickTake, plainLabel, type Cand, type CandStage } from "./candidates";
import "./candidates.css";

export function CandidateBox({ shot, stage, data, start, stale, onClose }: { shot: string; stage: "image" | "last"; data: CandStage; start?: number; stale?: string[]; onClose: () => void }) {
  const st = useStudio();
  const takes = data.takes;
  const [cur, setCur] = useState<number>(start ?? takes[takes.length - 1]?.n ?? 1);
  const labels = [...new Set(takes.map((t) => t.label).filter(Boolean))];
  const [cmp, setCmp] = useState<boolean>(labels.length >= 2);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key === "Escape") (e.stopImmediatePropagation(), onClose());
      const i = takes.findIndex((t) => t.n === cur);
      if (e.key === "ArrowRight" && i < takes.length - 1) setCur(takes[i + 1].n);
      if (e.key === "ArrowLeft" && i > 0) setCur(takes[i - 1].n);
    };
    window.addEventListener("keydown", k, true);
    return () => window.removeEventListener("keydown", k, true);
  }, [cur, takes, onClose]);
  const t = takes.find((x) => x.n === cur) ?? takes[takes.length - 1];
  if (!t) return null;
  // 对比：新配方 vs 旧配方（各取最新一版）；没有两种标签就拿当前选中的和前一版
  const byLabel = (l: string) => [...takes].reverse().find((x) => x.label === l);
  const pair: [Cand, Cand] | null =
    labels.length >= 2 ? [byLabel(labels[0] as string)!, byLabel(labels[1] as string)!] : takes.length >= 2 ? [takes[Math.max(0, takes.indexOf(t) - 1)], t] : null;
  const name = `${shot.split("-")[1]} ${stage === "image" ? "首帧" : "尾帧"}`;
  const use = async (x: Cand) => {
    setBusy(true);
    const ok = await pickTake(shot, stage, x.n, data.active, () => void st.refreshAfter([shot]), st.notify);
    setBusy(false);
    if (ok) onClose();
  };
  return createPortal(
    <div className="cb-scrim cb-viewer" onMouseDown={(e) => e.target === e.currentTarget && onClose()} role="dialog" aria-label={`${name} 候选版本`}>
      <div className="cb-box">
        <header className="cb-head">
          <b>{name}</b>
          <span className="cb-sub">
            {takes.length} 个候选{data.active != null ? ` · 当前用的是 #${data.active}` : " · 还没选定用哪张"}
          </span>
          <span className="cb-grow" />
          {pair && (
            <button type="button" className={`ds-btn sm${cmp ? " primary" : ""}`} onClick={() => setCmp((v) => !v)}>
              {cmp ? "看单张" : "对比"}
            </button>
          )}
          <button type="button" className="ds-btn sm" onClick={onClose}>
            关闭 Esc
          </button>
        </header>
        <div className="cb-stage">
          {cmp && pair ? (
            <MediaCompare
              kind="image"
              a={{ src: pair[0].url, label: `#${pair[0].n} · ${candLabel(pair[0]) || "候选"}` }}
              b={{ src: pair[1].url, label: `#${pair[1].n} · ${candLabel(pair[1]) || "候选"}` }}
              onPick={passed(pair[0]) && passed(pair[1]) ? (k) => void use(k === "a" ? pair[0] : pair[1]) : undefined}
              picked={data.active === pair[0].n ? "a" : data.active === pair[1].n ? "b" : null}
            />
          ) : (
            <figure className="cb-fig">
              <img src={t.url} alt={`${name} #${t.n}`} />
              <figcaption>
                <b>候选 #{t.n}</b>
                {candLabel(t) && <span className="cb-badge">{candLabel(t)}</span>}
                {stale && stale.length > 0 && <span className="cb-badge warn" title={`规则更新过：${stale.join("、")}；图本身还能用`}>规则已更新</span>}
                {!passed(t) && <span className="cb-badge bad">{t.why_not ?? t.bad ?? "不合格"}</span>}
                {data.active === t.n && <span className="cb-badge ok">当前</span>}
              </figcaption>
            </figure>
          )}
        </div>
        <footer className="cb-foot">
          <ol className="cb-thumbs" aria-label="全部候选">
            {takes.map((x) => (
              <li key={x.n}>
                <button type="button" className={`cb-th${x.n === t.n && !cmp ? " on" : ""}${data.active === x.n ? " act" : ""}`} onClick={() => (setCur(x.n), setCmp(false))} title={`#${x.n}${candLabel(x) ? ` · ${candLabel(x)}` : ""}`}>
                  <img src={thumb(x.url, 120) ?? x.url} alt="" loading="lazy" />
                  <span>
                    #{x.n}
                    {plainLabel(x.label) ? ` ${plainLabel(x.label)}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ol>
          {!cmp && (
            passed(t) ? (
              <button type="button" className="ds-btn primary" disabled={busy || data.active === t.n} onClick={() => void use(t)} title="设为这一镜当前用的图（10 秒内可撤销）">
                {data.active === t.n ? "正在用这张" : busy ? "设置中…" : `用这张（#${t.n}）`}
              </button>
            ) : (
              <span className="cb-sub">{t.why_not ?? "这张不合格"}，不作候选；等新配方出图</span>
            )
          )}
        </footer>
      </div>
    </div>,
    document.body,
  );
}
