// UIRSI2 · L-116「待你看」阵列页（#/queue）。照 FILMUI 稿 data/review_pages/filmui/owner_queue.html 实现（电影胶片 A 风格）。
// 项目方 11:5x：“uiux 需要添加个要我看的阵列，点击去审核。其中，我需要全自动检测，尽量少人的操作。”
// · 只放三类：必须你拍板 / 机签抽检 / 审美挑选（GET /api/owner/queue）；其余系统自动处理，空队列写今天自动处理了多少项。
// · 每项一键决定（1 / 2 / 3，挑选 1–N，↵ 选推荐要先打开审核），← → / ↑ ↓ 换项，空格或双击打开审核视图，Esc 返回，Z 撤销上一个。
// · 登录即本人：POST /api/owner/decide 带 by=owner，服务器从登录会话认人、自动记审计；理由选填（点选词 + 一句）。
// · 队列读不到（接口失败或来源坏了）→ 写“队列读取失败：<来源>”，不显示“没有需要你看的”（SYSARCH / 总调度）。
import { useCallback, useEffect, useMemo, useState } from "react";
import { useStudio } from "../../store";
import { decideItem, pickItem, queueFailText, undoItem, useOwnerQueue, type OwnerQueue, type QueueItem } from "../ownerQueue";
import "../ownerqueue.css";
import { LookPeople } from "../OwnerDecision";
import { editReason, itemSentence, twoActs } from "../queueActs";
import { plainText } from "../plainWords"; // W5b：卡片标题 / 候选名过人话词典（词典只在 v3/plainWords.ts） // W5 UIUX：每条只有“批准 / 用这张”+“修改”

// W5 UIUX 11-03：分组名改大白话；C-20 🔴批准 🟡点开看 🟢告知
const GROUPS: { kind: QueueItem["kind"]; title: string; sub: string; mark: string }[] = [
  { kind: "decide", title: "要你批准", sub: "花钱、删除、推翻以前的决定、导入新一季——系统不会替你定", mark: "🔴" },
  { kind: "gate", title: "稿子写好了，等你看", sub: "故事线、大纲、剧本；点一条去那一页看，看完点“用这版”或“修改”", mark: "🟡" },
  { kind: "pick", title: "挑一张", sub: "候选都已过了系统检查；标“推荐”的是系统建议", mark: "🟡" },
  { kind: "spot", title: "抽查一下", sub: "系统已自动通过的图，每 10 张抽 1 张给你看一眼；没问题点“批准”", mark: "🟢" },
];
const REASONS: Record<QueueItem["kind"], string[]> = {
  gate: [],
  decide: ["同意系统建议", "要先看更多", "以后都这样处理"],
  spot: ["身份不像", "造型不对", "手 / 肢体坏", "场景不对", "画面假"],
  pick: ["更像本人", "造型更对", "光线更好", "构图更好"],
};
type Done = { id: string; label: string; at: string; title: string; thumb?: string | null };
/** 202 模式（C-09）：点了就先收下，卡片原地换成“已收到，系统处理中”，后台处理完从待办里消失 */
type Ack = { label: string; at: string; err?: string };

const dotOf = (s: string) => (s === "pass" ? "g" : s === "fail" ? "a" : "n");
const hhmm = () => new Date().toTimeString().slice(0, 5);

function Strip({ item, h = 150, onPick, chosen }: { item: QueueItem; h?: number; onPick?: (k: string) => void; chosen?: string | null }) {
  const media = item.media.filter((m) => m.url);
  if (!media.length) return <div className="oq-strip oq-nomedia" style={{ height: h }}>{item.category_label}</div>;
  return (
    <div className="oq-strip" style={{ ["--h" as string]: `${h}px` }}>
      {media.slice(0, 4).map((m, i) => {
        const rec = item.kind === "pick" && item.recommend?.choice === m.key;
        return (
          <div key={i} className={`oq-fr${rec ? " rec" : ""}${chosen && chosen === m.key ? " chosen" : ""}${onPick ? " pick" : ""}`} onClick={onPick && m.key ? (e) => (e.stopPropagation(), onPick(m.key!)) : undefined}>
            <div className="oq-img">{m.kind === "video" ? <video src={m.url!} muted preload="metadata" /> : m.kind === "audio" ? <audio controls preload="none" src={m.url!} /> : <img src={m.url!} alt={m.label ?? ""} loading="lazy" draggable={false} />}</div>
            <span className="oq-ed">{(rec ? "推荐 · " : "") + plainText(m.label ?? "")}</span>
          </div>
        );
      })}
    </div>
  );
}

