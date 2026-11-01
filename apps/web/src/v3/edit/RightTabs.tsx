// fredw-92/W4b：精修模式右栏内容（外壳画标签条）——提示词 | 版本 | 规则 | 高级
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { EditButton } from "../../ds/editdel";
import type { H3Blocks, ShotSummary, SopShot } from "../../types";
import { api } from "../../api";
import { useStudio } from "../../store";
import { useUi } from "../ui.helpers";
import type { Slot } from "../api_v1";
import { currentTake, fmtSec, focusSlot, gateOf, gpuLabel, isStale, lockedTake, setEdit, setShotUi, takesOf, useEdit } from "./state";
import { LaneSelect } from "./LaneSelect";
import { ImageParamsPanel } from "./ImageParams";
import { SLOT_NAME, submitFrame, submitVideo } from "./actions";
import { VersionChain, TakeMeta } from "./VersionChain";
import { ShotAssetsTab } from "./ShotAssetsTab";
import { ShotLinesList } from "../sound/ShotLines";
import { LlmOverride } from "../pages/LlmOverride";
import { useLlmOverride } from "../pages/LlmOverride.helpers";
import { StoryboardGrid } from "../StoryboardDetails";
import { missingOf, storyboardOf } from "../StoryboardDetails.helpers";
import "./edit.css";
import { AUTO_SHORT, STALE_SHORT } from "../words";

import { isMine, plain, type RightTab } from "./rightTabs.helpers";
export type { RightTab };

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
      {tab === "assets" && <ShotAssetsTab shot={shot} />}
      {tab === "sound" && <SoundTab shot={shot} />}
      {tab === "rules" && <RulesTab shot={shot} />}
      {tab === "advanced" && <AdvancedTab shot={shot} />}
    </div>
  );
}

