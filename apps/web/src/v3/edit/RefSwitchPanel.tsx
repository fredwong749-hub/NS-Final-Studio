// fredw-92/W4b：本镜参考切换面板 + 应用前看影响面（spec §6.2 / §6.3）。外壳（Canvas.tsx）提供浮层容器并负责打开 / 关闭。
// 只能选资产库里已有的资产；改集默认需项目方本人勾选（by=owner）。不做成人 / 内容限制。
// 入口：审片行的小造型卡 / 场景小卡、精修左栏的角色卡 / 场景卡、精修参考条。
import { useEffect, useMemo, useState } from "react";
import type { ShotSummary } from "../../types";
import { useStudio } from "../../store";
import {
  apiV1, errText, opt, PART_KEYS, PART_LABEL,
  type PartKey, type RefChange, type RefOption, type RefPreview, type RefScope,
} from "../api_v1";
import { bumpShotRefs, imgOf, lookName, sceneEff, useShotRefs } from "./RefBar";
import { AssetDrawer } from "./AssetDrawer";
import { etaFor, trackJob, type DrawerOpen } from "./state";
import "./edit.css";

export type RefTarget = { kind: "character"; id: string } | { kind: "scene" };

export interface RefSwitchPanelProps {
  shot: ShotSummary;
  target: RefTarget;
  onClose: () => void;
}

function Tile({ o, on, eff, onClick }: { o: RefOption; on: boolean; eff: boolean; onClick: () => void }) {
  const url = o.thumb_url ?? o.url;
  return (
    <button className={`v3e-tile ${on ? "on" : ""} ${eff ? "eff" : ""}`} onClick={onClick} title={o.name ?? o.id}>
      {url ? <img src={url} alt="" loading="lazy" /> : <span className="e">{o.letter ?? "无图"}</span>}
      {o.is_default && <i className="def">集默认</i>}
      <span className="nm">
        {o.letter ? `${o.letter} ` : ""}
        {o.name ?? o.label ?? o.id}
      </span>
    </button>
  );
}

