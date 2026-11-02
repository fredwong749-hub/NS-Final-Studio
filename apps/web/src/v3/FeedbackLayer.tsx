// UIRSI2 · 反馈模式（总调度 11-02：项目方要“反馈模式”；后端 FEEDBACK，接口 docs/feedback/API.md §5）。
// 顶栏开关“反馈”打开后：鼠标移到任意帧 / 视频 / 字段 / 按钮上高亮，点一下弹文字框（自动带镜号、对象、版本、视频时间码，帧和视频可附截图），
// 一键提交（提交人取登录会话）；“反馈 N”打开列表抽屉：按状态分组，圆点只用 灰 / 琥珀 / 绿，已修 / 已验证 / 已关单的条目有“没修好”（打回）。
// 风格按电影胶片 A。Esc 关弹框 / 抽屉；反馈模式开着时页面上的点击只用来选目标，不触发原功能。
import { useEffect, useRef, useState } from "react";
import { useStudio } from "../store";
import { DOT_WORD, pickOf, reopenFeedback, setFbDrawer, setFbMode, snapMedia, submitFeedback, uiDot, useFeedback, type FbItem, type FbPick } from "./feedback";
import "./feedback.css";

/** 顶栏：反馈模式开关 + 反馈列表入口 */
export function FeedbackToggle() {
  const { mode, list, err } = useFeedback();
  const open = list ? list.dots.red : 0;
  const doing = list ? list.dots.yellow : 0;
  return (
    <span className="fb-ui fb-top">
      {/* UIFIX-S（总调度 13:4x：“反馈旁边单独一个 ● 1 看不懂”）：合成一个按钮“反馈 · N”；点 = 开 / 关反馈模式；反馈列表在 工具 ▾ → 运行 → 反馈列表 */}
      <button className={`v3-btn fb-switch${mode ? " on" : ""}`} aria-pressed={mode} onClick={() => setFbMode(!mode)}
        title={`${err ? `反馈列表读不到：${err}` : `${doing} 条处理中 · ${open} 条新的 / 被打回 · ${list?.dots.green ?? 0} 条已修`}
${mode ? "反馈模式开着：点页面上要改的地方写一句；再点这里关掉（Esc 也行）" : "点一下进入反馈模式：点任意帧、视频、字段或按钮，写一句哪里不对"}
反馈列表：工具 ▾ → 运行 → 反馈列表`}>
        {mode ? "反馈中…" : "反馈"}{err ? " · !" : open + doing ? ` · ${open + doing}` : ""}
      </button>
    </span>
  );
}

function FbDialog({ pick, onClose }: { pick: FbPick; onClose: () => void }) {
  const st = useStudio();
  const [text, setText] = useState("");
  const [snap, setSnap] = useState(() => !!pick.media);
  const [busy, setBusy] = useState(false);
  const ta = useRef<HTMLTextAreaElement>(null);
  useEffect(() => ta.current?.focus(), []);
  const shot = snapMedia(pick.media);
  const send = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const it = await submitFeedback({
        text: text.trim(), route: location.pathname + location.search + location.hash, ep: pick.ep, shot: pick.shot, target: pick.target,
        take: pick.take, timecode: pick.timecode, screenshot: snap ? shot : null, viewport: { w: innerWidth, h: innerHeight, dpr: devicePixelRatio },
        context: { summary: pick.summary },
      });
      st.notify(`反馈已提交 ${it.id ?? ""}：在“反馈”列表里能看到处理进度`);
      onClose();
    } catch (e) {
      st.notify(`反馈没提交上：${(e as Error).message}`, "err");
      setBusy(false);
    }
  };
  const r = pick.el.getBoundingClientRect();
  const left = Math.min(Math.max(12, r.left), innerWidth - 392);
  const top = r.bottom + 8 + 260 < innerHeight ? r.bottom + 8 : Math.max(12, r.top - 268);
  return (
    <div className="fb-ui fb-dlg" style={{ left, top }} role="dialog" aria-label="写反馈" onKeyDown={(e) => (e.stopPropagation(), e.key === "Escape" && onClose(), (e.ctrlKey || e.metaKey) && e.key === "Enter" && void send())}>
      <div className="fb-ctx">{pick.summary || "这一处"}</div>
      <textarea ref={ta} value={text} onChange={(e) => setText(e.target.value)} placeholder="哪里不对？一句话就行（Ctrl + Enter 提交）" rows={3} />
      <div className="fb-row">
        {shot ? (
          <label className="fb-snap">
            <input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)} /> 附截图
            <img src={shot} alt="" />
          </label>
        ) : (
          <span className="fb-hint">自动带上：页面地址、对象、版本{pick.timecode != null ? "、时间码" : ""}</span>
        )}
        <span className="fb-grow" />
        <button className="v3-btn" onClick={onClose}>取消</button>
        <button className="v3-btn fb-send" disabled={!text.trim() || busy} onClick={() => void send()}>
          {busy ? "提交中…" : "提交"}
        </button>
      </div>
    </div>
  );
}