// ---------- 声音（UIRSI B4）：这一镜的台词逐句 ▶、整镜连播；配乐 / 全集台词去声音页 ----------
function SoundTab({ shot }: { shot: ShotSummary }) {
  const ep = Number(shot.id.match(/^ep(\d+)/)?.[1]) || 1;
  return (
    <div className="v3e-sound">
      <ShotLinesList shot={shot.id} compact />
      <p className="v3e-note">
        <a className="v3p-link" href={`#/sound?tab=bgm&ep=${ep}&shot=${shot.id}`}>这一镜的配乐 →</a>{" "}
        <a className="v3p-link" href={`#/sound?tab=lines&ep=${ep}&shot=${shot.id}`}>整集台词 →</a>
      </p>
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

// UXF2 #26：只写中文名，不再露出英文字段名
const H3_FIELDS: [keyof H3Blocks, string, string][] = [
  ["alignment", "对齐句", "系统按时长生成，不能改"],
  ["body", "画面", ""],
  ["soundscape", "环境声", ""],
  ["music", "配乐", ""],
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
      await submitVideo(shot.id, { gpu: es.gpu, prompt_override: h3Joined, ...(cv ? { parent: cv.n } : {}) }, studio.notify, studio.refreshAfter);
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
      <EditButton type="prompt" id={`shot:${shot.id}/image_prompt`} size="xs" label="说哪里不对，让系统改" onChanged={() => void studio.refreshAfter([shot.id])} />
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
      <EditButton type="prompt" id={`shot:${shot.id}/last_prompt`} size="xs" label="说哪里不对，让系统改" onChanged={() => void studio.refreshAfter([shot.id])} />
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
              {hint && <small>{hint}</small>}
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
      <div className="v3e-note">下一次出视频原样用上面这段。“按改后的提示词重渲视频”只用这一次；要以后一直用，点“保存为长期修改”（登录即本人确认，可撤销）。</div>
      {/* 回退补回（旧检查器 H3Panel）：视频提示词长期修改（画面 / 环境声），撤销 = 回到剧本编译结果 */}
      {h3 && (
        <div className="v3e-row-btns">
          <button
            className="v3e-btn sm primary"
            disabled={!h3B || (h3.body === h3B.body && h3.soundscape === h3B.soundscape)}
            onClick={async () => {
              try {
                const r = await api.putH3Override(shot.id, { body: h3.body ?? null, soundscape: h3.soundscape ?? null, base_sha: shot.h3_prompt_sha256 ?? null, note: "登录点选：保存视频提示词长期修改" });
                studio.notify(r.status === "draft" ? `已保存为草稿：${(r.failed ?? []).join("、") || "规则检查没过"}` : "视频提示词已保存为长期修改，之后出视频都用它");
                void studio.refreshAfter([shot.id]);
              } catch (err) {
                studio.notify(`没保存上：${(err as Error).message}`, "err");
              }
            }}
            title="把画面 / 环境声的修改存为这一镜的长期视频提示词"
          >
            保存为长期修改
          </button>
          {d.edit.h3_prompt_override && (
            <button
              className="v3e-btn sm"
              onClick={async () => {
                try {
                  await api.putH3Override(shot.id, { clear: true, note: "登录点选：撤销视频提示词长期修改" });
                  studio.notify("已撤销长期修改，回到剧本编译结果");
                  void studio.refreshAfter([shot.id]);
                } catch (err) {
                  studio.notify(`没撤销成：${(err as Error).message}`, "err");
                }
              }}
            >
              撤销长期修改
            </button>
          )}
        </div>
      )}
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
  const NAME: Record<Slot, string> = { first: "首帧提示词", last: "尾帧提示词", video: "视频提示词" }; // UX4（审查 #26）：不写“H3 四块”

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
          <span className="hint">{vGate ?? (h3Dirty ? (h3Joined ? "只这一次用改过的提示词重出视频" : "原文里找不到改动的块，不能拼回") : "先改上面任一块")}</span>
          <button className="v3e-btn sm" disabled={!h3Dirty || busy} title={h3Dirty ? "放弃这次改动，回到剧本原文" : "还没改过，不用还原"} onClick={() => setH3(h3B)}>
            还原
          </button>
          <button className="v3e-btn primary sm" disabled={!h3Joined || busy || !!vGate} title={vGate ?? undefined} onClick={() => void rerenderVideo()}>
            只这一次用改后的提示词重出
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

// ---------- 规则（UXF2 #28）：分成“需要你处理”（红，只有这一类算数）和“系统提示”（灰，默认折叠） ----------

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
  const STG: Record<string, string> = { image: "首帧", last: "尾帧", video: "视频" };

  const mine: { text: string; cls: string }[] = [];
  const info: { text: string; who?: string; cls?: string }[] = [];
  for (const b of sop.s?.blockers ?? []) (isMine(b) ? mine.push({ text: plain(b.text), cls: "bad" }) : info.push({ text: plain(b.text), who: b.actor_label }));
  for (const it of rd?.items ?? []) {
    const t = `${it.label}${it.reason ? `：${it.reason}` : ""}`;
    // 就绪检查没过的是流程状态（缺尾帧、剧本缺字段等），由出图 / 写作那边补，不算“要你处理”
    if (it.level === "fail" || it.level === "warn") info.push({ text: plain(t), cls: it.level === "fail" ? "warn" : undefined });
  }
  for (const [k, v] of stale) mine.push({ text: `${STG[k] ?? k}已过期：${v!.join("；")}，需重出`, cls: "warn" });
  for (const w of Object.values(sop.s?.stages ?? {}).flatMap((st) => st.warnings ?? [])) info.push({ text: plain(w.text) });
  const seen = new Set<string>();
  const infoU = info.filter((x) => (seen.has(x.text) ? false : (seen.add(x.text), true)));

  return (
    <div className="v3e-scroll">
      <div className="v3e-fld">
        <span>定稿进度</span>
        <ol className="v3e-gates">
          {/* UXF4（审查 N1）：自动测试定稿写明待复审，不算“已定稿” */}
          <li className={lf ? (isStale(lf) || lf.auto ? "warn" : "ok") : "todo"}>首帧{lf ? (isStale(lf) ? ` #${lf.n} ${STALE_SHORT}` : lf.auto ? ` #${lf.n} ${AUTO_SHORT}` : ` 已定稿 #${lf.n}`) : " 未定稿"}</li>
          <li className={ll ? (isStale(ll) || ll.auto ? "warn" : "ok") : lf ? "todo" : "wait"}>
            尾帧{ll ? (isStale(ll) ? ` #${ll.n} ${STALE_SHORT}` : ll.auto ? ` #${ll.n} ${AUTO_SHORT}` : ` 已定稿 #${ll.n}`) : lf ? " 未定稿" : "（等首帧定稿）"}
          </li>
          <li className={gateOf(d, "video") ? "wait" : "todo"}>视频{gateOf(d, "video") ? `：${gateOf(d, "video")}` : " 可以出"}</li>
        </ol>
      </div>
      {/* 回退补回（旧检查器 H3Panel）：视频提示词规则逐条检查（§9A）+ 缺的字段 */}
      {(shot.h3_lint?.length || shot.h3_missing?.length) ? (
        <details className="v3e-fld" open={shot.h3_lint_ok === false || !!shot.h3_missing?.length}>
          <summary>
            视频提示词规则检查<small>{shot.h3_lint_ok === false ? `没过 ${(shot.h3_lint ?? []).filter((x) => !x.ok && !x.overridden).length} 条` : "都过了"}{shot.h3_missing?.length ? ` · 缺 ${shot.h3_missing.join("、")}` : ""}</small>
          </summary>
          <ul className="v3e-list">
            {(shot.h3_lint ?? []).map((x) => (
              <li key={x.rule_id} className={x.ok ? "ok" : x.overridden ? "warn" : "bad"} title={x.sop_ref ?? ""}>
                {x.ok ? "✓" : x.overridden ? "△" : "✗"} {x.msg ?? x.detail}
                {x.overridden ? "（已豁免）" : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      <div className="v3e-fld">
        <span>
          需要你处理<small>{mine.length ? `${mine.length} 项` : ""}</small>
        </span>
        {sop.err && <div className="v3e-note warn">流程关口读不到：{sop.err}</div>}
        {mine.length ? (
          <ul className="v3e-list">
            {mine.map((m, i) => (
              <li key={i} className={m.cls}>
                {m.text}
              </li>
            ))}
          </ul>
        ) : (
          <div className="v3e-ro">没有要你处理的</div>
        )}
      </div>
      <details className="v3e-fold">
        <summary>
          系统提示（{infoU.length + (sop.s ? 1 : 0) + (d.compiled.dropped_triggers.length ? 1 : 0)} 条，不用你处理）
        </summary>
        <ul className="v3e-list dim">
          {sop.s && <li>流程进度：{sop.s.stage_label}</li>}
          {infoU.map((x, i) => (
            <li key={i} className={x.cls}>
              {x.text}
              {x.who ? <small> · {x.who}</small> : null}
            </li>
          ))}
          {d.compiled.dropped_triggers.length > 0 && <li>出图时自动去掉的 LoRA 触发词：{d.compiled.dropped_triggers.join("、")}（不影响画面）</li>}
          {rd?.items.filter((it) => it.level !== "fail" && it.level !== "warn").length ? (
            <li>就绪检查通过 {rd.items.filter((it) => it.level !== "fail" && it.level !== "warn").length} 项</li>
          ) : null}
        </ul>
      </details>
    </div>
  );
}

// ---------- 本镜长期设置（存进 ShotEdit，之后每次出图都用）：负面词、锁种、尾帧来源、上传尾帧、配乐、备注 ----------
const LAST_SRC: [string, string][] = [
  ["gen", "生成（由首帧编辑出尾帧）"],
  ["next", "用下一镜首帧（衔接）"],
  ["upload", "上传的图"],
  ["video", "视频末帧抽帧"],
];
function PersistPanel({ shot }: { shot: ShotSummary }) {
  const studio = useStudio();
  const es = useEdit();
  const d = studio.details[shot.id]!;
  const e = d.edit;
  const [neg, setNeg] = useState(e.image_negative ?? "");
  const [music, setMusic] = useState(e.music ?? "");
  const [note, setNote] = useState(e.note ?? "");
  useEffect(() => {
    setNeg(e.image_negative ?? "");
    setMusic(e.music ?? "");
    setNote(e.note ?? "");
  }, [shot.id, e.image_negative, e.music, e.note]);
  const save = (patch: Partial<typeof e>, ok: string) => void studio.saveEdit(shot.id, { ...e, ...patch }, { quiet: true }).then((r) => r && studio.notify(ok));
  const take = (slot: Slot) => currentTake(es, d, shot.id, slot);
  const seedRow = (label: string, key: "image_seed" | "last_seed" | "video_seed", slot: Slot) => {
    const cur = e[key] ?? null;
    const t = take(slot);
    return (
      <div className="v3e-kv-row" key={key}>
        <dt>{label}</dt>
        <dd>
          {cur != null ? <b>锁定 {cur}</b> : "随机"}{" "}
          {t && t.seed != null && cur !== t.seed && (
            <button className="v3e-link" onClick={() => save({ [key]: t.seed } as Partial<typeof e>, `已锁种：${label}之后都用 #${t.n} 的种子 ${t.seed}`)} title={`把当前 #${t.n} 的种子写进本镜，之后每次出${label}都用它`}>
              锁定 #{t.n} 的种子
            </button>
          )}{" "}
          {cur != null && (
            <button className="v3e-link" onClick={() => save({ [key]: null } as Partial<typeof e>, `已解锁：${label}种子改回随机`)}>
              解锁
            </button>
          )}
        </dd>
      </div>
    );
  };
  const negBase = d.compiled.image_negative ?? "";
  return (
    <>
      <div className="v3e-fld">
        <span>
          负面词<small>{e.image_negative != null ? "本镜改过" : "用的是编译结果"}</small>
        </span>
        <textarea className="v3e-ta mono" rows={3} value={neg} placeholder={negBase} onChange={(ev) => setNeg(ev.target.value)} />
        <div className="v3e-row-btns">
          <button className="v3e-btn sm" disabled={neg === (e.image_negative ?? "")} onClick={() => save({ image_negative: neg.trim() ? neg : null }, "负面词已保存，下一次出图起用")}>
            保存负面词
          </button>
          {e.image_negative != null && (
            <button className="v3e-btn sm" onClick={() => save({ image_negative: null }, "负面词已恢复成编译结果")}>
              恢复默认
            </button>
          )}
        </div>
      </div>
      <div className="v3e-fld">
        <span>
          种子<small>锁种 = 之后每次出这一格都用同一个种子</small>
        </span>
        <dl className="v3e-kv">
          {seedRow("首帧", "image_seed", "first")}
          {seedRow("尾帧", "last_seed", "last")}
          {seedRow("视频", "video_seed", "video")}
        </dl>
      </div>
      <div className="v3e-fld">
        <span>尾帧从哪来</span>
        <select className="v3e-sel" value={e.last_source ?? "gen"} onChange={(ev) => save({ last_source: ev.target.value as typeof e.last_source, last_frame: ev.target.value === "next" ? "next" : e.last_frame }, "尾帧来源已改")}>
          {LAST_SRC.map(([k, l]) => (
            <option key={k} value={k}>
              {l}
            </option>
          ))}
        </select>
        <div className="v3e-row-btns">
          <button className="v3e-btn sm" disabled={!shot.next_shot || e.last_source === "next"} onClick={() => save({ last_source: "next", last_frame: "next" }, "已设：尾帧 = 下一镜首帧")} title="一键衔接：这一镜的尾帧直接用下一镜的首帧">
            ⛓ 尾帧 = 下一镜首帧
          </button>
          <label className="v3e-btn sm" title="上传一张图作为尾帧的新版本（旧版本都保留）">
            上传尾帧…
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              hidden
              onChange={async (ev) => {
                const f = ev.target.files?.[0];
                ev.target.value = "";
                if (!f) return;
                try {
                  await api.uploadLastFrame(shot.id, f);
                  studio.notify("已上传为尾帧（旧版本都在）");
                  void studio.refreshShots([shot.id]);
                } catch (err) {
                  studio.notify(`上传尾帧失败：${(err as Error).message}`, "err");
                }
              }}
            />
          </label>
        </div>
      </div>
      <div className="v3e-fld">
        <span>
          本镜配乐提示<small>{e.music ? "本镜改过" : "没写就用本集配乐"}</small>
        </span>
        <textarea className="v3e-ta" rows={2} value={music} onChange={(ev) => setMusic(ev.target.value)} />
        <div className="v3e-row-btns">
          <button className="v3e-btn sm" disabled={music === (e.music ?? "")} onClick={() => save({ music: music.trim() ? music : null }, "本镜配乐提示已保存")}>
            保存配乐提示
          </button>
          {e.music && (
            <button className="v3e-btn sm" onClick={() => save({ music: null }, "已恢复：用本集配乐")}>
              恢复默认
            </button>
          )}
        </div>
      </div>
      <div className="v3e-fld">
        <span>本镜备注</span>
        <textarea className="v3e-ta" rows={2} value={note} placeholder="写给自己 / 团队的备注" onChange={(ev) => setNote(ev.target.value)} />
        <div className="v3e-row-btns">
          <button className="v3e-btn sm" disabled={note === (e.note ?? "")} onClick={() => save({ note }, "备注已保存")}>
            保存备注
          </button>
        </div>
      </div>
    </>
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
  const vt = currentTake(es, d, shot.id, "video");
  const vp = (vt?.params ?? {}) as Record<string, unknown>;
  const open = (mode: "regen" | "video") =>
    setEdit(() => ({ loop: { shot: shot.id, slot: mode === "video" ? "video" : slot === "video" ? "first" : slot, mode, parent: mode === "video" ? vt?.n ?? null : null } }));
  return (
    <div className="v3e-scroll v3e-params">
      {/* UIRSI r11：一处看全、一处改；改完直接从这里出新版 */}
      <div className="v3e-params-go">
        <button className="v3e-btn primary sm" onClick={() => open("regen")} title="用下面的出图参数出新的一版（提示词在「提示词」页签改）">
          按这些参数出新的{slot === "video" ? "首帧" : SLOT_NAME[slot]}…
        </button>
        <button className="v3e-btn sm" onClick={() => open("video")} title="视频：种子 / 底模 / 尾帧给法 / 附加 LoRA 在弹窗里逐次选">
          改视频参数重渲…
        </button>
        {/* UIDEBUG #4：旧检查器下线后“上传自己的首帧”没入口了——放回这里（存为新的一版，不覆盖旧版） */}
        <label className="v3e-btn sm" title="上传一张图作为首帧的新版本（旧版本都保留）">
          上传首帧…
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            onChange={async (e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (!f) return;
              try {
                const r = await api.uploadFirstFrame(shot.id, f);
                studio.notify(`已上传为首帧 #${r.n}（旧版本都在）`);
                void studio.refreshShots([shot.id]);
              } catch (err) {
                studio.notify(`上传首帧失败：${(err as Error).message}`, "err");
              }
            }}
          />
        </label>
      </div>
      {/* fredw-92/PX：出图参数（下一次出首帧 / 尾帧用；修改诉求面板不再重复放一份） */}
      <div className="v3e-fld">
        <span>
          出图参数<small>下一次出首帧 / 尾帧用 · Image 2.1</small>
        </span>
        <ImageParamsPanel gpu={es.gpu} />
      </div>
      <div className="v3e-fld">
        <span>
          视频参数<small>{vt ? `当前视频 #${vt.n} 用的；改了要重渲` : "还没有视频"}</small>
        </span>
        {vt ? (
          <dl className="v3e-kv">
            {Object.entries(vp)
              .filter(([, v]) => v != null && typeof v !== "object")
              .slice(0, 12)
              .map(([k, v]) => (
                <div key={k} className="v3e-kv-row">
                  <dt>{k}</dt>
                  <dd>{String(v)}</dd>
                </div>
              ))}
          </dl>
        ) : (
          <div className="v3e-ro">—</div>
        )}
      </div>
      {/* 回退补回（regress_r1 #2 / #10 + 旧检查器）：负面词可改、锁种、尾帧来源、上传尾帧、本镜配乐、本镜备注——都存进本镜修改（ShotEdit），之后每次出图都用 */}
      <PersistPanel shot={shot} />
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
        <span>工作流</span>
        <div className="v3e-ro mono">{t?.workflow ?? "—"}</div>
      </div>
      <div className="v3e-fld">
        <span>
          默认用卡<small>“自动”= 出图优先用出图道、出视频挑空闲的卡</small>
        </span>
        <LaneSelect value={es.gpu} onChange={(g) => setEdit(() => ({ gpu: g }))} kind={slot === "video" ? "video" : "image"} />
      </div>
      <button className="v3e-btn sm" onClick={() => ui.openRefSwitch(shot.id, shot.characters[0] ? { kind: "character", id: shot.characters[0].character } : { kind: "scene" })}>
        切换本镜参考…
      </button>
    </div>
  );
}

export default RightTabs;
