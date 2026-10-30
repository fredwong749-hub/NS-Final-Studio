import { useEffect, useState } from "react";

/** 按集渲染（项目方本人）：经 gpu3 桥的 owner-run（写 lend.gpuN = "owner-run {run_id}" + 队列，weita_runner 消费）。
 *  只给项目方本人点：先预览（dry_run，不写任何东西）→ 勾选“由项目方本人启动”→ 启动。🔴 集按钮置灰，没有绕过入口。
 *  Claude / agent 会话不得代点（总调度 2026-10-30）。 */

interface RunItem {
  shot: string;
  step: string;
  eligible: boolean;
  reasons: string[];
}
interface RunResp {
  run_id: string;
  dry_run: boolean;
  gpu: number;
  steps: string[];
  gpu_holder: unknown;
  shots: RunItem[];
  counts?: Record<string, number>;
  queued?: { id: string; shot: string; step: string }[];
}

async function post<T>(url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const t = await r.text();
  if (!r.ok) {
    let m = t;
    try {
      const d = JSON.parse(t).detail;
      m = typeof d === "string" ? d : JSON.stringify(d);
    } catch {
      /* 原文 */
    }
    throw new Error(m);
  }
  return JSON.parse(t) as T;
}

const STEPS = [
  ["frames", "首尾帧"],
  ["video", "视频"],
  ["4k", "4K"],
] as const;

export function OwnerRunPanel({ defaultEp }: { defaultEp: number }) {
  const [ep, setEp] = useState(defaultEp);
  const [gpu, setGpu] = useState(3);
  const [steps, setSteps] = useState<string[]>(["frames", "video"]);
  const [note, setNote] = useState("");
  const [elig, setElig] = useState<{ allowed: boolean; reason: string } | null>(null);
  const [preview, setPreview] = useState<RunResp | null>(null);
  const [owner, setOwner] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; err?: boolean } | null>(null);

  useEffect(() => setEp(defaultEp), [defaultEp]);
  // 封板修复：换集先清空资格，丢弃旧集的迟到响应
  useEffect(() => {
    let alive = true;
    setPreview(null);
    setOwner(false);
    setElig(null);
    fetch(`/api/gpu3/episodes/${ep}/run-eligibility`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(
        (v) => alive && setElig(v),
        (e: Error) => alive && setElig({ allowed: false, reason: `读取失败：${e.message}` }),
      );
    return () => {
      alive = false;
    };
  }, [ep]);
  // 封板修复：改 GPU / 步骤 / 说明都要重新预览、重新勾选项目方
  const reset = () => {
    setPreview(null);
    setOwner(false);
  };

  const body = (dry: boolean) => ({ gpu, steps, note, dry_run: dry, by: "owner" });
  const doPreview = async () => {
    setBusy(true);
    setMsg(null);
    setOwner(false);
    try {
      setPreview(await post<RunResp>(`/api/gpu3/episodes/${ep}/run`, body(true)));
    } catch (e) {
      setMsg({ text: `预览失败：${(e as Error).message}`, err: true });
    } finally {
      setBusy(false);
    }
  };
  const doRun = async () => {
    setBusy(true);
    try {
      const r = await post<RunResp>(`/api/gpu3/episodes/${ep}/run`, body(false));
      setMsg({ text: `已启动 ${r.run_id}：入队 ${r.queued?.length ?? 0} 项（GPU${r.gpu}）。进度看上方 GPU 状态与镜头行。` });
      setPreview(null);
      setOwner(false);
    } catch (e) {
      setMsg({ text: `启动失败：${(e as Error).message}`, err: true });
    } finally {
      setBusy(false);
    }
  };
  const blocked = elig != null && !elig.allowed;
  const eligible = preview?.shots.filter((s) => s.eligible) ?? [];

  return (
    <section className="gpu-row owner-run">
      <header>
        <b>按集渲染（项目方本人）</b>
        <span className="gpu-muted">由项目方本人启动；Claude 会话不代点</span>
      </header>
      <div className="or-form">
        <label>
          集 <input type="number" min={1} max={60} value={ep} onChange={(e) => setEp(Math.max(1, Number(e.target.value) || 1))} />
        </label>
        <label>
          GPU
          <select value={gpu} onChange={(e) => (setGpu(Number(e.target.value)), reset())}>
            {/* GPU1 固定给 Qwen 写作模型（项目方），GPU2 坏卡：只列 GPU0 / GPU3 */}
            <option value={0}>GPU0</option>
            <option value={3}>GPU3</option>
          </select>
        </label>
        {STEPS.map(([k, label]) => (
          <label key={k}>
            <input
              type="checkbox"
              checked={steps.includes(k)}
              onChange={(e) => (setSteps((s) => (e.target.checked ? [...s, k] : s.filter((x) => x !== k))), reset())}
            />{" "}
            {label}
          </label>
        ))}
      </div>
      <input className="or-note" value={note} onChange={(e) => (setNote(e.target.value), reset())} placeholder="这次为什么跑（必填）" />
      {blocked ? (
        <div className="gpu-err">{elig!.reason}</div>
      ) : (
        <div className="or-actions">
          <button className="btn-mini" disabled={busy || !elig || !note.trim() || steps.length === 0} onClick={doPreview}>
            {busy && !preview ? "预览中…" : "预览（不启动）"}
          </button>
        </div>
      )}
      {preview && !blocked && (
        <div className="or-preview">
          <div>
            GPU{preview.gpu} · 可跑 {eligible.length} 项 / 共 {preview.shots.length} 项
            {preview.gpu_holder ? <span className="gpu-err"> · 这张卡被占用：{JSON.stringify(preview.gpu_holder).slice(0, 120)}</span> : null}
          </div>
          <ul>
            {preview.shots
              .filter((s) => !s.eligible)
              .slice(0, 12)
              .map((s) => (
                <li key={`${s.shot}-${s.step}`} className="gpu-muted">
                  跳过 {s.shot} {s.step}：{s.reasons.join("、")}
                </li>
              ))}
          </ul>
          <label className="or-confirm">
            <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} /> 我是项目方，由我本人启动这次渲染
          </label>
          <button className="btn primary" disabled={busy || !elig || !owner || eligible.length === 0 || !!preview.gpu_holder} onClick={doRun}>
            {busy ? "启动中…" : `启动 ep${String(ep).padStart(2, "0")}（${eligible.length} 项）`}
          </button>
        </div>
      )}
      {msg && <div className={msg.err ? "gpu-err" : "gpu-muted"}>{msg.text}</div>}
    </section>
  );
}
