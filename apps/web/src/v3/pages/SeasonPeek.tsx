// UIRSI r43（总调度 11-02 02:2x 规格 §四，项目方 02:1x：“参考过程我也觉得不好看，能给我更专业的 layout 吗？”）
// 全剧总览单击镜头卡 → 右侧滑出的详情抽屉（约 520px，盖在页面上，Esc 关闭，不跳页；双击卡片仍进画布）。
// 从上到下五块，每块小号标题 + 细分隔线：① 当前首帧大图 + 状态文字 + 原因；② 参考图（固定 4 列）；③ 出图历史（新 → 旧）；
// ④ 检查结果（项目 / 结果两列）；⑤ 操作：打开画布 / 重出 / 更多。全部中性色，不用彩色角标。
// 数据：GET /api/shots/{id}/refs（参考）· GET /api/candidates?ep=N（历史，旧剧本版本已隔离不在这里）·
//       GET /api/shots/{id}/takes/image/{n}/checks（检查，ns_api.takes_ui.take_checks）。
import { useEffect, useState } from "react";
import { useStudio } from "../../store";
import { thumb } from "../../thumb";
import type { ShotSummary } from "../../types";
import { apiV1, type ShotRefsV1 } from "../api_v1";
import { epOf, loadCandidates, plainLabel, reloadCandidates, type Cand, type CandShots } from "../candidates";
import { regenTake } from "../RegenButton.helpers";
import { Pop } from "../widgets";
import { dotOf, statusWord, type MainStatus } from "./seasonDot";

type Img = { url: string; label: string };
const fileUrl = (f: string | null | undefined) => (f ? (f.startsWith("/") ? f : `/files/${f.replace(/^data\//, "")}`) : null);

function refImgs(d: ShotRefsV1 | null): Img[] {
  const out: Img[] = [];
  for (const c of d?.characters ?? []) {
    const ch = c as unknown as { name?: string; effective?: { images?: { file?: string; url?: string | null; kind?: string }[] } };
    for (const i of ch.effective?.images ?? []) {
      const u = i.url ?? fileUrl(i.file);
      const word = i.kind === "face" ? `身份脸 · ${ch.name ?? ""}` : i.kind === "sheet" ? `造型设定图 · ${ch.name ?? ""}` : i.kind === "board" ? "参考板" : "参考图";
      if (u) out.push({ url: u, label: word });
    }
  }
  const sc = d?.scene?.effective;
  const su = sc && typeof sc === "object" ? sc.url : null;
  if (su) out.push({ url: su, label: "场景底图" });
  return out;
}

type Hist = Img & { stage: "image" | "last"; n: number; at: string };
function history(c: CandShots | null, shot: string): Hist[] {
  const out: Hist[] = [];
  for (const [st, word] of [["image", "首帧"], ["last", "尾帧"]] as const) {
    const s = c?.[shot]?.[st];
    for (const t of s?.takes ?? []) {
      const verdict = t.rejected ? "已驳回" : t.bad || t.ok === false ? `没过${t.why_not || t.bad ? ` · ${t.why_not ?? t.bad}` : ""}` : s?.active === t.n ? "通过 · 当前" : "通过";
      out.push({ url: t.url, stage: st, n: t.n, at: t.created_at ?? "", label: `${word}第 ${t.n} 版 · ${verdict}${t.label ? ` · ${plainLabel(t.label)}` : ""}` });
    }
  }
  return out.sort((a, b) => (b.at || "").localeCompare(a.at || "") || b.n - a.n);
}

