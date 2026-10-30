// fredw-92/W4b：精修模式右栏内容（外壳画标签条）——提示词 | 版本 | 规则 | 高级
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { H3Blocks, ShotSummary, SopShot } from "../../types";
import { api } from "../../api";
import { useStudio } from "../../store";
import { useUi } from "../ui";
import type { Slot } from "../api_v1";
import { currentTake, fmtSec, focusSlot, gateOf, gpuLabel, isStale, lockedTake, setEdit, setShotUi, takesOf, useEdit } from "./state";
import { ImageParamsPanel } from "./ImageParams";
import { SLOT_NAME, submitFrame, submitVideo } from "./actions";
import { VersionChain, TakeMeta } from "./VersionChain";
import { LlmOverride, useLlmOverride } from "../pages/LlmOverride";
import { missingOf, StoryboardGrid, storyboardOf } from "../StoryboardDetails";
import "./edit.css";

export type RightTab = "prompt" | "versions" | "rules" | "advanced";
export const RIGHT_TABS: [RightTab, string][] = [
  ["prompt", "提示词"],
  ["versions", "版本"],
  ["rules", "规则"],
  ["advanced", "高级"],
];

export interface RightTabsProps {
  shot: ShotSummary;
  /** 外壳负责标签条与切换；W4b 只渲染 tab 对应内容 */
  tab: RightTab;
}

export function RightTabs({ shot, tab }: RightTabsProps) {
  const studio = useStudio();
  const d = studio.details[shot.id];
  if (!d) return <div className="v3e-rt"><div className="v3e-note">正在读取 {shot.id}…</div></div>;
  return (
    <div className="v3e-rt">
      {tab === "prompt" && <PromptTab key={shot.id} shot={shot} />}
      {tab === "versions" && <VersionChain shot={shot} />}
      {tab === "rules" && <RulesTab shot={shot} />}
      {tab === "advanced" && <AdvancedTab shot={shot} />}
    </div>
  );
}

// ---------- 提示词：只显示聚焦阶段那一段（v3.1 §2.3）；项目方 / 写作方原文，改了原样保存 ----------

/** 编辑框：至少 12 行，随内容长高 */
function GrowText({ value, onChange, dirty, small, readOnly }: { value: string; onChange?: (v: string) => void; dirty?: boolean; small?: boolean; readOnly?: boolean }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const fit = () => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  };
  useLayoutEffect(fit, [value]);
  // 右栏宽度变了 / 字体加载完 / 折叠区展开，都要重新量
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let w = el.clientWidth;
    const ro = new ResizeObserver(() => {
      if (el.clientWidth !== w) {
        w = el.clientWidth;
        fit();
      }
    });
    ro.observe(el);
    void document.fonts?.ready.then(fit);
    return () => ro.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <textarea
      ref={ref}
      className={`grow ${small ? "sm" : ""} ${dirty ? "dirty" : ""}`}
      rows={small ? 4 : 12}
      value={value}
      readOnly={readOnly}
      onChange={(e) => onChange?.(e.target.value)}
    />
  );
}

const H3_FIELDS: [keyof H3Blocks, string, string][] = [
  ["alignment", "对齐句", "系统按时长生成"],
  ["body", "画面", "integrated_multimodal_description"],
  ["soundscape", "环境声", "overall_soundscape"],
  ["music", "配乐", "non_diegetic_music"],
];

