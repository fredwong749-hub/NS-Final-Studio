// EDITDEL（2026-10-31）：处处可编辑 + 可删除的通用组件。后端 services/api/ns_api/edits.py、trash.py。
//
// 用法（详见文件末尾注释）：
//   <EditButton type="image" id={`take:${shot}/image/${n}`} src={url} label="改这张" onChanged={reload} />
//   <EditButton type="image" id={`file:${relPath}`} src={url} />                // 流水线首帧 / 设定图 / 场景图
//   <EditButton type="video" id={`take:${shot}/video/${n}`} src={videoUrl} />   // 视频：可在时间轴上打点
//   <EditButton type="script" id={`run:${runId}/P4`} />                          // 剧本段：写作模型改写，待确认
//   <EditButton type="prompt" id={`shot:${shot}/image_prompt`} />                // 提示词
//   <DeleteButton type="take" id={`${shot}/image/${n}`} onDeleted={reload} />    // 软删除到回收站，可撤销
//   <TrashPage />                                                                 // 回收站页（还原 / 永久删除：二次确认，身份取登录会话）
import { useCallback, useEffect, useRef, useState, type PointerEvent as RPointerEvent, type ReactNode } from "react";
import { Button, Drawer, Empty, LoadError, Loading, Modal, Tag } from "./index";
import "./editdel.css";
import { TileBar } from "./TileBar";
import { editApi, trashApi } from "./editdel.api";
import type { Box, EditItem, EditType, TrashEntry, TrashImpact, TrashType } from "./editdel.api";
// PW-019：接口与小工具在 ./editdel.api（组件文件只导出组件）；类型照旧可从这里拿
export type { EditType, TrashType, Box, EditPlan, EditItem, TrashImpact, TrashEntry } from "./editdel.api";

const ACTION_LABEL: Record<string, string> = {
  inpaint: "局部重绘（只改框里）",
  edit: "整图按指令改",
  regen: "整图重出（换种子）",
  refs: "换参考再改",
  seed: "换种子重出",
  prompt_only: "只改提示词",
  video_rerun: "改参数重出视频",
  text_rewrite: "写作模型改写（待确认）",
  reject: "不执行（违反锁定规则）",
};
const STATUS: Record<EditItem["status"], [string, "neutral" | "busy" | "ok" | "warn" | "bad" | "info"]> = {
  planning: ["正在理解", "busy"],
  planned: ["已出计划", "info"],
  blocked: ["被规则拦下", "bad"],
  running: ["正在修", "busy"],
  done: ["修好了，待你看", "ok"],
  proposed: ["改写好了，待确认", "warn"],
  adopted: ["已采用", "ok"],
  rejected: ["没采用", "neutral"],
  rolled_back: ["已回滚", "neutral"],
  failed: ["失败", "bad"],
  cancelled: ["已取消", "neutral"],
  contract_failed: ["未通过（自动重出 3 次仍不合格）", "bad"],
  base_rejected: ["底图不合格，没有修", "bad"],
};

