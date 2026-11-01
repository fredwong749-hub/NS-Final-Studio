// UX5（A §3.6 / B §6.1）：精修右栏“本镜资产”——这一镜用到哪些资产（人物 · 形象 · 场景），以及每格出图 / 出视频时
// 盖章记下的依赖版本（定妆 / 身份 LoRA / 出图预设 / 视频基底 / 附加视频 LoRA / 音色），哪些“依赖已更新”。
// 每一项都能“打开 ↗”到资产中心对应的地方（带 from=本镜，资产中心页头有“← 回到本镜”）。只读：换资产仍走参考切换面板。
// UX6（B §6.1 kept）：每条“依赖已更新”旁有“保留旧版…”——项目方原话必填（by=owner + owner_quote，缺了后端 403），
// 只对此刻那一个新版本生效；依赖再变一次会重新提示。
import { thumb } from "../../thumb";
import { useEffect, useState } from "react";
import type { ShotSummary } from "../../types";
import { LoadError, Loading, Tag } from "../../ds";
import { p1Api, revApi, STAGE_NAME, type ShotDeps, type StaleDep, type Stage } from "../assets/rev_api";
import { OwnerConfirm } from "../assets/OwnerConfirm";
import { useUi } from "../ui.helpers";
import { AssetRefs } from "./AssetRefs";
import { useLookInfo } from "../looks";

function LookTitle({ c }: { c: { character: string; look_id: string | null; look_name: string } }) {
  const lk = useLookInfo(c.character, c.look_id, c.look_name || null);
  return <small>{lk.title || "集默认形象"}</small>;
}

/** 依赖键 → 资产中心路由 */
function routeOf(key: string, from: string): string {
  const [t, a] = key.split(":");
  const q = (o: Record<string, string>) => `#/assets?${new URLSearchParams({ ...o, from })}`;
  if (t === "identity") return q({ char: a });
  if (t === "loraslot") return q({ type: "lora" });
  if (t === "preset") return q({ type: "preset", q: a });
  if (t === "vbase" || t === "vlora") return q({ type: "vbase" });
  if (t === "voice") return q({ type: "voice" });
  return q({});
}

