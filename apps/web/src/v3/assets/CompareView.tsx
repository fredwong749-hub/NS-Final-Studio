// UX5：版本对比（C_research #8 / #12）——并排 / 滑块两种模式，左右各标版本；只并排展示，不给“哪个更好”的判断。
import { useState } from "react";
import { Button, Modal, Seg } from "../../ds";

export interface CmpSide {
  url: string;
  label: string;
  sub?: string;
}

export function CompareView({ a, b, onClose, title = "版本对比" }: { a: CmpSide; b: CmpSide; onClose: () => void; title?: string }) {
  const [mode, setMode] = useState<"side" | "slide">("side");
  const [pos, setPos] = useState(50);
  const [L, R] = [a, b];
  return (
    <Modal
      wide
      title={title}
      sub="只把两版放在一起看，不评价内容。滑块模式：左边是第一版，拖动看分界。"
      onClose={onClose}
      foot={
        <>
          <Seg value={mode} onChange={setMode} options={[["side", "并排"], ["slide", "滑块"]]} label="对比方式" />
          <span className="grow" />
          <Button onClick={onClose}>关闭</Button>
        </>
      }
    >
      {mode === "side" ? (
        <div className="ac-cmp-side">
          {[L, R].map((s, i) => (
            <figure key={i}>
              <img src={s.url} alt={s.label} />
              <figcaption>
                <b>{s.label}</b>
                {s.sub && <span>{s.sub}</span>}
              </figcaption>
            </figure>
          ))}
        </div>
      ) : (
        <div className="ac-cmp-slide">
          <div className="ac-cmp-stage" style={{ ["--pos" as string]: `${pos}%` }}>
            <img src={R.url} alt={R.label} />
            <img className="top" src={L.url} alt={L.label} />
            <i className="bar" aria-hidden="true" />
            <span className="lab l">{L.label}</span>
            <span className="lab r">{R.label}</span>
          </div>
          <input type="range" min={0} max={100} value={pos} onChange={(e) => setPos(Number(e.target.value))} aria-label="滑块位置" />
        </div>
      )}
    </Modal>
  );
}