/** 统一入口的挑选卡：每个候选内嵌可播放的音频 / 可点开大图的缩略图，点“用这个”一次选定（L-123：只有“用这个 / 修改”） */
function PickCards({ item, onPick, onRevise }: { item: QueueItem; onPick: (k: string) => Promise<void>; onRevise: (reason: string) => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [rev, setRev] = useState(false);
  const [txt, setTxt] = useState("");
  const ps = item.pick_state;
  const run = async (k: string, f: () => Promise<void>) => {
    setBusy(k);
    try {
      await f();
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="oq-pk" onClick={(e) => e.stopPropagation()}>
      {ps?.state === "failed" ? (
        <p className="oq-fail" role="alert">
          上次没处理成功（{ps.error}），系统会再试；你也可以再点一次。
        </p>
      ) : null}
      {ps?.delegate && ps.state === "done" ? (
        <p className="oq-pk-note">
          总调度按你睡前的授权先替你选了：{ps.delegate.label ?? ps.delegate.choice}{ps.delegate.score != null ? `（${ps.delegate.score} 分）` : ""}。想换就点别的候选，或点“修改”。
        </p>
      ) : null}
      {ps?.state === "revise_requested" ? <p className="oq-pk-note">已收到你的修改：{ps.reason || "（没写）"}。系统在按这句话重做；也可以现在直接选一个。</p> : null}
      {item.people?.length ? <LookPeople people={item.people} /> : null}
      <div className="oq-pk-row">
        {(item.candidates ?? []).map((c) => {
          const rec = item.recommend?.choice === c.key;
          return (
            <div key={c.key} className={`oq-pk-c${rec ? " rec" : ""}`}>
              <div className="oq-pk-h">
                <b>{plainText(c.label)}</b>
                {rec ? <em>推荐</em> : null}
              </div>
              {c.audio ? (
                <audio controls preload="none" src={c.audio} />
              ) : c.thumb ? (
                <a href={c.full ?? c.thumb} target="_blank" rel="noreferrer" title="点开看大图">
                  <img src={c.thumb} alt={c.label} loading="lazy" />
                </a>
              ) : (
                <div className="oq-nomedia">没有可预览的内容</div>
              )}
              <button className={rec ? "oq-main" : ""} disabled={busy !== null} onClick={() => void run(c.key, () => onPick(c.key))}>
                {busy === c.key ? "收到…" : c.audio ? "用这个" : "用这张"}
              </button>
            </div>
          );
        })}
      </div>
      <div className="oq-pk-rv">
        {rev ? (
          <>
            <input value={txt} onChange={(e) => setTxt(e.target.value)} onKeyDown={(e) => e.stopPropagation()} placeholder="想怎么改？一句话" />
            <button disabled={busy !== null || !txt.trim()} onClick={() => void run("revise", async () => (await onRevise(txt.trim()), setRev(false), setTxt("")))}>
              提交修改
            </button>
          </>
        ) : (
          <button onClick={() => setRev(true)}>修改</button>
        )}
      </div>
    </div>
  );
}

/** L-136 代选模式横幅：开着时显示“代选模式开启中（L-136）”+ 一键撤销（POST /api/owner/delegate/revoke，登录即本人） */
type DelegateStatus = { enabled: boolean; label: string | null; picked: number; gates: number; page: string; enabled_at?: string | null };
function DelegateBanner() {
  const [d, setD] = useState<DelegateStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const r = await fetch("/api/owner/delegate", { credentials: "same-origin" });
      if (r.ok) setD((await r.json()) as DelegateStatus);
    } catch {
      /* 读不到就不显示横幅 */
    }
  }, []);
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 30000);
    return () => clearInterval(t);
  }, [load]);
  if (!d?.enabled) return null;
  const revoke = async () => {
    setBusy(true);
    try {
      const r = await fetch("/api/owner/delegate/revoke", { method: "POST", credentials: "same-origin" });
      if (r.ok) setD((await r.json()) as DelegateStatus);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="oq-delegate" role="status" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", padding: "8px 12px", margin: "8px 0", border: "1px solid #e0b050", borderRadius: 6 }}>
      <b>{d.label ?? "代选模式开启中（L-136）"}</b>
      <span>
        已代选 {d.picked} 条挑选、{d.gates} 个写作闸门；你在网页上做任何决定后自动关闭。
      </span>
      <a href={d.page} target="_blank" rel="noreferrer">
        看代选汇总
      </a>
      <button disabled={busy} onClick={() => void revoke()}>
        {busy ? "撤销中…" : "撤销代选"}
      </button>
    </div>
  );
}