function PromptTab({ shot }: { shot: ShotSummary }) {
  const studio = useStudio();
  const es = useEdit();
  const d = studio.details[shot.id]!;
  const focus = focusSlot(es, d, shot.id);
  const firstC = d.compiled.image_prompt;
  const lastC = d.compiled_last.last_prompt;
  const [first, setFirst] = useState(d.edit.image_prompt ?? firstC);
  const [last, setLast] = useState(d.edit.last_prompt ?? lastC);
  const [busy, setBusy] = useState(false);
  // F2：导演加强（项目方原文；“让模型给建议”只填进输入框，不自动保存），旁边 ⚙ 只改这一次用的模型
  const [boostF, setBoostF] = useState(d.edit.boost_first ?? "");
  const [boostL, setBoostL] = useState(d.edit.boost_last ?? "");
  const [boostLlm, setBoostLlm] = useLlmOverride("canvas.boost");
  const [suggesting, setSuggesting] = useState<"first" | "last" | null>(null);
  // H3 四块：下一次出视频用的那段（原样发给 H3）；改了只用于“按改后的提示词重渲视频”这一次（prompt_override）
  const h3Full = shot.h3_prompt ?? d.compiled.video_prompt ?? "";
  const h3B = shot.h3_blocks ?? null;
  const [h3, setH3] = useState<H3Blocks | null>(h3B);
  useEffect(() => {
    setFirst(d.edit.image_prompt ?? firstC);
    setLast(d.edit.last_prompt ?? lastC);
    setBoostF(d.edit.boost_first ?? "");
    setBoostL(d.edit.boost_last ?? "");
  }, [d.edit.image_prompt, d.edit.last_prompt, d.edit.boost_first, d.edit.boost_last, firstC, lastC]);
  useEffect(() => setH3(h3B), [h3Full]); // eslint-disable-line react-hooks/exhaustive-deps
  const boostDirty = boostF !== (d.edit.boost_first ?? "") || boostL !== (d.edit.boost_last ?? "");
  const firstDirty = first !== (d.edit.image_prompt ?? firstC);
  const lastDirty = last !== (d.edit.last_prompt ?? lastC);
  const dirty = firstDirty || lastDirty || boostDirty;
  const h3Dirty = !!(h3 && h3B && H3_FIELDS.some(([k]) => h3[k] !== h3B[k]));
  // 只把改动的块在原文里原样替换（其余字符一个不动）；找不到原块就不能拼
  const h3Joined = (() => {
    if (!h3 || !h3B || !h3Dirty) return null;
    let out = h3Full;
    for (const [k] of H3_FIELDS) {
      if (h3[k] === h3B[k]) continue;
      if (!h3B[k] || !out.includes(h3B[k])) return null;
      out = out.replace(h3B[k], () => h3[k]);
    }
    return out;
  })();
  const vGate = gateOf(d, "video");
  const suggest = async (which: "first" | "last") => {
    setSuggesting(which);
    try {
      const r = await api.boostSuggest(shot.id, which, boostLlm);
      (which === "first" ? setBoostF : setBoostL)(r.suggestion);
      studio.notify(`已用 ${r.model} 生成导演加强建议（只填入输入框，未保存）`);
    } catch (e) {
      studio.notify(`导演加强：${(e as Error).message}`, "err");
    } finally {
      setSuggesting(null);
    }
  };
  const lockFirst = lockedTake(d, "first");

  const save = async (rerender: boolean) => {
    setBusy(true);
    const body = {
      ...d.edit,
      image_prompt: first === firstC ? null : first,
      last_prompt: last === lastC ? null : last,
      boost_first: boostF.trim() ? boostF : null,
      boost_last: boostL.trim() ? boostL : null,
    };
    try {
      await studio.saveEdit(shot.id, body);
      if (rerender) {
        const slot = focus === "last" && lockFirst ? "last" : "first";
        await submitFrame(shot.id, { stage: slot, mode: "regen", prompt: slot === "first" ? first : last, gpu: es.gpu }, `按新提示词重出${SLOT_NAME[slot]}`, studio.notify, studio.refreshAfter);
      }
    } finally {
      setBusy(false);
    }
  };
  const rerenderVideo = async () => {
    if (!h3Joined) return;
    setBusy(true);
    try {
      const cv = currentTake(es, d, shot.id, "video");
      await submitVideo(shot.id, { gpu: es.gpu as 3 | 0, prompt_override: h3Joined, ...(cv ? { parent: cv.n } : {}) }, studio.notify, studio.refreshAfter);
    } finally {
      setBusy(false);
    }
  };
  const sc = d.script;
  const sbMiss = missingOf(shot, storyboardOf(shot, d));
  const setFocus =(s: Slot) => setShotUi(shot.id, { slot: s });

  const firstFld = (open: boolean) => (
    <label className="v3e-fld">
      <span>
        首帧提示词<small>{d.edit.image_prompt != null ? "人工改过" : "编译结果"} · 原样发给 Image 2.1</small>
      </span>
      <GrowText value={first} onChange={setFirst} dirty={firstDirty} small={!open} />
      {d.edit.image_prompt != null && (
        <button className="v3e-link" onClick={() => setFirst(firstC)}>
          丢掉人工修改，回到编译结果
        </button>
      )}
    </label>
  );
  const lastFld = (open: boolean) => (
    <label className="v3e-fld">
      <span>
        尾帧提示词<small>由定稿首帧编辑而来 · 原样发给 Image 2.1</small>
      </span>
      <GrowText value={last} onChange={setLast} dirty={lastDirty} small={!open} />
      {d.edit.last_prompt != null && (
        <button className="v3e-link" onClick={() => setLast(lastC)}>
          丢掉人工修改，回到编译结果
        </button>
      )}
    </label>
  );
  const vt = currentTake(es, d, shot.id, "video");
  const vp = (vt?.params ?? null) as (Record<string, unknown> & { first?: { n?: number }; last?: { n?: number } }) | null;
  const videoFld = (
    <div className="v3e-h3">
      {h3 ? (
        H3_FIELDS.map(([k, label, hint]) => (
          <label key={k} className="v3e-fld">
            <span className="k">
              {label}
              <code>{hint}</code>
            </span>
            <GrowText
              value={h3[k] ?? ""}
              readOnly={k === "alignment"}
              small={k !== "body"}
              dirty={!!h3B && h3[k] !== h3B[k]}
              onChange={(v) => setH3({ ...h3, [k]: v })}
            />
          </label>
        ))
      ) : (
        <label className="v3e-fld">
          <span>H3 提示词（没拆出四块，整段显示）</span>
          <GrowText value={h3Full} readOnly />
        </label>
      )}
      <div className="v3e-note">下一次出视频原样用上面这段；这里的改动只用于“按改后的提示词重渲视频”这一次，不改剧本。长期修改走审片里的 H3 面板（项目方确认）。</div>
      <div className="v3e-fld">
        <span>
          视频参数{vt ? <small>当前视频 #{vt.n}</small> : <small>还没有视频</small>}
        </span>
        {vp ? (
          <dl className="v3e-kv">
            <dt>种子</dt>
            <dd>{String(vp.seed ?? vt?.seed ?? "—")}</dd>
            <dt>步数</dt>
            <dd>{String(vp.steps ?? "—")}</dd>
            <dt>时长</dt>
            <dd>
              {vp.seconds != null ? `${vp.seconds} 秒` : "—"}
              {vp.frames != null ? ` · ${vp.frames} 帧` : ""}
            </dd>
            <dt>LoRA</dt>
            <dd>{String(vp.lora_strength ?? "—")}</dd>
            <dt>首尾帧</dt>
            <dd>
              首帧 #{vp.first?.n ?? "—"} · 尾帧 #{vp.last?.n ?? "—"}
            </dd>
            <dt>用卡</dt>
            <dd>{gpuLabel(vp.gpu as number | undefined)}</dd>
            <dt>耗时</dt>
            <dd>{typeof vp.render_s === "number" ? fmtSec(vp.render_s) : "—"}</dd>
            <dt>提示词</dt>
            <dd>{vp.prompt_override ? "这一版用了改过的提示词" : "剧本原文"}</dd>
          </dl>
        ) : (
          <div className="v3e-ro">{vt ? "这一版没有记录参数" : "—"}</div>
        )}
        <button
          className="v3e-btn sm"
          disabled={!!vGate}
          title={vGate ?? undefined}
          onClick={() => setEdit(() => ({ loop: { shot: shot.id, slot: "video", mode: "video", parent: vt?.n ?? null } }))}
        >
          改参数重渲…
        </button>
      </div>
    </div>
  );

  const others: Slot[] = (["first", "last", "video"] as Slot[]).filter((s) => s !== focus);
  const NAME: Record<Slot, string> = { first: "首帧提示词", last: "尾帧提示词", video: "视频提示词（H3 四块）" };

  return (
    <>
      <div className="v3e-scroll">
        <div className="v3e-ptabs" role="tablist" aria-label="提示词阶段">
          {(["first", "last", "video"] as Slot[]).map((s) => (
            <button key={s} role="tab" aria-selected={focus === s} className={focus === s ? "on" : ""} onClick={() => setFocus(s)}>
              {SLOT_NAME[s]}
            </button>
          ))}
        </div>
        {focus === "first" ? firstFld(true) : focus === "last" ? lastFld(true) : videoFld}
        {/* fredw-92/U4：本镜全部分镜字段（剧本原文，只读），默认收起 */}
        <details className="v3e-fold">
          <summary>
            本镜分镜（剧本原文，只读）{sbMiss.length ? <span className="sb-badge" style={{ marginLeft: 8 }} title={sbMiss.map((f) => f.label).join("、")}>缺 {sbMiss.length} 项</span> : null}
          </summary>
          <StoryboardGrid s={shot} d={d} narrow />
        </details>

        {others.map((s) => (
          <details key={s} className="v3e-fold">
            <summary>
              {NAME[s]}
              {(s === "first" && firstDirty) || (s === "last" && lastDirty) || (s === "video" && h3Dirty) ? " · 有未保存的修改" : ""}
            </summary>
            {s === "first" ? firstFld(false) : s === "last" ? lastFld(false) : videoFld}
          </details>
        ))}
        <details className="v3e-fold">
          <summary>动作 / 运镜 · 对白（剧本原文，只读）</summary>
          <div className="v3e-fld">
            <span>动作 / 运镜</span>
            <div className="v3e-ro">{sc.motion_prompt || "—"}</div>
          </div>
          <div className="v3e-fld">
            <span>
              对白 / 独白<small>{sc.dialogue.length ? `${sc.dialogue.length} 句` : "本镜无对白"}</small>
            </span>
            {sc.dialogue.map((l, i) => (
              <div key={i} className="v3e-dl">
                <b>{l.speaker_note ?? "—"}</b> {l.text}
              </div>
            ))}
            {sc.voiceover && (
              <div className="v3e-dl">
                <b>{sc.voiceover.note}（独白）</b> {sc.voiceover.text}
              </div>
            )}
          </div>
        </details>
        {focus !== "video" && (
          <details className="v3e-fold" open={!!(d.edit.boost_first || d.edit.boost_last) || undefined}>
            <summary>导演加强（可选，项目方原文；拼进首帧 / 尾帧提示词）</summary>
            <div className="v3e-boost">
              <span className="v3e-muted">让模型给建议（只填进框里，不保存）</span>
              <button className="v3e-btn sm" disabled={!!suggesting} onClick={() => void suggest("first")}>
                {suggesting === "first" ? "生成中…" : "首帧建议"}
              </button>
              <button className="v3e-btn sm" disabled={!!suggesting} onClick={() => void suggest("last")}>
                {suggesting === "last" ? "生成中…" : "尾帧建议"}
              </button>
              <LlmOverride purpose="director_boost" where="canvas.boost" value={boostLlm} onChange={setBoostLlm} />
            </div>
            <label className="v3e-fld">
              <span>首帧加强</span>
              <textarea rows={3} value={boostF} onChange={(e) => setBoostF(e.target.value)} />
            </label>
            <label className="v3e-fld">
              <span>尾帧加强</span>
              <textarea rows={3} value={boostL} onChange={(e) => setBoostL(e.target.value)} />
            </label>
          </details>
        )}
      </div>
      {focus === "video" ? (
        <div className="v3e-foot">
          <span className="hint">{vGate ?? (h3Dirty ? (h3Joined ? "改动只用于这一次重渲" : "原文里找不到改动的块，不能拼回") : "改了块可只为这一次重渲")}</span>
          <button className="v3e-btn sm" disabled={!h3Dirty || busy} onClick={() => setH3(h3B)}>
            还原
          </button>
          <button className="v3e-btn primary sm" disabled={!h3Joined || busy || !!vGate} title={vGate ?? undefined} onClick={() => void rerenderVideo()}>
            按改后的提示词重渲视频
          </button>
        </div>
      ) : (
        <div className="v3e-foot">
          <span className="hint">{dirty ? "有未保存的修改" : "改完保存；可直接按新提示词重出"}</span>
          <button className="v3e-btn sm" disabled={!dirty || busy} onClick={() => void save(false)}>
            保存
          </button>
          <button
            className="v3e-btn primary sm"
            disabled={!dirty || busy || (focus === "last" && !lockFirst)}
            title={focus === "last" && !lockFirst ? "先定稿首帧" : undefined}
            onClick={() => void save(true)}
          >
            保存并重出{focus === "last" && lockFirst ? "尾帧" : "首帧"}
          </button>
        </div>
      )}
    </>
  );
}

// ---------- 规则：关口 + 机检 + 定稿关口 ----------
function RulesTab({ shot }: { shot: ShotSummary }) {
  const studio = useStudio();
  const d = studio.details[shot.id]!;
  const [sop, setSop] = useState<{ s: SopShot | null; err: string | null }>({ s: null, err: null });
  useEffect(() => {
    let dead = false;
    api.sopEpisode(d.episode.number).then(
      (e) => !dead && setSop({ s: e.shots.find((x) => x.id === shot.id) ?? null, err: null }),
      (e) => !dead && setSop({ s: null, err: (e as Error).message }),
    );
    return () => {
      dead = true;
    };
  }, [d.episode.number, shot.id]);
  const lf = lockedTake(d, "first");
  const ll = lockedTake(d, "last");
  const stale = Object.entries(shot.stale ?? {}).filter(([, v]) => v && v.length);
  const rd = shot.readiness;

  return (
    <div className="v3e-scroll">
      <div className="v3e-fld">
        <span>定稿关口</span>
        <ol className="v3e-gates">
          <li className={lf ? (isStale(lf) ? "warn" : "ok") : "todo"}>首帧{lf ? (isStale(lf) ? ` #${lf.n} 过期·需重出` : ` 已定稿 #${lf.n}`) : " 未定稿"}</li>
          <li className={ll ? (isStale(ll) ? "warn" : "ok") : lf ? "todo" : "wait"}>
            尾帧{ll ? (isStale(ll) ? ` #${ll.n} 过期·需重出` : ` 已定稿 #${ll.n}`) : lf ? " 未定稿" : "（等首帧定稿）"}
          </li>
          <li className={gateOf(d, "video") ? "wait" : "todo"}>视频{gateOf(d, "video") ? `：${gateOf(d, "video")}` : " 可以出"}</li>
        </ol>
      </div>
      <div className="v3e-fld">
        <span>SOP 关口</span>
        {sop.err ? (
          <div className="v3e-note warn">{sop.err}</div>
        ) : !sop.s ? (
          <div className="v3e-note">读取中…</div>
        ) : (
          <>
            <div className="v3e-ro">
              现在停在 <b>{sop.s.stage} {sop.s.stage_label}</b>
            </div>
            <ul className="v3e-list">
              {sop.s.blockers.map((b, i) => (
                <li key={i}>
                  {b.text} <small>{b.actor_label}</small>
                </li>
              ))}
              {Object.values(sop.s.stages).flatMap((st) => st.warnings ?? []).map((w, i) => (
                <li key={`w${i}`} className="warn">
                  提醒：{w.text}
                </li>
              ))}
              {!sop.s.blockers.length && <li>无卡点</li>}
            </ul>
          </>
        )}
      </div>
      {rd && (
        <div className="v3e-fld">
          <span>就绪检查</span>
          <ul className="v3e-list">
            {rd.items.map((it, i) => (
              <li key={i} className={it.level === "fail" ? "bad" : it.level === "warn" ? "warn" : ""}>
                {it.label}
                {it.reason ? `：${it.reason}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="v3e-fld">
        <span>过期原因</span>
        {stale.length ? (
          <ul className="v3e-list">
            {stale.map(([k, v]) => (
              <li key={k} className="warn">
                {k === "image" ? "首帧" : k === "last" ? "尾帧" : "视频"}：{v!.join("；")}
              </li>
            ))}
          </ul>
        ) : (
          <div className="v3e-ro">无</div>
        )}
      </div>
      {d.compiled.dropped_triggers.length > 0 && (
        <div className="v3e-fld">
          <span>编译器丢掉的触发词</span>
          <div className="v3e-ro mono">{d.compiled.dropped_triggers.join(", ")}</div>
        </div>
      )}
    </div>
  );
}

// ---------- 高级：负面词、种子、参考图、视频参数、默认用卡 ----------
function AdvancedTab({ shot }: { shot: ShotSummary }) {
  const studio = useStudio();
  const es = useEdit();
  const d = studio.details[shot.id]!;
  const slot = focusSlot(es, d, shot.id);
  const t = currentTake(es, d, shot.id, slot);
  const ui = useUi();
  return (
    <div className="v3e-scroll">
      {/* fredw-92/PX：出图参数（下一次出首帧 / 尾帧用） */}
      <div className="v3e-fld">
        <span>
          出图参数<small>下一次出首帧 / 尾帧用 · Image 2.1</small>
        </span>
        <ImageParamsPanel gpu={es.gpu} />
      </div>
      <div className="v3e-fld">
        <span>负面词</span>
        <div className="v3e-ro mono">{d.edit.image_negative ?? d.compiled.image_negative ?? "—"}</div>
      </div>
      <div className="v3e-fld">
        <span>
          {SLOT_NAME[slot]}当前版本{t ? ` #${t.n}` : ""}
        </span>
        {t ? <TakeMeta t={t} parent={t.parent != null ? takesOf(d, slot).find((x) => x.n === t.parent) ?? null : null} /> : <div className="v3e-ro">还没有版本</div>}
      </div>
      {t?.references?.length ? (
        <div className="v3e-fld">
          <span>这一版用到的参考图</span>
          <div className="v3e-ro mono small">{t.references.join("\n")}</div>
        </div>
      ) : null}
      <div className="v3e-fld">
        <span>本镜种子设置</span>
        <dl className="v3e-kv">
          <dt>首帧</dt>
          <dd>{d.edit.image_seed ?? "随机"}</dd>
          <dt>尾帧</dt>
          <dd>{d.edit.last_seed ?? "随机"}</dd>
          <dt>视频</dt>
          <dd>{d.edit.video_seed ?? "随机"}</dd>
        </dl>
      </div>
      <div className="v3e-fld">
        <span>工作流</span>
        <div className="v3e-ro mono">{t?.workflow ?? "—"}</div>
      </div>
      <div className="v3e-fld">
        <span>默认用卡</span>
        <select value={es.gpu} onChange={(e) => setEdit(() => ({ gpu: Number(e.target.value) as 0 | 3 }))}>
          <option value={3}>{gpuLabel(3)}</option>
          <option value={0}>{gpuLabel(0)}</option>
        </select>
      </div>
      <button className="v3e-btn sm" onClick={() => ui.openRefSwitch(shot.id, shot.characters[0] ? { kind: "character", id: shot.characters[0].character } : { kind: "scene" })}>
        切换本镜参考…
      </button>
    </div>
  );
}

export default RightTabs;
