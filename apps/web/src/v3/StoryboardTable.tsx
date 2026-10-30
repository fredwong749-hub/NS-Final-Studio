// fredw-92/U4：分镜表（一镜一行、一字段一列；表头与镜号列固定、横向滚动；单元格点开看全文；缺的标红；导出 CSV）
// + 集头的“本集配乐 / N 镜缺分镜字段 / 展开全部分镜详情 / 分镜表”。全部只读，原文逐字。
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useStudio } from "../store";
import type { Episode, ShotSummary } from "../types";
import { H3_BLOCKS, SB_FIELDS, episodeMissing, MissBadge, sbText, sbUi, storyboardOf, useSbUi, type SbKey } from "./StoryboardDetails";
import { Pop } from "./widgets";

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
  const miss = useMemo(() => episodeMissing(ep, details), [ep, details]);
  const nMiss = [...miss.values()].filter((m) => m.length).length;
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
        title={nMiss ? (ui.onlyMissing ? "点击：显示全部镜头" : "点击：只看缺分镜字段的镜头") : "本集分镜字段齐全"}
      >
        {nMiss ? `${nMiss} 镜缺分镜字段` : "分镜字段齐全"}
        {ui.onlyMissing ? " · 只看这些 ✕" : ""}
      </button>
      <button className={`sb-chip${ui.expandAll ? " on" : ""}`} onClick={() => sbUi.setExpandAll(!ui.expandAll)} title="每一行都展开分镜详情（记住）">
        {ui.expandAll ? "收起全部分镜详情" : "展开全部分镜详情"}
      </button>
      <button className="sb-chip" onClick={() => sbUi.setTable(true)} title="一镜一行、一字段一列；可导出 CSV">
        分镜表
      </button>
    </div>
  );
}

type Col = { key: string; label: string; w: number; mono?: boolean; text: (s: ShotSummary) => string; miss: (s: ShotSummary, m: Set<SbKey>) => boolean; none?: string };

function useColumns(details: ReturnType<typeof useStudio>["details"]): Col[] {
  return useMemo(() => {
    const W: Partial<Record<SbKey, number>> = { scene: 140, cast: 140, link: 120, img: 340, motion: 320, end: 200, expr: 160, dialogue: 180, vo: 160, sound_h3: 240, sound: 220, intimate: 90, music_cue: 170, duration: 100 };
    const NONE: Partial<Record<SbKey, string>> = { dialogue: "本镜无对白", vo: "无", intimate: "无", expr: "—", sound: "—" };
    const cols: Col[] = SB_FIELDS.filter((f) => f.key !== "h3").map((f) => ({
      key: f.key,
      label: f.label,
      w: W[f.key] ?? 160,
      mono: f.key === "sound_h3",
      text: (s) => {
        const sb = storyboardOf(s, details[s.id]);
        return sb ? sbText(s, sb, f.key) : "";
      },
      miss: (_s, m) => m.has(f.key),
      none: NONE[f.key],
    }));
    for (const [b, label] of H3_BLOCKS)
      cols.push({
        key: `h3.${b}`,
        label: `H3 · ${label}`,
        w: b === "body" ? 320 : 220,
        mono: true,
        text: (s) => {
          const sb = storyboardOf(s, details[s.id]);
          return sb?.h3_prompt ? s.h3_blocks?.[b] ?? "" : "";
        },
        miss: (s, m) => m.has("h3") || !s.h3_blocks?.[b],
      });
    return cols;
  }, [details]);
}

const csvCell = (v: string) => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

/** 分镜表浮层（Canvas 挂载；开关在 sbUi） */
export function StoryboardTable({ ep }: { ep: Episode }) {
  const st = useStudio();
  const ui = useSbUi();
  const cols = useColumns(st.details);
  const miss = useMemo(() => episodeMissing(ep, st.details), [ep, st.details]);
  const [open, setOpen] = useState<Set<string>>(new Set());
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
      return [short(s.id), (miss.get(s.id) ?? []).map((f) => f.label).join("、"), ...cols.map((c) => (c.miss(s, m) ? `【缺】${c.text(s)}` : c.text(s)))];
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
          {ep.shots.length} 镜 · 剧本原文，只读 · 点单元格看全文 · 点镜号回到画布
        </small>
        <span className="v3-grow" />
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
      <div className="sbt-scroll">
        {shots.length ? (
          <table style={{ width: 76 + cols.reduce((n, c) => n + c.w, 0) }}>
            <colgroup>
              <col style={{ width: 76 }} />
              {cols.map((c) => (
                <col key={c.key} style={{ width: c.w }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th className="sbt-id">镜号</th>
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
                  <tr key={s.id} className={s.id === st.sel ? "sel" : ""}>
                    <td className="sbt-id">
                      <button onClick={() => (st.select(s.id), sbUi.setTable(false))} title="回到画布并选中这一镜">
                        {short(s.id)}
                      </button>
                      <MissBadge miss={ms} />
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
                      if (empty)
                        return (
                          <td key={c.key} className={isMiss ? "miss" : "none"}>
                            <div className="sbt-cell">{isMiss ? "缺" : c.none ?? "—"}</div>
                          </td>
                        );
                      return (
                        <td key={c.key} className={isMiss ? "miss" : ""}>
                          {isMiss && <div className="sbt-cell">缺{c.key === "duration" ? "（系统默认）" : ""}</div>}
                          {!(isMiss && c.key === "duration") && (
                            <div className={`sbt-cell${open.has(k) ? " open" : ""}${c.mono ? " mono" : ""}`} onClick={() => toggle(k)} title={open.has(k) ? "收起" : "点开看全文"} style={isMiss ? { fontWeight: "normal", color: "var(--c-text-2)", cursor: "zoom-in" } : undefined}>
                              {t}
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
