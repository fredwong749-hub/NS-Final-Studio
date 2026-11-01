// momoso 品牌标识组件（项目方 2026-10-31：“NS · 分集编辑器改名为momoso Agentic Drama Studio”“给个好看logo，momoso的字也改成平台名字风格”）。
// 图形 + 原创几何字形 momoso（apps/web/scripts/brand_logo.py 生成 brand_art.ts），副标题 AGENTIC DRAMA STUDIO 用低一级的系统字体。
// 项目方已挑定候选 2（双环）；换候选只改下面 CANDIDATE 一个数字（favicon 跑一次 brand_logo.py 同步）。
import { useId } from "react";
import { BRAND_ART, type BrandCandidate } from "./brand_art";

const CANDIDATE: BrandCandidate = 2; // 项目方 2026-10-31 原话：“候选 2 · 双环”
const PRODUCT = "momoso Agentic Drama Studio";

function Defs({ id, c }: { id: string; c: BrandCandidate }) {
  const [a, b] = BRAND_ART[c].grad;
  return (
    <defs>
      <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor={a} />
        <stop offset="1" stopColor={b} />
      </linearGradient>
    </defs>
  );
}

export function BrandMark({ size = 22, c = CANDIDATE }: { size?: number; c?: BrandCandidate }) {
  const id = `bm${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    <svg className="ds-brand-mark" viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
      <Defs id={id} c={c} />
      <g dangerouslySetInnerHTML={{ __html: BRAND_ART[c].mark.replaceAll("__G__", id) }} />
    </svg>
  );
}

export function BrandWord({ height = 14, c = CANDIDATE }: { height?: number; c?: BrandCandidate }) {
  const id = `bw${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const pad = 1.2;
  const w = BRAND_ART[c].wordW + pad * 2;
  const h = 10 + pad * 2;
  return (
    <svg className="ds-brand-word" viewBox={`${-pad} ${-pad} ${w} ${h}`} height={height} width={(height * w) / h} aria-hidden="true">
      <Defs id={id} c={c} />
      <g dangerouslySetInnerHTML={{ __html: BRAND_ART[c].word.replaceAll("__G__", id) }} />
    </svg>
  );
}

/** 标识：mode = full（图形 + 字标 + 副标题）/ word（图形 + 字标）/ mark（只图形）。悬停一律看全称。 */
export function Brand({ mode = "full", size = 22, className = "" }: { mode?: "full" | "word" | "mark"; size?: number; className?: string }) {
  return (
    <span className={`ds-brand ${mode} ${className}`} title={PRODUCT} aria-label={PRODUCT} role="img">
      <BrandMark size={size} />
      {mode !== "mark" && (
        <span className="ds-brand-txt">
          <BrandWord height={Math.round(size * 0.62)} />
          {mode === "full" && <span className="ds-brand-sub">Agentic Drama Studio</span>}
        </span>
      )}
    </span>
  );
}
