// V2-WALK W-22 / W-18：故事线（P1）闸门 + 评审分 + 造型表。只有“用这版”和“修改”两个按钮（L-123：没有“不要”）；
// 评审没过门槛的故事线不给项目方看：闸门没到“等你看”、或评审判不过时不显示按钮，只说明现在在等什么。
// 新建剧本页的写作流程面板和运行详情页的故事线段共用这里。
import { useCallback, useEffect, useState } from "react";
import { useStudio } from "../../store";
import type { AFlow, LookChar } from "./AutoflowPanel";

// “修改”：常用诉求一键点，点一个就提交（一键原则 L-123）；也可以在文字框里补一句再提交
const QUICK = ["故事再狠一点", "男主更有魅力", "节奏更快", "换个结局", "人物更立体", "多一点反转"];

const ITEM_NAME: Record<string, string> = { act3: "第三幕", arc: "人物弧光", men: "男性角色", hooks: "钩子", av: "声画", theme: "主题", assets: "资产用法", craft: "写法" };

/** 轮到项目方看：只有 verdict = 等你看故事线（= 评审过了门槛）才给按钮；其他状态一律不显示（W-25：不能绕过评审门槛） */
export function canShowP1(d: AFlow | null | undefined): boolean {
  if (!d) return false;
  return d.verdict === "awaiting_owner_p1" && d.p1_review?.latest?.passed !== false && d.owner_gates?.gates?.P1?.status !== "revise_requested";
}

/** 现在是第几轮：上一轮没过 → 下一轮；上一轮还在评（没出分）→ 就是这一轮 */
export function p1Round(d: AFlow): number {
  const l = d.p1_review?.latest;
  return l ? (l.passed === false ? l.n + 1 : l.n) : 1;
}

/** 故事线还在评审 / 返修（没过门槛、也没点“用这版”）：页面上的节点写“评审中”，“通过”只有过了门槛才能用 */
export function p1InReview(d: AFlow | null | undefined): boolean {
  return !!d && !!d.stages?.some((s) => s.id === "P1G") && d.owner_gates?.gates?.P1?.status !== "approved" && !canShowP1(d) && d.verdict !== "p1_review_failed";
}

const getJson = <T,>(url: string) => fetch(`${url}?t=${Date.now()}`).then((r) => (r.ok ? (r.json() as Promise<T>) : null)).catch(() => null);

/** 取这部剧的写作状态（8 秒刷新）；没开始写作流程返回 null */
export function useAutoflow(runId: string): { d: AFlow | null; reload: () => void } {
  const [d, setD] = useState<AFlow | null>(null);
  const load = useCallback(() => {
    fetch(`/api/script-autoflow/${encodeURIComponent(runId)}`)
      .then((r) => (r.ok ? (r.json() as Promise<AFlow>) : null))
      .then((x) => setD(x && x.verdict !== "not_started" ? x : null))
      .catch(() => setD(null));
  }, [runId]);
  useEffect(() => {
    setD(null);
    load();
    const t = window.setInterval(load, 8000);
    return () => window.clearInterval(t);
  }, [load]);
  return { d, reload: load };
}

