import { useEffect, useState } from "react";
import { api } from "../api";
import type { ShotRefs } from "../types";
import "../assets.css";

const ROLE_LABEL: Record<string, string> = {
  face: "脸",
  outfit: "上身",
  shoes: "鞋",
  nails: "美甲",
  hair: "发型",
  makeup: "妆",
  accessory: "饰",
};

/** 参考图组预览（规范 §3.4.5 / E6）：本镜实际送进图像模型的参考图，按顺序编号；超限的删除线，没图的只用文字 */
export function RefGroup({ shotId }: { shotId: string }) {
  const [data, setData] = useState<ShotRefs | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setData(null);
    setErr(null);
    api.looks.refs(shotId).then(
      (r) => alive && setData(r),
      (e: Error) => alive && setErr(e.message),
    );
    return () => {
      alive = false;
    };
  }, [shotId]);

  if (err) return <div className="bad small">参考图组不可用：{err}</div>;
  if (!data) return <div className="muted small">加载参考图组…</div>;
  if (!data.refs.length) return <div className="muted small">本镜没有出场角色，不送参考图（纯文生图）</div>;

  return (
    <div className="ref-group">
      <div className="ref-group-head small">
        <b>参考图组</b>
        <span className="muted">
          {data.model} · 实际送入 {data.count}/{data.limit} 张 · 顺序：脸 → 上身 → 鞋 → 美甲 → 发型 → 妆 → 饰
        </span>
      </div>
      <div className="ref-strip">
        {data.refs.map((r, i) => {
          const cls = ["ref-cell", r.text_only ? "text-only" : "", r.truncated ? "truncated" : "", r.duplicate ? "dup" : ""]
            .filter(Boolean)
            .join(" ");
          const note = r.text_only ? "只用文字描述" : r.truncated ? "改用文字描述" : r.duplicate ? "与前图重复，不重复送" : "";
          return (
            <div key={i} className={cls} title={`${r.label}${r.file ? `\n${r.file}` : ""}${note ? `\n${note}` : ""}`}>
              <div className="ref-img">
                {r.url && !r.text_only ? <img src={r.url} alt={r.label} loading="lazy" draggable={false} /> : <span className="ref-none">无图</span>}
                {r.index != null && !r.truncated && <span className="ref-no">@图{r.index}</span>}
              </div>
              <div className="ref-cap">
                <span className="ref-role">{ROLE_LABEL[r.role] ?? r.role}</span>
                <span className="ref-name">{r.label.replace(`${r.name} `, "")}</span>
              </div>
              {note && <div className="ref-note">{note}</div>}
            </div>
          );
        })}
      </div>
      {data.anchor_lines.length > 0 && (
        <details className="ref-anchors">
          <summary className="small muted">锚点声明预览（{data.anchor_lines.length} 行）</summary>
          <pre className="small">{data.anchor_lines.join("\n")}</pre>
        </details>
      )}
    </div>
  );
}
