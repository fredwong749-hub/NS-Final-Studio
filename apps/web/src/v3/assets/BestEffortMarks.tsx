// L-215 块 J（复审第 4 条）：资产换了几种做法都没出来、系统先按“尽力版”继续的，在资产页顶部列一行小标记（只文字，不挡任何操作）。
import { useEffect, useState } from "react";

type Mark = { id: string; who: string; what: string; mark: string; say: string };

export function BestEffortMarks() {
  const [items, setItems] = useState<Mark[]>([]);
  useEffect(() => {
    let live = true;
    fetch("/api/assets/best-effort")
      .then((r) => (r.ok ? r.json() : { items: [] }))
      .then((d: { items?: Mark[] }) => live && setItems(Array.isArray(d.items) ? d.items : []))
      .catch(() => live && setItems([]));
    return () => {
      live = false;
    };
  }, []);
  if (!items.length) return null;
  return (
    <div className="ac-besteffort" role="status">
      {items.map((m) => (
        <div key={m.id} className="ac-besteffort-i" title={m.say}>
          <span className="ac-besteffort-tag">{m.mark}</span>
          <span>
            {m.who}的{m.what}：{m.say}
          </span>
        </div>
      ))}
    </div>
  );
}
