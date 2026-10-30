// fredw-92/W4b：和上一版并排对比；回退 = 把旧版设为当前（新版不删）；从任一版继续改
import { useEffect } from "react";
import type { ShotSummary } from "../../types";
import { useStudio } from "../../store";
import { slotToStage } from "../api_v1";
import { setEdit, takesOf, useEdit, pickTake } from "./state";
import { SLOT_NAME } from "./actions";
import { TakeMeta } from "./VersionChain";

export function CompareModal({ shot }: { shot: ShotSummary }) {
  const studio = useStudio();
  const es = useEdit();
  const c = es.compare!;
  const list = takesOf(studio.details[shot.id], c.slot);
  const a = list.find((t) => t.n === c.a);
  const b = list.find((t) => t.n === c.b);
  const close = () => setEdit(() => ({ compare: null }));
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  const use = async (n: number) => {
    pickTake(shot.id, c.slot, n);
    await studio.activate(shot.id, slotToStage(c.slot), n);
    close();
  };
  const cont = (n: number) => setEdit(() => ({ compare: null, loop: { shot: shot.id, slot: c.slot, mode: "instruct", parent: n } }));

  return (
    <div className="v3e-modal" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="v3e-dlg cmp" role="dialog" aria-label="并排对比">
        <header>
          <div>
            <h3>
              {shot.id} {SLOT_NAME[c.slot]} · #{c.b} ↔ #{c.a}
            </h3>
            <div className="sub">左 = 上一版，右 = 这一版；回退只是把旧版设为当前，新版保留</div>
          </div>
          <button className="v3e-x" onClick={close} aria-label="关闭">
            ×
          </button>
        </header>
        <div className="v3e-cmpgrid">
          {[b, a].map((t, i) => (
            <figure key={i}>
              {t ? (
                c.slot === "video" && t.url ? (
                  <video src={t.url} controls preload="metadata" />
                ) : (t.url ?? t.last_url) ? (
                  <img src={(t.url ?? t.last_url)!} alt="" />
                ) : (
                  <div className="e">无图</div>
                )
              ) : (
                <div className="e">找不到这一版</div>
              )}
              <figcaption>
                <b>{i === 0 ? `上一版 #${c.b}` : `这一版 #${c.a}`}</b>
                {t && <TakeMeta t={t} parent={i === 1 ? b ?? null : null} />}
                {t && (
                  <div className="acts">
                    <button className="v3e-btn sm" onClick={() => void use(t.n)}>
                      {i === 0 ? `回退到 #${t.n}` : `用 #${t.n}`}
                    </button>
                    {c.slot !== "video" && (
                      <button className="v3e-btn sm" onClick={() => cont(t.n)}>
                        从 #{t.n} 继续改
                      </button>
                    )}
                  </div>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </div>
  );
}