/** 两个动作：主按钮“批准 / 用这张”（键盘 1）+“修改”（键盘 2，写一句话怎么改）。没有“不要 / 稍后”（L-123） */
function TwoActs({ item, onDecide, onOpen, reason, sticky }: { item: QueueItem; onDecide: (choice: string, reason: string) => void; onOpen?: () => void; reason?: string; sticky?: boolean }) {
  const { use, edit } = twoActs(item);
  const [rev, setRev] = useState(false);
  const [txt, setTxt] = useState("");
  const said = (reason ?? "").trim();
  return (
    <div className={`oq-acts oq-two${sticky ? " sticky" : ""}`} onClick={(e) => e.stopPropagation()}>
      {use.kind === "choice" ? (
        <button className="oq-main" data-act="use" onClick={() => onDecide(use.key, said)} title={`${use.label}（键盘 1）`}>
          <span>{use.label}</span>
          <kbd>1</kbd>
        </button>
      ) : use.kind === "link" ? (
        <a className="oq-main oq-go" data-act="use" href={use.href}>
          <span>{use.label}</span>
        </a>
      ) : (
        <button className="oq-main" data-act="use" disabled title={use.why}>
          <span>{use.label}</span>
        </button>
      )}
      {edit.kind === "choice" ? (
        rev || said ? (
          <span className="oq-rev">
            {!said && <input autoFocus value={txt} onChange={(e) => setTxt(e.target.value)} onKeyDown={(e) => (e.stopPropagation(), e.key === "Enter" && txt.trim() && onDecide(edit.key, txt.trim()))} placeholder={edit.ask ?? "想怎么改？写一句话"} />}
            <button data-act="edit" disabled={!(said || txt.trim())} onClick={() => onDecide(edit.key, said || txt.trim())}>
              <span>{edit.submit ?? (said ? "按这句话修改" : "提交修改")}</span>
            </button>
          </span>
        ) : (
          <button data-act="edit" onClick={() => setRev(true)} title={`${edit.ask ?? "写一句话怎么改"}（键盘 2）`}>
            <span>{edit.label}</span>
            <kbd>2</kbd>
          </button>
        )
      ) : edit.kind === "link" ? (
        <a className="oq-go" data-act="edit" href={edit.href} title="去那一页改">
          <span>修改</span>
        </a>
      ) : (
        <button data-act="edit" disabled title={edit.why}>
          <span>修改</span>
        </button>
      )}
      {onOpen && (
        <a className="oq-rs" onClick={onOpen}>
          看详情 ›
        </a>
      )}
    </div>
  );
}