export function P1Gate({ run, d, hasStory, onChanged }: { run: string; d: AFlow; hasStory: boolean; onChanged: () => void }) {
  const st = useStudio();
  const [busy, setBusy] = useState(false);
  const [revising, setRevising] = useState(false);
  const [note, setNote] = useState("");
  const gate = d.owner_gates?.gates?.P1;
  const can = canShowP1(d) && hasStory;
  const free = d.writer_backend === "claude_agent";
  const failed = d.p1_review?.latest?.passed === false || d.verdict === "p1_review_failed";
  const send = (body: { action: "approve" | "revise"; note?: string }, ok: string) => {
    setBusy(true);
    fetch(`/api/script-autoflow/${encodeURIComponent(run)}/gate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: "P1", ...body }) })
      .then(async (r) => {
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `没成功（${r.status}）`);
        st.notify(ok);
        setRevising(false);
        setNote("");
        onChanged();
      })
      .catch((e: Error) => st.notify(e.message, "err"))
      .finally(() => setBusy(false));
  };
  if (!can) {
    const word =
      gate?.status === "approved"
        ? "已用这版"
        : gate?.status === "revise_requested"
          ? `已收下修改，正在重写${gate.note ? `：${gate.note}` : ""}`
          : d.verdict === "p1_review_failed"
            ? "评审三轮都没过，已转给总调度处理"
            : failed
              ? `故事线评审没过（第 ${d.p1_review?.latest?.n ?? 1} 轮 ${d.p1_review?.latest?.mean ?? "—"} 分），写手正在按意见改，过了门槛后给你看`
              : d.p1_review || /^(awaiting_writer|awaiting_p1|waiting_p1)/.test(d.verdict)
                ? `故事线在评审 / 在改，第 ${p1Round(d)} 轮评审分出来、过了门槛后给你看`
                : "";
    return word ? (
      <div className="af-gate">
        <span className="af-gstate">
          <i className={`af-dot ${gate?.status === "approved" ? "green" : ""}`} aria-hidden /> {word}
        </span>
      </div>
    ) : null;
  }
  return (
    <div className="af-gate">
      {revising ? (
        <div className="af-rev">
          <div className="af-quick">
            {QUICK.map((q) => (
              <button key={q} type="button" className="v3-btn sm" disabled={busy} onClick={() => send({ action: "revise", note: note.trim() ? `${q}；${note.trim()}` : q }, "已收下你的修改，正在重写")}>
                {q}
              </button>
            ))}
          </div>
          <div className="af-rev2">
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="想补充一句也可以（可不写）" maxLength={200} />
            <button type="button" className="v3-btn" disabled={!note.trim() || busy} onClick={() => send({ action: "revise", note: note.trim() }, "已收下你的修改，正在重写")}>
              按这句改
            </button>
            <button type="button" className="v3-btn" onClick={() => setRevising(false)}>
              取消
            </button>
          </div>
        </div>
      ) : (
        <>
          <button type="button" className="v3-btn primary" disabled={busy} onClick={() => send({ action: "approve" }, "已用这版，接着往下写")}>
            用这版
          </button>
          <button type="button" className="v3-btn" disabled={busy} onClick={() => setRevising(true)}>
            修改
          </button>
        </>
      )}
      <span className="af-muted">{free ? "写手直接写，本次不花外部接口费用（$0.00）" : "重写会按写作模型计费"}</span>
    </div>
  );
}

export function ReviewBlock({ d }: { d: AFlow }) {
  const rs = d.p1_review?.rounds ?? [];
  const min = d.p1_review?.threshold?.min_mean ?? 34;
  if (!rs.length) return <p className="af-muted">还没有评审结果。</p>;
  return (
    <div className="af-review">
      {[...rs].reverse().map((r) => (
        <div key={r.n} className="af-rv">
          {r.mean == null ? (
            <p className="af-verdict">
              <i className="af-dot" aria-hidden />
              <b>第 {r.n} 轮评审中</b>
              <span className="af-muted"> · {(r.totals ?? []).filter((t) => t != null).length}/{d.p1_review?.threshold?.judges ?? 3} 已交</span>
            </p>
          ) : (
          <p className="af-verdict">
            <i className={`af-dot ${r.passed ? "green" : "amber"}`} aria-hidden />
            <b>
              第 {r.n} 轮评审 · 均分 {r.mean}
            </b>
            <span className="af-muted"> · 门槛 {min} · {r.passed ? "过了" : "没过"}</span>
          </p>
          )}
          <div className="af-rvt">
            {(r.totals ?? []).map((t, i) => (
              <span key={i}>
                评委 {i + 1}　<b>{t}</b>
              </span>
            ))}
          </div>
          <div className="af-rvi">
            {Object.entries(r.item_mean ?? {})
              .filter(([k]) => ITEM_NAME[k])
              .map(([k, v]) => (
                <span key={k}>
                  {ITEM_NAME[k]}
                  <i style={{ ["--w" as string]: `${Math.round((v / 5) * 100)}%` }} />
                  <b>{v}</b>
                </span>
              ))}
          </div>
          {!!r.top_fixes?.length && (
            <details className="af-fix">
              <summary>评委意见（{r.top_fixes.length} 条）</summary>
              <ol>
                {r.top_fixes.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ol>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

/** 运行详情页的故事线段：两个按钮 + 造型表 + 评审分（取代“让模型改 / 改原文 / 返修这一段”）。没走写作流程的旧稿返回 null */
export function P1Extras({ runId, hasStory }: { runId: string; hasStory: boolean }) {
  const { d, reload } = useAutoflow(runId);
  const [looks, setLooks] = useState<LookChar[] | null>(null);
  useEffect(() => {
    void getJson<LookChar[]>(`/files/pipeline/runs/${encodeURIComponent(runId)}/P1_looks.json`).then((x) => setLooks(Array.isArray(x) ? x : null));
  }, [runId, d?.verdict]);
  if (!d) return null;
  return (
    <div className="af-p1x">
      <P1Gate run={runId} d={d} hasStory={hasStory} onChanged={reload} />
      {looks && canShowP1(d) && (
        <details className="af-fix" open>
          <summary>造型表</summary>
          {looks.map((c) => (
            <div key={c.name} className="af-read">
              <h3>{c.name}</h3>
              <ul>
                {(c.looks ?? []).map((l) => (
                  <li key={l.id}>
                    <b>造型 {l.id}</b>
                    <div className="af-sm">{l.zh}</div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </details>
      )}
      <details className="af-fix" open={d.p1_review?.latest?.passed === false}>
        <summary>评审分{d.p1_review?.latest ? (d.p1_review.latest.mean == null ? `（第 ${d.p1_review.latest.n} 轮评审中）` : `（第 ${d.p1_review.latest.n} 轮均分 ${d.p1_review.latest.mean}）`) : ""}</summary>
        <ReviewBlock d={d} />
      </details>
    </div>
  );
}
