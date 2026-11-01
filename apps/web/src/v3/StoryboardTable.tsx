// fredw-92/U4：分镜表（一镜一行、一字段一列；表头与镜号列固定、横向滚动；单元格点开看全文；缺的标红；导出 CSV）
// + 集头的“本集配乐 / N 镜缺分镜字段 / 展开全部分镜详情 / 分镜表”。全部只读，原文逐字。
// fredw-92/UXF5（审查 #19 / #20 / #21）：镜号后加首帧 / 尾帧 / 视频缩略图（固定在左边）；点“缺 N 项”横向滚到缺的格子并闪一下；
//   旧稿没有场景 / 人物行时用画布识别到的场景、人物（灰字标“系统识别”）；视频提示词默认一列，可分四块；表头全是中文、不出现内部词。
//   剧本字段都是内容，表里不做行内编辑——点镜号回画布、点“精修”进这一镜改。
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useStudio } from "../store";
import type { Episode, ShotSummary } from "../types";
import { MissBadge } from "./StoryboardDetails";
import { H3_BLOCKS, SB_FIELDS, episodeMissing, plainText, sbText, sbUi, storyboardOf, useSbUi, type SbKey } from "./StoryboardDetails.helpers";
import { Pop } from "./widgets";
import { frameState, isSysText, sceneOf, scriptGaps } from "./status";
import { useSop } from "./sop.helpers";
import { ProduceHistoryChip } from "./ProduceHistory";

const short = (id: string) => id.split("-")[1];

/** 本集配乐：整行原文 + 【BGM】英文（后端 U4 带 music_raw / music_bgm；旧后端从 music 推） */
function episodeMusic(ep: Episode) {
  const x = ep as Episode & { music_raw?: string; music_bgm?: string };
  const raw = x.music_raw ?? ep.music?.raw ?? "";
  const bgm = x.music_bgm ?? (ep.music && ep.music.default !== raw ? ep.music.default : "");
  return { raw, bgm, edit: ep.music?.source === "edit" ? ep.music.text : "" };
}