function Empty({ q, fail }: { q: OwnerQueue | null; fail: string | null }) {
  if (fail)
    return (
      <div className="oq-empty" role="alert">
        <h2 className="oq-fail">{fail}</h2>
        <p className="oq-ft">读不到的时候不当成“没有要你做的事”——系统已经记下这个问题，每 20 秒自动再试，读到了这里会自己出来。</p>
      </div>
    );
  if (!q) return <div className="oq-empty">正在读待办…</div>;
  const a = q.auto_today;
  const rows: [string, string | number][] = [
    ["出图（首帧候选）", a.n_image],
    ["尾帧", a.n_last],
    ["视频", a.n_video],
    ["机签通过", a.signed],
    ["自动重出", a.redo],
    [`机签与人工一致率（回归集 ${a.agreement_n ?? "?"} 张）`, a.agreement == null ? "—" : `${Math.round(a.agreement * 100)}%`],
  ];
  return (
    <div className="oq-empty">
      <h2>现在没有要你做的事</h2>
      <p className="oq-ft">系统自己在往下做。有新的需要你批准、挑图或看稿的，会出现在这里，顶部“待办”的数字会变。</p>
      <div className="oq-n">
        {a.total}
        <small>今天系统自动处理的项</small>
      </div>
      <table>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <td>{k}</td>
              <td className="v">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {q.master_waits?.n ? <p className="oq-ft">{q.master_waits.title}</p> : null}
      <p className="oq-ft">
        想看整部剧走到哪了：<a href="#/overview">全剧总览</a>。
      </p>
    </div>
  );
}

function Review({ item, pos, total, onBack, onPrev, onNext, onDecide }: { item: QueueItem; pos: number; total: number; onBack: () => void; onPrev: () => void; onNext: () => void; onDecide: (choice: string, reason: string) => void }) {
  const [tags, setTags] = useState<string[]>([]);
  const [line, setLine] = useState("");
  const [chosen, setChosen] = useState<string | null>(item.kind === "pick" ? item.recommend?.choice ?? null : null);
  useEffect(() => (setTags([]), setLine(""), setChosen(item.kind === "pick" ? item.recommend?.choice ?? null : null)), [item.id, item.kind, item.recommend]);
  const reason = [...tags, line.trim()].filter(Boolean).join("；");
  const media = item.media.filter((m) => m.url);
  const scores = item.kind === "pick" ? (item as QueueItem & { candidates?: { key: string; scores: QueueItem["scores"] }[] }).candidates?.find((c) => c.key === chosen)?.scores ?? item.scores : item.scores;
  const allPass = scores.length > 0 && scores.every((s) => s.status !== "fail");
  return (
    <div className="oq-rv">
      <section className="oq-stg">
        <nav className="oq-nav">
          <a onClick={onBack}>‹ 返回队列</a>
          <a onClick={onPrev}>上一项 ←</a>
          <a onClick={onNext}>下一项 →</a>
          <span className="oq-pos">
            {String(pos + 1).padStart(2, "0")} / {total} · {item.kind_label}
          </span>
        </nav>
        <div className={`oq-media${media.length > 2 ? " grid" : ""}`}>
          {media.length ? (
            media.map((m, i) => (
              <figure key={i} className={`oq-cell${item.kind === "pick" ? " pick" : ""}${chosen && chosen === m.key ? " chosen" : ""}`} onClick={item.kind === "pick" && m.key ? () => setChosen(m.key!) : undefined}>
                {m.kind === "video" ? <video src={m.url!} controls autoPlay muted loop /> : m.kind === "audio" ? <audio controls src={m.url!} /> : <img src={m.url!} alt={m.label ?? ""} draggable={false} />}
                <figcaption>
                  {item.recommend?.choice === m.key ? <b>系统推荐 · </b> : null}
                  {m.label}
                </figcaption>
              </figure>
            ))
          ) : (
            <div className="oq-cell oq-text">
              <p>{item.detail}</p>
              {item.quote ? <p className="oq-quote">你当时说：{item.quote}</p> : null}
            </div>
          )}
        </div>
      </section>
      <aside className="oq-side">
        <div className="oq-k">{item.category_label}</div>
        <h2>{plainText(item.title)}</h2>
        <p className="oq-why">{plainText(item.detail)}</p>
        {scores.length > 0 && (
          <>
            <h4>
              系统检测<span>{allPass ? "● 全部过线 / 只记录" : "有不过的项"}</span>
            </h4>
            {scores.map((s) => (
              <div key={s.id} className="oq-chk">
                <i className={`oq-dot ${dotOf(s.status)}`} />
                <b>{s.id}</b>
                <span className="oq-cd" title={`${s.title}：${s.detail}`}>
                  <span className="t">{s.title.split("（")[0]}</span> {s.detail}
                </span>
              </div>
            ))}
          </>
        )}
        {item.recommend && (
          <>
            <h4>系统推荐</h4>
            <div className="oq-recbox">
              <b>{(() => { const u = twoActs(item).use; return u.kind === "choice" && u.key === item.recommend!.choice && u.label === "批准" ? "批准" : item.options.find((o) => o.key === item.recommend!.choice)?.label ?? item.recommend!.choice; })()}</b>：{item.recommend.why}
            </div>
          </>
        )}
        <h4>
          想怎么改<span>点“批准”可以不写；点“修改”要写一句</span>
        </h4>
        <div className="oq-rsn">
          {REASONS[item.kind].map((t) => (
            <a key={t} className={tags.includes(t) ? "on" : ""} onClick={() => setTags((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]))}>
              {t}
            </a>
          ))}
          <input value={line} onChange={(e) => setLine(e.target.value)} placeholder="一句话，例如：脸不像，眼睛再大一点" onKeyDown={(e) => e.stopPropagation()} />
        </div>
        {/* W5 UIUX：详情里也只有两个动作；挑选类先在左边点中一张，“用这张”用点中的那张 */}
        {item.kind === "pick" && chosen ? (
          <div className="oq-acts sticky oq-two">
            <button className="oq-main" data-act="use" onClick={() => onDecide(chosen, reason)}>
              <span>用这张</span>
              <kbd>↵</kbd>
            </button>
            {item.link ? (
              <a className="oq-go" data-act="edit" href={item.link}>
                <span>修改</span>
              </a>
            ) : null}
          </div>
        ) : (
          <TwoActs item={item} onDecide={onDecide} reason={reason} sticky />
        )}
        <p className="oq-aud">你已登录，点了就生效，系统自动记下（谁 · 什么时候 · 选了什么 · 那句话）；10 分钟内可按 Z 撤销。</p>
      </aside>
    </div>
  );
}

