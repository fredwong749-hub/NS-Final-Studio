// V2 资产页（#/assets；总调度 20:10）：只读 assets_v2/manifest.json（经 /api/v2/assets），不退回 V1。
// 女主 lead_f 按类分组：身份脸 / 造型 O1–O4 / 鞋 SH1–SH2 / 身体饰品 J1–J2；
// 成人类（O2 / O3 / J1 / J2）只显示文字卡“仅本地，项目方触发”，没有缩略图，也没有按钮；
// 每张资产只有“用这张 / 修改”（L-123）：现在每项只有 1 张登记图 = 当前，所以只有“修改”；有候选后候选卡上才会出“用这张”。
// 其他人物和场景还没有设定图：显示“等剧本定稿后出候选”，不放空白格。旧的资产中心留在 #/assets-v1，不删。
import { useCallback, useEffect, useState } from "react";
import { LoadError, Skel } from "../../ds";
import { EditBox } from "../EditBox";
import { SafeImg } from "../pages/FramesPage";
import "./v2assets.css";

type Edit = { id: string; text: string; state: string; at: string; note: string } | null;
type Card = { id: string; kind: string; name: string; adult: boolean; url: string | null; text: string; can_edit: boolean; edit: Edit };
type Group = { key: string; title: string; cards: Card[] };
type Data = { run: string; locked: boolean; characters: { id: string; display_name: string; groups: Group[] }[]; pending: { label: string; note: string }[] };

const SUGGEST: Record<string, string[]> = {
  face: ["脸更像本人", "更写实", "皮肤更细腻", "画质更清晰"],
  look: ["领口 / 袖口再挺一点", "更写实的面料", "颜色再准一点", "换个角度"],
  item: ["款式更准", "颜色再准一点", "换个角度", "背景干净一点"],
};

function AssetCard({ c, onEdit }: { c: Card; onEdit: (c: Card) => void }) {
  if (c.adult || !c.url)
    return (
      <div className={`v2a-card text${c.adult ? " adult" : ""}`}>
        <b className="v2a-name">{c.name}</b>
        <span className="v2a-text">{c.text}</span>
      </div>
    );
  return (
    <div className="v2a-card">
      <div className="v2a-img">
        <SafeImg src={c.url} alt={c.name} />
        <span className="v2a-badge">当前</span>
      </div>
      <b className="v2a-name">{c.name}</b>
      {c.edit && <span className="v2a-note">{c.edit.note}</span>}
      <div className="v2a-bar">
        {c.can_edit && (
          <button type="button" className="v2a-edit" onClick={() => onEdit(c)}>
            修改
          </button>
        )}
      </div>
    </div>
  );
}

export default function V2AssetsPage() {
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<Card | null>(null);
  const load = useCallback(() => {
    fetch("/api/v2/assets")
      .then(async (r) => (r.ok ? ((await r.json()) as Data) : Promise.reject(new Error(((await r.json().catch(() => ({}))) as { detail?: string }).detail ?? `HTTP ${r.status}`))))
      .then((x) => (setD(x), setErr(null)))
      .catch((e) => setErr(String((e as Error).message ?? e)));
  }, []);
  useEffect(() => load(), [load]);
  if (err && !d) return <div className="v3p-page"><LoadError what="资产" err={err} retry={load} /></div>;
  if (!d) return <div className="v3p-page"><Skel h={480} /></div>;
  return (
    <div className="v3p-page v2a-page">
      <header className="v3p-head">
        <h1>资产</h1>
        <span className="v3p-muted">{d.locked ? "已锁定，改动要项目方点选" : "还没锁定"}</span>
      </header>
      {d.characters.map((ch) => (
        <section key={ch.id} className="v2a-char">
          <h2>{ch.display_name}</h2>
          {ch.groups.map((g) => (
            <div key={g.key} className="v2a-group">
              <h3>{g.title}</h3>
              <div className="v2a-grid">
                {g.cards.map((c) => (
                  <AssetCard key={c.id} c={c} onEdit={setEditing} />
                ))}
              </div>
            </div>
          ))}
        </section>
      ))}
      {d.pending.map((p) => (
        <section key={p.label} className="v2a-char">
          <h2>{p.label}</h2>
          <div className="v2a-card text wide">
            <span className="v2a-text">{p.note}</span>
          </div>
        </section>
      ))}
      {editing && (
        <EditBox
          title={`修改 · ${editing.name}`}
          suggestions={SUGGEST[editing.kind] ?? SUGGEST.item}
          onSubmit={async (text, chips) => {
            let r: Response;
            try {
              r = await fetch(`/api/v2/assets/${encodeURIComponent(editing.id)}/edit`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, chips }) });
            } catch {
              throw new Error("网络不通，没有记下来，请再点一次“生成”");
            }
            if (!r.ok) throw new Error("没有记下来，请再点一次“生成”");
            load();
          }}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
