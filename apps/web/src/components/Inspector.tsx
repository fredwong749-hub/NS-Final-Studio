import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { useStudio, type InspectorTab } from "../store";
import type { ShotDetail, ShotEdit, Stage, Take } from "../types";
import { fmtTime, isFailed, JOB_LABEL, joinReason, LAST_SOURCE_LABEL, parseReason, REJECT_CODES, REVIEW_LABEL, segDiff, STAGE_LABEL, stageActive, stageTakes } from "../util";
import { AUDIO_SOURCE_LABEL, CUE_EXAMPLE, CUE_HINT, H3_MUSIC_HINT, MUSIC_SOURCE_LABEL, SOUNDSCAPE_EXAMPLE, SOUNDSCAPE_HINT } from "../audio";
import { LooksSection } from "./LooksSection";
import { WatchVideo } from "./Player";
import { RefGroup } from "./RefGroup";
import { JobBar, Score } from "./frames";
import { PersonRow } from "./ShotCard";
import { ReadinessList } from "./ShotRow";

// ---------- 表单：字段用字符串保存，保存时再转换 ----------
const FORM_KEYS = [
  "expression", "image_prompt", "image_negative", "video_prompt", "note", "image_seed", "video_seed", "last_frame",
  "last_prompt", "last_seed", "last_source", "boost_first", "boost_last", "cam_size", "cam_angle", "cam_move", "cam_lens",
  "soundscape", "music",
] as const;
type FormKey = (typeof FORM_KEYS)[number];
type Form = Record<FormKey, string>;

function toForm(e: ShotEdit, d: ShotDetail): Form {
  const cam = d.summary.camera;
  const ce = (k: "size" | "angle" | "move" | "lens") => (cam.sources[k] === "edit" ? cam[k] : "");
  return {
    expression: e.expression ?? "",
    image_prompt: e.image_prompt ?? "",
    image_negative: e.image_negative ?? "",
    video_prompt: e.video_prompt ?? "",
    note: e.note ?? "",
    image_seed: e.image_seed == null ? "" : String(e.image_seed),
    video_seed: e.video_seed == null ? "" : String(e.video_seed),
    last_frame: e.last_frame ?? "",
    last_prompt: e.last_prompt ?? "",
    last_seed: e.last_seed == null ? "" : String(e.last_seed),
    last_source: e.last_source ?? "",
    boost_first: e.boost_first ?? "",
    boost_last: e.boost_last ?? "",
    soundscape: e.soundscape ?? "",
    music: e.music ?? "",
    cam_size: ce("size"),
    cam_angle: ce("angle"),
    cam_move: ce("move"),
    cam_lens: ce("lens"),
  };
}

export function parseSeed(v: string, label: string): number | null {
  const t = v.trim();
  if (!t) return null;
  if (!/^\d+$/.test(t) || !Number.isSafeInteger(Number(t))) throw new Error(`${label}必须是非负整数`);
  return Number(t);
}

function fromForm(f: Form, base: ShotEdit): ShotEdit {
  const s = (v: string) => (v.trim() ? v : null);
  // 运镜四字段按「景别，机位，运镜，焦段」拼进 camera；后端按同一规则拆回，没写的字段仍用自动解析
  const camera = [f.cam_size, f.cam_angle, f.cam_move, f.cam_lens].map((x) => x.trim()).filter(Boolean).join("，");
  return {
    ...base,
    camera: camera || null,
    expression: s(f.expression),
    image_prompt: s(f.image_prompt),
    image_negative: s(f.image_negative),
    video_prompt: s(f.video_prompt),
    note: f.note,
    image_seed: parseSeed(f.image_seed, "首帧种子"),
    video_seed: parseSeed(f.video_seed, "视频种子"),
    last_frame: s(f.last_frame),
    last_prompt: s(f.last_prompt),
    last_seed: parseSeed(f.last_seed, "尾帧种子"),
    last_source: (s(f.last_source) as ShotEdit["last_source"]) ?? null,
    boost_first: s(f.boost_first),
    boost_last: s(f.boost_last),
    soundscape: s(f.soundscape),
    music: s(f.music),
  };
}

const sameForm = (a: Form, b: Form) => FORM_KEYS.every((k) => a[k] === b[k]);

const SIZE_PRESETS = ["大远景", "远景", "全景", "中全景", "中景", "中近景", "近景", "特写", "极近特写", "大特写"];
const ANGLE_PRESETS = ["平视", "低机位", "低机位仰拍", "高机位俯拍", "俯拍", "仰拍", "顶拍", "侧拍", "背影", "过肩", "主观视角"];
const MOVE_PRESETS = [
  "static camera 固定", "camera push in 缓慢推近", "camera pull back 缓慢拉远", "camera tilt up 缓慢上摇", "camera tilt down 缓慢下摇",
  "camera pan left 左摇", "camera pan right 右摇", "handheld follow 轻微手持", "tracking shot 跟拍", "orbit 环绕", "slow motion 慢动作",
];
const LENS_PRESETS = ["24mm", "35mm", "50mm", "85mm", "135mm", "广角", "长焦", "微距"];

const TABS: [InspectorTab, string][] = [
  ["first", "首帧"],
  ["last", "尾帧"],
  ["video", "视频"],
  ["script", "剧本"],
  ["people", "人物"],
  ["boost", "导演加强"],
  ["review", "审核"],
];

// ---------- 小组件 ----------
function KV({ k, v }: { k: string; v: ReactNode }) {
  if (v == null || v === "" || (Array.isArray(v) && v.length === 0)) return null;
  return (
    <div className="kv">
      <div className="kv-k">{k}</div>
      <div className="kv-v">{v}</div>
    </div>
  );
}

function Field({ label, hint, children, action }: { label: string; hint?: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="field">
      <span className="field-label">
        {label}
        {hint && <span className="field-hint">{hint}</span>}
        {action}
      </span>
      {children}
    </div>
  );
}

function Diff({ from, to }: { from: string; to: string }) {
  if (!to.trim() || from === to) return null;
  return (
    <div className="diff" title="与当前编译结果的差异：绿 = 新增，红 = 删除">
      {segDiff(from, to).map((p, i) => (
        <span key={i} className={`d-${p.op}`}>
          {p.text}
        </span>
      ))}
    </div>
  );
}

