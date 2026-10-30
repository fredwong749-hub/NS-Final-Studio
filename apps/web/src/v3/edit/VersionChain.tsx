// fredw-92/W4b：版本 = 修改链（parent 连成树）；选中一版 → 和上一版并排、回退、从这里继续改
import type { ShotSummary } from "../../types";
import { useStudio } from "../../store";
import { MODE_LABEL, ROLE_LABEL, STRENGTH_LABEL, slotToStage, type Slot } from "../api_v1";
import { activeN, currentTake, focusSlot, pickTake, takeBadge, setEdit, setShotUi, takeUrl, takesOf, useEdit, type TakeX } from "./state";
import { SLOT_NAME } from "./actions";
import { TakeParams } from "./ImageParams";

/** parent：对比用的上一版（出图参数里和它不同的项高亮；fredw-92/PX） */
export function TakeMeta({ t, parent }: { t: TakeX; parent?: TakeX | null }) {
  const p = t.params;
  const image = t.stage !== "video";
  return (
    <>
    <dl className="v3e-kv">
      <dt>改法</dt>
      <dd>{t.mode ? MODE_LABEL[t.mode] ?? t.mode : t.parent != null ? "—" : "生成"}</dd>
      <dt>原话</dt>
      <dd className="quote">{t.instruction || "—"}</dd>
      <dt>幅度</dt>
      <dd>{t.strength ? STRENGTH_LABEL[t.strength] : "—"}</dd>
      <dt>参考</dt>
      <dd>
        {t.refs?.length
          ? t.refs.map((r, i) => (
              <span key={i} className="v3e-chip">
                图{i + 2} {r.label ?? r.asset_id ?? r.path?.split("/").pop()} · 取{ROLE_LABEL[r.role] ?? r.role}
              </span>
            ))
          : (t.references?.length ?? 0) > 0
            ? `${t.references!.length} 张`
            : "—"}
      </dd>
      <dt>种子</dt>
      <dd>{t.seed ?? "—"}</dd>
      {p && !image && (
        <>
          <dt>视频参数</dt>
          <dd>
            {[p.steps != null && `步数 ${p.steps}`, p.seconds != null && `${p.seconds} 秒`, p.lora_strength != null && `LoRA ${p.lora_strength}`, p.prompt_override && "提示词已覆盖"]
              .filter(Boolean)
              .join(" · ") || "默认"}
          </dd>
        </>
      )}
      <dt>时间</dt>
      <dd>{t.created_at?.replace("T", " ").slice(0, 16) ?? "—"}</dd>
    </dl>
    {image && <TakeParams t={t} parent={parent} />}
    </>
  );
}