type Check = { id: string; title: string; status: string | null; detail: string };
type Checks = { items: Check[]; judge: { verdict: string | null; reasons: string[] } | null; identity?: Record<string, number> };
// 出场人物（r43 项目方 02:4x“缺乏很多细节，比如人物什么的”）：身份脸 + 本镜造型设定图 + 这张图里的身份相似度（Q1）
type Who = { id: string; name: string; face: string | null; sheet: string | null; look: string | null; lookId: string | null };
function castOf(d: ShotRefsV1 | null): Who[] {
  return (d?.characters ?? []).map((c) => {
    const imgs = ((c.effective?.images ?? []) as { file?: string; url?: string | null; kind?: string }[]).filter((i) => typeof i === "object");
    const pick = (k: string) => { const i = imgs.find((x) => x.kind === k); return i ? i.url ?? fileUrl(i.file) : null; };
    return { id: c.id, name: c.name, face: pick("face"), sheet: pick("sheet"), look: c.effective?.look_name ?? null, lookId: c.effective?.look ?? null };
  });
}
// 检查项大白话名（GEN_CONTRACT postflight 的 Q 编号）
const CHECK_NAME: Record<string, string> = { Q1: "脸像", Q2: "造型 / 外套", Q3: "景别", Q4: "质感", Q5: "手和肢体", Q6: "文字 / 水印", Q7: "场景一致", Q8: "发色", Q9: "看图检查" };
const RESULT: Record<string, string> = { pass: "通过", fail: "没过", warn: "有疑问", untested: "未测", skip: "不适用", na: "不适用" };

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="sd-sec">
      <h5>{title}</h5>
      {children}
    </section>
  );
}