/** 集头：本集配乐｜N 镜缺分镜字段（点击只看这些）｜展开全部分镜详情｜分镜表 */
export function SbEpisodeBar({ ep }: { ep: Episode }) {
  const { details } = useStudio();
  const ui = useSbUi();
  const { sop } = useSop();
  // UXF1 #4：与顶栏步骤①“N 镜待补”同一份判定（分镜字段缺的 ∪ SOP 停在剧本的阻塞项），不再一边“待补”一边“齐全”
  const gaps = useMemo(() => scriptGaps(ep, details, sop), [ep, details, sop]);
  const nMiss = gaps.size;
  // UM-P0-01：系统内部检查项（校验器、规则号、采纳记录……）不上屏，合成“系统检查中”
  const gapAll = [...new Set([...gaps.values()].flat())];
  const gapWhy = gapAll.filter((w) => !isSysText(w));
  const gapSys = gapAll.length - gapWhy.length;
  const m = episodeMusic(ep);
  return (
    <div className="sb-ephead">
      <Pop
        label={
          <>
            本集配乐{" "}
            {m.raw || m.bgm ? <span>{m.raw || m.bgm}</span> : <b style={{ color: "var(--c-bad-text)" }}>缺</b>}
          </>
        }
        btnClass={`sb-chip${m.raw || m.bgm ? "" : " bad"}`}
        title="本集配乐（剧本 **配乐** 行原文 + 【BGM】英文）"
      >
        {() => (
          <div className="sb-music">
            <b>配乐（剧本整行原文）</b>
            {m.raw ? <div className="sb-txt">{m.raw}</div> : <span className="sb-miss">缺</span>}
            <b>【BGM】英文（给音乐模型 / H3 默认配乐）</b>
            {m.bgm ? <div className="sb-txt mono">{m.bgm}</div> : <span className="sb-miss">缺</span>}
            {m.edit && (
              <>
                <b>人工改过（当前生效）</b>
                <div className="sb-txt mono">{m.edit}</div>
              </>
            )}
          </div>
        )}
      </Pop>
      <button
        className={`sb-chip${nMiss ? " bad" : " ok"}${ui.onlyMissing ? " on" : ""}`}
        disabled={!nMiss && !ui.onlyMissing}
        onClick={() => sbUi.setOnlyMissing(!ui.onlyMissing)}
        title={nMiss ? [...[...gaps.entries()].map(([id, w]) => `${short(id)}：${w.filter((x) => !isSysText(x)).join("、") || "系统检查中"}`), ui.onlyMissing ? "点击：显示全部镜头" : "点击：只看这些镜头"].join("\n") : "本集剧本与分镜字段齐全"}
      >
        {nMiss ? (gapWhy.length ? `${nMiss} 镜待补：${gapWhy.slice(0, 2).join("、")}${gapWhy.length > 2 ? " 等" : ""}` : `${nMiss} 镜系统检查中`) : "分镜字段齐全"}
        {nMiss && gapSys && gapWhy.length ? ` · 另有系统检查 ${gapSys} 项` : ""}
        {ui.onlyMissing ? " · 只看这些 ✕" : ""}
      </button>
      <ProduceHistoryChip ep={ep.number} />
      <button className={`sb-chip sb-opt${ui.expandAll ? " on" : ""}`} onClick={() => sbUi.setExpandAll(!ui.expandAll)} title="每一行都展开分镜详情（记住）">
        {ui.expandAll ? "收起全部分镜详情" : "展开全部分镜详情"}
      </button>
      <button className="sb-chip sb-opt" onClick={() => sbUi.setTable(true)} title="一镜一行、一字段一列；可导出 CSV">
        分镜表
      </button>
      {/* UXF1 #9：窄屏 / 有“待你决定”时，上面两个次要入口收进这里 */}
      <span className="sb-opt-more">
        <Pop label="⋯" btnClass="sb-chip" title="展开全部分镜详情 / 分镜表">
          {(close) => (
            <div className="sb-opt-list">
              <button className={`sb-chip${ui.expandAll ? " on" : ""}`} onClick={() => (sbUi.setExpandAll(!ui.expandAll), close())}>
                {ui.expandAll ? "收起全部分镜详情" : "展开全部分镜详情"}
              </button>
              <button className="sb-chip" onClick={() => (sbUi.setTable(true), close())}>
                分镜表
              </button>
            </div>
          )}
        </Pop>
      </span>
    </div>
  );
}

type Col = {
  key: string;
  label: string;
  w: number;
  mono?: boolean;
  text: (s: ShotSummary) => string;
  /** 剧本没写、画面里识别到的（旧稿的场景 / 人物）：灰字显示，不算填了 */
  derived?: (s: ShotSummary) => string;
  miss: (s: ShotSummary, m: Set<SbKey>) => boolean;
  none?: string;
};

/** UX4（审查 R10）：场景列和审片行的场景小卡用同一套识别顺序（ReviewRow.useShotScene）：
 *  场景库名 → data/scenes.json 里 scene_id 的名字 → 剧本地点 → scene_id。场景名表整页只读一次。 */
let sceneNamesP: Promise<Map<string, string>> | null = null;
function loadSceneNames(): Promise<Map<string, string>> {
  if (!sceneNamesP)
    sceneNamesP = fetch("/api/projects")
      .then((r) => (r.ok ? r.json() : []))
      .then((ps: { slug: string; is_default?: boolean }[]) => {
        const slug = (ps.find((p) => p.is_default) ?? ps[0])?.slug;
        return slug ? fetch(`/api/projects/${encodeURIComponent(slug)}/file/data/scenes.json`).then((r) => (r.ok ? r.json() : null)) : null;
      })
      .then((d: { scenes?: { scene_id: string; place?: string; name?: string }[] } | null) => new Map((d?.scenes ?? []).map((x) => [x.scene_id, x.name || x.place || x.scene_id] as [string, string])))
      .catch(() => new Map<string, string>());
  return sceneNamesP;
}
function useSceneNameOf(details: ReturnType<typeof useStudio>["details"]) {
  const { sop } = useSop();
  const [names, setNames] = useState<Map<string, string> | null>(null);
  useEffect(() => {
    let alive = true;
    void loadSceneNames().then((m) => alive && setNames(m));
    return () => {
      alive = false;
    };
  }, []);
  return useMemo(() => {
    const ids = new Map((sop?.shots ?? []).map((x) => [x.id, (x as { scene_id?: string | null }).scene_id ?? null] as [string, string | null]));
    return (s: ShotSummary): string => {
      const vs = (details[s.id]?.visual_spec?.scene ?? null) as Record<string, unknown> | string | null;
      const x = s as { scene_name?: string | null; scene?: { name?: string } | null };
      const id = ids.get(s.id) ?? (vs && typeof vs === "object" && typeof vs.id === "string" ? vs.id : null);
      const place = vs && typeof vs === "object" && typeof vs.place === "string" ? vs.place : typeof vs === "string" ? vs : null;
      return x.scene_name || x.scene?.name || (id ? names?.get(id) : null) || place || sceneOf(details[s.id]) || id || "";
    };
  }, [details, sop, names]);
}

