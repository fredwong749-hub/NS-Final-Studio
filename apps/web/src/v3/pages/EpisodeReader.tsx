// UIRSI r21：剧本页的“创作者视角”——主角是这一集的剧情和画面，不是写作流水线。
// 读这一集的剧本分镜（P4 原文，只排版不改字）+ 故事线里的本集一句话 + 出图线的首帧草图：
// 每一镜一张卡：左边竖屏首帧（点开大图，←/→ 翻镜），右边 镜号 · 景别 · 时长 · 人物 · 画面 · 台词。
import { useEffect, useMemo, useState } from "react";
import { Skel } from "../../ds";
import { thumb } from "../../thumb";
import { EditButton } from "../../ds/editdel";
import { storyFrame, useStoryImages } from "../storyImages";
import { candidateFor, useCandidates } from "../candidates";
import { useStudio } from "../../store";
import { storyApi } from "./story_api";

import { type Parsed, parseP4, readable } from "./EpisodeReader.helpers";
const SIZE = /(大特写|特写|近景|中近景|中景|中全景|全景|远景|大远景)/;
const sizeOf = (img: string) => SIZE.exec(img)?.[1] ?? "";
// DATAALIGN：只去掉站位细节，“画外 / 局部”照原文保留（以前整段括号删掉，画外的人也显示成在场）
const castOf = (f: Record<string, string>) =>
  (f["人物"] ?? "").replace(/[（(]([^）)]*)[）)]/g, (_m, inner: string) => {
    const head = inner.split(/[｜|]/)[0].trim();
    return head && head !== "在画" ? `（${head}）` : "";
  }).trim();
const dialogOf = (f: Record<string, string>) => f["对白"] ?? "";
const secOf = (f: Record<string, string>) => /(\d+(?:\.\d+)?)\s*秒?/.exec(f["时长"] ?? "")?.[1] ?? "";