/* ================================================================ 图片框选 / 视频打点 */
function BoxPicker({ src, boxes, onChange }: { src: string; boxes: Box[]; onChange: (b: Box[]) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{ x: number; y: number; cx: number; cy: number } | null>(null);
  const pos = (e: RPointerEvent) => {
    const r = ref.current!.getBoundingClientRect();
    return { x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)) };
  };
  const cur: Box | null = drag ? [Math.min(drag.x, drag.cx), Math.min(drag.y, drag.cy), Math.abs(drag.cx - drag.x), Math.abs(drag.cy - drag.y)] : null;
  return (
    <div className="ed-pick">
      <div
        ref={ref}
        className="ed-pick-img"
        onPointerDown={(e) => {
          (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
          const p = pos(e);
          setDrag({ x: p.x, y: p.y, cx: p.x, cy: p.y });
        }}
        onPointerMove={(e) => drag && setDrag({ ...drag, cx: pos(e).x, cy: pos(e).y })}
        onPointerUp={() => {
          if (cur && cur[2] > 0.02 && cur[3] > 0.02) onChange([...boxes, cur.map((v) => Math.round(v * 1000) / 1000) as Box]);
          setDrag(null);
        }}
      >
        <img src={src} alt="要改的图" draggable={false} />
        {[...boxes, ...(cur ? [cur] : [])].map((b, i) => (
          <i key={i} className="ed-box" style={{ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${b[2] * 100}%`, height: `${b[3] * 100}%` }}>
            {i < boxes.length && <b>{i + 1}</b>}
          </i>
        ))}
      </div>
      <div className="ed-row ds-muted">
        在图上拖一个框，框出你觉得错的地方（可不框：不框 = 整图改）。
        {boxes.length > 0 && (
          <Button size="xs" variant="ghost" onClick={() => onChange([])}>
            清除框（{boxes.length}）
          </Button>
        )}
      </div>
    </div>
  );
}

function VideoMarker({ src, marks, onChange }: { src: string; marks: number[]; onChange: (m: number[]) => void }) {
  const ref = useRef<HTMLVideoElement>(null);
  return (
    <div className="ed-pick">
      <video ref={ref} src={src} controls className="ed-video" />
      <div className="ed-row">
        <Button size="sm" onClick={() => ref.current && onChange([...marks, Math.round(ref.current.currentTime * 10) / 10].sort((a, b) => a - b))}>
          在当前时间打点
        </Button>
        {marks.map((t, i) => (
          <Tag key={i} tone="accent" pill>
            <span onClick={() => ref.current && (ref.current.currentTime = t)} style={{ cursor: "pointer" }}>
              {t.toFixed(1)} s
            </span>{" "}
            <span onClick={() => onChange(marks.filter((_, k) => k !== i))} style={{ cursor: "pointer" }} title="去掉这个点">
              ✕
            </span>
          </Tag>
        ))}
      </div>
    </div>
  );
}

/* ================================================================ EditDrawer */
export interface EditTarget {
  type: EditType;
  id: string;
  /** 图片 / 视频地址（框选、打点、对比用） */
  src?: string | null;
  /** 抽屉标题里显示的名字，如“ep01-S1 首帧 v3” */
  label?: ReactNode;
  version?: number;
}

export function EditDrawer({ target, onClose, onChanged }: { target: EditTarget; onClose: () => void; onChanged?: (it: EditItem) => void }) {
  const [fb, setFb] = useState("");
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [marks, setMarks] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [cur, setCur] = useState<EditItem | null>(null);
  const [hist, setHist] = useState<EditItem[] | null>(null);
  const [engines, setEngines] = useState<{ id: string; label: string; enabled: boolean }[]>([]);
  const [engine, setEngine] = useState<string>("");
  useEffect(() => {
    if (target.type !== "image") return;
    editApi
      .engines()
      .then((r) => {
        setEngines(r.engines.filter((e) => e.enabled));
        setEngine(r.default);
      })
      .catch(() => undefined);
  }, [target.type]);

  const loadHist = useCallback(() => {
    editApi
      .list(target.type, target.id, 10)
      .then((r) => setHist(r.edits))
      .catch(() => setHist([]));
  }, [target.type, target.id]);
  useEffect(loadHist, [loadHist]);

  // 进度轮询：正在修时每 2 s 读一次
  useEffect(() => {
    if (!cur || !["running", "planning"].includes(cur.status)) return;
    const t = setInterval(() => {
      editApi
        .get(cur.edit_id)
        .then((it) => {
          setCur(it);
          if (!["running", "planning"].includes(it.status)) loadHist();
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(t);
  }, [cur, loadHist]);

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const annotations = boxes.length || marks.length ? { ...(boxes.length ? { box: boxes[0], boxes } : {}), ...(marks.length ? { time_s: marks[0], times: marks } : {}) } : undefined;
      const it = await editApi.create({ type: target.type, id: target.id, version: target.version, feedback: fb.trim(), annotations, by: "owner", engine: engine || undefined });
      setCur(it);
      loadHist();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const act = async (fn: () => Promise<EditItem>) => {
    setBusy(true);
    setErr(null);
    try {
      const it = await fn();
      setCur(it);
      loadHist();
      onChanged?.(it);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const what = { image: "这张图", video: "这条视频", script: "这段剧本", prompt: "这段提示词", asset: "这个资产字段" }[target.type];
  return (
    <Drawer
      wide
      title={<>修改 · {target.label ?? what}</>}
      onClose={onClose}
      foot={
        <div className="ed-row">
          <span className="ds-muted grow">先由逻辑模型把你的话变成修改计划，再交给出图 / 视频 / 写作模型执行；结果是新版本，原版本保留。</span>
          <Button variant="primary" disabled={!fb.trim() || busy} why="先写下哪里不对" onClick={submit}>
            {busy ? "提交中…" : "让系统修"}
          </Button>
        </div>
      }
    >
      {target.type === "image" && target.src && <BoxPicker src={target.src} boxes={boxes} onChange={setBoxes} />}
      {target.type === "video" && target.src && <VideoMarker src={target.src} marks={marks} onChange={setMarks} />}
      <label className="ed-label">
        哪里不对？（直接说，比如“脸不像林晚、皮肤太油”）
        <textarea className="ed-text" rows={3} value={fb} onChange={(e) => setFb(e.target.value)} placeholder={`说说${what}哪里不满意`} />
      </label>
      {engines.length > 1 && (
        <label className="ed-label">
          改图模型
          <select className="ed-input" value={engine} onChange={(e) => setEngine(e.target.value)}>
            {engines.map((e) => (
              <option key={e.id} value={e.id}>
                {e.label}
              </option>
            ))}
          </select>
        </label>
      )}
      {err && <LoadError what="修改" err={err} />}
      {cur && <EditResult it={cur} src={target.src} busy={busy} onAdopt={() => act(() => editApi.adopt(cur.edit_id))} onReject={() => act(() => editApi.reject(cur.edit_id))} onRollback={() => act(() => editApi.rollback(cur.edit_id))} />}
      <h4 className="ds-section-t">这件东西的修改记录</h4>
      {hist === null ? (
        <Loading />
      ) : hist.length === 0 ? (
        <p className="ds-muted">还没有修改过。</p>
      ) : (
        <ul className="ed-hist">
          {hist.map((h) => (
            <li key={h.edit_id} className={cur?.edit_id === h.edit_id ? "on" : ""} onClick={() => setCur(h)}>
              <Tag tone={STATUS[h.status]?.[1] ?? "neutral"} size="xs">
                {STATUS[h.status]?.[0] ?? h.status}
              </Tag>
              <span className="grow">{h.feedback}</span>
              <span className="ds-muted">{h.created_at?.slice(5, 16).replace("T", " ")}</span>
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}

function EditResult({ it, src, busy, onAdopt, onReject, onRollback }: { it: EditItem; src?: string | null; busy: boolean; onAdopt: () => void; onReject: () => void; onRollback: () => void }) {
  const p = it.plan;
  const [label, tone] = STATUS[it.status] ?? [it.status, "neutral"];
  const r = it.result ?? {};
  return (
    <section className="ed-result">
      <div className="ed-row">
        <Tag tone={tone} dot>
          {label}
        </Tag>
        {p && <Tag tone="info">{ACTION_LABEL[p.action] ?? p.action}</Tag>}
        {it.status === "running" && it.job && <span className="ds-muted">任务 {it.job.state === "queued" ? "排队中" : "进行中"}{it.job.eta_s ? `，约 ${Math.round(it.job.eta_s)} 秒` : ""}</span>}
        {it.planner?.cost_usd != null && <span className="ds-muted">逻辑模型 ${it.planner.cost_usd.toFixed(4)}</span>}
        {r.preflight?.status && <Tag tone={r.preflight.status === "pass" ? "ok" : r.preflight.status === "fail" ? "bad" : "neutral"} title={(r.preflight.reasons ?? []).join("；")}>契约提交前 {r.preflight.status === "pass" ? "通过" : r.preflight.status}</Tag>}
        {r.postflight?.status && <PostTag p={r.postflight} />}
      </div>
      {p?.understanding && <p>系统理解：{p.understanding}</p>}
      {p?.instruction && (
        <details>
          <summary>修改指令（给出图模型）</summary>
          <pre className="ed-pre">{p.instruction}</pre>
        </details>
      )}
      {(p?.fixes?.length ?? 0) > 0 && <p className="ds-muted">系统调整：{p!.fixes!.join("；")}</p>}
      {(p?.lock_conflicts?.length ?? 0) > 0 && (
        <ul className="ed-warn">
          {p!.lock_conflicts!.map((c, i) => (
            <li key={i}>
              {c.rule}：{c.message}
            </li>
          ))}
        </ul>
      )}
      {(it.error || it.job?.error) && <LoadError what="这次修改" err={it.error || it.job?.error} />}
      {r.url && (
        <div className="ed-compare">
          {src && (
            <figure>
              <figcaption>原来</figcaption>
              {it.type === "video" ? <video src={src} controls /> : <img src={src} alt="原来" />}
            </figure>
          )}
          <figure>
            <figcaption>修改后</figcaption>
            {it.type === "video" ? <video src={r.url} controls /> : <img src={r.url} alt="修改后" />}
          </figure>
        </div>
      )}
      {(r.attempts?.length ?? 0) > 1 && (
        <details>
          <summary>
            按生成契约自动重出 {r.attempts!.filter((a) => !a.skipped).length - 1} 次{r.contract_failed ? "，仍未通过" : "后通过"}（只把通过的版本给你看）
          </summary>
          <ol className="ed-attempts">
            {r.attempts!.map((a) => (
              <li key={a.k}>
                {a.skipped ? `跳过：${a.skipped}` : `${a.change ?? ""} · ${a.ok ? "通过" : `没过 ${(a.failed ?? []).join(" ")}`}`}
              </li>
            ))}
          </ol>
        </details>
      )}
      {it.status === "base_rejected" && r.message && <p className="ed-warn">{r.message}</p>}
      {r.contract_failed && <p className="ed-warn">{r.message ?? "这次修改没有通过生成契约，不作为候选。可以换个说法再提，或交总调度处理。"}</p>}
      {r.kind === "proposal" && (
        <>
          <p>
            <Tag tone="warn">待确认</Tag> 改写由写作模型给出，确认后才写回。
            {r.chain_check && (r.chain_check.ok ? <Tag tone="ok">链条校验通过</Tag> : r.chain_check.ok === false ? <Tag tone="bad">链条校验没过</Tag> : null)}
          </p>
          <pre className="ed-pre ed-diff">{r.diff || r.text}</pre>
        </>
      )}
      {it.learning?.draft && <p className="ds-muted">同类修改已被采用 {it.learning.count} 次，系统写了规则草案：{it.learning.draft}</p>}
      <div className="ed-row">
        {["done", "proposed"].includes(it.status) && (
          <>
            <Button variant="primary" disabled={busy} onClick={onAdopt}>
              采用（设为当前）
            </Button>
            <Button disabled={busy} onClick={onReject}>
              不采用
            </Button>
          </>
        )}
        {it.status === "adopted" && r.kind !== "proposal" && (
          <Button disabled={busy} onClick={onRollback}>
            回滚到修改前
          </Button>
        )}
      </div>
    </section>
  );
}

/** 契约质检：有一项没过 = 没过；没有没过但有没测的项 = 未测（REFLOCK：remote 缺时 Q1/Q3/Q5/Q6 untested，不能写“通过”） */
function PostTag({ p }: { p: NonNullable<NonNullable<EditItem["result"]>["postflight"]> }) {
  const items = p.items ?? [];
  const fail = items.filter((i) => i.status === "fail").map((i) => i.id);
  const untested = items.filter((i) => i.status === "untested").map((i) => i.id);
  const [txt, tone] = fail.length ? [`没过 ${fail.join(" ")}`, "warn" as const] : untested.length ? [`未测 ${untested.join(" ")}`, "neutral" as const] : p.status === "pass" ? ["通过", "ok" as const] : [p.status ?? "", "neutral" as const];
  return (
    <Tag tone={tone} title={(p.reasons ?? []).join("；") || p.detail || ""}>
      契约质检 {txt}
    </Tag>
  );
}

/* ================================================================ EditButton */
export function EditButton({ label = "修改", size = "sm", onChanged, ...target }: EditTarget & { label?: ReactNode; size?: "xs" | "sm" | "md"; onChanged?: (it: EditItem) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button size={size} title="指出哪里不对，系统来修（结果是新版本）" onClick={(e) => (e.stopPropagation(), setOpen(true))}>
        ✎ {label}
      </Button>
      {open && <EditDrawer target={target} onClose={() => setOpen(false)} onChanged={onChanged} />}
    </>
  );
}

/* ================================================================ DeleteButton */
export function DeleteButton({ type, id, label = "删除", size = "sm", icon, soft, onDeleted }: { type: TrashType; id: string; label?: ReactNode; size?: "xs" | "sm" | "md"; icon?: boolean; soft?: boolean; onDeleted?: (e: TrashEntry) => void }) {
  const [imp, setImp] = useState<TrashImpact | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<TrashEntry | null>(null);
  const open = async () => {
    setErr(null);
    setBusy(true);
    try {
      setImp(await trashApi.impact(type, id));
    } catch (e) {
      setErr((e as Error).message);
      setImp({ name: id, type_label: "", files: [], blocked: [], confirm: [], notes: [], needs_confirm: false, can_delete: false });
    } finally {
      setBusy(false);
    }
  };
  const go = async () => {
    setBusy(true);
    try {
      const e = await trashApi.remove(type, id, imp?.needs_confirm ?? false);
      setDone(e);
      setImp(null);
      onDeleted?.(e);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const undo = async () => {
    if (!done) return;
    setBusy(true);
    try {
      await trashApi.restore(done.entry_id);
      setDone(null);
      onDeleted?.({ ...done, state: "restored" });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button variant={soft ? "ghost" : "danger"} size={size} icon={icon} disabled={busy} title="移到回收站（可还原）" onClick={(e) => (e.stopPropagation(), open())}>
        {icon ? "🗑" : soft ? label : `🗑 ${label}`}
      </Button>
      {imp && (
        <Modal
          title={soft ? `把 ${imp.type_label ?? ""}「${imp.name}」移到回收站？` : `删除 ${imp.type_label ?? ""}「${imp.name}」？`}
          sub="移到回收站，可以一键还原；永久删除要在回收站里另外确认。"
          onClose={() => setImp(null)}
          foot={
            <>
              <Button onClick={() => setImp(null)}>取消</Button>
              <Button variant="danger" solid disabled={!imp.can_delete || busy} why={imp.blocked.join("；") || err || "现在不能删"} onClick={go}>
                {soft ? "移到回收站" : imp.needs_confirm ? "确认删除" : "删除"}
              </Button>
            </>
          }
        >
          {err && <LoadError what="影响面" err={err} />}
          {imp.blocked.length > 0 && (
            <ul className="ed-warn">
              {imp.blocked.map((x, i) => (
                <li key={i}>不能删：{x}</li>
              ))}
            </ul>
          )}
          {imp.confirm.length > 0 && (
            <ul className="ed-caution">
              {imp.confirm.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          )}
          {imp.notes.map((x, i) => (
            <p key={i} className="ds-muted">
              {x}
            </p>
          ))}
          {imp.files.length > 0 && <p className="ds-muted">会移走 {imp.files.length} 个文件 / 目录。</p>}
        </Modal>
      )}
      {done && (
        <div className="ed-toast" role="status">
          已移到回收站：{done.name}
          <Button size="xs" onClick={undo} disabled={busy}>
            撤销
          </Button>
          <Button size="xs" variant="ghost" onClick={() => setDone(null)}>
            ✕
          </Button>
        </div>
      )}
    </>
  );
}

/* ================================================================ 小工具 */
type TileActProps = { edit?: EditTarget | null; del?: { type: TrashType; id: string } | null; onChanged?: () => void };

/** 图 / 视频格的“修改 / 删除”按钮（只有按钮，放进 ds/TileBar 的 actions 槽；点击不冒泡到格子） */
export function TileActionButtons({ edit, del, onChanged }: TileActProps) {
  if (!edit && !del) return null;
  return (
    <>
      {edit && <EditButton {...edit} size="xs" label="改" onChanged={() => onChanged?.()} />}
      {del && <DeleteButton type={del.type} id={del.id} size="xs" icon onDeleted={() => onChanged?.()} />}
    </>
  );
}

/** 只有操作、没有状态的格子：一条 TileBar（UIPIXEL：不再单独 absolute 在右下角，和状态牌 / 任务条叠在一起） */
export function TileActions(p: TileActProps) {
  if (!p.edit && !p.del) return null;
  return <TileBar actions={<TileActionButtons {...p} />} />;
}

/* ================================================================ TrashPage */
export function TrashPage() {
  const [rows, setRows] = useState<TrashEntry[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [purging, setPurging] = useState<TrashEntry | null>(null);
  const [busy, setBusy] = useState(false);
  const [showPurged, setShowPurged] = useState(false);
  const load = useCallback(() => {
    setErr(null);
    trashApi
      .list(showPurged)
      .then((r) => setRows(r.entries))
      .catch((e) => setErr((e as Error).message));
  }, [showPurged]);
  useEffect(load, [load]);
  const restore = async (e: TrashEntry) => {
    setBusy(true);
    try {
      await trashApi.restore(e.entry_id);
      load();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const purge = async () => {
    if (!purging) return;
    setBusy(true);
    try {
      await trashApi.purge(purging.entry_id);
      setPurging(null);
      load();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="ed-trash">
      <header className="ed-row">
        <h2 className="grow">回收站</h2>
        <label className="ds-muted">
          <input type="checkbox" checked={showPurged} onChange={(e) => setShowPurged(e.target.checked)} /> 显示已永久删除
        </label>
        <Button size="sm" onClick={load}>
          刷新
        </Button>
      </header>
      <p className="ds-muted">删除的剧本、版本、成片、资产都在这里，可以还原。永久删除不能恢复。</p>
      {err && <LoadError what="回收站" err={err} retry={load} />}
      {rows === null ? (
        <Loading />
      ) : rows.length === 0 ? (
        <Empty icon="🗑" title="回收站是空的" />
      ) : (
        <table className="ed-table">
          <thead>
            <tr>
              <th />
              <th>类型</th>
              <th>名称</th>
              <th>删除时间</th>
              <th>文件</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.entry_id} className={e.state === "purged" ? "gone" : ""}>
                <td>{e.preview ? <img src={e.preview} alt="" className="ed-thumb" /> : null}</td>
                <td>
                  <Tag size="xs">{e.type_label}</Tag>
                </td>
                <td title={e.id}>{e.name}</td>
                <td className="ds-muted">{e.deleted_at?.replace("T", " ")}</td>
                <td className="ds-muted">{e.files?.length ?? 0}</td>
                <td className="ed-row">
                  {e.state === "trashed" ? (
                    <>
                      <Button size="xs" variant="ok" disabled={busy} onClick={() => restore(e)}>
                        还原
                      </Button>
                      <Button
                        size="xs"
                        variant="danger"
                        disabled={busy}
                        onClick={() => setPurging(e)}
                      >
                        永久删除
                      </Button>
                    </>
                  ) : (
                    <Tag size="xs" tone="void">
                      已永久删除
                    </Tag>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {purging && (
        <Modal
          title={`永久删除「${purging.name}」？`}
          sub="这是第二次确认：文件会从磁盘上删掉，不能恢复。"
          onClose={() => setPurging(null)}
          foot={
            <>
              <Button onClick={() => setPurging(null)}>取消</Button>
              <Button variant="danger" solid disabled={busy} onClick={purge}>
                确认永久删除
              </Button>
            </>
          }
        >
          <p className="ds-muted">
            {purging.type_label} · {purging.files?.length ?? 0} 个文件 / 目录 · 删除于 {purging.deleted_at?.replace("T", " ")}
          </p>
        </Modal>
      )}
    </div>
  );
}

/*
接线说明（给 UIRSI / 各页面）：
  画布首帧 / 尾帧格     <EditButton type="image" id={`take:${shot}/${stage}/${n}`} src={url} label="修改" onChanged={reload} />
                        <DeleteButton type="take" id={`${shot}/${stage}/${n}`} icon onDeleted={reload} />   （stage = image | last）
  画布视频格            <EditButton type="video" id={`take:${shot}/video/${n}`} src={videoUrl} />  + DeleteButton type="take" id={`${shot}/video/${n}`}
  画布提示词            <EditButton type="prompt" id={`shot:${shot}/image_prompt`} />（last_prompt / boost_first …）
  资产中心卡片 / 详情   图片：<EditButton type="image" id={`file:${relPath}`} src={url} />（relPath 相对项目根，如 assets/characters/...）
                        参考图删除 <DeleteButton type="asset_ref" id={`${assetId}/${refId}`} />，版本 type="asset_version" id={`${assetId}/${version}`}，
                        整件单品 / 造型 type="asset" id={assetId}
  设定图挑选            <EditButton type="image" id={`file:${relPath}`} src={url} />
  新建剧本每段产物      <EditButton type="script" id={`run:${runId}/${node}`} />（node = P1..P4；整季加 @集号）
  写过的剧本列表        <DeleteButton type="story_run" id={runId} />
  导入候选稿            <DeleteButton type="import_candidate" id={path} />（path = data/staging_v3/… 或 data/staging_input/…）
  成片页                <DeleteButton type="cut" id={`episodes/${file}`} />
  回收站页              <TrashPage />（建议路由 #/trash）
*/