/** 视频提示词：默认一整列；分四块时 = 开头对齐 / 画面 / 环境声 / 配乐 */
function useColumns(details: ReturnType<typeof useStudio>["details"], split: boolean): Col[] {
  const sceneName = useSceneNameOf(details);
  return useMemo(() => {
    const W: Partial<Record<SbKey, number>> = { scene: 140, cast: 130, link: 120, img: 320, motion: 300, end: 180, expr: 150, dialogue: 180, vo: 140, sound_h3: 200, sound: 180, intimate: 90, music_cue: 160, duration: 112 };
    const NONE: Partial<Record<SbKey, string>> = { dialogue: "本镜无对白", vo: "无", intimate: "无", expr: "—", sound: "—" };
    const sbOf = (s: ShotSummary) => storyboardOf(s, details[s.id]);
    const DERIVED: Partial<Record<SbKey, (s: ShotSummary) => string>> = {
      scene: sceneName,
      cast: (s) => s.characters.map((c) => c.name).join("、"),
    };
    const cols: Col[] = SB_FIELDS.filter((f) => f.key !== "h3").map((f) => ({
      key: f.key,
      label: f.label,
      w: W[f.key] ?? 160,
      text: (s) => {
        const sb = sbOf(s);
        return sb ? sbText(s, sb, f.key) : "";
      },
      derived: DERIVED[f.key],
      miss: (_s, m) => m.has(f.key),
      none: NONE[f.key],
    }));
    if (!split)
      cols.push({
        key: "h3",
        label: "视频提示词",
        w: 340,
        mono: true,
        text: (s) => (sbOf(s) ? s.h3_prompt || s.video_prompt || "" : ""),
        miss: (_s, m) => m.has("h3"),
      });
    else
      for (const [b, label] of H3_BLOCKS)
        cols.push({
          key: `h3.${b}`,
          label: `视频提示词 · ${label}`,
          w: b === "body" ? 320 : 220,
          mono: true,
          text: (s) => (sbOf(s) ? s.h3_blocks?.[b] ?? "" : ""),
          miss: (s, m) => m.has("h3") || !s.h3_blocks?.[b],
        });
    return cols;
  }, [details, split, sceneName]);
}

const csvCell = (v: string) => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

