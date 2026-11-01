// fredw-92/W4b：图片精修循环（§7.1 四种改法）+ 视频改参数重渲（§D）。
// 提示词 / 修改要求是项目方原话：原样发送，不改写、不检测。
// fredw-92/UXF2（审查 #23 / #24 / #29）：不再是盖住大图的模态框，改成停靠在大格右边的面板（大图一直看得见）；
//   局部重绘标“即将支持”；视频“提示词覆盖”预填当前提示词（没改就不发），试验选项收进“更多”；用卡写真实道名。
import { thumb } from "../../thumb";
import { useEffect, useMemo, useState } from "react";
import type { ShotSummary } from "../../types";
import { api } from "../../api";
import { useStudio } from "../../store";
import { useUi } from "../ui.helpers";
import {
  apiV1, isNotReady, opt, MODE_LABEL, ROLE_LABEL, STRENGTH_LABEL,
  type EditMode, type FrameSlot, type RefRole, type RefSpec, type Strength, type VideoJobBody,
} from "../api_v1";
import { currentTake, etaFor, fmtSec, setEdit, takeUrl, takesOf, useEdit } from "./state";
import { LaneSelect } from "./LaneSelect";
import { laneWait } from "./LaneSelect.helpers";
import { useLanes, type LanePick } from "./lanes";
import { SLOT_NAME, submitFrame, submitVideo } from "./actions";
import { ExtraVideoLoras, type ExtraLoraPick } from "./ExtraVideoLoras";
import { VideoBasePicker } from "./VideoBase";
import { baseFixed, initialBase, useVideoBases } from "./VideoBase.helpers";
import { paramBody, presetLabelOf, useParamChoice } from "./ImageParams.helpers";

type LoopMode = EditMode | "inpaint" | "video";
const MODES: [LoopMode, string][] = [
  ["regen", "改提示词重出"],
  ["instruct", "指令改图"],
  ["refs", "换参考再改"],
  ["inpaint", "局部重绘"],
];

interface RefPick extends RefSpec {
  key: string;
  on: boolean;
}

/** 可选参考：v1 /refs（W5）→ 退回现有 /api/looks/shots/{id}/refs */
function useRefChoices(shot: string) {
  const [list, setList] = useState<RefPick[] | null>(null);
  const [note, setNote] = useState("");
  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const r = await apiV1.shotRefs(shot);
        const out: RefPick[] = [];
        for (const c of r.characters ?? []) {
          (c.effective?.images ?? []).forEach((im, i) => {
            const url = typeof im === "string" ? im : im.url ?? null;
            out.push({ key: `${c.id}:img${i}`, path: url ?? undefined, url, label: `${c.name}${typeof im === "object" && im.label ? ` · ${im.label}` : ""}`, role: i === 0 ? "identity" : "item", on: false });
          });
          for (const [part, opts] of Object.entries(c.options?.parts ?? {})) {
            for (const o of (opts ?? []).map(opt)) {
              out.push({ key: `${c.id}:${part}:${o.id}`, asset_id: o.id, url: o.thumb_url ?? o.url ?? null, label: `${c.name} · ${o.name ?? o.label ?? o.id}`, role: "item", on: false });
            }
          }
        }
        if (!dead) setList(out);
      } catch (e) {
        if (!isNotReady(e)) {
          if (!dead) setNote((e as Error).message);
        }
        try {
          const old = await api.looks.refs(shot);
          if (dead) return;
          setNote("参考切换接口后端未就绪（W5），这里列的是本镜现有参考图");
          setList(
            old.refs
              .filter((r) => r.file)
              .map((r, i) => ({ key: `old${i}`, path: r.file!, url: r.url, label: `${r.name} · ${r.label}`, role: (r.role === "face" || r.role === "identity" ? "identity" : "item") as RefRole, on: false })),
          );
        } catch (e2) {
          if (!dead) {
            setNote(`读取参考失败：${(e2 as Error).message}`);
            setList([]);
          }
        }
      }
    })();
    return () => {
      dead = true;
    };
  }, [shot]);
  return { list, setList, note };
}

