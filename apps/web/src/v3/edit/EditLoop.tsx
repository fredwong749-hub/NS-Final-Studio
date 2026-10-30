// fredw-92/W4b：图片精修循环（§7.1 四种改法）+ 视频改参数重渲（§D）。
// 提示词 / 修改要求是项目方原话：原样发送，不预填、不改写、不检测。
import { useEffect, useMemo, useState } from "react";
import type { ShotSummary } from "../../types";
import { api } from "../../api";
import { useStudio } from "../../store";
import { useUi } from "../ui";
import {
  apiV1, isNotReady, opt, MODE_LABEL, ROLE_LABEL, STRENGTH_LABEL,
  type EditMode, type FrameSlot, type RefRole, type RefSpec, type Strength, type VideoJobBody,
} from "../api_v1";
import { currentTake, etaFor, fmtSec, gpuLabel, setEdit, takeUrl, takesOf, useEdit } from "./state";
import { SLOT_NAME, submitFrame, submitVideo } from "./actions";
import { ExtraVideoLoras, type ExtraLoraPick } from "./ExtraVideoLoras";
import { ImageParamsPanel, paramBody, useParamChoice } from "./ImageParams";

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
  const [gpu, setGpu] = useState<0 | 3>(es.gpu);
  const [busy, setBusy] = useState(false);
  const refs = useRefChoices(id);
  useParamChoice();   // 面板改了 → 重新算摘要
  const pb = paramBody(mode);
  const paramSummary = pb.preset ? ` · ${pb.preset}${pb.params ? ` 改 ${Object.keys(pb.params).length} 项` : ""}` : " · 默认（项目方选定 C）";
  const ui = useUi();

  // 视频参数
  const vt = slot === "video" ? currentTake(es, d, id, "video") : null;
  const vp = vt?.params ?? {};
  const [v, setV] = useState({
    prompt_override: "",
    seed: vp.seed != null ? String(vp.seed) : "",
    steps: vp.steps != null ? String(vp.steps) : "",
    seconds: vp.seconds != null ? String(vp.seconds) : shot.duration?.seconds ? String(shot.duration.seconds) : "",
    lora_strength: vp.lora_strength != null ? String(vp.lora_strength) : "",
  });
  const [xLora, setXLora] = useState<ExtraLoraPick | null>(vp.loras?.[0] ?? null);   // fredw-92/VB

  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);

  const eta = etaFor(slot, gpu, Number(v.seconds) || shot.duration?.seconds);
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
      const body: VideoJobBody = { gpu: gpu as 3 | 0 };
      if (vt) body.parent = vt.n;
      if (v.prompt_override.trim()) body.prompt_override = v.prompt_override;
      for (const k of ["seed", "steps", "seconds", "lora_strength"] as const) {
        const n = num(v[k]);
        if (n !== undefined && !Number.isNaN(n)) body[k] = n;
      }
      if (xLora) body.loras = [xLora];
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
    <div className="v3e-modal" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="v3e-dlg loop" role="dialog" aria-label="修改诉求">
        <header>
          {parentTake && takeUrl(parentTake) ? <img className="v3e-dthumb" src={takeUrl(parentTake)!} alt="" /> : <span className="v3e-dthumb e" />}
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
                title={m === "inpaint" ? "需要新增蒙版流程（视频卡 GPU3 上的蒙版工作流，封板后做）" : undefined}
                onClick={() => setMode(m)}
              >
                {t}
                {m === "inpaint" && <small>需要新增蒙版流程</small>}
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
                        {r.url ? <img src={r.url} alt="" loading="lazy" /> : <span className="e">无图</span>}
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
          {mode === "inpaint" && <div className="v3e-note">局部重绘需要新增蒙版流程（视频卡 GPU3），封板后做。</div>}
          {mode === "video" && (
            <div className="v3e-vform">
              <label className="v3e-fld wide">
                <span>提示词覆盖（不填 = 用当前 H3 提示词原样；填了这一次原样替换）</span>
                <textarea rows={5} value={v.prompt_override} onChange={(e) => setV({ ...v, prompt_override: e.target.value })} />
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
                  <input inputMode="decimal" value={v[k]} placeholder={ph} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
                </label>
              ))}
              <ExtraVideoLoras value={xLora} onChange={setXLora} />
            </div>
          )}
          {mode !== "video" && mode !== "inpaint" && (
            <label className="v3e-fld seed">
              <span>种子（可空 = 随机）</span>
              <input inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder={parentTake ? `上一版 ${parentTake.seed}` : "随机"} />
            </label>
          )}
          {/* fredw-92/PX：出图参数（与右栏「高级」共用同一份选择） */}
          {mode !== "video" && mode !== "inpaint" && (
            <details className="v3e-fold wide">
              <summary>出图参数{paramSummary}</summary>
              <ImageParamsPanel gpu={gpu} mode={mode} />
            </details>
          )}
        </div>

        <footer>
          <label className="v3e-gpu">
            用卡
            <select value={gpu} onChange={(e) => setGpu(Number(e.target.value) as 0 | 3)}>
              <option value={3}>{gpuLabel(3)}</option>
              <option value={0}>{gpuLabel(0)}</option>
            </select>
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
    </div>
  );
}
