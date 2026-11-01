// UIRSI r41（项目方 11-02 00:5x：“旧版本的东西就隔离开吧,然后在我的网页里面尽量给我看最新的”）：
// 已隔离的旧版本（剧本重导前出的，文件在 data/_quarantine_20261102_oldscript）只在这里看——行尾 ⋯ 菜单“历史版本”打开，只读，不参与挑选。
import { useEffect, useState } from "react";
import { Modal } from "../ds";
import { thumb } from "../thumb";
import { epOf, type Cand } from "./candidates";

type HistRow = Partial<Record<"image" | "last", { takes: (Cand & { quarantined?: boolean })[] }>>;
const STAGE = { image: "首帧", last: "尾帧" } as const;

export function HistoryBox({ shot, onClose }: { shot: string; onClose: () => void }) {
  const [row, setRow] = useState<HistRow | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    fetch(`/api/candidates?ep=${epOf(shot)}&history=true`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d: { shots?: Record<string, HistRow> }) => setRow(d.shots?.[shot] ?? {}))
      .catch((e) => setErr(String((e as Error).message ?? e)));
  }, [shot]);
  const list = (["image", "last"] as const).flatMap((st) => (row?.[st]?.takes ?? []).filter((t) => t.quarantined).map((t) => ({ st, t })));
  return (
    <Modal title={`${shot.split("-")[1]} 历史版本`} sub="剧本更新前出的旧版本，已移进隔离区（不删，可恢复）；只供查看，不参与挑选" onClose={onClose} wide>
      {err ? (
        <p className="ds-small ds-muted">历史版本暂时读不到：后台恢复后再试。</p>
      ) : !row ? (
        <p className="ds-small ds-muted">读取中…</p>
      ) : !list.length ? (
        <p className="ds-small ds-muted">这一镜没有已隔离的旧版本。</p>
      ) : (
        <ul className="hist-grid">
          {list.map(({ st, t }) => (
            <li key={`${st}-${t.n}`} title={t.why_not ?? ""}>
              {t.url ? <img src={thumb(t.url, 240) ?? t.url} alt={`${STAGE[st]} #${t.n}`} loading="lazy" data-zoom-label={`${shot.split("-")[1]} · ${STAGE[st]} #${t.n} · 历史`} /> : <span className="hist-none">图不在</span>}
              <small>
                {STAGE[st]} #{t.n}
                {t.created_at ? ` · ${t.created_at.slice(5, 16).replace("T", " ")}` : ""}
              </small>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