/** 分镜表浮层（Canvas 挂载；开关在 sbUi） */
export function StoryboardTable({ ep }: { ep: Episode }) {
  const st = useStudio();
  const ui = useSbUi();
  const [split, setSplit] = useState(false);
  const cols = useColumns(st.details, split);
  const miss = useMemo(() => episodeMissing(ep, st.details), [ep, st.details]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const scroller = useRef<HTMLDivElement>(null);
  const [flash, setFlash] = useState<{ id: string; n: number } | null>(null);
  /** 审查 #20：跳到这一镜第一个缺的格子（扣掉左边固定的镜号 + 缩略图列），整行缺的格子闪一下 */
  const jump = (id: string) => {
    const box = scroller.current;
    const tr = box?.querySelector<HTMLTableRowElement>(`tr[data-shot="${CSS.escape(id)}"]`);
    if (!box || !tr) return;
    const first = tr.querySelector<HTMLTableCellElement>("td.miss");
    const stickyW = [...tr.querySelectorAll<HTMLTableCellElement>("td.sbt-sticky")].reduce((n, td) => n + td.offsetWidth, 0);
    const top = tr.offsetTop - (box.querySelector("thead")?.offsetHeight ?? 0) - 8;
    box.scrollTo({ left: first ? Math.max(0, first.offsetLeft - stickyW - 24) : box.scrollLeft, top: Math.max(0, top), behavior: "smooth" });
    setFlash({ id, n: Date.now() });
  };
  useLayoutEffect(() => {
    if (ui.table && ui.focus) jump(ui.focus);
  }, [ui.table, ui.focusRev]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!flash) return;
    const t = window.setTimeout(() => setFlash(null), 2400);
    return () => window.clearTimeout(t);
  }, [flash]);
  useEffect(() => {
    if (!ui.table) return;
    const h = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopImmediatePropagation();
      sbUi.setTable(false);
    };
    window.addEventListener("keydown", h, true);
    return () => window.removeEventListener("keydown", h, true);
  }, [ui.table]);
  if (!ui.table) return null;
  const shots = ui.onlyMissing ? ep.shots.filter((s) => miss.get(s.id)?.length) : ep.shots;
  const nMiss = [...miss.values()].filter((m) => m.length).length;
  const toggle = (k: string) =>
    setOpen((o) => {
      const n = new Set(o);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const exportCsv = () => {
    const head = ["镜号", "缺项", ...cols.map((c) => c.label)];
    const rows = ep.shots.map((s) => {
      const m = new Set((miss.get(s.id) ?? []).map((f) => f.key));
      return [short(s.id), (miss.get(s.id) ?? []).map((f) => f.label).join("、"), ...cols.map((c) => (c.miss(s, m) ? `【缺】${c.text(s)}` : c.text(s) || (c.derived?.(s) ? `（系统识别）${c.derived(s)}` : "")))];
    });
    const csv = "﻿" + [head, ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `ep${String(ep.number).padStart(2, "0")}_分镜表.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return createPortal(
    <div className="sbt" role="dialog" aria-label={`第 ${ep.number} 集分镜表`}>
      <header className="sbt-head">
        <h2>
          第 {ep.number} 集 · {ep.title} · 分镜表
        </h2>
        <small>
          {ep.shots.length} 镜 · 剧本原文，只读 · 点单元格看全文 · 点镜号回到画布 · 点“缺 N 项”跳到缺的格子
        </small>
        <span className="v3-grow" />
        <label className="sbt-split" title="视频提示词分成 开头对齐 / 画面 / 环境声 / 配乐 四列">
          <input type="checkbox" checked={split} onChange={(e) => setSplit(e.target.checked)} /> 视频提示词分四列
        </label>
        <button className={`sb-chip${nMiss ? " bad" : " ok"}${ui.onlyMissing ? " on" : ""}`} disabled={!nMiss && !ui.onlyMissing} onClick={() => sbUi.setOnlyMissing(!ui.onlyMissing)}>
          {nMiss ? `${nMiss} 镜缺分镜字段` : "分镜字段齐全"}
          {ui.onlyMissing ? " · 只看这些 ✕" : ""}
        </button>
        <button className="v3-btn" onClick={exportCsv} title="导出本集全部镜头（UTF-8，Excel 可直接打开）">
          导出 CSV
        </button>
        <button className="v3-btn" onClick={() => sbUi.setTable(false)}>
          关闭 Esc
        </button>
      </header>
      <div className="sbt-scroll" ref={scroller}>
        {shots.length ? (
          <table style={{ width: ID_W + THUMB_W + cols.reduce((n, c) => n + c.w, 0) }}>
            <colgroup>
              <col style={{ width: ID_W }} />
              <col style={{ width: THUMB_W }} />
              {cols.map((c) => (
                <col key={c.key} style={{ width: c.w }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th className="sbt-id sbt-sticky">镜号</th>
                <th className="sbt-thumbs sbt-sticky">首帧 · 尾帧 · 视频</th>
                {cols.map((c) => (
                  <th key={c.key}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shots.map((s) => {
                const ms = miss.get(s.id) ?? [];
                const m = new Set(ms.map((f) => f.key));
                const loaded = !!storyboardOf(s, st.details[s.id]);
                return (
                  <tr key={s.id} data-shot={s.id} className={`${s.id === st.sel ? "sel" : ""}${flash?.id === s.id ? " flash" : ""}`}>
                    <td className="sbt-id sbt-sticky">
                      <button className="sbt-idbtn" onClick={() => (st.select(s.id), sbUi.setTable(false))} title="回到画布并选中这一镜">
                        {short(s.id)}
                      </button>
                      <MissBadge miss={ms} onJump={() => jump(s.id)} />
                      <button className="sbt-edit" onClick={() => (st.select(s.id), st.setCanvasMode("edit"), sbUi.setTable(false))} title="进精修改这一镜">
                        精修 →
                      </button>
                    </td>
                    <td className="sbt-thumbs sbt-sticky">
                      <Thumbs s={s} />
                    </td>
                    {cols.map((c) => {
                      const t = c.text(s);
                      const k = `${s.id}|${c.key}`;
                      const isMiss = loaded && c.miss(s, m);
                      const empty = !t.trim();
                      if (!loaded)
                        return (
                          <td key={c.key} className="none">
                            <div className="sbt-cell">读取中…</div>
                          </td>
                        );
                      if (empty) {
                        const dv = c.derived?.(s);
                        return (
                          <td key={c.key} className={isMiss ? "miss" : "none"}>
                            {isMiss && <div className="sbt-cell">缺</div>}
                            {dv ? (
                              <div className="sbt-cell sbt-derived" title="剧本里没有这一行；这是画布从画面 / 镜头数据里识别到的，仅供参考">
                                {dv}
                                <small>系统识别</small>
                              </div>
                            ) : (
                              !isMiss && <div className="sbt-cell">{c.none ?? "—"}</div>
                            )}
                          </td>
                        );
                      }
                      return (
                        <td key={c.key} className={isMiss ? "miss" : ""}>
                          {isMiss && <div className="sbt-cell">缺{c.key === "duration" ? "（系统默认）" : ""}</div>}
                          {!(isMiss && c.key === "duration") && (
                            <div className={`sbt-cell${open.has(k) ? " open" : ""}${c.mono ? " mono" : ""}`} onClick={() => toggle(k)} title={open.has(k) ? "收起" : "点开看全文"} style={isMiss ? { fontWeight: "normal", color: "var(--c-text-2)", cursor: "zoom-in" } : undefined}>
                              {plainText(t)}
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className="sbt-empty">本集没有缺分镜字段的镜头</div>
        )}
      </div>
    </div>,
    document.body,
  );
}

const ID_W = 84;
const THUMB_W = 188;

/** 审查 #19：首帧 / 尾帧 / 视频缩略图；点图 = 回画布全屏看首尾帧，点视频 = 进精修看视频 */
function Thumbs({ s }: { s: ShotSummary }) {
  const st = useStudio();
  const d = st.details[s.id];
  const go = (stage: "image" | "last") => {
    st.select(s.id);
    sbUi.setTable(false);
    st.openViewer(s.id, stage, "pair");
  };
  const cell = (stage: "image" | "last" | "video", url: string | null | undefined, label: string) => {
    const fs = frameState(s, d, stage);
    const tag = fs === "stale" ? "过期" : fs === "orphan" ? "作废" : fs === "bad" ? "坏图" : fs === "locked" ? "定稿" : "";
    if (!url)
      return (
        <span className="sbt-th none" title={`还没有${label}`}>
          {label}
        </span>
      );
    const onClick = stage === "video" ? () => (st.select(s.id), st.setCanvasMode("edit"), sbUi.setTable(false)) : () => go(stage);
    return (
      <button className={`sbt-th ${fs}`} onClick={onClick} title={`${label}${tag ? `（${tag}）` : ""}：${stage === "video" ? "进精修看视频" : "点开全屏看首尾帧"}`}>
        <img src={url} alt={label} loading="lazy" draggable={false} />
        {stage === "video" && <i className="sbt-play" />}
        {tag && <b>{tag}</b>}
      </button>
    );
  };
  return (
    <div className="sbt-throw">
      {cell("image", s.first_frame, "首帧")}
      {cell("last", s.last_frame_target, "尾帧")}
      {cell("video", s.video ? s.first_frame ?? null : null, "视频")}
    </div>
  );
}