export function SeasonDrawer({ shot, sum, status, meta, onClose }: { shot: string; sum: ShotSummary | undefined; status: MainStatus | null | undefined; meta: string; onClose: () => void }) {
  const st = useStudio();
  const [refs, setRefs] = useState<Img[] | null>(null);
  const [cast, setCast] = useState<Who[] | null>(null);
  const [cands, setCands] = useState<CandShots | null>(null);
  const [checks, setChecks] = useState<Checks | null | "none">(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setRefs(null);
    setCands(null);
    setChecks(null);
    setCast(null);
    apiV1
      .shotRefs(shot)
      .then(async (d) => {
        if (!alive) return;
        setRefs(refImgs(d));
        const ws = castOf(d);
        setCast(ws);
        // r44（总调度：林晚造型 A 明明有 sleevefix 设定图却显示“无设定图”）：本镜设定图按 asset_refs.sheet_of（继承链）取，与出图同一张
        const pairs = ws.filter((w) => w.lookId).map((w) => `${w.id}:${w.lookId}`).join(",");
        if (!pairs) return;
        const r = await fetch(`/api/season/sheets?pairs=${encodeURIComponent(pairs)}`).then((x) => (x.ok ? (x.json() as Promise<{ sheets: Record<string, string | null> }>) : null)).catch(() => null);
        if (alive && r) setCast(ws.map((w) => ({ ...w, sheet: (w.lookId ? r.sheets[`${w.id}:${w.lookId}`] : null) ?? w.sheet })));
      })
      .catch(() => alive && (setRefs([]), setCast([])));
    loadCandidates(epOf(shot)).then((c) => alive && setCands(c)).catch(() => alive && setCands({}));
    return () => {
      alive = false;
    };
  }, [shot]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && (e.stopPropagation(), onClose());
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [onClose]);
  const img = cands?.[shot]?.image;
  const takes = [...(img?.takes ?? [])].sort((a: Cand, b: Cand) => b.n - a.n);
  // r45（项目方截图 ep06-S2 第 6 版）：默认当前版本 → 最近一张通过的 → 都没过才显示最新失败的，并在图上写清“未通过：原因”
  const okTake = takes.find((t) => t.ok !== false && !t.bad && !t.rejected);
  const curN = img?.active ?? okTake?.n ?? takes[0]?.n ?? null;
  const cur = takes.find((t) => t.n === curN) ?? null;
  const big = sum?.first_frame ?? cur?.url ?? null;
  useEffect(() => {
    if (cands == null) return;
    if (curN == null) return setChecks("none");
    let alive = true;
    fetch(`/api/shots/${encodeURIComponent(shot)}/takes/image/${curN}/checks`)
      .then((r) => (r.ok ? (r.json() as Promise<Checks>) : null))
      .then((d) => alive && setChecks(d ?? "none"), () => alive && setChecks("none"));
    return () => {
      alive = false;
    };
  }, [shot, curN, cands]);
  const hist = cands == null ? null : history(cands, shot);
  const dot = dotOf(status);
  const openCanvas = () => (onClose(), (location.hash = `#${shot}`));
  const regen = () => {
    if (curN == null) return;
    setBusy(true);
    regenTake(shot, "image", curN)
      .then(() => (st.notify(`${shot} 已排上重出首帧（基于第 ${curN} 版换 seed；新图过检查才设为当前）`), reloadCandidates(epOf(shot))))
      .catch((e: Error) => st.notify(`${shot} 重出没排上：${e.message}`, "err"))
      .finally(() => setBusy(false));
  };
  return (
    <>
      <div className="sd-scrim" onClick={onClose} aria-hidden />
      <aside className="sd" role="dialog" aria-label={`${shot} 详情`}>
        <header className="sd-head">
          <b className="sd-title">第 {epOf(shot)} 集 · {shot.split("-")[1]}</b>
          <span className="sd-sub">{meta}</span>
          <span className="grow" />
          <button type="button" className="sd-x" onClick={onClose} title="关闭（Esc）" aria-label="关闭">
            ✕
          </button>
        </header>
        <div className="sd-body">
          <Section title="出场人物">
            {cast == null ? (
              <p className="sd-muted">读取中…</p>
            ) : cast.length ? (
              <ul className="sd-cast">
                {cast.map((w) => {
                  const sim = checks && checks !== "none" ? checks.identity?.[w.id] : undefined;
                  return (
                    <li key={w.id}>
                      {w.face ? <img src={thumb(w.face, 160) ?? w.face} alt="" data-zoom-label={`${w.name} · 身份脸`} /> : <span className="sd-ph">无身份脸</span>}
                      {w.sheet ? <img src={thumb(w.sheet, 160) ?? w.sheet} alt="" data-zoom-label={`${w.name} · 本镜造型设定图`} /> : <span className="sd-ph">无设定图</span>}
                      <span>
                        <b>{w.name}</b>
                        <small>{w.look ?? "造型未标"} · {sim != null ? `身份相似度 ${sim.toFixed(2)}` : curN == null ? "还没出图，没有相似度" : "这张图没测相似度"}</small>
                      </span>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="sd-muted">这一镜没有登记人物</p>
            )}
          </Section>
          <Section title={sum?.first_frame || img?.active != null ? "当前首帧" : cur ? (cur.ok === false || cur.bad ? `最新一版（首帧第 ${cur.n} 版，没通过，所有版本都没过）` : `最近通过的候选（首帧第 ${cur.n} 版，还没定为当前）`) : "当前首帧"}>
            {cur && !sum?.first_frame && (cur.ok === false || cur.bad) && <p className="sd-fail">未通过：{(cur.why_not ?? cur.bad ?? "").replace(/^未通过：/, "") || "检查没过"}</p>}
            {big ? (
              <img className={`sd-big${cur && !sum?.first_frame && (cur.ok === false || cur.bad) ? " failed" : ""}`} src={thumb(big, 720) ?? big} alt="" data-zoom-label={`${shot} · 首帧${curN != null ? ` 第 ${curN} 版` : ""}`} />
            ) : (
              <div className="sd-big sd-none">{status?.main5 === "doing" && !status.running ? "排队中" : status?.running ? "正在出" : "未开始"}</div>
            )}
            <p className="sd-status">
              {dot && <i className={`sd-dot d-${dot}${dot === "run" ? " is-rendering" : ""}`} aria-hidden />}
              <b>{statusWord(status)}</b>
              {status?.why ? <span className="sd-why"> · {status.why}</span> : null}
            </p>
          </Section>
          <Section title="参考图">
            {refs == null ? (
              <p className="sd-muted">读取中…</p>
            ) : refs.length ? (
              <ul className="sd-grid4">
                {refs.map((x) => (
                  <li key={x.url}>
                    <img src={thumb(x.url, 240) ?? x.url} alt="" loading="lazy" data-zoom-label={`${shot} · ${x.label}`} />
                    <small title={x.label}>{x.label}</small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="sd-muted">这一镜没有登记参考图</p>
            )}
          </Section>
          <Section title="出图历史">
            {hist == null ? (
              <p className="sd-muted">读取中…</p>
            ) : hist.length ? (
              <ul className="sd-hist">
                {hist.map((x) => (
                  <li key={`${x.stage}${x.n}`}>
                    <img src={thumb(x.url, 200) ?? x.url} alt="" loading="lazy" data-zoom-label={`${shot} · ${x.label}`} />
                    <small title={x.label}>{x.label}</small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="sd-muted">现行剧本下还没出过图</p>
            )}
          </Section>
          <Section title={`检查结果${curN != null ? `（首帧第 ${curN} 版）` : ""}`}>
            {checks == null ? (
              <p className="sd-muted">读取中…</p>
            ) : checks === "none" || (!checks.items.length && !checks.judge) ? (
              <p className="sd-muted">{curN == null ? "还没有可检查的版本" : "这一版没有检查记录"}</p>
            ) : (
              <table className="sd-table">
                <thead>
                  <tr>
                    <th>项目</th>
                    <th>结果</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.items.map((c) => (
                    <tr key={c.id} title={c.title}>
                      <td>{CHECK_NAME[c.id] ?? c.title}</td>
                      <td>
                        {RESULT[c.status ?? ""] ?? c.status ?? "—"}
                        {c.detail && c.status !== "pass" ? <span className="sd-why"> · {c.detail}</span> : null}
                      </td>
                    </tr>
                  ))}
                  {checks.judge && (
                    <tr title={checks.judge.reasons.join("\n")}>
                      <td>看图判定</td>
                      <td>
                        {RESULT[String(checks.judge.verdict ?? "").toLowerCase()] ?? checks.judge.verdict ?? "未出"}
                        {checks.judge.reasons[0] ? <span className="sd-why"> · {checks.judge.reasons[0]}</span> : null}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </Section>
        </div>
        <footer className="sd-foot">
          <button type="button" className="v3-btn primary" onClick={openCanvas} title="打开这一镜（画布每镜一行）；双击卡片也能直接进">
            在分镜打开
          </button>
          {/* NAVIA：同一镜在出图 / 视频页的同一个抽屉（深链接，后退回到总览） */}
          <a className="v3-btn" href={`#/frames?ep=${Number(/^ep(\d+)/.exec(shot)?.[1] ?? 0)}&shot=${shot}`} onClick={onClose} title="在“出图”页打开这一镜的首尾帧抽屉">
            出图
          </a>
          <a className="v3-btn" href={`#/videos?ep=${Number(/^ep(\d+)/.exec(shot)?.[1] ?? 0)}&shot=${shot}`} onClick={onClose} title="在“视频”页打开这一镜的视频抽屉">
            视频
          </a>
          <button type="button" className="v3-btn" disabled={busy || curN == null} onClick={regen} title={curN == null ? "还没出过首帧，等排队出图" : `基于首帧第 ${curN} 版换 seed 再出一张；新图过检查才设为当前，旧版保留`}>
            {busy ? "正在排…" : "重出"}
          </button>
          <Pop label={<>更多 ▾</>} btnClass="v3-btn" align="up-right" title="精修、多选">
            {(close) => (
              <div className="v3-tools sd-more">
                <button onClick={() => (close(), st.select(shot), st.setCanvasMode("edit"), openCanvas())}>
                  <span>精修这一镜</span>
                  <small>打开画布的精修视图（局部改图、换参考）</small>
                </button>
                <button onClick={() => (close(), st.select(shot, { ctrl: true }))}>
                  <span>加入多选</span>
                  <small>之后可在画布批量出图 / 审片</small>
                </button>
              </div>
            )}
          </Pop>
        </footer>
      </aside>
    </>
  );
}