/** 按 parent 排成树（深度优先，孩子按 n） */
function chainOrder(list: TakeX[]): { t: TakeX; depth: number }[] {
  const ns = new Set(list.map((t) => t.n));
  const kids = new Map<number | null, TakeX[]>();
  for (const t of list) {
    const p = t.parent != null && ns.has(t.parent) ? t.parent : null;
    kids.set(p, [...(kids.get(p) ?? []), t]);
  }
  const out: { t: TakeX; depth: number }[] = [];
  const walk = (p: number | null, depth: number) => {
    for (const t of (kids.get(p) ?? []).sort((a, b) => a.n - b.n)) {
      out.push({ t, depth });
      walk(t.n, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

function lineage(list: TakeX[], t: TakeX | null): TakeX[] {
  const out: TakeX[] = [];
  const seen = new Set<number>();
  let c: TakeX | undefined | null = t;
  while (c && !seen.has(c.n)) {
    out.unshift(c);
    seen.add(c.n);
    c = c.parent != null ? list.find((x) => x.n === c!.parent) : null;
  }
  return out;
}

export function VersionChain({ shot }: { shot: ShotSummary }) {
  const studio = useStudio();
  const es = useEdit();
  const id = shot.id;
  const d = studio.details[id];
  const slot = focusSlot(es, d, id);
  const list = takesOf(d, slot);
  const cur = currentTake(es, d, id, slot);
  const act = activeN(d, slot);
  const parent = cur?.parent != null ? list.find((t) => t.n === cur.parent) ?? null : null;
  const live = es.jobs.filter((j) => j.shot === id && j.slot === slot && (j.state === "queued" || j.state === "running") && !j.notReady);

  return (
    <div className="v3e-ver">
      <div className="v3e-seg full">
        {(["first", "last", "video"] as Slot[]).map((s) => (
          <button key={s} className={slot === s ? "on" : ""} onClick={() => setShotUi(id, { slot: s })}>
            {SLOT_NAME[s]} {takesOf(d, s).length}
          </button>
        ))}
      </div>
      <div className="v3e-verhead">
        <b>
          {SLOT_NAME[slot]} · {list.length} 版{cur ? ` · 选中 #${cur.n}` : ""}
        </b>
        <span>{(() => {
          const lk = list.find((t) => t.locked);
          return lk ? (takeBadge(lk)?.cls === "warn" ? `定稿 #${lk.n} 过期·需重出` : `已定稿 #${lk.n}`) : "未定稿";
        })()}</span>
      </div>
      {!list.length ? (
        <div className="v3e-note">还没有{SLOT_NAME[slot]}版本。</div>
      ) : (
        <div className="v3e-chain">
          {chainOrder(list).map(({ t, depth }) => (
            <button
              key={t.n}
              className={`node ${cur?.n === t.n ? "sel" : ""}`}
              style={{ paddingLeft: 8 + Math.min(depth, 6) * 16 }}
              onClick={() => pickTake(id, slot, t.n)}
              onDoubleClick={() => t.parent != null && setEdit(() => ({ compare: { shot: id, slot, a: t.n, b: t.parent! } }))}
            >
              {depth > 0 && <span className="tw">└</span>}
              {takeUrl(t) ? <img src={takeUrl(t)!} alt="" loading="lazy" /> : <span className="th e" />}
              <b>#{t.n}</b>
              <span className="v3e-chip">{t.mode ? MODE_LABEL[t.mode] ?? t.mode : "生成"}</span>
              <span className="ins">{t.instruction ?? ""}</span>
              {t.n === act && <span className="tag cur">当前</span>}
              {takeBadge(t) && <span className={`tag ${takeBadge(t)!.cls}`} title={takeBadge(t)!.why || undefined}>{takeBadge(t)!.text}</span>}
            </button>
          ))}
          {live.map((j) => (
            <div key={j.id} className="node gen" style={{ paddingLeft: 8 + 16 }}>
              <span className="tw">└</span>
              <span className="th e" />
              <span className="v3e-chip">{j.label}</span>
              <span className="tag busy">{j.state === "queued" ? "排队中" : "生成中"}</span>
            </div>
          ))}
        </div>
      )}

      {cur && (
        <>
          <div className="v3e-lineage">
            修改链：
            {lineage(list, cur).map((t, i, a) => (
              <span key={t.n}>
                <a onClick={() => pickTake(id, slot, t.n)}>
                  #{t.n} {t.mode ? MODE_LABEL[t.mode] ?? t.mode : "生成"}
                </a>
                {i < a.length - 1 ? " › " : ""}
              </span>
            ))}
          </div>
          <div className="v3e-pair">
            {[parent, cur].map((t, i) => (
              <figure key={i} className={i === 1 ? "this" : ""}>
                {t && takeUrl(t) ? <img src={takeUrl(t)!} alt="" /> : <div className="e">{i === 0 ? "没有上一版（这是起点）" : "无图"}</div>}
                <figcaption>{i === 0 ? (t ? `上一版 #${t.n}` : "—") : `这一版 #${cur.n}${cur.n === act ? " · 当前" : ""}`}</figcaption>
              </figure>
            ))}
          </div>
          <div className="v3e-veracts">
            <button className="v3e-btn primary sm" disabled={cur.n === act} onClick={() => void studio.activate(id, slotToStage(slot), cur.n)}>
              {cur.n === act ? `#${cur.n} 是当前` : `设 #${cur.n} 为当前（回退）`}
            </button>
            <button className="v3e-btn sm" disabled={!parent} onClick={() => parent && setEdit(() => ({ compare: { shot: id, slot, a: cur.n, b: parent.n } }))}>
              全屏对比
            </button>
            {slot !== "video" && (
              <button className="v3e-btn sm" onClick={() => setEdit(() => ({ loop: { shot: id, slot, mode: "instruct", parent: cur.n } }))}>
                从 #{cur.n} 继续改
              </button>
            )}
          </div>
          <TakeMeta t={cur} parent={parent} />
          <div className="v3e-note">每次修改都生成新的一版挂在上一版下面；旧版不删，随时回退。</div>
        </>
      )}
    </div>
  );
}