export default function OwnerQueuePage() {
  const st = useStudio();
  const { q, err } = useOwnerQueue();
  const fail = queueFailText(q, err);
  const [flt, setFlt] = useState<"all" | QueueItem["kind"]>("all");
  const [sel, setSel] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  const [done, setDone] = useState<Done[]>([]);
  const [ack, setAck] = useState<Record<string, Ack>>({});
  const items = useMemo(() => {
    const all = q?.items ?? [];
    const order = GROUPS.map((g) => g.kind);
    return all.filter((x) => flt === "all" || x.kind === flt).sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  }, [q, flt]);
  const cur = items[Math.min(sel, Math.max(0, items.length - 1))];
  const opened = open ? items.find((x) => x.id === open) ?? null : null;

  const decide = useCallback(
    async (it: QueueItem, choice: string, reason = "") => {
      const acts = twoActs(it);
      const isEdit = acts.edit.kind === "choice" && acts.edit.key === choice;
      if (isEdit) reason = editReason(it, choice, reason); // 拍板类：reason = “要求修改：<那句话>”（后端 choice 仍是反向选项）
      const label = isEdit ? (reason.startsWith("要求修改：") ? reason : `修改：${reason}`) : acts.use.kind === "choice" && acts.use.key === choice ? acts.use.label : it.options.find((o) => o.key === choice)?.label ?? choice;
      // 202 模式：先在原地显示“已收到，系统处理中”，不等后端
      setAck((m) => ({ ...m, [it.id]: { label, at: hhmm() } }));
      try {
        if (it.pick_api) {
          // 统一入口：选定后真的生效（写配置），撤不回，不进“刚处理”的撤销列表
          await pickItem(it.id, choice, reason);
          st.notify(`已收到：${label}，系统处理中`);
          if (open) setOpen(null);
          return;
        }
        await decideItem(it.id, choice, reason);
        setDone((d) => [{ id: it.id, label, at: hhmm(), title: it.title, thumb: it.media.find((m) => m.url)?.url }, ...d].slice(0, 30));
        st.notify(`已收到：${label}（Z 撤销）`);
        if (open) {
          const rest = items.filter((x) => x.id !== it.id);
          setOpen(rest.length ? rest[Math.min(sel, rest.length - 1)].id : null);
        }
      } catch (e) {
        setAck((m) => ({ ...m, [it.id]: { label, at: hhmm(), err: (e as Error).message } }));
        st.notify(`没收到，请再点一次：${(e as Error).message}`, "err");
      }
    },
    [st, open, items, sel],
  );
  const undo = useCallback(async () => {
    const last = done[0];
    if (!last) return;
    try {
      await undoItem(last.id);
      setDone((d) => d.slice(1));
      setAck((m) => {
        const n = { ...m };
        delete n[last.id];
        return n;
      });
      st.notify(`已撤销：${last.title}`);
    } catch (e) {
      st.notify(`撤不回：${(e as Error).message}`, "err");
    }
  }, [done, st]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const n = items.length;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") {
        e.preventDefault();
        if (!n) return;
        const i = (Math.min(sel, n - 1) + 1) % n;
        setSel(i);
        if (open) setOpen(items[i].id);
      } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!n) return;
        const i = (Math.min(sel, n - 1) - 1 + n) % n;
        setSel(i);
        if (open) setOpen(items[i].id);
      } else if ((e.key === " " || e.key === "Enter") && !open && cur) {
        e.preventDefault();
        if (cur.kind === "gate") {
          if (cur.link) location.hash = cur.link; // 写作闸门：直接去那一页处理
        } else setOpen(cur.id);
      } else if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(null);
      } else if (e.key === "1" || e.key === "2") {
        // W5 UIUX：1 = 批准 / 用这张；2 = 修改（打开详情写一句话）
        const it = opened ?? cur;
        if (!it) return;
        const a = twoActs(it);
        e.preventDefault();
        e.stopPropagation();
        if (e.key === "1") {
          if (a.use.kind === "choice") void decide(it, a.use.key);
          else if (a.use.kind === "link") location.hash = a.use.href;
        } else if (a.edit.kind === "link") location.hash = a.edit.href;
        else if (!opened) setOpen(it.id);
      } else if (e.key === "z" || e.key === "Z") {
        e.preventDefault();
        void undo();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [items, sel, open, opened, cur, decide, undo]);

  if (opened) {
    const pos = items.indexOf(opened);
    const go = (d: number) => {
      const i = (pos + d + items.length) % items.length;
      setSel(i);
      setOpen(items[i].id);
    };
    return <Review item={opened} pos={pos} total={items.length} onBack={() => setOpen(null)} onPrev={() => go(-1)} onNext={() => go(1)} onDecide={(c, r) => void decide(opened, c, r)} />;
  }

  const a = q?.auto_today;
  return (
    <div className="oq-page">
      <header className="oq-head">
        <div>
          <h1>待办</h1>
          <p>
            只放需要你动手的事：每条点“批准 / 用这张”或“修改”（写一句话）就行，点完系统自己往下走。
            {a && !fail ? (
              <>
                今天系统已自己处理了 <span className="mono">{a.total}</span> 项（出图 {a.n_image} · 尾帧 {a.n_last} · 视频 {a.n_video}），不用你管。
              </>
            ) : null}
          </p>
        </div>
        {q && q.count > 0 && !fail && (
          <div className="oq-r">
            <div className="oq-flt">
              {(["all", "gate", "decide", "spot", "pick"] as const).map((k) => (
                <a key={k} className={flt === k ? "on" : ""} onClick={() => (setFlt(k), setSel(0))}>
                  {k === "all" ? `全部 ${q.count}` : `${GROUPS.find((g) => g.kind === k)!.title} ${q.counts[k] ?? 0}`}
                </a>
              ))}
            </div>
            <div className="oq-kh">← → 换一条 · 1 批准 / 用这张 · 2 修改 · 空格 看详情 · Z 撤销上一个</div>
          </div>
        )}
      </header>
      <DelegateBanner />
      {fail && q && q.count > 0 ? (
        <p className="oq-fail" role="alert">
          {fail}（下面的数可能不全）
        </p>
      ) : null}
      {!q || fail && !q.count || q.count === 0 ? (
        <Empty q={q} fail={fail} />
      ) : (
        GROUPS.filter((g) => items.some((x) => x.kind === g.kind)).map((g) => (
          <section key={g.kind} className="oq-group" aria-label={g.title}>
            <div className="oq-grp">
              <i className={`oq-dot ${g.kind === "decide" ? "a" : "n"}`} />
              <h2>
                <span aria-hidden>{g.mark}</span> {g.title}
              </h2>
              <span>{g.sub}</span>
            </div>
            {items
              .filter((x) => x.kind === g.kind)
              .map((it) => {
                const i = items.indexOf(it);
                const k = ack[it.id];
                if (k && !k.err)
                  return (
                    <article key={it.id} className="oq-it oq-ack" data-id={it.id} role="status">
                      <span className="oq-no">✓</span>
                      <div className="oq-tx">
                        <h3>已收到，系统处理中</h3>
                        <p className="oq-why">
                          {it.title} · {k.label} · {k.at}。处理完这一条会自己消失。
                        </p>
                      </div>
                    </article>
                  );
                return (
                  it.kind === "gate" ? (
                    <article key={it.id} className={`oq-it oq-gate${i === Math.min(sel, items.length - 1) ? " sel" : ""}`} data-id={it.id} onClick={() => it.link && (location.hash = it.link)}>
                      <span className="oq-no">{String(i + 1).padStart(2, "0")}</span>
                      <div className="oq-tx">
                        <h3>{plainText(it.title)}</h3>
                        <p className="oq-why">{itemSentence(it)}</p>
                      </div>
                      <TwoActs item={it} onDecide={(c, r) => void decide(it, c, r)} />
                    </article>
                  ) : (
                  <article key={it.id} className={`oq-it${it.pick_api ? " oq-pickapi" : ""}${i === Math.min(sel, items.length - 1) ? " sel" : ""}`} data-id={it.id} onClick={() => setSel(i)} onDoubleClick={() => !it.pick_api && (setSel(i), setOpen(it.id))}>
                    <span className="oq-no">{String(i + 1).padStart(2, "0")}</span>
                    {it.pick_api ? null : <Strip item={it} />}
                    <div className="oq-tx">
                      <h3>{plainText(it.title)}</h3>
                      <p className="oq-why">{itemSentence(it)}</p>
                      {k?.err ? <p className="oq-fail" role="alert">刚才没收到（{k.err}），请再点一次。</p> : null}
                      {it.recommend ? (
                        <p className="oq-rec">
                          <i className="oq-dot n" />
                          <b>系统推荐：</b>
                          {(() => {
                            const u = twoActs(it).use;
                            return u.kind === "choice" && u.key === it.recommend!.choice && u.label === "批准" ? "批准" : it.options.find((o) => o.key === it.recommend!.choice)?.label ?? it.recommend!.choice;
                          })()}
                          （{it.recommend.why}）
                        </p>
                      ) : null}
                      {it.link ? (
                        <p className="oq-src">
                          <a href={it.link} onClick={(e) => e.stopPropagation()}>
                            去对应页面看 ›
                          </a>
                        </p>
                      ) : null}
                    </div>
                    {it.pick_api ? (
                      <PickCards
                        item={it}
                        onPick={(k) => decide(it, k)}
                        onRevise={async (r) => {
                          try {
                            await pickItem(it.id, "revise", r);
                            st.notify("已记下修改意见");
                          } catch (e) {
                            st.notify(`没记上：${(e as Error).message}`, "err");
                          }
                        }}
                      />
                    ) : (
                      <TwoActs item={it} onDecide={(c, r) => void decide(it, c, r)} onOpen={() => (setSel(i), setOpen(it.id))} />
                    )}
                  </article>
                  )
                );
              })}
          </section>
        ))
      )}
      {done.length > 0 && (
        <section className="oq-group" aria-label="刚处理">
          <div className="oq-grp">
            <h2>刚处理</h2>
            <span>都已记下；10 分钟内可撤销</span>
          </div>
          {done.map((d, i) => (
            <div key={d.id + d.at} className="oq-done">
              <span className="oq-no">✓</span>
              <span>
                {d.thumb ? <img src={d.thumb} alt="" /> : null}
                {d.title} · {d.label} · {d.at}
              </span>
              {i === 0 ? <a onClick={() => void undo()}>撤销（Z）</a> : <span />}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