export function EditLoop({ shot }: { shot: ShotSummary }) {
  const studio = useStudio();
  const es = useEdit();
  const loop = es.loop!;
  const id = shot.id;
  const d = studio.details[id];
  const [mode, setMode] = useState<LoopMode>(loop.mode);
  const slot = loop.slot;
  const parentTake = useMemo(() => takesOf(d, slot).find((t) => t.n === loop.parent) ?? null, [d, slot, loop.parent]);
  const close = () => setEdit(() => ({ loop: null }));

  // 改提示词重出：显示当前提示词（项目方 / 写作方已有的原文）供改；没改就不发 prompt
  const basePrompt = parentTake?.prompt || (slot === "last" ? d?.edit.last_prompt ?? d?.compiled_last.last_prompt : d?.edit.image_prompt ?? d?.compiled.image_prompt) || "";
  const [prompt, setPrompt] = useState(basePrompt);
  const [instruction, setInstruction] = useState("");
  const [strength, setStrength] = useState<Strength>("medium");
  const [seed, setSeed] = useState("");
  const [gpu, setGpu] = useState<LanePick>(es.gpu);
  const { lanes } = useLanes();
  const [busy, setBusy] = useState(false);
  const refs = useRefChoices(id);
  useParamChoice();   // 面板改了 → 重新算摘要
  const pb = paramBody(mode);
  // UX4：摘要写预设名字（“徕卡 S★（默认）”），不写 id，也不再写过时的“项目方选定 C”
  const pLabel = presetLabelOf(pb.preset);
  const paramSummary = ` · ${pLabel}${!pb.preset && pLabel !== "默认预设" ? "（默认）" : ""}${pb.params ? ` 改 ${Object.keys(pb.params).length} 项` : ""}`;
  const ui = useUi();

  // 视频参数
  const vt = slot === "video" ? currentTake(es, d, id, "video") : null;
  const vp = vt?.params ?? {};
  // 视频提示词：预填（这一版用过的覆盖 > 当前 H3 原文）；和 H3 原文一样就不发（= 用剧本原文）
  const h3Base = shot.h3_prompt ?? d?.compiled.video_prompt ?? "";
  const vpo = (vp as { prompt_override?: string | null }).prompt_override;
  const [v, setV] = useState({
    prompt_override: vpo || h3Base,
    seed: vp.seed != null ? String(vp.seed) : "",
    steps: vp.steps != null ? String(vp.steps) : "",
    seconds: vp.seconds != null ? String(vp.seconds) : shot.duration?.seconds ? String(shot.duration.seconds) : "",
    lora_strength: vp.lora_strength != null ? String(vp.lora_strength) : "",
  });
  const [xLora, setXLora] = useState<ExtraLoraPick | null>(vp.loras?.[0] ?? null);   // fredw-92/VB
  const [vBase, setVBase] = useState<string>(initialBase(vp, !!vt));   // fredw-92/PF：沿用这一版的；没有视频版本 → 配置默认
  const vBases = useVideoBases();
  const vFixed = baseFixed(vBases, vBase);   // Pika Flex：步数 / LoRA 强度固定，不发
  // UX4：尾帧怎么用（video-jobs 的 last_frame_mode，fredw-92/QCV）。默认沿用这一版；老版本没记 = “首尾帧都用”
  const [lfm, setLfm] = useState<"use" | "none" | "auto">(((vp as { last_frame_mode?: string }).last_frame_mode as "use" | "none" | "auto") || "use");
  const vqc = (shot as { video_qc?: { verdict?: string | null; labels?: string[] | null; metrics?: { frozen_tail_s?: number } | null } | null }).video_qc;
  const frozenTail = !!vqc && vqc.verdict !== "pass" && ((vqc.metrics?.frozen_tail_s ?? 0) >= 0.8 || (vqc.labels ?? []).some((l) => l.includes("定住") || l.includes("静止")));

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  const eta0 = etaFor(slot, gpu, Number(v.seconds) || shot.duration?.seconds);
  const eta = { ...eta0, eta: eta0.eta + laneWait(gpu, slot === "video" ? "video" : "image", lanes) };
  const poDirty = v.prompt_override !== h3Base;
  const pickedRefs = (refs.list ?? []).filter((r) => r.on);
  const num = (s: string) => (s.trim() === "" ? undefined : Number(s));

  const canSubmit =
    !busy &&
    (mode === "video" ||
      (mode === "regen" && prompt.trim() !== "") ||
      (mode === "instruct" && instruction.trim() !== "" && parentTake) ||
      (mode === "refs" && pickedRefs.length > 0 && parentTake));

  async function submit() {
    setBusy(true);
    let ok = false;
    if (mode === "video") {
      const body: VideoJobBody = { gpu };
      if (vt) body.parent = vt.n;
      if (v.prompt_override.trim() && poDirty) body.prompt_override = v.prompt_override;
      body.base = vBase;
      for (const k of ["seed", "steps", "seconds", "lora_strength"] as const) {
        if (vFixed && (k === "steps" || k === "lora_strength")) continue;
        const n = num(v[k]);
        if (n !== undefined && !Number.isNaN(n)) body[k] = n;
      }
      if (xLora) body.loras = [xLora];
      body.last_frame_mode = lfm;   // RR：后端默认随基底（official_base = 只给首帧），界面选什么就明确发什么
      ok = await submitVideo(id, body, studio.notify, studio.refreshAfter);
    } else if (mode !== "inpaint") {
      const fs = slot as FrameSlot;
      const body = { stage: fs, mode: mode as EditMode, gpu } as Parameters<typeof submitFrame>[1];
      if (parentTake && mode !== "regen") body.parent = parentTake.n;
      if (parentTake && mode === "regen") body.parent = parentTake.n;
      if (mode === "regen" && prompt !== basePrompt) body.prompt = prompt;
      if (mode === "instruct" || mode === "refs") {
        if (instruction.trim()) body.instruction = instruction;
        body.strength = strength;
      }
      if (mode === "refs") body.refs = pickedRefs.map(({ asset_id, path, role }) => (asset_id ? { asset_id, role } : { path, role }));
      const sd = num(seed);
      if (sd !== undefined && !Number.isNaN(sd)) body.seed = sd;
      ok = await submitFrame(id, body, `${MODE_LABEL[mode]}·${SLOT_NAME[fs]}`, studio.notify, studio.refreshAfter);
    }
    setBusy(false);
    if (ok) close();
  }

  return (
    <aside className="v3e-dock" data-overlay="edit-loop">
      <div className="v3e-dlg loop docked" role="region" aria-label="修改诉求">
        <header>
          {parentTake && takeUrl(parentTake) ? <img className="v3e-dthumb" src={thumb(takeUrl(parentTake)!, 240) ?? takeUrl(parentTake)!} alt="" /> : <span className="v3e-dthumb e" />}
          <div>
            <h3>
              {mode === "video" ? `改参数重渲 · ${id} 视频` : `修改诉求 · ${id} ${SLOT_NAME[slot]}`}
            </h3>
            <div className="sub">
              {mode === "video"
                ? `首尾帧已定稿；不填的参数用渲染器默认${vt ? `，基于视频 #${vt.n}` : ""}`
                : parentTake
                  ? `作用在 ${SLOT_NAME[slot]} #${parentTake.n} 上；改完生成新的一版，挂在 #${parentTake.n} 下面（可对比、回退、继续改）`
                  : "这一格还没有图：只能改提示词整张出"}
            </div>
          </div>
          <button className="v3e-x" onClick={close} aria-label="关闭">
            ×
          </button>
        </header>

        {mode !== "video" && (
          <div className="v3e-seg">
            {MODES.map(([m, t]) => (
              <button
                key={m}
                className={mode === m ? "on" : ""}
                disabled={m === "inpaint" || (m !== "regen" && !parentTake)}
                title={m === "inpaint" ? "局部重绘（画蒙版只改一块）即将支持" : undefined}
                onClick={() => setMode(m)}
              >
                {t}
                {m === "inpaint" && <small>即将支持</small>}
              </button>
            ))}
          </div>
        )}

        <div className="v3e-dbody">
          {mode === "regen" && (
            <label className="v3e-fld">
              <span>{SLOT_NAME[slot]}提示词（原样发给 Image 2.1，整张重新生成）</span>
              <textarea rows={9} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
              <small>{prompt === basePrompt ? "没改动：按当前提示词重出" : "已改动：这次用改后的提示词；要长期保存请在右栏「提示词」里保存"}</small>
            </label>
          )}
          {(mode === "instruct" || mode === "refs") && (
            <>
              <label className="v3e-fld">
                <span>{mode === "instruct" ? "修改要求（原话原样传，保留构图只改指定内容）" : "修改要求（可不填；各参考图用途按下面的标注排成 图1、图2…）"}</span>
                <textarea rows={4} value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="写下要怎么改" />
              </label>
              <div className="v3e-fld">
                <span>改动幅度</span>
                <div className="v3e-seg sm">
                  {(Object.keys(STRENGTH_LABEL) as Strength[]).map((s) => (
                    <button key={s} className={strength === s ? "on" : ""} onClick={() => setStrength(s)}>
                      {STRENGTH_LABEL[s]}
                    </button>
                  ))}
                </div>
                <small>小 = 只动细节；中 = 改指定内容；大 = 允许大改（构图可能变）</small>
              </div>
            </>
          )}
          {mode === "refs" && (
            <div className="v3e-fld">
              <span>
                新参考（图1 = 当前图 #{parentTake?.n}；勾选的依次为 图2、图3…）
                <button className="v3e-link" onClick={() => ui.openRefSwitch(id, shot.characters?.[0] ? { kind: "character", id: shot.characters[0].character } : { kind: "scene" })}>
                  去切换本镜参考 →
                </button>
              </span>
              {refs.note && <small className="warn">{refs.note}</small>}
              {refs.list == null ? (
                <small>读取参考…</small>
              ) : refs.list.length === 0 ? (
                <small>没有可选参考</small>
              ) : (
                <div className="v3e-refgrid">
                  {refs.list.map((r) => (
                    <div key={r.key} className={`v3e-refpick ${r.on ? "on" : ""}`}>
                      <button
                        className="im"
                        onClick={() => refs.setList((l) => l!.map((x) => (x.key === r.key ? { ...x, on: !x.on } : x)))}
                        title={r.label}
                      >
                        {r.url ? <img src={thumb(r.url, 240) ?? r.url} alt="" loading="lazy" /> : <span className="e">无图</span>}
                        {r.on && <i>图{pickedRefs.findIndex((p) => p.key === r.key) + 2}</i>}
                      </button>
                      <div className="nm">{r.label}</div>
                      <select value={r.role} onChange={(e) => refs.setList((l) => l!.map((x) => (x.key === r.key ? { ...x, role: e.target.value as RefRole } : x)))}>
                        {(Object.keys(ROLE_LABEL) as RefRole[]).map((k) => (
                          <option key={k} value={k}>
                            取{ROLE_LABEL[k]}
                          </option>
                        ))}
                      </select>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {mode === "inpaint" && <div className="v3e-note">局部重绘即将支持。</div>}
          {mode === "video" && (
            <div className="v3e-vform">
              <label className="v3e-fld wide">
                <span>
                  视频提示词（这一次原样发送；不改 = 用剧本原文）
                  {poDirty && (
                    <button className="v3e-link" onClick={() => setV({ ...v, prompt_override: h3Base })}>
                      还原成剧本原文
                    </button>
                  )}
                </span>
                <textarea rows={8} className={poDirty ? "dirty" : ""} value={v.prompt_override} onChange={(e) => setV({ ...v, prompt_override: e.target.value })} />
                <small>{poDirty ? "已改动：只这一次用改过的提示词，不改剧本" : "没改动：按剧本原文出"}</small>
              </label>
              {(
                [
                  ["seed", "种子", "随机"],
                  ["steps", "步数", "默认"],
                  ["seconds", "秒数", "默认"],
                  ["lora_strength", "LoRA 强度", "默认"],
                ] as const
              ).map(([k, t, ph]) => (
                <label key={k} className="v3e-fld">
                  <span>{t}</span>
                  {vFixed && (k === "steps" || k === "lora_strength") ? (
                    <input disabled value="" placeholder="这个出片方式不用填" />
                  ) : (
                    <input inputMode="decimal" value={v[k]} placeholder={ph} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
                  )}
                </label>
              ))}
              {/* UX4：尾帧用法放在主表单（和“静止·不合格 / 结尾定住”质检角标对上），出片方式（视频基底）也提出来，人话写清楚 */}
              <div className="v3e-fld wide">
                <span>
                  <b style={{ whiteSpace: "nowrap", fontWeight: "inherit", flex: "none" }}>尾帧怎么用</b>
                  <small className={frozenTail ? "warn" : undefined}>
                    {frozenTail
                      ? `这一版质检：${(vqc?.labels ?? []).join("、") || "结尾定住"}。可以试“只用首帧”或“自动”，让结尾不被尾帧拉住`
                      : "默认首尾帧都给：视频从首帧走到尾帧"}
                  </small>
                </span>
                <div className="v3e-seg sm">
                  {(
                    [
                      ["use", "首尾帧都用", "视频从定稿首帧走到定稿尾帧（默认）"],
                      ["none", "只用首帧", "不给尾帧：动作更自由，结尾不会被拉回尾帧定住；画面终点不保证和尾帧一样"],
                      ["auto", "自动", "首尾帧几乎一样时只给首帧（避免整段定住），不一样时首尾帧都给"],
                    ] as const
                  ).map(([k, t, tip]) => (
                    <button key={k} className={lfm === k ? "on" : ""} onClick={() => setLfm(k)} title={tip}>
                      {t}
                    </button>
                  ))}
                </div>
              </div>
              <VideoBasePicker value={vBase} onChange={setVBase} />
              <details className="v3e-fold wide" open={!!xLora || undefined}>
                <summary>更多（试验选项：附加 LoRA）</summary>
                <ExtraVideoLoras value={xLora} onChange={setXLora} />
              </details>
            </div>
          )}
          {mode !== "video" && mode !== "inpaint" && (
            <label className="v3e-fld seed">
              <span>种子（可空 = 随机）</span>
              <input inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder={parentTake ? `上一版 ${parentTake.seed}` : "随机"} />
            </label>
          )}
          {/* UIRSI r11（D12）：出图参数只在右栏「参数」一处改；这里写这次会用的参数摘要 */}
          {mode !== "video" && mode !== "inpaint" && (
            <div className="v3e-fld wide">
              <span>出图参数</span>
              <div className="v3e-ro">
                这次用{paramSummary.replace(/^ · /, "：")}
                <button className="v3e-link" onClick={() => ui.setRightTab("advanced")} title="在右栏「参数」里改（和这里同一份）">
                  去「参数」改 ›
                </button>
              </div>
            </div>
          )}
        </div>

        <footer>
          <label className="v3e-gpu">
            用卡
            <LaneSelect value={gpu} onChange={setGpu} kind={slot === "video" ? "video" : "image"} frames={shot.h3_frames} />
          </label>
          <span className="eta">
            预计约 {fmtSec(eta.eta)}
            {eta.queue ? `（前面 ${eta.queue} 个）` : ""} · 排队中可取消
          </span>
          <span className="sp" />
          <button className="v3e-btn" onClick={close}>
            取消
          </button>
          <button className="v3e-btn primary" disabled={!canSubmit} onClick={() => void submit()}>
            {busy ? "提交中…" : mode === "video" ? "重渲视频" : "生成新的一版"}
          </button>
        </footer>
      </div>
    </aside>
  );
}
