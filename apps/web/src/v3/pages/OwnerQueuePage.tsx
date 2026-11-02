// UIRSI2 · L-116「待你看」阵列页（#/queue）。照 FILMUI 稿 data/review_pages/filmui/owner_queue.html 实现（电影胶片 A 风格）。
// 项目方 11:5x：“uiux 需要添加个要我看的阵列，点击去审核。其中，我需要全自动检测，尽量少人的操作。”
// · 只放三类：必须你拍板 / 机签抽检 / 审美挑选（GET /api/owner/queue）；其余系统自动处理，空队列写今天自动处理了多少项。
// · 每项一键决定（1 / 2 / 3，挑选 1–N，↵ 选推荐要先打开审核），← → / ↑ ↓ 换项，空格或双击打开审核视图，Esc 返回，Z 撤销上一个。
// · 登录即本人：POST /api/owner/decide 带 by=owner，服务器从登录会话认人、自动记审计；理由选填（点选词 + 一句）。
// · 队列读不到（接口失败或来源坏了）→ 写“队列读取失败：<来源>”，不显示“没有需要你看的”（SYSARCH / 总调度）。
import { useCallback, useEffect, useMemo, useState } from "react";
import { useStudio } from "../../store";
import { decideItem, queueFailText, undoItem, useOwnerQueue, type OwnerQueue, type QueueItem } from "../ownerQueue";
import "../ownerqueue.css";

const GROUPS: { kind: QueueItem["kind"]; title: string; sub: string }[] = [
  { kind: "decide", title: "必须你拍板", sub: "花钱 · 下载许可 · 删除 · 推翻旧审美 · 导入新季" },
  { kind: "spot", title: "机签抽检", sub: "机签通过的按每 10 张抽 1 张，给你复核" },
  { kind: "pick", title: "审美挑选", sub: "只放过了契约的候选；白框是系统推荐" },
];
const REASONS: Record<QueueItem["kind"], string[]> = {
  decide: ["同意系统建议", "要先看更多", "以后都这样处理"],
  spot: ["身份不像", "造型不对", "手 / 肢体坏", "场景不对", "画面假"],
  pick: ["更像本人", "造型更对", "光线更好", "构图更好"],
};
type Done = { id: string; label: string; at: string; title: string; thumb?: string | null };

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
            <div className="oq-img">{m.kind === "video" ? <video src={m.url!} muted preload="metadata" /> : <img src={m.url!} alt={m.label ?? ""} loading="lazy" draggable={false} />}</div>
            <span className="oq-ed">{(rec ? "推荐 · " : "") + (m.label ?? "")}</span>
          </div>
        );
      })}
    </div>
  );
}