export function RefSwitchPanel({ shot, target: tgt, onClose }: RefSwitchPanelProps) {
  const studio = useStudio();
  const target = tgt.kind === "scene" ? "__scene" : tgt.id;
  const r = useShotRefs(shot.id);
  const close = onClose;
  const [asset, setAsset] = useState<DrawerOpen | null>(null);
  const isScene = target === "__scene";
  const c = r.data?.characters.find((x) => x.id === target) ?? null;
  const brief = shot.characters.find((x) => x.character === target);
  const title = isScene ? "场景" : c?.name ?? brief?.name ?? target;

  const [look, setLook] = useState<string | null>(null);
  const [parts, setParts] = useState<Partial<Record<PartKey, string | null>>>({});
  const [scene, setScene] = useState<string | null>(null);
  const [copyFrom, setCopyFrom] = useState("");
  const [reset, setReset] = useState(false);
  const [step, setStep] = useState<1 | 2>(1);
  const [scope, setScope] = useState<RefScope>("shot");
  const [owner, setOwner] = useState(false);
  const [pv, setPv] = useState<{ data: RefPreview | null; err: string | null; busy: boolean }>({ data: null, err: null, busy: false });
  const [applying, setApplying] = useState(false);

  // 浮层与 Esc 由外壳负责

  const change: RefChange = useMemo(() => {
    if (reset) return { reset: true, ...(isScene ? {} : { characters: { [target]: {} } }) };
    if (copyFrom) return { copy_from: copyFrom };
    if (isScene) return scene != null ? { scene } : {};
    const ch: { look?: string | null; parts?: Partial<Record<PartKey, string | null>> } = {};
    if (look) ch.look = look;
    if (Object.keys(parts).length) ch.parts = parts;
    return Object.keys(ch).length ? { characters: { [target]: ch } } : {};
  }, [reset, copyFrom, isScene, scene, look, parts, target]);
  const hasChange = Object.keys(change).length > 0;

  const summary = (() => {
    if (reset) return "恢复集默认";
    if (copyFrom) return `整套参考借用 ${copyFrom}`;
    const out: string[] = [];
    if (isScene && scene) out.push(`场景 → ${scene === "none" ? "不用底图" : (r.data?.scene?.options ?? []).map(opt).find((o) => o.id === scene)?.name ?? scene}`);
    if (look) out.push(`整套形象 → ${(c?.options?.looks ?? []).map(opt).find((o) => o.id === look)?.name ?? look}`);
    for (const [p, v] of Object.entries(parts)) {
      const o = (c?.options?.parts?.[p as PartKey] ?? []).map(opt).find((x) => x.id === v);
      out.push(`${PART_LABEL[p as PartKey]} → ${v == null ? "不指定" : o?.name ?? v}`);
    }
    return out.join("；");
  })();

  useEffect(() => {
    if (step !== 2) return;
    let dead = false;
    setPv({ data: null, err: null, busy: true });
    apiV1.refsPreview(shot.id, scope, change).then(
      (data) => !dead && setPv({ data, err: null, busy: false }),
      (e) => !dead && setPv({ data: null, err: errText(e, "W5 /refs/preview"), busy: false }),
    );
    return () => {
      dead = true;
    };
  }, [step, scope, change, shot.id]);

  const apply = async (rerender: boolean) => {
    if (scope === "episode" && !owner) return studio.notify("改本集默认需要项目方本人勾选确认", "err");
    setApplying(true);
    try {
      const res = await apiV1.refsApply(shot.id, scope, change, rerender, scope === "episode" ? "owner" : undefined);
      // F2：重出首帧的任务接进任务条（/api/jobs 轮询，完成后刷新那一镜）
      const rr = res.rerender ?? [];
      for (const r of rr) {
        if (!r.ok || !r.job_id) continue;
        trackJob({
          id: r.job_id,
          shot: r.shot_id,
          slot: "first",
          label: "换参考后重出首帧",
          gpu: 3,
          eta_s: etaFor("first", 3).eta,
          onDone: (j) => {
            void studio.refreshAfter([r.shot_id]);
            studio.notify(j.state === "done" ? `${r.shot_id} 首帧已重出` : `${r.shot_id} 重出首帧失败：${j.error ?? ""}`, j.state === "done" ? "ok" : "err");
          },
        });
      }
      const bad = rr.filter((r) => !r.ok);
      studio.notify(
        `已应用（${res.affected?.length ?? 0} 镜受影响${rerender ? `，已排队重出首帧 ${rr.length - bad.length} 镜` : ""}）${bad.length ? `；${bad.map((r) => `${r.shot_id}：${r.error ?? "失败"}`).join("；")}` : ""}`,
        bad.length ? "err" : "ok",
      );
      await studio.refreshAfter([...new Set([shot.id, ...(res.affected ?? [])])]);
      bumpShotRefs();
      close();
    } catch (e) {
      studio.notify(`应用：${errText(e, "W5 /refs/apply")}`, "err");
    } finally {
      setApplying(false);
    }
  };

  const otherShots = (studio.episode?.shots ?? []).filter((s) => s.id !== shot.id);
  const editAsset = (a: string, kind: "look" | PartKey, label: string) =>
    setAsset({ shot: shot.id, asset: a, character: isScene ? "" : target, label, kind });

  // 「编辑这个资产」：同一个浮层里换成资产编辑器（§7.3：资产页、参考卡共用一个编辑器）
  if (asset) return <AssetDrawer shot={shot} open={asset} onClose={() => setAsset(null)} embedded />;

  return (
    <div className="v3e-dlg refs embed" aria-label="切换本镜参考">
        <header>
          {!isScene && (c ? imgOf(c) : brief?.face_url) ? <img className="v3e-dthumb" src={(c ? imgOf(c) : brief?.face_url)!} alt="" /> : <span className="v3e-dthumb e" />}
          <div>
            <h3>
              {shot.id} · {title}
              {c ? ` · ${lookName(c)}` : ""}
            </h3>
            <div className="sub">{step === 1 ? "本镜参考：只能选资产库里已有的资产" : "第 2 步：选范围、看影响"}</div>
          </div>
          {step === 1 && !isScene && c && (
            <button className="v3e-btn sm" onClick={() => editAsset(c.effective?.look ?? target, "look", `${c.name} · ${lookName(c)}`)}>
              编辑这个资产
            </button>
          )}
          <button className="v3e-x" onClick={close} aria-label="关闭">
            ×
          </button>
        </header>

        {step === 1 ? (
          <div className="v3e-dbody">
            {r.notReady && (
              <div className="v3e-note warn">
                参考切换后端未就绪（W5：GET /api/shots/{"{id}"}/refs）。下面只显示本镜当前生效的造型，暂不能切换。
              </div>
            )}
            {r.error && <div className="v3e-note warn">{r.error}</div>}
            {!r.data && brief && (
              <div className="v3e-slots">
                {brief.slots.map((s) => (
                  <div key={s.slot} className="row">
                    <span className="k">{s.slot}</span>
                    {s.items.map((it) => (
                      <span key={it.id} className="v3e-tile ro">
                        {it.thumb_url ? <img src={it.thumb_url} alt="" /> : <span className="e">无图</span>}
                        <span className="nm">{it.name}</span>
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            )}

            {c && (
              <>
                <section>
                  <h4>
                    ① 整套形象<span>点一下整套换掉 · 绿框 = 当前生效 · 蓝框 = 你选的</span>
                  </h4>
                  <div className="v3e-tiles big">
                    {(c.options?.looks ?? []).map(opt).map((o) => (
                      <Tile key={o.id} o={o} eff={o.current ?? o.id === c.effective?.look} on={look === o.id} onClick={() => { setReset(false); setCopyFrom(""); setLook(look === o.id ? null : o.id); }} />
                    ))}
                  </div>
                </section>
                <section>
                  <h4>
                    ② 单件替换<span>只换这一件，其余保持当前形象</span>
                  </h4>
                  {PART_KEYS.map((p) => {
                    const opts = (c.options?.parts?.[p] ?? []).map(opt);
                    if (!opts.length) return null;
                    const eff = c.effective?.parts?.[p];
                    return (
                      <div key={p} className="v3e-partrow">
                        <span className="k">
                          {PART_LABEL[p]}
                          {eff && (
                            <button className="v3e-link" onClick={() => editAsset(eff, p, `${c.name} · ${PART_LABEL[p]}`)}>
                              编辑
                            </button>
                          )}
                        </span>
                        <div className="v3e-tiles">
                          {opts.map((o) => (
                            <Tile
                              key={o.id}
                              o={o}
                              eff={o.current ?? o.id === eff}
                              on={parts[p] === o.id}
                              onClick={() => {
                                setReset(false);
                                setCopyFrom("");
                                setParts((m) => {
                                  const n = { ...m };
                                  if (n[p] === o.id) delete n[p];
                                  else n[p] = o.id;
                                  return n;
                                });
                              }}
                            />
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </section>
              </>
            )}

            {isScene && r.data && (
              <section>
                <h4>
                  ③ 场景底图<span>其他机位 / 时段候选，或不用底图</span>
                </h4>
                <div className="v3e-tiles big">
                  {(r.data.scene?.options ?? []).map(opt).map((o) => (
                    <Tile key={o.id} o={o} eff={o.current ?? sceneEff(r.data!.scene).id === o.id} on={scene === o.id} onClick={() => { setReset(false); setCopyFrom(""); setScene(scene === o.id ? null : o.id); }} />
                  ))}
                  {!(r.data.scene?.options ?? []).map(opt).some((o) => o.id === "none") && (
                    <Tile o={{ id: "none", name: "不用底图" }} eff={sceneEff(r.data.scene).id === "none"} on={scene === "none"} onClick={() => setScene(scene === "none" ? null : "none")} />
                  )}
                </div>
              </section>
            )}

            {r.data && (
              <section>
                <h4>
                  ④ 借用 / 恢复<span>复制另一镜的整套参考；或在任一版本上「设为参考」（⋯ 菜单）</span>
                </h4>
                <div className="v3e-borrow">
                  <label>
                    用
                    <select value={copyFrom} onChange={(e) => { setCopyFrom(e.target.value); setReset(false); }}>
                      <option value="">（选一镜）</option>
                      {otherShots.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.id}
                        </option>
                      ))}
                    </select>
                    的设置
                  </label>
                  <label>
                    <input type="checkbox" checked={reset} onChange={(e) => { setReset(e.target.checked); setCopyFrom(""); }} /> 恢复集默认
                  </label>
                </div>
              </section>
            )}
          </div>
        ) : (
          <div className="v3e-dbody apply">
            <div className="v3e-what">
              <span>改什么</span>
              <b>{summary}</b>
            </div>
            <div className="v3e-applygrid">
              <div>
                <h4>范围</h4>
                {(
                  [
                    ["shot", "只这一镜", shot.id],
                    ["scene", "本场景（同场几镜一起改）", ""],
                    ["episode", "本集默认（等于改造型确认）", ""],
                  ] as [RefScope, string, string][]
                ).map(([k, t, n]) => (
                  <label key={k} className={`v3e-radio ${scope === k ? "on" : ""}`}>
                    <input type="radio" checked={scope === k} onChange={() => setScope(k)} /> {t}
                    <small>{n}</small>
                  </label>
                ))}
                {scope === "episode" && (
                  <label className="v3e-owner">
                    <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} /> 我是项目方本人，确认改本集默认（原造型确认失效，需要重新确认）
                  </label>
                )}
                <small className="v3e-hint">只记“与上一层不同的部分”：镜头覆盖 → 场景覆盖 → 集默认。</small>
              </div>
              <div>
                <h4>
                  影响面<span>已出过图的镜头会标为过期，需要重出</span>
                </h4>
                {pv.busy ? (
                  <div className="v3e-note">计算影响面…</div>
                ) : pv.err ? (
                  <div className="v3e-note warn">{pv.err}</div>
                ) : pv.data ? (
                  <>
                    <table className="v3e-tbl">
                      <thead>
                        <tr>
                          <th>镜头</th>
                          <th>应用后</th>
                        </tr>
                      </thead>
                      <tbody>
                        {pv.data.affected.map((s) => (
                          <tr key={s}>
                            <td>{s}</td>
                            <td>{pv.data!.stale.includes(s) ? <span className="warn">过期 → 重出首帧</span> : "未出图，无需重出"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {pv.data.continuity_warnings.length > 0 && (
                      <div className="v3e-risk">
                        <b>衔接风险</b>
                        <ul>
                          {pv.data.continuity_warnings.map((w, i) => (
                            <li key={i}>{typeof w === "string" ? w : `${w.shot_id ? `${w.shot_id}：` : ""}${w.message ?? JSON.stringify(w)}`}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                ) : null}
              </div>
            </div>
          </div>
        )}

        <footer>
          {step === 1 ? (
            <>
              <span className="eta">{hasChange ? `将修改：${summary}` : "选一项要换的"}</span>
              <span className="sp" />
              <button className="v3e-btn" onClick={close}>
                取消
              </button>
              <button className="v3e-btn primary" disabled={!hasChange} onClick={() => setStep(2)}>
                下一步：选范围、看影响 →
              </button>
            </>
          ) : (
            <>
              <span className="eta">{pv.data ? `${pv.data.stale.length} 镜会过期` : ""}</span>
              <span className="sp" />
              <button className="v3e-btn" onClick={() => setStep(1)}>
                ← 返回
              </button>
              <button className="v3e-btn" disabled={applying || (scope === "episode" && !owner)} onClick={() => void apply(false)}>
                只应用，稍后重出
              </button>
              <button className="v3e-btn primary" disabled={applying || (scope === "episode" && !owner)} onClick={() => void apply(true)}>
                应用并重出首帧
              </button>
            </>
          )}
        </footer>
    </div>
  );
}

export default RefSwitchPanel;