/** 把一段文字里的加强原文高亮出来（看清加强落在哪） */
function Highlight({ text, marks }: { text: string; marks: (string | null | undefined)[] }) {
  const ms = marks.filter((m): m is string => !!m && text.includes(m));
  if (!ms.length) return <>{text}</>;
  const parts: ReactNode[] = [];
  let rest = text;
  let k = 0;
  while (rest) {
    const hit = ms
      .map((m) => [rest.indexOf(m), m] as const)
      .filter(([i]) => i >= 0)
      .sort((a, b) => a[0] - b[0])[0];
    if (!hit) {
      parts.push(rest);
      break;
    }
    parts.push(rest.slice(0, hit[0]));
    parts.push(
      <mark key={k++} className="boost-mark">
        {hit[1]}
      </mark>,
    );
    rest = rest.slice(hit[0] + hit[1].length);
  }
  return <>{parts}</>;
}

const H3_SOURCE_CHIP: Record<string, string> = { gpu3: "chip-ok", script: "chip-accent", laptop: "chip-warn" };

/** H3 提示词（SOP §9A.1 官方 FL2VA 四块）：对齐句与配乐 N/A 固定；只有项目方能改正文与环境声（需填确认原话） */
function H3Panel({ s, id, notify, refresh }: { s: ShotDetail["summary"]; id: string; notify: (m: string, k?: "ok" | "err") => void; refresh: () => Promise<void> | void }) {
  const b = s.h3_blocks;
  const base = s.h3_edit_base ?? b;
  const baseBody = (base?.body ?? "").replace(/^\[Shot 1\]\s*/, "");
  const baseSound = base?.soundscape ?? "";
  const [body, setBody] = useState(baseBody);
  const [sound, setSound] = useState(baseSound);
  const [note, setNote] = useState("");
  // E7④：原话改为可选；勾选“我是项目方”即可保存，记录里写明是勾选确认
  const [owner, setOwner] = useState(false);
  const [busy, setBusy] = useState(false);
  const [undelivered, setUndelivered] = useState<string | null>(null);
  useEffect(() => {
    setBody(baseBody);
    setSound(baseSound);
  }, [baseBody, baseSound]);
  const confirmNote = () => (note.trim() ? note.trim() : `项目方在画布勾选确认（${new Date().toLocaleString("zh-CN", { hour12: false })}）`);
  if (!b) return <div className="muted small">后端还没有下发 H3 提示词（h3_prompt）：请重启画布 API</div>;
  const lint = s.h3_lint ?? [];
  const ov = s.h3_override;
  const missing = s.h3_missing ?? [];
  const failed = lint.filter((r) => !r.ok && r.level === "block" && !r.overridden);
  const changed = body !== baseBody || sound !== baseSound;
  const send = async (clear: boolean) => {
    if (!owner) {
      notify("请先勾选“我是项目方，确认这次修改”", "err");
      return;
    }
    const n = confirmNote();
    setBusy(true);
    try {
      // 封板修复：带上画布显示的提示词 sha（gpu3 判过期 409）
      const r = await api.putH3Override(
        id,
        clear ? { note: n, clear: true } : { body: body !== baseBody ? body : null, soundscape: sound !== baseSound ? sound : null, note: n, base_sha: s.h3_prompt_sha256 ?? null },
      );
      // 封板修复：未送达 gpu3 不能报“可出视频”，给重发按钮
      const lost = !clear && r.delivered === false;
      setUndelivered(lost ? (r.delivery?.error ?? "gpu3 桥不可达或拒绝") : null);
      if (lost) notify(`H3 已存本地，但未送达 gpu3：${r.delivery?.error ?? "桥不可达或拒绝"}（可勾选项目方后点“重发 gpu3”）`, "err");
      else notify(clear ? "已撤销 H3 画布修改" : r.status === "renderable" ? "H3 提示词已保存（通过 §9A，可出视频）" : `已存为草稿：未通过 ${(r.failed ?? []).join("、")}`, !clear && r.status !== "renderable" ? "err" : "ok");
      setNote("");
      setOwner(false);
      await refresh();
    } catch (e) {
      notify(`保存失败：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };
  const resend = async () => {
    if (!owner) return notify("请先勾选“我是项目方，确认这次修改”", "err");
    setBusy(true);
    try {
      const r = await api.gpu3Resend(id, "h3_edit");
      setUndelivered(r.delivered ? null : (r.delivery?.error ?? "gpu3 桥不可达或拒绝"));
      notify(r.delivered ? "已重发到 gpu3" : `重发仍未送达 gpu3：${r.delivery?.error ?? "桥不可达或拒绝"}`, r.delivered ? "ok" : "err");
      setOwner(false);
      await refresh();
    } catch (e) {
      notify(`重发失败：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="h3-panel">
      <div className="h3-head">
        <span className="audio-title">H3 提示词（官方格式）</span>
        <span className={`chip ${H3_SOURCE_CHIP[s.h3_prompt_source ?? "laptop"] ?? "chip-dark"}`} title={s.h3_prompt_where}>
          {s.h3_prompt_source_label}
        </span>
        <span
          className={`chip ${s.duration?.source === "script" ? "chip-dark" : "chip-warn"}`}
          title={`${s.duration?.source === "script" ? "剧本 **时长** 写明" : "剧本没写时长，按默认 10 秒"}；H3 帧数按 17k+5 网格（124–362 帧，24 fps）取档，请求里的帧数 = 这里的帧数`}
        >
          时长 {s.duration?.seconds ?? 10} 秒{s.duration?.source === "script" ? "" : "（剧本未写·默认）"} → H3 {s.h3_frames} 帧 ≈ {s.h3_sss ?? (s.h3_frames ? (s.h3_frames / 24).toFixed(2) : "—")} 秒
        </span>
        <span className={`chip ${s.h3_lint_ok ? "chip-ok" : "chip-bad"}`}>{s.h3_lint_ok ? "§9A 机检通过" : `§9A 未通过 ${failed.length} 条`}</span>
        {s.h3_override_stale && (
          <span className="chip chip-bad" title="保存修改之后剧本 **H3提示词** 又更新了：请重新确认或撤销">
            剧本已更新·需重新确认
          </span>
        )}
      </div>
      <div className="h3-lint" title="悬停看说明；黄 = warn（待验证规则，不拦截）；灰 = 项目方原话豁免">
        {lint.map((r) => (
          <span
            key={r.rule_id}
            className={`chip ${r.ok ? "chip-ok" : r.overridden ? "chip-dark" : r.level === "warn" ? "chip-warn" : "chip-bad"}`}
            title={`${r.rule_id}（${r.sop_ref}，${r.level}${r.overridden ? "，已豁免" : ""}）：${r.detail}`}
          >
            {r.ok ? "✓" : "✗"} {r.rule_id}
          </span>
        ))}
      </div>
      {missing.length > 0 && (
        <div className="warn small">
          剧本没有英文{missing.includes("body") ? "正文" : ""}
          {missing.includes("body") && missing.includes("soundscape") ? "和" : ""}
          {missing.includes("soundscape") ? "环境声" : ""}：这里先放剧本中文原文占位（不机翻）。H3-A7 需要英文正文（剧本 v3 提供 **H3提示词**）
        </div>
      )}
      {ov && (
        <div className={`small ${ov.status === "renderable" ? "muted" : "warn"}`}>
          项目方修改 {ov.at ?? ""}：「{ov.note}」· {ov.status === "renderable" ? "通过 §9A，gpu3 可出视频" : `草稿（未通过 ${ov.failed.join("、")}，S4 仍阻塞）`}
        </div>
      )}
      <div className="h3-block">
        <div className="h3-k">
          对齐句 <span className="field-hint">自动生成，不可改（S.SS = 帧数 / 24）</span>
        </div>
        <div className="final-prompt h3-fixed">{b.alignment}</div>
      </div>
      <div className="h3-block">
        <div className="h3-k">当前生效的正文与环境声</div>
        <div className="final-prompt">
          <b>[Shot 1]</b> {b.body.replace(/^\[Shot 1\]\s*/, "")}
          <br />
          <b>overall_soundscape:</b> {b.soundscape}
        </div>
      </div>
      <Field label="integrated_multimodal_description: [Shot 1]" hint="英文正文；台词写 (S1) … <d>[Chinese] 原文</d>；不写否定句、不加图像风格后缀">
        <textarea data-field="h3_body" rows={7} value={body} onChange={(e) => setBody(e.target.value)} />
        <Diff from={baseBody} to={body !== baseBody ? body : ""} />
      </Field>
      <Field label="overall_soundscape" hint="1–4 句英文：环境声、动作声、非语言人声；不写台词、不写否定句">
        <textarea data-field="soundscape" rows={3} value={sound} onChange={(e) => setSound(e.target.value)} placeholder={SOUNDSCAPE_EXAMPLE} />
        <div className="audio-hint">{SOUNDSCAPE_HINT}</div>
      </Field>
      <div className="h3-block">
        <div className="h3-k">
          non_diegetic_music{" "}
          <span className="chip chip-dark" title="取值顺序：本镜人工 > 剧本 H3 自带 > 本集默认 > N/A">
            {MUSIC_SOURCE_LABEL[s.h3_music_source ?? "none"] ?? s.h3_music_source}
          </span>{" "}
          <span className="field-hint">在下方「配乐」改（英文进 H3）</span>
        </div>
        <div className="final-prompt h3-fixed">{b.music || "N/A"}</div>
      </div>
      <div className="h3-confirm">
        <label title="只有项目方本人能保存 H3 修改；未通过 §9A 的只存为草稿">
          <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} /> 我是项目方，确认这次修改
        </label>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="原话（可选）：例 正文按这个改，可以出" />
      </div>
      <div className="h3-actions">
        <button className="btn" disabled={busy || !changed || !owner} onClick={() => send(false)}>
          保存 H3
        </button>
        {ov && (
          <button className="btn-mini" disabled={busy || !owner} onClick={() => send(true)} title="撤销画布修改，回到剧本 / 笔记本草稿">
            撤销画布修改
          </button>
        )}
        {changed && (
          <button
            className="btn-mini"
            disabled={busy}
            onClick={() => {
              setBody(baseBody);
              setSound(baseSound);
            }}
          >
            放弃未保存的改动
          </button>
        )}
        {undelivered && (
          <button className="btn-mini" disabled={busy || !owner} onClick={() => void resend()} title="原样重发已保存的 H3 修改到 gpu3（需勾选项目方）">
            重发 gpu3
          </button>
        )}
      </div>
      {undelivered && <div className="warn small">H3 修改已存本地，未送达 gpu3：{undelivered}</div>}
      {s.h3_take && (
        <div className="muted small" title={s.h3_take.prompt}>
          gpu3 视频 v{s.h3_take.n} 实际提示词 sha256 {s.h3_take.prompt_sha256?.slice(0, 12)}…
          {s.h3_take.prompt_sha256_source === "computed" ? "（画布计算）" : ""}
          {s.h3_take.is_h3 ? "" : "：旧链提示词，不符合 §9A（只作历史）"}
        </div>
      )}
      <details className="more">
        <summary>完整 H3 提示词</summary>
        <pre className="final-prompt h3-full">{s.h3_prompt}</pre>
      </details>
      {s.legacy_video_prompt && (
        <details className="more">
          <summary>旧版视频提示词（legacy，只作历史，不进 H3）</summary>
          <div className="final-prompt muted">{s.legacy_video_prompt}</div>
        </details>
      )}
    </section>
  );
}

function SeedField({ label, value, onChange, activeSeed }: { label: string; value: string; onChange: (v: string) => void; activeSeed: number | undefined }) {
  const locked = value.trim() !== "";
  return (
    <Field
      label={label}
      action={
        <label className="lock-seed" title="锁种：把种子写进修改，之后的渲染都用这个种子">
          <input type="checkbox" checked={locked} onChange={(e) => onChange(e.target.checked ? String(activeSeed ?? "") : "")} /> 锁种
        </label>
      }
    >
      <input value={value} onChange={(e) => onChange(e.target.value)} inputMode="numeric" placeholder={activeSeed != null ? `当前版本 ${activeSeed}（不锁则随机）` : "随机"} />
    </Field>
  );
}

const STAGE_WORD: Record<Stage, string> = { image: "首帧", last: "尾帧", video: "视频" };

/** 对比位：左 = 当前版本，右 = 候选（最新的非当前版本，或在版本条里点选的）；
 *  正在渲染时右侧显示进度，完成后新版本自动出现在右侧 → 设为当前 一键 */
function TakeCompare({ d, stage }: { d: ShotDetail; stage: Stage }) {
  const { preview, setPreview, activate, openViewer, liveJob } = useStudio();
  const s = d.summary;
  const id = s.id;
  // gpu3 负责的镜头：看 gpu3 版本链（只读，当前由 gpu3 决定）；否则笔记本 takes
  const list = stageTakes(d, stage);
  const activeN = stageActive(d, stage);
  const readOnly = !!d.gpu3_takes;
  const cur = list.find((t) => t.n === activeN);
  const newest = [...list].reverse().find((t) => t.n !== activeN);
  const picked =
    preview && preview.shotId === id && preview.stage === stage ? list.find((t) => t.n === preview.n && t.n !== activeN) : undefined;
  const cand = picked ?? newest;
  const latestN = list.at(-1)?.n;
  const seen = useRef(latestN);
  useEffect(() => {
    // 新版本到了：回到「最新候选」
    if (seen.current !== latestN) {
      seen.current = latestN;
      if (preview?.shotId === id && preview.stage === stage) setPreview(null);
    }
  }, [latestN, preview, id, stage, setPreview]);
  const live = liveJob(id, stage);
  const fresh = !!(cand && (!cur || cand.n > cur.n));
  const word = STAGE_WORD[stage];
  // 尾帧的当前值可能不是生成版本（下一镜首帧 / 上传 / 视频抽帧）
  const curUrl = stage === "video" ? s.video : stage === "image" ? s.first_frame : s.last_frame_target;
  const curSrc = stage === "last" && s.last_frame_source && s.last_frame_source !== "gen" ? LAST_SOURCE_LABEL[s.last_frame_source] : null;
  const view = (n?: number | null) => stage !== "video" && openViewer(id, stage, cand ? "ab" : "pair", n ?? null);

  const media = (url: string | null | undefined, t: Take | undefined, isCur: boolean) => {
    if (!url) return <div className="tc-empty">还没有{word}</div>;
    if (stage === "video")
      return isCur ? <WatchVideo id="main-player" src={url} poster={s.first_frame} /> : <video src={url} controls playsInline poster={t?.last_url ?? undefined} />;
    return <img src={url} alt="" onClick={() => view(t && !isCur ? t.n : cand?.n)} title="点击全屏对比" />;
  };

  return (
    <section className="tc">
      <div className="tc-pair">
        <figure className="tc-slot cur">
          <figcaption>
            <b>当前</b>
            {cur && <span className="chip chip-dark">v{cur.n}</span>}
            {curSrc && <span className="chip chip-dark">{curSrc}</span>}
            <Score sc={cur?.score} />
            {(s.stale[stage] ?? []).length > 0 && (
              <span className="chip chip-warn" title={(s.stale[stage] ?? []).join("、")}>
                过期
              </span>
            )}
          </figcaption>
          {media(curUrl, cur, true)}
        </figure>
        <figure className={`tc-slot cand${fresh ? " fresh" : ""}`}>
          {live ? (
            <>
              <figcaption>
                <b>新版本</b>
                <span className="chip chip-busy">{live.gpu3 ? "已请 gpu3" : live.job.state === "running" ? "渲染中" : "排队"}</span>
              </figcaption>
              <div className="tc-pending">
                <JobBar live={live} />
                <span className="muted">{live.gpu3 ? `gpu3 出完新 take 后自动出现在这里（每 30 s 查一次）` : `完成后新${word}自动出现在这里`}</span>
              </div>
            </>
          ) : cand ? (
            <>
              <figcaption>
                <b>{fresh ? "新版本" : "候选"}</b>
                <span className="chip chip-accent">v{cand.n}</span>
                <Score sc={cand.score} />
                {cand.qc?.nudity && <span className="chip chip-bad">质检未过</span>}
              </figcaption>
              {media(stage === "video" ? cand.url : cand.url, cand, false)}
            </>
          ) : (
            <>
              <figcaption>
                <b>候选</b>
              </figcaption>
              <div className="tc-empty dashed">
                改下面的提示词，点「重出{word}」
                <br />
                新版本会出现在这里，和当前并排对比
              </div>
            </>
          )}
        </figure>
      </div>
      {cand && !live && (
        <div className="tc-actions">
          {readOnly ? (
            <span className="chip chip-src-gpu3" title="gpu3 负责此镜：当前版本由 gpu3 决定；画布“设为当前”待 gpu3 侧接口（POST /api/shots/{id}/gpu3-activate）">
              gpu3 版本（只读）
            </span>
          ) : (
            <button className="btn primary" disabled={!!cand.qc?.nudity} onClick={() => void activate(id, stage, cand.n)} title="Shift+Enter">
              设 v{cand.n} 为当前 <kbd>Shift+Enter</kbd>
            </button>
          )}
          {stage !== "video" && (
            <button className="btn" onClick={() => view(cand.n)}>
              全屏对比 <kbd>C</kbd>
            </button>
          )}
          {cand.prompt && cur?.prompt && cand.prompt !== cur.prompt && (
            <details className="tc-diff">
              <summary>提示词差异</summary>
              <div className="diff">
                {segDiff(cur.prompt, cand.prompt).map((x, i) => (
                  <span key={i} className={`d-${x.op}`}>
                    {x.text}
                  </span>
                ))}
              </div>
            </details>
          )}
        </div>
      )}
      {list.length > 0 && (
        // 版本条默认折叠（总调度 / 前端返工 audit：改词→重出→对比→选定要一屏完成），点开选候选
        <details className="tc-strip-wrap">
          <summary className="muted">
            全部{word}版本 {list.length} 个（点开选候选）
          </summary>
        <div className="tc-strip">
          {[...list].reverse().map((t) => {
            const thumb = stage === "video" ? t.last_url : t.url;
            return (
              <button
                key={t.n}
                className={`tc-thumb${t.n === activeN ? " cur" : ""}${t.n === cand?.n ? " on" : ""}`}
                onClick={() => (t.n === activeN ? setPreview(null) : setPreview({ shotId: id, stage, n: t.n }))}
                title={`v${t.n} · 种子 ${t.seed} · ${fmtTime(t.created_at)}${t.n === activeN ? "（当前）" : " · 点击放到候选位"}`}
              >
                {thumb ? <img src={thumb} alt="" loading="lazy" /> : <span className="muted">v{t.n}</span>}
                <i>v{t.n}</i>
              </button>
            );
          })}
        </div>
        </details>
      )}
    </section>
  );
}

function ReviewBox({ d }: { d: ShotDetail }) {
  const { setReview, canPass } = useStudio();
  const s = d.summary;
  const cur = parseReason(s.review.reason);
  const [code, setCode] = useState(cur.code || "画面");
  const [note, setNote] = useState(cur.note);
  useEffect(() => {
    const r = parseReason(s.review.reason);
    setCode(r.code || "画面");
    setNote(r.note);
  }, [s.id, s.review.reason]);
  const passOk = canPass(s);
  return (
    <div className="review-box">
      <div>
        状态：<span className={`review-badge r-${s.review.state}`}>{REVIEW_LABEL[s.review.state]}</span>
        {s.review.reason && <span className="muted"> {s.review.reason}</span>}
        {s.review.at && <span className="muted"> · {fmtTime(s.review.at)}</span>}
      </div>
      <div className="row-actions">
        <select value={code} onChange={(e) => setCode(e.target.value)}>
          {REJECT_CODES.map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
        <input className="grow" placeholder="打回备注（可选）" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn bad" onClick={() => void setReview([s.id], "rejected", joinReason(code, note))}>
          打回
        </button>
        {s.review.state !== "unreviewed" && (
          <button className="btn-mini" onClick={() => void setReview([s.id], "unreviewed")}>
            重置
          </button>
        )}
      </div>
      {!passOk && <div className="muted small">通过前需完整看过一遍当前视频（播放到结尾）。</div>}
      {Object.keys(s.needs_review ?? {}).length > 0 && (
        <div className="warn small">
          渲染器标记需复核：
          {Object.keys(s.needs_review)
            .map((k) => STAGE_LABEL[k] ?? k)
            .join("、")}
        </div>
      )}
    </div>
  );
}

/** 画面说明（visual_spec）：通用 JSON 渲染，嵌套对象逐层展开 */
function SpecView({ v }: { v: unknown }): ReactNode {
  if (v == null || v === "") return <span className="muted">—</span>;
  if (Array.isArray(v)) {
    if (!v.length) return <span className="muted">—</span>;
    if (v.every((x) => typeof x !== "object")) return <>{v.join("、")}</>;
    return (
      <ol className="spec-list">
        {v.map((x, i) => (
          <li key={i}>
            <SpecView v={x} />
          </li>
        ))}
      </ol>
    );
  }
  if (typeof v === "object")
    return (
      <dl className="spec">
        {Object.entries(v as Record<string, unknown>)
          .filter(([, x]) => x != null && x !== "" && !(Array.isArray(x) && !x.length))
          .map(([k, x]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>
                <SpecView v={x} />
              </dd>
            </div>
          ))}
      </dl>
    );
  return <>{String(v)}</>;
}

// ---------- 检查器 ----------
export function Inspector() {
  const { sel, details, detailErr, refreshShots } = useStudio();
  const d = sel ? details[sel] : undefined;
  if (!sel) return <aside className="inspector empty">未选择镜头</aside>;
  // 封板修复：加载失败显示原因 + 重试，不再停在“加载…”
  if (!d && detailErr[sel])
    return (
      <aside className="inspector empty">
        {sel} 加载失败：{detailErr[sel]}{" "}
        <button className="btn-mini" onClick={() => void refreshShots([sel])}>
          重试
        </button>
      </aside>
    );
  if (!d) return <aside className="inspector empty">加载 {sel}…</aside>;
  return <InspectorBody key={d.summary.id} d={d} />;
}

function InspectorBody({ d }: { d: ShotDetail }) {
  const st = useStudio();
  const { jobs, latest, saveEdit, render, setConfirmReq, notify, refreshAfter, dirtyRef, inspTab, openInspTab, setReview, canPass, setRejectFor } = st;
  const id = d.summary.id;
  const server = useMemo(() => toForm(d.edit, d), [d]);
  const [form, setForm] = useState<Form>(server);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [suggesting, setSuggesting] = useState<"first" | "last" | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const uploadStage = useRef<"image" | "last">("image");
  const dirty = !sameForm(form, server);

  const lastServer = useRef(server);
  useEffect(() => {
    setForm((f) => (sameForm(f, lastServer.current) ? server : f));
    lastServer.current = server;
  }, [server]);
  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty, dirtyRef]);
  useEffect(
    () => () => {
      dirtyRef.current = false;
    },
    [dirtyRef],
  );

  const setF = (k: FormKey) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const on = (k: FormKey) => (e: { target: { value: string } }) => setF(k)(e.target.value);
  /** 提示词框直接显示编译结果；和编译结果相同 = 不改（存 null） */
  const onPrompt = (k: FormKey, compiled: string) => (e: { target: { value: string } }) =>
    setF(k)(e.target.value === compiled ? "" : e.target.value);

  const save = useCallback(
    async (quiet = false) => {
      let body: ShotEdit;
      try {
        body = fromForm(form, d.edit);
      } catch (e) {
        notify((e as Error).message, "err");
        return false;
      }
      setSaving(true);
      const ok = await saveEdit(id, body, { quiet });
      setSaving(false);
      return ok;
    },
    [form, d.edit, id, notify, saveEdit],
  );

  // ?field=soundscape 之类：深链直接定位到某个编辑框（截图 / 从别处跳转）
  useEffect(() => {
    const f = new URLSearchParams(location.search).get("field");
    if (f) setTimeout(() => document.querySelector<HTMLElement>(`[data-field="${f}"]`)?.scrollIntoView({ block: "center" }), 300);
  }, []);

  const saveRef = useRef(save);
  saveRef.current = save;
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void saveRef.current();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  /** 保存（若有改动）后入队；都要确认 */
  function saveAndRender(stage: Stage, title: string) {
    setConfirmReq({
      title,
      lines: [`${id} ${dirty ? "先保存当前修改，再" : ""}重新生成${STAGE_LABEL[stage]}（GPU 串行队列）。`],
      confirmLabel: dirty ? "保存并入队" : "入队",
      onConfirm: async () => {
        if (dirty && !(await save(true))) return;
        setBusy(true);
        await render(id, stage);
        setBusy(false);
      },
    });
  }

  async function upload(file: File) {
    setBusy(true);
    try {
      if (uploadStage.current === "image") await api.uploadFirstFrame(id, file);
      else {
        const r = await api.uploadLastFrame(id, file);
        setForm((f) => ({ ...f, last_frame: r.last_frame, last_source: "upload" }));
      }
      notify(`${STAGE_LABEL[uploadStage.current]}已上传`);
      await refreshAfter([id]);
    } catch (e) {
      notify(`上传失败：${(e as Error).message}`, "err");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function frameAction(stage: Stage, kind: "regen" | "edit" | "upload" | "pick") {
    if (kind === "regen") return saveAndRender(stage, `重新生成${STAGE_LABEL[stage]}`);
    if (kind === "edit") return openInspTab(stage === "image" ? "first" : "last", stage === "image" ? "image_prompt" : "last_prompt");
    if (kind === "pick") return openInspTab("takes");
    uploadStage.current = stage === "last" ? "last" : "image";
    fileRef.current?.click();
  }

  async function suggest(which: "first" | "last") {
    if (d.summary.explicit_hold) {
      notify("露骨红标镜头：项目方自行处理，不用模型生成", "err");
      return;
    }
    setSuggesting(which);
    try {
      const r = await api.boostSuggest(id, which);
      setF(which === "first" ? "boost_first" : "boost_last")(r.suggestion);
      notify(`已用 ${r.model} 生成建议（只填入输入框，未保存）`);
    } catch (e) {
      notify((e as Error).message, "err");
    } finally {
      setSuggesting(null);
    }
  }

  const s = d.summary;
  const sc = d.script;
  const c = d.compiled;
  const live = jobs.find((j) => j.shot_id === id && (j.state === "queued" || j.state === "running"));
  const failed = isFailed(s, latest.get(id), d);
  const lastJob = jobs.find((j) => j.shot_id === id);
  const activeOf = (stage: Stage) => d.takes.takes.find((t) => t.stage === stage && t.n === d.takes.active[stage]);
  const passOk = canPass(s);
  const lastSrc = (form.last_source || s.last_frame_source || "") as string;
  const cf = d.compiled_file ?? {};

  const tab: InspectorTab = inspTab === "takes" ? "first" : inspTab;
  const liveOf = (stage: Stage) => st.liveJob(id, stage);
  /** 底部操作条：保存 + 「重出」（先保存再入队，不弹确认），新版本自动出现在上面的对比位 */
  const stageBar = (stage: Stage) => {
    const word = STAGE_LABEL[stage];
    const lj = liveOf(stage);
    const blocked =
      stage === "last" ? (!s.first_frame ? "尾帧以首帧为底图，先出首帧" : !s.last_supported ? "尾帧生成尚未上线" : "") : stage === "video" && !s.first_frame ? "先出首帧" : "";
    return (
      <div className="stage-bar">
        <button className="btn" disabled={!dirty || saving} onClick={() => void save()} title="Ctrl+S">
          {saving ? "保存中…" : "只保存"}
        </button>
        {dirty && (
          <button className="btn ghost" disabled={saving} onClick={() => setForm(server)}>
            放弃修改
          </button>
        )}
        <span className="grow" />
        {lj ? (
          <JobBar live={lj} />
        ) : (
          <button
            className="btn primary big"
            disabled={!!blocked || busy}
            title={blocked || (dirty ? "先保存修改，再入队；完成后新版本出现在上方候选位" : "用当前提示词换种子重出")}
            onClick={async () => {
              setBusy(true);
              await st.rerender(id, stage, dirty ? () => save(true) : undefined);
              setBusy(false);
            }}
          >
            {dirty ? `保存并重出${word}` : `重出${word}`}
          </button>
        )}
      </div>
    );
  };
  const saveBar = (
    <div className="form-actions">
      <button className="btn primary" disabled={!dirty || saving} onClick={() => void save()}>
        {saving ? "保存中…" : "保存"} <kbd>Ctrl+S</kbd>
      </button>
      <button className="btn" disabled={!dirty || saving} onClick={() => setForm(server)}>
        放弃修改
      </button>
      {dirty && <span className="badge b-edited">未保存</span>}
    </div>
  );

  function setLastSource(src: string) {
    const uploaded = (v: string | null | undefined) => (v && v !== "next" ? v : "");
    setForm((f) => ({
      ...f,
      last_source: src,
      last_frame: src === "next" ? "next" : src === "upload" ? uploaded(f.last_frame) || uploaded(d.edit.last_frame) : "",
    }));
  }

  return (
    <aside className="inspector v2 v3" tabIndex={-1} id="inspector">
      {/* T59：头部一行镜号 + 景别·运镜·时长 + 审核状态；第二行集名与负责方（说明在悬停提示里）；通过 / 打回为文字按钮 */}
      <div className="insp-head sticky t59">
        <div className="ih-row">
          <b className="ih-id">{id.split("-")[1]}</b>
          <span className="ih-meta">
            {[s.camera.size, s.camera.angle, s.camera.move]
              .filter(Boolean)
              .map((t) => (/[一-鿿]/.test(t) ? t.replace(/^[A-Za-z][A-Za-z ]*\s+(?=[一-鿿])/, "") : t)) // 运镜有中文就只显示中文
              .map((x) => (
              <span key={x}>{x}</span>
            ))}
            <span className={s.duration?.source === "script" ? "" : "ih-dflt"} title={s.duration?.source === "script" ? "剧本写明的时长" : "剧本没写时长，按默认 10 秒"}>
              时长 {s.duration?.seconds ?? 10} 秒{s.h3_frames ? ` · ${s.h3_frames} 帧` : ""}
              {s.duration?.source !== "script" && "（默认）"}
            </span>
          </span>
          <span className="grow" />
          <span className={`status ${s.review.state === "passed" ? "ok" : s.review.state === "rejected" ? "bad" : ""}`}>{REVIEW_LABEL[s.review.state]}</span>
        </div>
        <div className="ih-row ih-sub">
          <span>
            第 {d.episode.number} 集 · {d.episode.title}
          </span>
          {s.owner === "gpu3" && (
            <span
              className="ih-owner"
              title={`${s.owner_reason ?? ""}
${
                d.gpu3_takes
                  ? "下面是 gpu3 版本链（只读）；「保存并重出」= 保存后直接请 gpu3 重出，等待状态显示在镜头行和对比位"
                  : "下面的版本是笔记本旧版本，未用于视频；「重出」会改成请 gpu3 重出"
              }`}
            >
              gpu3 负责{d.gpu3_takes ? " · 版本只读" : ""}
            </span>
          )}
          {s.adult && (
            <span className="status" title={c.adult_reasons.join("、")}>
              本地渲染
            </span>
          )}
          {s.has_boost && <span className="status">已加强</span>}
          {live && (
            <span className="status busy">
              {STAGE_LABEL[live.stage]}
              {JOB_LABEL[live.state]}
            </span>
          )}
          {failed && <span className="status bad">渲染失败</span>}
          <span className="grow" />
          <button className="ih-act" disabled={!passOk} title={passOk ? "通过（A）" : "请先完整播放一遍当前视频"} onClick={() => void setReview([id], "passed")}>
            通过 <kbd>A</kbd>
          </button>
          <button className="ih-act" onClick={() => setRejectFor([id])} title="打回（X）">
            打回 <kbd>X</kbd>
          </button>
        </div>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        hidden
        disabled={busy}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
        }}
      />

      <nav className="insp-tabs">
        {TABS.map(([t, l]) => (
          <button key={t} className={inspTab === t ? "on" : ""} onClick={() => openInspTab(t)}>
            {l}
            {t === "boost" && s.has_boost && " ●"}
          </button>
        ))}
      </nav>

      <div className="insp-tab-body">
        {tab === "script" && (
          <div className="compare3">
            <section>
              <div className="sub-title">剧本原文</div>
              <KV k="画面备注" v={sc.img_note} />
              <KV k="画面 img" v={sc.img_prompt} />
              <KV k="动作 motion" v={sc.motion_prompt} />
              <KV k="音效" v={sc.sound} />
              <KV k="旁白" v={sc.voiceover && `${sc.voiceover.note ? `（${sc.voiceover.note}）` : ""}${sc.voiceover.text}`} />
              <KV
                k="对白"
                v={
                  sc.dialogue.length ? (
                    <ul className="plain">
                      {sc.dialogue.map((x, i) => (
                        <li key={i}>
                          {x.speaker_note && <span className="muted">（{x.speaker_note}）</span>}
                          {x.text}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    sc.dialogue_raw
                  )
                }
              />
              <KV k="extras" v={sc.extras.length ? sc.extras.map((x) => `${x.label}：${x.text}`).join("；") : null} />
              <KV k="装饰状态" v={sc.decor_state} />
              <KV k="来源行号" v={String(sc.source_line)} />
            </section>
            <section>
              <div className="sub-title">画面说明 visual_spec</div>
              {d.visual_spec ? <SpecView v={d.visual_spec} /> : <div className="muted small">还没有 visual_spec.json（渲染器出图时生成）</div>}
              {typeof cf.end_state === "string" && cf.end_state && <KV k="结束状态" v={cf.end_state} />}
            </section>
            <section>
              <div className="sub-title">最终提示词</div>
              <KV k="首帧" v={<Highlight text={d.assembled.first} marks={[s.boost.first, s.boost.episode_first]} />} />
              <KV k="尾帧" v={<Highlight text={d.assembled.last} marks={[s.boost.last, s.boost.episode_last]} />} />
              <KV k="视频" v={c.video_prompt} />
            </section>
          </div>
        )}

        {tab === "first" && (
          <>
            <TakeCompare d={d} stage="image" />
            <Field
              label="首帧提示词"
              hint="直接改；和编译结果不同的部分会高亮"
              action={
                <button className="btn-mini" disabled={!form.image_prompt} onClick={() => setF("image_prompt")("")} title="丢掉人工修改，回到编译结果">
                  恢复编译结果
                </button>
              }
            >
              <textarea data-field="image_prompt" rows={6} value={form.image_prompt || c.image_prompt} onChange={onPrompt("image_prompt", c.image_prompt)} />
              <Diff from={c.image_prompt} to={form.image_prompt} />
            </Field>
            {/* 保存并重出紧贴提示词：改词 → 重出 → 上方对比位看结果 → 选定，一屏完成 */}
            {stageBar("image")}
            <details className="more">
              <summary>负面词 · 种子 · 参考图组</summary>
            <Field
              label="首帧负面词"
              action={
                <button className="btn-mini" onClick={() => setF("image_negative")(c.image_negative)}>
                  填入编译结果
                </button>
              }
            >
              <textarea rows={2} value={form.image_negative} onChange={on("image_negative")} placeholder={c.image_negative} />
            </Field>
            <KV k="未加载触发词" v={c.dropped_triggers.join("、")} />
            <KV k="成人判定" v={c.adult ? `是：${c.adult_reasons.join("、")}` : "否"} />
            <KV k="过期" v={[...(s.stale.image ?? []), ...(s.stale_global.image ?? []).map((x) => `${x}（全局）`)].join("、")} />
            <SeedField label="首帧种子" value={form.image_seed} onChange={setF("image_seed")} activeSeed={activeOf("image")?.seed} />
            <div className="sub-title">本镜参考图组（送进 Qwen Image 2.1 的顺序）</div>
            <RefGroup shotId={id} />
            </details>
          </>
        )}

        {tab === "last" && (
          <>
            <TakeCompare d={d} stage="last" />
            <div className="field">
              <span className="field-label">尾帧来源</span>
              <div className="radios">
                {(["gen", "next", "upload", "video"] as const).map((src) => (
                  <label key={src}>
                    <input type="radio" checked={lastSrc === src} disabled={src === "next" && !d.next_shot} onChange={() => setLastSource(src)} />{" "}
                    {LAST_SOURCE_LABEL[src]}
                    {src === "next" && d.next_shot && `（${d.next_shot}）`}
                  </label>
                ))}
              </div>
              {lastSrc === "upload" && (
                <button className="btn-mini" onClick={() => frameAction("last", "upload")}>
                  选择图片上传…
                </button>
              )}
              {!s.last_supported && <div className="warn small">尾帧生成（render_last_frame）尚未上线，「生成」暂不能入队</div>}
            </div>
            {(lastSrc === "gen" || !lastSrc) && (
              <>
                <Field
                  label="尾帧提示词"
                  hint={`来源：${{ edit: "人工", compiler: "编译器（motion 结束状态）", fallback: "API 兜底规则" }[s.last_prompt_source]}`}
                  action={
                    <button className="btn-mini" disabled={!form.last_prompt} onClick={() => setF("last_prompt")("")} title="丢掉人工修改，回到编译结果">
                  恢复编译结果
                </button>
                  }
                >
                  <textarea data-field="last_prompt" rows={8} value={form.last_prompt || d.compiled_last.last_prompt} onChange={onPrompt("last_prompt", d.compiled_last.last_prompt)} />
                  <Diff from={d.compiled_last.last_prompt} to={form.last_prompt} />
                </Field>
                <KV k="底图" v={s.first_frame ? <img className="kv-thumb" src={s.first_frame} alt="" /> : <span className="warn">先出首帧</span>} />
                <SeedField label="尾帧种子" value={form.last_seed} onChange={setF("last_seed")} activeSeed={activeOf("last")?.seed} />
              </>
            )}
            <details className="more">
              <summary>目标尾帧 vs 视频实际尾帧</summary>
            <div className="frame-pair">
              <figure>
                {s.last_frame_target ? <img src={s.last_frame_target} alt="目标尾帧" /> : <div className="thumb-empty">没有目标尾帧</div>}
                <figcaption>目标尾帧</figcaption>
              </figure>
              <figure>
                {s.last_frame_actual ? <img src={s.last_frame_actual} alt="实际尾帧" /> : <div className="thumb-empty">还没有视频</div>}
                <figcaption>实际尾帧（视频抽帧）</figcaption>
              </figure>
            </div>
            </details>
            {stageBar("last")}
          </>
        )}

        {tab === "video" && (
          <>
            <TakeCompare d={d} stage="video" />
            <div className="row2">
              {(
                [
                  ["cam_size", "景别", "size", SIZE_PRESETS],
                  ["cam_angle", "机位", "angle", ANGLE_PRESETS],
                  ["cam_move", "运镜", "move", MOVE_PRESETS],
                  ["cam_lens", "焦段", "lens", LENS_PRESETS],
                ] as const
              ).map(([k, label, ck, presets]) => (
                <Field key={k} label={label} hint={s.camera.sources[ck] === "auto" ? "占位 = 自动解析" : undefined}>
                  <input data-field={k === "cam_move" ? "camera" : undefined} list={`dl-${k}`} value={form[k]} onChange={on(k)} placeholder={s.camera[ck] || "未标注"} />
                  <datalist id={`dl-${k}`}>
                    {presets.map((p) => (
                      <option key={p} value={p} />
                    ))}
                  </datalist>
                </Field>
              ))}
            </div>
            <Field label="表情" hint="写 2–4 个可观察线索（眼神、眉、嘴角、呼吸、手）；运镜 / 表情只作镜头信息，不进 H3 提示词（H3 只改下方正文）">
              <input data-field="expression" value={form.expression} onChange={on("expression")} placeholder={s.expression.text || "未标注"} />
            </Field>
            <H3Panel key={id} s={s} id={id} notify={notify} refresh={() => refreshAfter([id])} />
            {s.audio ? (
              <section className="audio-sec">
                <div className="audio-title">配乐（英文进 H3 · 中文只给后期）</div>
                <Field
                  label="🎵 本镜配乐"
                  hint={H3_MUSIC_HINT}
                  action={
                    <>
                      <span className={`chip ${form.music ? "chip-accent" : s.audio.music.default_source === "none" ? "chip-dark" : "chip-ok"}`}>
                        {form.music ? "人工" : AUDIO_SOURCE_LABEL[s.audio.music.default_source] ?? s.audio.music.default_source}
                      </span>
                      <button className="btn-mini" disabled={!form.music} onClick={() => setF("music")("")} title={`回到剧本：${s.audio.music.default || "（空）"}`}>
                        恢复默认
                      </button>
                    </>
                  }
                >
                  <div className="inherit-line" title="本集配乐在集头「🎵 本集配乐（H3 默认）」里编辑">
                    <span className="chip chip-dark">继承本集</span>
                    <span className="muted">{s.audio.episode_music.text || "本集还没有配乐"}</span>
                  </div>
                  <textarea
                    data-field="music"
                    rows={2}
                    readOnly={!s.audio.supported.music}
                    value={form.music || s.audio.music.default}
                    onChange={onPrompt("music", s.audio.music.default)}
                    placeholder={`本镜没有单独提示时沿用本集配乐（英文进 H3）。例：${CUE_EXAMPLE}`}
                  />
                  <div className="audio-hint">{CUE_HINT}</div>
                  {!s.audio.supported.music && <div className="warn small">后端字段 ShotEdit.music 还没上线：暂时只能查看</div>}
                </Field>
              </section>
            ) : (
              <div className="muted small">声音字段（环境声 / 配乐）等后端上线后显示</div>
            )}
            <div className="sub-title">锚点声明预览</div>
            <ul className="plain anchors">
              <li>
                @图1 作为首帧，定义构图、姿态与道具状态{!s.first_frame && <span className="warn">（还没有首帧）</span>}
              </li>
              <li>
                {s.last_frame_target ? (
                  `@图2 作为尾帧（${LAST_SOURCE_LABEL[s.last_frame_source ?? "gen"]}），定义结束时的构图与姿态`
                ) : (
                  <span className="muted">无尾帧：只用首帧生成</span>
                )}
              </li>
              {s.characters.map((ch) => (
                <li key={ch.character}>
                  {ch.name} 对应人物参考（{ch.look_label || ch.look_name}），只采用外貌、发型和服装
                </li>
              ))}
            </ul>
            <SeedField label="视频种子" value={form.video_seed} onChange={setF("video_seed")} activeSeed={activeOf("video")?.seed} />
            {stageBar("video")}
          </>
        )}

        {tab === "boost" && (
          <>
            <div className="muted small">导演加强是项目方原文，渲染器把它拼进首帧 / 尾帧提示词。保存后，早于它的版本标「导演加强已改」；不会自动重渲。</div>
            {(["first", "last"] as const).map((w) => {
              const key = w === "first" ? "boost_first" : "boost_last";
              const ep = w === "first" ? d.episode.edit?.boost_first : d.episode.edit?.boost_last;
              const landed = w === "first" ? d.assembled.first_landed : d.assembled.last_landed;
              const epLanded = w === "first" ? d.assembled.first_episode_landed : d.assembled.last_episode_landed;
              return (
                <Field
                  key={w}
                  label={w === "first" ? "首帧加强" : "尾帧加强"}
                  action={
                    <button className="btn-mini" disabled={suggesting !== null} onClick={() => void suggest(w)} title="用 config/director_boost_llm.json 配置的模型生成建议，只填入输入框，不保存">
                      {suggesting === w ? "生成中…" : "用我的模型生成"}
                    </button>
                  }
                >
                  <textarea data-field={key} rows={4} value={form[key]} onChange={on(key)} />
                  {ep && (
                    <div className="small muted">
                      本集加强：{ep}
                      {epLanded === false && <span className="warn">（尚未写进最终提示词）</span>}
                    </div>
                  )}
                  {landed === false && <div className="warn small">已保存的本镜加强尚未出现在最终提示词里（等渲染器接入）</div>}
                </Field>
              );
            })}
            {saveBar}
            <div className="row-actions">
              <button className="btn" disabled={busy || !!live} onClick={() => saveAndRender("image", "应用并重出首帧")}>
                应用并重出首帧
              </button>
              <button
                className="btn"
                disabled={busy || !!live || !s.first_frame || !s.last_supported}
                onClick={() => saveAndRender("last", "应用并重出尾帧")}
                title={!s.last_supported ? "尾帧生成尚未上线" : !s.first_frame ? "先出首帧" : undefined}
              >
                应用并重出尾帧
              </button>
            </div>
            <div className="sub-title">最终提示词（黄色 = 加强落点）</div>
            <KV k="首帧" v={<Highlight text={d.assembled.first} marks={[s.boost.first, s.boost.episode_first]} />} />
            <KV k="尾帧" v={<Highlight text={d.assembled.last} marks={[s.boost.last, s.boost.episode_last]} />} />
          </>
        )}

        {tab === "people" && (
          <>
            <div className="people insp-people">
              {s.characters.map((ch) => (
                <PersonRow key={ch.character} c={ch} hl={false} onFace={() => st.openAssets({ character: ch.character, lookId: ch.look_id })} />
              ))}
            </div>
            <LooksSection shotId={id} />
          </>
        )}

        {tab === "review" && (
          <>
            <div className="sub-title">就绪与衔接（行内只显示摘要）</div>
            <ReadinessList s={s} />
            <ReviewBox d={d} />
            <Field label="备注" hint="存在 ShotEdit.note">
              <textarea rows={2} value={form.note} onChange={on("note")} />
            </Field>
            {saveBar}
          </>
        )}

        {(failed || d.error) && (
          <div className="error-sec">
            <div className="sub-title bad">错误</div>
            <pre className="error-box">{(failed && lastJob?.error) || d.error?.last || "（无错误详情）"}</pre>
            <div className="muted small">{fmtTime(lastJob?.state === "failed" ? lastJob.created_at : d.error?.at)}</div>
          </div>
        )}
      </div>
    </aside>
  );
}