function Acts({ item, onDecide, onOpen }: { item: QueueItem; onDecide: (choice: string) => void; onOpen?: () => void }) {
  return (
    <div className="oq-acts" onClick={(e) => e.stopPropagation()}>
      {item.options.map((o, i) => (
        <button key={o.key} className={(item.recommend ? item.recommend.choice === o.key : i === 0) ? "oq-main" : ""} onClick={() => onDecide(o.key)} title={`${o.label}（键盘 ${i + 1}）`}>
          <span>{o.label}</span>
          <kbd>{i + 1}</kbd>
        </button>
      ))}
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
        <p className="oq-ft">读不到的时候不当成“没有要看的”；已写报警（data/qa/alerts.jsonl · OWNERQ-READ），系统自动重试。</p>
      </div>
    );
  if (!q) return <div className="oq-empty">正在读队列…</div>;
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
      <h2>没有需要你看的</h2>
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
      <p className="oq-ft">有新的待办会出现在顶栏“待你看”，圆点变琥珀色。</p>
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
                {m.kind === "video" ? <video src={m.url!} controls autoPlay muted loop /> : <img src={m.url!} alt={m.label ?? ""} draggable={false} />}
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
        <h2>{item.title}</h2>
        <p className="oq-why">{item.detail}</p>
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
              <b>{item.options.find((o) => o.key === item.recommend!.choice)?.label ?? item.recommend.choice}</b>：{item.recommend.why}
            </div>
          </>
        )}
        <h4>
          理由<span>选填</span>
        </h4>
        <div className="oq-rsn">
          {REASONS[item.kind].map((t) => (
            <a key={t} className={tags.includes(t) ? "on" : ""} onClick={() => setTags((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]))}>
              {t}
            </a>
          ))}
          <input value={line} onChange={(e) => setLine(e.target.value)} placeholder="可不填，一句话" onKeyDown={(e) => e.stopPropagation()} />
        </div>
        <div className="oq-acts sticky">
          {item.kind === "pick" && chosen ? (
            <button className="oq-main" onClick={() => onDecide(chosen, reason)}>
              <span>用选中的这张</span>
              <kbd>↵</kbd>
            </button>
          ) : null}
          {item.options.map((o, i) => (
            <button key={o.key} className={item.kind !== "pick" && (item.recommend ? item.recommend.choice === o.key : i === 0) ? "oq-main" : ""} onClick={() => onDecide(o.key, reason)}>
              <span>{o.label}</span>
              <kbd>{i + 1}</kbd>
            </button>
          ))}
        </div>
        <p className="oq-aud">登录即本人：点了就生效，系统自动记审计（谁 · 什么时候 · 选了什么 · 理由），10 分钟内可按 Z 撤销。来源：{item.source}</p>
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
  const items = useMemo(() => {
    const all = q?.items ?? [];
    const order = GROUPS.map((g) => g.kind);
    return all.filter((x) => flt === "all" || x.kind === flt).sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind));
  }, [q, flt]);
  const cur = items[Math.min(sel, Math.max(0, items.length - 1))];
  const opened = open ? items.find((x) => x.id === open) ?? null : null;

  const decide = useCallback(
    async (it: QueueItem, choice: string, reason = "") => {
      const label = it.options.find((o) => o.key === choice)?.label ?? choice;
      try {
        await decideItem(it.id, choice, reason);
        setDone((d) => [{ id: it.id, label, at: hhmm(), title: it.title, thumb: it.media.find((m) => m.url)?.url }, ...d].slice(0, 30));
        st.notify(`已记下：${label}（已记审计 · Z 撤销）`);
        if (open) {
          const rest = items.filter((x) => x.id !== it.id);
          setOpen(rest.length ? rest[Math.min(sel, rest.length - 1)].id : null);
        }
      } catch (e) {
        st.notify(`没记上：${(e as Error).message}`, "err");
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
        setOpen(cur.id);
      } else if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(null);
      } else if (/^[1-9]$/.test(e.key)) {
        const it = opened ?? cur;
        const o = it?.options[Number(e.key) - 1];
        if (it && o) {
          e.preventDefault();
          e.stopPropagation();
          void decide(it, o.key);
        }
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
          <h1>待你看</h1>
          <p>
            只放需要你的事。
            {a && !fail ? (
              <>
                今天系统已自动处理 <span className="mono">{a.total}</span> 项（出图 {a.n_image} · 尾帧 {a.n_last} · 视频 {a.n_video}），机签 {a.signed} 张，自动重出 {a.redo} 次——这些都不进队列。
              </>
            ) : null}
          </p>
        </div>
        {q && q.count > 0 && !fail && (
          <div className="oq-r">
            <div className="oq-flt">
              {(["all", "decide", "spot", "pick"] as const).map((k) => (
                <a key={k} className={flt === k ? "on" : ""} onClick={() => (setFlt(k), setSel(0))}>
                  {k === "all" ? `全部 ${q.count}` : `${GROUPS.find((g) => g.kind === k)!.title} ${q.counts[k]}`}
                </a>
              ))}
            </div>
            <div className="oq-kh">← → 换项 · 1 / 2 / 3 一键决定 · 空格 打开审核 · Z 撤销上一个</div>
          </div>
        )}
      </header>
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
              <h2>{g.title}</h2>
              <span>{g.sub}</span>
            </div>
            {items
              .filter((x) => x.kind === g.kind)
              .map((it) => {
                const i = items.indexOf(it);
                return (
                  <article key={it.id} className={`oq-it${i === Math.min(sel, items.length - 1) ? " sel" : ""}`} data-id={it.id} onClick={() => setSel(i)} onDoubleClick={() => (setSel(i), setOpen(it.id))}>
                    <span className="oq-no">{String(i + 1).padStart(2, "0")}</span>
                    <Strip item={it} />
                    <div className="oq-tx">
                      <h3>{it.title}</h3>
                      <p className="oq-why">{it.detail}</p>
                      {it.recommend ? (
                        <p className="oq-rec">
                          <i className="oq-dot n" />
                          <b>系统推荐：</b>
                          {it.options.find((o) => o.key === it.recommend!.choice)?.label ?? it.recommend.choice}（{it.recommend.why}）
                        </p>
                      ) : null}
                      <p className="oq-src">
                        {it.source}
                        {it.script ? ` · ${it.script}` : ""}
                      </p>
                    </div>
                    <Acts item={it} onDecide={(c) => void decide(it, c)} onOpen={() => (setSel(i), setOpen(it.id))} />
                  </article>
                );
              })}
          </section>
        ))
      )}
      {done.length > 0 && (
        <section className="oq-group" aria-label="刚处理">
          <div className="oq-grp">
            <h2>刚处理</h2>
            <span>已记审计；10 分钟内可撤销</span>
          </div>
          {done.map((d, i) => (
            <div key={d.id + d.at} className="oq-done">
              <span className="oq-no">✓</span>
              <span>
                {d.thumb ? <img src={d.thumb} alt="" /> : null}
                {d.title} · {d.label} · 已记审计 {d.at}
              </span>
              {i === 0 ? <a onClick={() => void undo()}>撤销（Z）</a> : <span />}
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