const GROUPS: { dot: "red" | "yellow" | "green"; title: string }[] = [
  { dot: "red", title: "新反馈 / 被打回" },
  { dot: "yellow", title: "处理中" },
  { dot: "green", title: "已修 / 已验证" },
];

function FbDrawer() {
  const st = useStudio();
  const { list, err, mode } = useFeedback();
  const [note, setNote] = useState<Record<string, string>>({});
  const reopen = async (it: FbItem) => {
    try {
      await reopenFeedback(it.id, note[it.id] ?? "");
      st.notify(`${it.id} 已打回，回到新反馈`);
    } catch (e) {
      st.notify(`没打回：${(e as Error).message}`, "err");
    }
  };
  return (
    <aside className="fb-ui fb-drawer" role="dialog" aria-label="反馈列表" onKeyDown={(e) => e.key === "Escape" && setFbDrawer(false)}>
      <header>
        <h3>反馈</h3>
        <button className={`v3-btn fb-switch${mode ? " on" : ""}`} aria-pressed={mode} onClick={() => setFbMode(!mode)}>
          {mode ? "反馈模式：开" : "反馈模式：关"}
        </button>
        <button className="v3-btn" onClick={() => setFbDrawer(false)} title="关闭（Esc）">
          ×
        </button>
      </header>
      {err && <p className="fb-err">反馈列表读取失败：{err}</p>}
      {!err && !list && <p className="fb-hint">正在读…</p>}
      {list && !list.items.length && <p className="fb-hint">还没有反馈。打开“反馈模式”，点页面上要改的地方写一句。</p>}
      {list &&
        GROUPS.map((g) => {
          const items = list.items.filter((x) => x.dot === g.dot);
          if (!items.length) return null;
          const d = uiDot(g.dot);
          return (
            <section key={g.dot}>
              <h4>
                <i className={`v3-dot d-${d}`} aria-hidden /> {g.title} <span>{items.length}</span>
              </h4>
              {items.map((it) => (
                <article key={it.id} className="fb-item">
                  <div className="fb-meta">
                    <b>{it.id}</b> · {it.ep != null ? `第 ${it.ep} 集 ` : ""}
                    {it.shot ?? ""} {it.target?.kind ? `· ${{ first: "首帧", last: "尾帧", video: "视频", field: "字段", ui: "界面" }[it.target.kind as string] ?? it.target.kind}` : ""}
                    {it.timecode != null ? ` · ${it.timecode} 秒` : ""} · <span title={DOT_WORD[d]}>{it.status_zh ?? it.status}</span>
                    {it.reopened ? ` · 打回 ${it.reopened} 次` : ""}
                  </div>
                  <p className="fb-text">“{it.text}”</p>
                  {(it.fix_note || it.root_cause) && <p className="fb-fix">{it.fix_note ?? it.root_cause}</p>}
                  <div className="fb-foot">
                    {it.owner ? <span>负责：{it.owner}</span> : <span>待分派</span>}
                    {it.route ? (
                      <a href={it.route.includes("#") ? "#" + it.route.split("#")[1] : it.route} onClick={() => setFbDrawer(false)}>
                        去那一页
                      </a>
                    ) : null}
                    {["fixed", "verified", "closed"].includes(it.status) && (
                      <>
                        <input placeholder="哪里还不对（可不填）" value={note[it.id] ?? ""} onChange={(e) => setNote((n) => ({ ...n, [it.id]: e.target.value }))} onKeyDown={(e) => e.stopPropagation()} />
                        <button className="v3-btn" onClick={() => void reopen(it)} title="打回：回到新反馈，负责方重新处理">
                          没修好
                        </button>
                      </>
                    )}
                  </div>
                </article>
              ))}
            </section>
          );
        })}
    </aside>
  );
}

