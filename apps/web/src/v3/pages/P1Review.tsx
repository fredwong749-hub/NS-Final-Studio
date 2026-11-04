// V2-WALK W-22 / W-18：故事线（P1）闸门 + 评审分 + 造型表。只有“用这版”和“修改”两个按钮（L-123：没有“不要”）；
// 评审没过门槛的故事线不给项目方看：闸门没到“等你看”、或评审判不过时不显示按钮，只说明现在在等什么。
// 新建剧本页的写作流程面板和运行详情页的故事线段共用这里。
import { useEffect, useState } from "react";
import { useStudio } from "../../store";
import type { AFlow, LookChar } from "./AutoflowPanel";
import { canShowP1, holdText, p1Round, useAutoflow } from "./P1Review.logic";

// “修改”：常用诉求一键点，点一个就提交（一键原则 L-123）；也可以在文字框里补一句再提交
const QUICK = ["故事再狠一点", "男主更有魅力", "节奏更快", "换个结局", "人物更立体", "多一点反转"];

// 低于门槛、转给你定方向时只有两个按钮（用这版 / 修改）；“换个方向重写”是“修改”里的第 7 个选项，选了就要写一句新方向，提交走 redirect
const REDIRECT = "换个方向重写";

const ITEM_NAME: Record<string, string> = { act3: "第三幕", arc: "人物弧光", men: "男性角色", hooks: "钩子", av: "声画", theme: "主题", assets: "资产用法", craft: "写法" };

const getJson = <T,>(url: string) => fetch(`${url}?t=${Date.now()}`).then((r) => (r.ok ? (r.json() as Promise<T>) : null)).catch(() => null);

export function P1Gate({ run, d, hasStory, onChanged }: { run: string; d: AFlow; hasStory: boolean; onChanged: () => void }) {
  const st = useStudio();
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<"" | "revise">("");
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const gate = d.owner_gates?.gates?.P1;
  const can = canShowP1(d) && hasStory;
  const direction = d.verdict === "owner_direction"; // 低于门槛的稿由总调度转给你拍板
  const free = d.writer_backend === "claude_agent";
  const failed = d.p1_review?.latest?.passed === false || d.verdict === "p1_review_failed";
  const opts = d.p1_review?.revise_options ?? [];
  const od = d.p1_review?.owner_direction;
  // 取值顺序：后端的 fill_note → 从 next_action 里截出“写手会自动补上”那一句 → 按 p1_owner_hold_fields 生成
  const fromNext = (d.next_action ?? "").split("。").find((x) => x.includes("写手会自动补上"));
  const holdNote = od?.fill_note || (fromNext ? `${fromNext}。` : "") || holdText(d.p1_owner_hold_fields);
  const send = (body: { action: "approve" | "revise" | "redirect"; note?: string; options?: string[] }, ok: string) => {
    setBusy(true);
    fetch(`/api/script-autoflow/${encodeURIComponent(run)}/gate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: "P1", ...body }) })
      .then(async (r) => {
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : r.status === 403 ? "请先登录" : `没成功（${r.status}）`);
        st.notify(ok);
        setMode("");
        setNote("");
        setPicked([]);
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
      {direction && !mode && (
        <p className="af-muted af-dirnote">
          <i className="af-dot amber" aria-hidden /> {od?.why ? `${od.why}，总调度转给你定方向` : "这一版没到门槛，总调度转给你定方向"}
        </p>
      )}
      {!mode && holdNote && <p className="af-muted af-dirnote af-holdnote">{holdNote}</p>}
      {mode === "revise" && direction ? (
        <div className="af-rev">
          <div className="af-quick">
            {[...opts, REDIRECT].map((o) => (
              <button
                key={o}
                type="button"
                className={`v3-btn sm${picked.includes(o) ? " primary" : ""}`}
                aria-pressed={picked.includes(o)}
                onClick={() => setPicked((p) => (o === REDIRECT ? (p.includes(o) ? [] : [o]) : p.includes(o) ? p.filter((x) => x !== o) : [...p.filter((x) => x !== REDIRECT), o]))}
              >
                {o}
              </button>
            ))}
          </div>
          {picked.includes(REDIRECT) && <p className="af-muted af-dirnote">换个方向会把这一版和造型表归档，按你说的新方向从头写故事线。</p>}
          <div className="af-rev2">
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={picked.includes(REDIRECT) ? "说一句新方向（必填）" : "想补充一句也可以（选项和文字至少给一样）"}
              maxLength={300}
            />
            <button
              type="button"
              className="v3-btn primary"
              disabled={busy || (picked.includes(REDIRECT) ? !note.trim() : !picked.length && !note.trim())}
              onClick={() =>
                picked.includes(REDIRECT)
                  ? send({ action: "redirect", note: note.trim() }, "已收下新方向，故事线会按新方向重写")
                  : send({ action: "revise", options: picked, note: note.trim() }, "已收下你的修改，正在重写")
              }
            >
              {picked.includes(REDIRECT) ? "按新方向重写" : "提交修改"}
            </button>
            <button type="button" className="v3-btn" onClick={() => setMode("")}>
              取消
            </button>
          </div>
        </div>
      ) : mode === "revise" ? (
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
            <button type="button" className="v3-btn" onClick={() => setMode("")}>
              取消
            </button>
          </div>
        </div>
      ) : (
        <>
          <button type="button" className="v3-btn primary" disabled={busy} onClick={() => send({ action: "approve" }, "已用这版，接着往下写")}>
            {direction ? "用这版（低于门槛，由你拍板放行）" : "用这版"}
          </button>
          <button type="button" className="v3-btn" disabled={busy} onClick={() => setMode("revise")}>
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
