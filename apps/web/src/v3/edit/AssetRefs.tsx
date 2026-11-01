// 这一镜出首帧会用哪些参考图（REFLOCK：ns_agent.asset_refs）：按槽位顺序显示缩略图 + 写进提示词的“图N是…”原句；
// 缺图（阻断出图）红色，“只有设定图”黄色（建议补单品图）。数据：GET /api/shots/{id}/asset-refs（只读）。
import { useEffect, useState } from "react";
import { Skel, Tag } from "../../ds";
import { thumb } from "../../thumb";

type Member = { file: string; label: string; role: string; source: string };
type Slot = { index: number; kind: string; file: string; character: string | null; labels: string[]; members: Member[]; line: string };
type Refs = { slots: Slot[]; dropped: { label: string; why: string }[]; missing: { character: string | null; kind: string; detail: string }[]; warnings: { character: string | null; kind: string; detail: string; item?: string }[]; blocked: boolean; size?: string };

const KIND: Record<string, string> = { face: "脸", sheet: "设定图", item: "单品", board: "参考板", scene: "场景" };
const urlOf = (f: string) => (f.startsWith("data/") ? `/files/${f.slice(5)}` : `/api/assets/file?path=${encodeURIComponent(f)}`);

export function AssetRefs({ shot }: { shot: string }) {
  const [r, setR] = useState<Refs | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setR(null);
    setErr(null);
    fetch(`/api/shots/${encodeURIComponent(shot)}/asset-refs`)
      .then(async (x) => (x.ok ? x.json() : Promise.reject(new Error((await x.json().catch(() => ({}))).detail ?? `HTTP ${x.status}`))))
      .then((d: Refs) => alive && setR(d), (e: Error) => alive && setErr(e.message));
    return () => {
      alive = false;
    };
  }, [shot]);
  if (err) return <p className="ds-small ds-muted">出图参考：{err}</p>;
  if (!r) return <Skel h={96} />;
  return (
    <section className="ar-wrap" aria-label="这一镜出首帧用的参考图">
      <h4>
        出首帧用的参考 {r.blocked ? <Tag tone="bad" size="xs">资产缺图·阻断出图</Tag> : <Tag tone="ok" size="xs">参考齐了</Tag>}
      </h4>
      <ol className="ar-slots">
        {r.slots.map((s) => (
          <li key={s.index} className="ar-slot">
            <a href={urlOf(s.file)} target="_blank" rel="noreferrer" className="ar-img" title={s.file}>
              <img src={thumb(urlOf(s.file), 240) ?? urlOf(s.file)} alt={s.labels.join("、")} loading="lazy" />
              <b>图{s.index}</b>
            </a>
            <div className="ar-txt">
              <span className="ds-small">{KIND[s.kind] ?? s.kind} · {s.labels.join("、")}</span>
              <span className="ds-small ds-muted">{s.line}</span>
            </div>
          </li>
        ))}
      </ol>
      {r.missing.map((m, i) => (
        <p key={`m${i}`} className="ar-note bad">
          {m.kind}：{m.detail}
        </p>
      ))}
      {r.warnings.filter((w) => w.kind === "仅设定图").map((w, i) => (
        <p key={`w${i}`} className="ar-note warn">
          建议补单品图：{w.item ?? ""}（现在用设定图代替）
        </p>
      ))}
      {r.warnings.some((w) => w.kind !== "仅设定图") && (
        <details className="ar-note">
          <summary>其他说明（{r.warnings.filter((w) => w.kind !== "仅设定图").length}）</summary>
          {r.warnings.filter((w) => w.kind !== "仅设定图").map((w, i) => (
            <p key={`o${i}`} className="ar-note">
              {w.kind}：{w.detail.replace(/[a-z_]+\/[^\s，；]+/gi, "").replace(/\s+/g, " ").slice(0, 120)}
            </p>
          ))}
        </details>
      )}
      {r.dropped.length > 0 && <p className="ar-note">参考图位置不够、改用文字描述的：{r.dropped.map((d) => d.label.replace(/sk_[a-z0-9_]+/g, "")).join("、")}</p>}
    </section>
  );
}