/** 帧角标：这一镜这一格（首帧 / 尾帧 / 视频）上还没关的反馈 → 左上角一个圆点（琥珀 = 新 / 被打回，灰 = 处理中）；悬停看原话，点开列表抽屉 */
export function FbDot({ sid, kind }: { sid: string; kind: "first" | "last" | "video" }) {
  const { list } = useFeedback();
  const m = /ep(\d+)-(S\d+)/i.exec(sid);
  if (!list || !m) return null;
  const ep = Number(m[1]);
  const mine = list.items.filter((x) => x.ep === ep && x.shot === m[2] && x.target?.kind === kind && x.dot !== "green");
  if (!mine.length) return null;
  const d = mine.some((x) => x.dot === "red") ? "yellow" : "gray";
  return (
    <button
      className="fb-ui fb-dot"
      onClick={(e) => (e.stopPropagation(), setFbDrawer(true))}
      title={mine.map((x) => `${x.id} · ${x.status_zh ?? x.status}：${x.text}`).join(String.fromCharCode(10)) + String.fromCharCode(10) + "点开反馈列表"}
      aria-label={`反馈 ${mine.length} 条`}
    >
      <i className={`v3-dot d-${d}`} aria-hidden />
      {mine.length > 1 ? <b>{mine.length}</b> : null}
    </button>
  );
}

/** 挂在 App 里：反馈模式开着时的高亮 / 点选 / 弹框，以及列表抽屉 */
export function FeedbackHost() {
  const st = useStudio();
  const { mode, drawer } = useFeedback();
  const [pick, setPick] = useState<FbPick | null>(null);
  const [box, setBox] = useState<DOMRect | null>(null);
  useEffect(() => {
    if (!mode) {
      setBox(null);
      return;
    }
    const skip = (t: EventTarget | null) => !(t instanceof HTMLElement) || !!t.closest(".fb-ui");
    const move = (e: MouseEvent) => {
      if (skip(e.target) || pick) return;
      setBox(pickOf(e.target as HTMLElement, st.epNum ?? null).el.getBoundingClientRect());
    };
    const click = (e: MouseEvent) => {
      if (skip(e.target)) return;
      e.preventDefault();
      e.stopPropagation();
      setPick(pickOf(e.target as HTMLElement, st.epNum ?? null));
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pick) setFbMode(false);
    };
    document.addEventListener("mousemove", move, true);
    document.addEventListener("click", click, true);
    document.addEventListener("dblclick", click, true);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousemove", move, true);
      document.removeEventListener("click", click, true);
      document.removeEventListener("dblclick", click, true);
      document.removeEventListener("keydown", key);
    };
  }, [mode, pick, st.epNum]);
  return (
    <>
      {mode && box && !pick && <div className="fb-ui fb-hl" style={{ left: box.left - 2, top: box.top - 2, width: box.width + 4, height: box.height + 4 }} aria-hidden />}
      {mode && !pick && <div className="fb-ui fb-banner">反馈模式：点要改的地方写一句 · Esc 退出</div>}
      {pick && <FbDialog pick={pick} onClose={() => setPick(null)} />}
      {drawer && <FbDrawer />}
    </>
  );
}
