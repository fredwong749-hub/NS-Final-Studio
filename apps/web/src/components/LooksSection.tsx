import { useEffect, useState } from "react";
import { api } from "../api";
import { useStudio } from "../store";
import type { LookLayer, LookPatch, ResolvedLook, ShotLooks, Visibility } from "../types";
import { FIELD_LABEL } from "./LookStrip.helpers";

const LAYER_LABEL: Record<LookLayer, string> = { default: "默认", episode: "集计划", shot: "本镜覆盖" };
const VIS_LABEL: Record<Visibility, string> = { visible: "可见", hidden: "隐藏", in_box: "在匣" };

function Src({ s }: { s: LookLayer | null }) {
  if (!s) return null;
  return <span className={`src src-${s}`}>{LAYER_LABEL[s]}</span>;
}

/** 检查器第 5 组：本镜每个角色解析后的造型（/api/looks/shots/{id}），可覆盖本镜 / 恢复继承。不会触发渲染。 */
export function LooksSection({ shotId }: { shotId: string }) {
  const { catalog, notify, refreshLooks, epNum, showAffected } = useStudio();
  const [data, setData] = useState<ShotLooks | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    setData(null);
    api.looks.shot(shotId).then(
      (r) => {
        if (alive) {
          setData(r);
          setErr(null);
        }
      },
      (e: Error) => alive && setErr(e.message),
    );
    return () => {
      alive = false;
    };
  }, [shotId]);

  async function write(character: string, patch: LookPatch | null) {
    setBusy(true);
    try {
      const r = patch ? await api.looks.patchShot(shotId, character, patch) : await api.looks.clearShot(shotId, character);
      const what = patch ? "已覆盖本镜造型" : "已恢复继承";
      // 只影响本镜时只提示；波及多镜时弹影响范围（T54-B #3）
      if (r.affected_count > 1) showAffected(r, what);
      else notify(`${what}：影响 ${r.affected_count} 镜（不会自动重渲）`);
      setData(await api.looks.shot(shotId));
      await refreshLooks([epNum - 1, epNum, epNum + 1]);
    } catch (e) {
      notify(`造型修改失败：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  }

  if (err) return <div className="bad">造型接口不可用：{err}</div>;
  if (!data) return <div className="muted">加载造型…</div>;
  if (!data.characters.length) return <div className="muted">本镜没有检测到出场角色</div>;

  const refUrl = (r: ResolvedLook, ref: string) => {
    const lk = catalog?.looks.find((l) => l.id === r.look_id);
    const i = lk ? lk.reference_images.indexOf(ref) : -1;
    return i >= 0 ? (lk?.reference_urls?.[i] ?? null) : null;
  };

  return (
    <div className="looks">
      {data.script_decor_state && <div className="muted small">剧本装饰状态：{data.script_decor_state}</div>}
      {data.characters.map((r) => {
        const looks = catalog?.looks.filter((l) => l.character === r.character) ?? [];
        const frag = data.prompt.characters.find((p) => p.character === r.character);
        const errs = r.conflicts.filter((c) => c.severity !== "info");
        return (
          <div key={r.character} className={`look-card${errs.some((c) => c.severity === "error") ? " conflict" : ""}`}>
            <div className="look-card-head">
              <b>{r.label || r.name}</b>
              {r.has_override && <span className="badge b-override">本镜覆盖</span>}
              {r.changed_from_prev && (
                <span className="badge b-stale" title={`上一次出场：${r.prev_shot_id ?? "—"}`}>
                  换装点
                </span>
              )}
              {r.needs_review && <span className="badge b-stale">待确认</span>}
            </div>
            <dl className="slots">
              <div>
                <dt>造型</dt>
                <dd>
                  {r.look_name || r.look_id || "—"} <Src s={r.look_id_source} />
                </dd>
              </div>
              {Object.entries(r.slots).map(([slot, v]) => (
                <div key={slot} className={v.changed_from_prev ? "chg" : ""}>
                  <dt>{FIELD_LABEL[slot] ?? slot}</dt>
                  <dd>
                    {v.names.join("、") || v.items.join("、") || "—"} <Src s={v.source} />
                  </dd>
                </div>
              ))}
              <div className={r.d_state.changed_from_prev ? "chg" : ""}>
                <dt>装饰</dt>
                <dd>
                  {r.d_state.value ?? "—"} <Src s={r.d_state.source} />
                </dd>
              </div>
              {r.visibility.value && (
                <div>
                  <dt>可见性</dt>
                  <dd>
                    {VIS_LABEL[r.visibility.value as Visibility] ?? r.visibility.value} <Src s={r.visibility.source} />
                  </dd>
                </div>
              )}
            </dl>
            {r.reference_images.length > 0 && (
              <div className="refs">
                {r.reference_images.map((ref) => {
                  const u = refUrl(r, ref);
                  return u ? (
                    <img key={ref} src={u} alt={ref} title={ref} />
                  ) : (
                    <span key={ref} className="ref-id" title="参考图文件尚未就绪">
                      {ref}
                    </span>
                  );
                })}
              </div>
            )}
            {errs.map((c, i) => (
              <div key={i} className={`small ${c.severity === "error" ? "bad" : "warn"}`}>
                {c.severity === "error" ? "✖" : "⚠"} {c.message}
              </div>
            ))}
            {r.notes.map((n, i) => (
              <div key={i} className="muted small">
                · {n}
              </div>
            ))}
            {frag?.fragment && <div className="frag small">提示词片段：{frag.fragment}</div>}
            <div className="row-actions">
              <select disabled={busy} value="" onChange={(e) => e.target.value && void write(r.character, { look_id: e.target.value })}>
                <option value="">覆盖本镜造型为…</option>
                {looks.map((l) => (
                  <option key={l.id} value={l.id} disabled={l.id === r.look_id}>
                    {l.name || l.id}
                  </option>
                ))}
              </select>
              <select disabled={busy} value="" onChange={(e) => e.target.value && void write(r.character, { d_state: e.target.value })}>
                <option value="">装饰状态…</option>
                {catalog?.decor_states.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.id}
                  </option>
                ))}
              </select>
              <select
                disabled={busy}
                value=""
                onChange={(e) => e.target.value && void write(r.character, { visibility: e.target.value as Visibility })}
              >
                <option value="">可见性…</option>
                {(Object.keys(VIS_LABEL) as Visibility[]).map((v) => (
                  <option key={v} value={v}>
                    {VIS_LABEL[v]}
                  </option>
                ))}
              </select>
              {r.has_override && (
                <button className="btn-mini" disabled={busy} onClick={() => void write(r.character, null)}>
                  恢复继承
                </button>
              )}
            </div>
          </div>
        );
      })}
      {data.prompt.fragment && <div className="muted small">本镜造型提示词：{data.prompt.fragment}</div>}
    </div>
  );
}