/** live：这一集就是画布里的正式剧本 → 首帧图与画布同一张（当前首帧 > 候选 > 还没进版本的草图），不再各取各的 */
export function EpisodeReader({ runId, ep, series, live = false }: { runId: string; ep: number; series: boolean; live?: boolean }) {
  const [p4, setP4] = useState<Parsed | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [line, setLine] = useState<{ title?: string; owner_line?: string; logline?: string } | null>(null);
  const [scenes, setScenes] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<number | null>(null);
  const im = useStoryImages(0, runId);
  const studio = useStudio();
  const cands = useCandidates(ep);
  const canvasEp = live ? studio.episodes?.find((e) => e.number === ep) : undefined;
  useEffect(() => {
    let alive = true;
    setP4(null);
    setErr(null);
    storyApi.artifact(runId, "P4", series ? ep : null).then(
      (a) => alive && setP4(parseP4(a.text)),
      (e) => alive && setErr((e as Error).message),
    );
    storyApi.artifact(runId, "P1").then(
      (a) => {
        const j = (a.json as { episodes?: { episode: number; title?: string; owner_line?: string; logline?: string }[]; scenes?: { scene_id: string; name: string }[] }) ?? {};
        if (!alive) return;
        setLine((j.episodes ?? []).find((x) => x.episode === ep) ?? null);
        setScenes(Object.fromEntries((j.scenes ?? []).map((x) => [x.scene_id, x.name])));
      },
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [runId, ep, series]);
  // DATAALIGN（K-DATA-001）：阅读页首帧 = 画布同一格的同一张（ReviewRow Frame 同口径）；以前取“出图目录里最新一张任意图”
  // （可能是校验用的 raw 图 / 尾帧），和画布当前首帧对不上
  const imgOf = useMemo(() => {
    const pre = `ep${String(ep).padStart(2, "0")}-S`;
    return (n: number): { url: string; thumb?: string; draft: boolean } | null => {
      const id = `${pre}${n}`;
      if (live) {
        const cur = canvasEp?.shots.find((x) => x.id === id)?.first_frame;
        if (cur) return { url: cur, draft: false };
        const c = candidateFor(cands, id, "image");
        if (c) return { url: c.url, draft: false };
        if (cands?.[id]?.image?.takes.length) return null;
      }
      const f = storyFrame(im, id, "image");
      return f ? { url: f.url, thumb: f.thumb, draft: true } : null;
    };
  }, [im, ep, live, canvasEp, cands]);
  // 大图：←/→ 翻镜，Esc 关
  useEffect(() => {
    if (open == null || !p4) return;
    const on = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(null);
      if (e.key === "ArrowRight") setOpen((i) => (i == null ? i : Math.min(p4.shots.length - 1, i + 1)));
      if (e.key === "ArrowLeft") setOpen((i) => (i == null ? i : Math.max(0, i - 1)));
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [open, p4]);

  if (err) return <p className="ds-muted">这一集的分镜还没写出来。</p>;
  if (!p4) return <Skel h={360} />;
  const cur = open != null ? p4.shots[open] : null;
  const curImg = cur ? imgOf(cur.n) : null;
  const total = p4.shots.reduce((a, s) => a + (Number(secOf(s.fields)) || 0), 0);
  return (
    <section className="er" aria-label={`第 ${ep} 集剧本与画面`}>
      <header className="er-h">
        <h2>
          第 {ep} 集《{p4.title || line?.title || ""}》
        </h2>
        <p className="er-plot">{p4.plot || line?.logline || line?.owner_line}</p>
        <div className="er-actions">
          <EditButton type="script" id={`run:${runId}/P4${series ? `@${ep}` : ""}`} size="sm" label="改这一集…" />
          <EditButton type="script" id={`run:${runId}/P3${series ? `@${ep}` : ""}`} size="sm" label="改剧本台词…" />
        </div>
        <p className="er-meta">
          {p4.shots.length} 镜{total ? ` · 约 ${Math.round(total)} 秒` : ""}
          {p4.cast ? ` · ${p4.cast}` : ""}
        </p>
      </header>
      <ol className="er-shots">
        {p4.shots.map((s, i) => {
          const pic = imgOf(s.n);
          const size = sizeOf(s.img);
          const dlg = dialogOf(s.fields);
          return (
            <li key={s.n} className="er-shot">
              <button className={`er-pic${pic ? "" : " none"}`} onClick={() => setOpen(i)} title={pic ? (pic.draft ? "草图·还没进版本（看大图 ←/→ 翻镜）" : "看大图（←/→ 翻镜）") : "首帧还没出"}>
                {pic ? <img src={pic.thumb ?? thumb(pic.url, 480) ?? pic.url} alt={`镜 ${s.n}`} loading="lazy" decoding="async" /> : <span>首帧还没出</span>}
                <b className="er-no">{s.n}</b>
              </button>
              <div className="er-body">
                <div className="er-line1">
                  <b>镜 {s.n}</b>
                  {size && <span className="er-chip">{size}</span>}
                  {secOf(s.fields) && <span className="er-chip">{secOf(s.fields)} 秒</span>}
                  {castOf(s.fields) && <span className="er-cast">{castOf(s.fields)}</span>}
                </div>
                <p className="er-img">{readable(s.img, scenes)}</p>
                {dlg && <p className="er-dlg">{dlg}</p>}
                {s.fields["镜头运动"] && <p className="er-cam">{s.fields["镜头运动"].replace(/[｜|]/g, " · ")}</p>}
                {/* 项目方 11-01：每镜全部字段（提示词、声音、时长……）不许藏没——阅读模式里也能逐镜展开看原文 */}
                {Object.keys(s.fields).length > 0 && (
                  <details className="er-fields">
                    <summary>全部字段（{Object.keys(s.fields).length}）</summary>
                    <dl>
                      {Object.entries(s.fields).map(([k, v]) => (
                        <div key={k}>
                          <dt>{k}</dt>
                          <dd>{v}</dd>
                        </div>
                      ))}
                    </dl>
                  </details>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {cur && (
        <div className="er-big" role="dialog" aria-label="大图" onClick={() => setOpen(null)}>
          <div className="er-big-in" onClick={(e) => e.stopPropagation()}>
            {curImg ? <img src={curImg.url} alt="" /> : <div className="er-big-none">首帧还没出</div>}
            <div className="er-big-side">
              <b>
                第 {ep} 集 · 镜 {cur.n} {sizeOf(cur.img)}
              </b>
              <p>{readable(cur.img, scenes)}</p>
              {dialogOf(cur.fields) && <p className="er-dlg">{dialogOf(cur.fields)}</p>}
              <div className="er-big-nav">
                <button className="ds-btn sm" disabled={open === 0} onClick={() => setOpen((i) => (i ?? 1) - 1)}>
                  ← 上一镜
                </button>
                <button className="ds-btn sm" disabled={open === p4.shots.length - 1} onClick={() => setOpen((i) => (i ?? 0) + 1)}>
                  下一镜 →
                </button>
                <button className="ds-btn sm ghost" onClick={() => setOpen(null)}>
                  关闭 Esc
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