export function ShotAssetsTab({ shot }: { shot: ShotSummary }) {
  const { openRefSwitch } = useUi();
  const [d, setD] = useState<ShotDeps | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [keep, setKeep] = useState<{ st: Stage; n: number; x: StaleDep } | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setD(null);
    setErr(null);
    revApi.shotDeps(shot.id).then(
      (x) => alive && setD(x),
      (e) => alive && setErr(String((e as Error).message ?? e)),
    );
    return () => {
      alive = false;
    };
  }, [shot.id, tick]);
  const chars = shot.characters ?? [];
  const scene = (shot as { scene_id?: string | null }).scene_id ?? null;
  const from = shot.id;
  return (
    <div className="v3e-sa">
      <AssetRefs shot={shot.id} />
      <h4 className="ds-section-t">这一镜用到的资产</h4>
      <ul className="v3e-sa-list">
        {chars.map((c) => (
          <li key={c.character}>
            {c.face_url ? <img src={thumb(c.face_url, 120) ?? c.face_url} alt="" /> : <span className="ph">{(c.name ?? c.character).slice(0, 1)}</span>}
            <span className="t">
              <b>{c.name ?? c.character}</b>
              <LookTitle c={c} />
            </span>
            <button className="ds-btn xs ghost" onClick={() => openRefSwitch(shot.id, { kind: "character", id: c.character })} title="换这一镜的形象 / 单件（参考切换面板，先看影响面再应用）">
              替换…
            </button>
            <a className="ds-btn xs ghost" href={`#/assets?${new URLSearchParams({ char: c.character, from })}`} title="在资产中心打开这个角色">
              打开 ↗
            </a>
          </li>
        ))}
        {scene && (
          <li>
            <span className="ph">景</span>
            <span className="t">
              <b>{scene}</b>
              <small>场景</small>
            </span>
            <button className="ds-btn xs ghost" onClick={() => openRefSwitch(shot.id, { kind: "scene" })} title="换这一镜的场景底图（参考切换面板）">
              替换…
            </button>
            <a className="ds-btn xs ghost" href={`#/assets?${new URLSearchParams({ type: "scene", q: scene, from })}`} title="在资产中心找这个场景">
              打开 ↗
            </a>
          </li>
        )}
        {!chars.length && !scene && <li className="ds-muted">这一镜没有登记人物和场景。</li>}
      </ul>

      <h4 className="ds-section-t">出图 / 出视频时用的版本</h4>
      {err && <LoadError what="本镜依赖" err={err} hint="出过的版本记了用哪个定妆 / LoRA / 预设 / 基底；API 重启后这里列出，并标出哪些已更新。" />}
      {!d && !err && <Loading />}
      {d &&
        (["image", "last", "video"] as Stage[]).map((st) =>
          (d.stages[st] ?? []).map((t) => (
            <section key={`${st}${t.n}`} className="v3e-sa-stage">
              <header>
                <b>
                  {STAGE_NAME[st]} #{t.n}
                </b>
                {t.locked && <Tag tone="ok">定稿</Tag>}
                {t.active && !t.locked && <Tag>当前</Tag>}
                {!t.stamped && <span className="ds-muted ds-small">旧版本，出的时候还没记录依赖</span>}
                {t.stale_deps.filter((x) => !x.waived).length > 0 && <Tag tone="stale" dot>依赖已更新 {t.stale_deps.filter((x) => !x.waived).length}</Tag>}
                {t.stale_deps.some((x) => x.waived) && <Tag tone="info">保留旧版 {t.stale_deps.filter((x) => x.waived).length}</Tag>}
              </header>
              {t.stale_deps.length > 0 && (
                <ul className="v3e-sa-why">
                  {t.stale_deps.map((x, i) => (
                    <li key={i} className={x.waived ? "kept" : ""}>
                      <span>{x.text ?? x.key}</span>
                      {x.waived ? (
                        <small className="ds-muted" title={`项目方 ${x.waived.at}`}>
                          已保留旧版：「{x.waived.owner_quote}」
                        </small>
                      ) : (
                        <button className="ds-btn xs ghost" onClick={() => setKeep({ st, n: t.n, x })} title="这一格不重出，继续用旧版（只对这一个新版本生效）">
                          保留旧版…
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {t.deps.length > 0 && (
                <ul className="v3e-sa-deps">
                  {t.deps
                    .filter((x) => !x.key.startsWith("global:") && !x.key.startsWith("shot"))
                    .map((x) => (
                      <li key={x.key} className={x.fresh ? "" : "stale"}>
                        <span className="t">{x.label}</span>
                        <span className="v">
                          {x.fresh ? `v${x.v ?? "?"}` : `v${x.v ?? "?"} → v${x.current_v ?? "?"}`}
                        </span>
                        <a href={routeOf(x.key, from)} title="在资产中心打开">
                          ↗
                        </a>
                      </li>
                    ))}
                </ul>
              )}
            </section>
          )),
        )}
      {d && !Object.values(d.stages).some((x) => x?.length) && <p className="ds-muted ds-small">这一镜还没出过图。</p>}
      {keep && (
        <OwnerConfirm
          title={`保留旧版 · ${shot.id} ${STAGE_NAME[keep.st]} #${keep.n}`}
          sub={keep.x.text}
          gated
          gateLabel="保留旧版（不随依赖更新重出）"
          okText="保留旧版"
          lines={["这一格不再提示这条“依赖已更新”（记在你的账户名下）。", "只对现在这个新版本生效：依赖再改一次，会重新提示。不删、不改任何出图。"]}
          onClose={() => {
            setKeep(null);
            setTick((n) => n + 1);
          }}
          onConfirm={async (quote) => {
            await p1Api.keep(shot.id, { stage: keep.st, key: keep.x.key, n: keep.n, by: "owner", owner_quote: quote });
            return "已记下：这一格保留旧版";
          }}
        />
      )}
    </div>
  );
}
