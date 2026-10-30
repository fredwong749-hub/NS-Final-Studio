import { Fragment, useEffect, useState } from "react";
import { AUDIO_SOURCE_LABEL, EP_MUSIC_EXAMPLE, EP_MUSIC_HINT } from "../audio";
import { useStudio } from "../store";
import type { CharacterBrief, Episode } from "../types";
import { matchFilter } from "../util";
import { seamCheck, seamState } from "./Seam";
import { SelectionBar } from "./SelectionBar";
import { OwnerPanel, SopStageBar, useSopEpisode } from "./SopBar";
import { ShotRow } from "./ShotRow";
import { ShotTable } from "./ShotTable";

/** 本集造型条：每个角色「脸图 + 造型字母 + 单品缩略」，点击高亮该角色在 6 张卡上的人物行 */
function EpisodeLooks({ ep }: { ep: Episode }) {
  const { hlChar, setHlChar, openAssets } = useStudio();
  const byChar = new Map<string, CharacterBrief>();
  for (const s of ep.shots) for (const c of s.characters) if (!byChar.has(c.character)) byChar.set(c.character, c);
  if (!byChar.size) return <span className="muted">本集无出场角色</span>;
  return (
    <div className="ep-looks-v2">
      {[...byChar.values()].map((c) => {
        const looks = [...new Set(ep.shots.flatMap((s) => s.characters.filter((x) => x.character === c.character).map((x) => x.look_label || x.look_name)))];
        const thumbs = c.slots.flatMap((s) => s.items.filter((i) => i.thumb_url).slice(0, 1));
        return (
          <button
            key={c.character}
            className={`ep-look${hlChar === c.character ? " on" : ""}`}
            onClick={() => setHlChar(hlChar === c.character ? null : c.character)}
            onDoubleClick={() => openAssets({ character: c.character, lookId: c.look_id })}
            title={`${c.label}\n点击：高亮该角色的人物行；双击：打开资产页`}
          >
            {c.face_url ? <img className="face-sm" src={c.face_url} alt="" /> : <span className="face-sm face-missing" />}
            <span>{c.name}</span>
            <b className="look-letter">{looks.join("/") || "—"}</b>
            {c.d_state && <span className="dstate">{c.d_state}</span>}
            {thumbs.slice(0, 4).map((t) => (
              <img key={t.id} className="item-sm" src={t.thumb_url!} alt="" title={t.name} />
            ))}
          </button>
        );
      })}
    </div>
  );
}

/** 本集背景音乐（后期混音）：默认取剧本 **配乐** 行的【BGM】英文提示 */
function EpisodeMusic({ ep }: { ep: Episode }) {
  const { saveEpisodeEdit } = useStudio();
  const m = ep.music;
  const supported = ep.audio_supported?.episode_music ?? false;
  const [open, setOpen] = useState(() => new URLSearchParams(location.search).get("epmusic") === "1");
  const [v, setV] = useState(m?.text ?? "");
  const [busy, setBusy] = useState(false);
  useEffect(() => setV(m?.text ?? ""), [ep.number, m?.text]);
  const src = m?.source ?? "none";
  const save = async (value: string | null) => {
    setBusy(true);
    if (await saveEpisodeEdit(ep.number, { music: value })) setOpen(false);
    setBusy(false);
  };
  return (
    <div className="ep-music">
      <div className="ep-music-line">
        <span className="ep-music-k">🎵 本集背景音乐（后期混音）</span>
        <span className={`chip ${src === "edit" ? "chip-accent" : src === "none" ? "chip-warn" : "chip-ok"}`}>
          {src === "script" ? "剧本【BGM】" : AUDIO_SOURCE_LABEL[src] ?? src}
        </span>
        <span className={`ep-music-text${m?.text ? "" : " muted"}`} title={m?.raw ? `剧本配乐行原文：${m.raw}` : undefined}>
          {m?.text || "还没有：写一句乐器 / 速度 / 节奏，后期配乐用"}
        </span>
        <button className="btn" onClick={() => setOpen((o) => !o)}>
          {open ? "收起" : "编辑"}
        </button>
      </div>
      {open && (
        <div className="ep-music-edit">
          <textarea rows={3} value={v} onChange={(e) => setV(e.target.value)} placeholder="Sparse piano notes at a slow tempo…" readOnly={!supported} />
          <div className="audio-hint">
            {EP_MUSIC_HINT}
            <br />
            例：<i>{EP_MUSIC_EXAMPLE}</i>
            {m?.raw && (
              <>
                <br />
                剧本配乐行原文：{m.raw}
              </>
            )}
          </div>
          {!supported && <div className="warn">后端字段 EpisodeEdit.music 还没上线：暂时只能查看，保存会被拒绝</div>}
          <div className="row-actions">
            <button className="btn primary" disabled={!supported || busy || v === (m?.text ?? "")} onClick={() => void save(v.trim() || null)}>
              保存本集背景音乐
            </button>
            <button
              className="btn"
              disabled={!supported || busy || src !== "edit"}
              onClick={() => void save(null)}
              title={m?.default ? `回到剧本：${m.default}` : "清除人工修改"}
            >
              恢复剧本默认
            </button>
            <span className="muted small">只用于后期混音，不影响画面、不进 H3 视频提示词，不会让版本过期</span>
          </div>
        </div>
      )}
    </div>
  );
}

/** 本集导演加强：项目方原文，作用于本集全部镜头 */
function EpisodeBoost({ ep }: { ep: Episode }) {
  const { saveEpisodeEdit } = useStudio();
  const [first, setFirst] = useState(ep.edit?.boost_first ?? "");
  const [last, setLast] = useState(ep.edit?.boost_last ?? "");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setFirst(ep.edit?.boost_first ?? "");
    setLast(ep.edit?.boost_last ?? "");
  }, [ep.number, ep.edit?.boost_first, ep.edit?.boost_last]);
  const dirty = first !== (ep.edit?.boost_first ?? "") || last !== (ep.edit?.boost_last ?? "");
  return (
    <div className="ep-boost">
      <label>
        <span>本集首帧加强</span>
        <textarea rows={2} value={first} onChange={(e) => setFirst(e.target.value)} />
      </label>
      <label>
        <span>本集尾帧加强</span>
        <textarea rows={2} value={last} onChange={(e) => setLast(e.target.value)} />
      </label>
      <div className="ep-boost-actions">
        <button
          className="btn primary"
          disabled={!dirty || busy}
          onClick={async () => {
            setBusy(true);
            await saveEpisodeEdit(ep.number, { boost_first: first || null, boost_last: last || null });
            setBusy(false);
          }}
        >
          保存本集加强
        </button>
        <span className="muted small">作用于本集 {ep.shots.length} 镜；保存后旧版本标「本集加强已改」，不会自动重渲</span>
      </div>
    </div>
  );
}

const SEAM_TEXT = { linked: "已衔接", stale: "下一镜首帧换过，视频过期", custom: "独立尾帧", none: "未衔接" } as const;

/** 本集就绪：就绪 N / M 镜 + 衔接表（data/renders_gpu3/epXX/continuity_sheet.jpg） */
function EpisodeReadinessBar({ ep }: { ep: Episode }) {
  const r = ep.readiness;
  if (!r) return null;
  const epTag = `ep${String(ep.number).padStart(2, "0")}`;
  const all = r.total > 0 && r.ready === r.total;
  return (
    <div className="ep-ready">
      <span className={`ep-ready-count ${all ? "r-ok" : "r-fail"}`} title="首帧·尾帧（同一 take 链）·img·motion·时长·sound/H3·配乐 cue·本集 BGM 全齐且衔接通过的镜头数（docs/audit/shot_readiness_and_continuity.md §2）">
        就绪 {r.ready} / {r.total} 镜
      </span>
      <span className={`chip ${r.owner === "gpu3" ? "chip-src-gpu3" : "chip-src-laptop"}`} title="首尾帧和视频由哪条流水线负责（config/shot_ownership.json）">
        {r.owner === "gpu3" ? "gpu3 负责全集（笔记本帧只作历史）" : "笔记本负责"}
      </span>
      {r.continuity_sheet ? (
        <a className="ep-sheet" href={r.continuity_sheet} target="_blank" rel="noreferrer" title={`衔接表 ${r.continuity_sheet_path}：相邻镜头「上一镜尾帧 / 下一镜首帧」拼图`}>
          <img src={r.continuity_sheet} alt="衔接表" />
          <span>衔接表</span>
        </a>
      ) : (
        <span className="muted small" title={`data/renders_gpu3/${epTag}/continuity_sheet.jpg（gpu3 合成前生成）`}>
          衔接表未生成
        </span>
      )}
    </div>
  );
}

const GPU3_EP = "gpu3 负责此集（避免两条链）：在每镜 ⋯ 菜单里「请 gpu3 重出」";

export function EpisodeView() {
  const st = useStudio();
  const { episode, details, latest, sel, multi, select, filter, setSeam, setDrawer, summaryById, requestBatch, setMulti, listMode, density, hlChar } = st;
  const [synOpen, setSynOpen] = useState(false);
  // 选中的镜头滚到可见（键盘 ←/→、深链 #ep01-S3、检查器跳转）
  useEffect(() => {
    if (!sel) return;
    const t = setTimeout(() => document.querySelector(`.srow[data-shot="${sel}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 60);
    return () => clearTimeout(t);
  }, [sel, episode?.number]);
  const [boostOpen, setBoostOpen] = useState(false);
  const [ownerOpen, setOwnerOpen] = useState(false);
  const { sop, error: sopError } = useSopEpisode(episode?.number);
  if (!episode) return <div className="empty">请选择一集</div>;

  const passed = episode.shots.filter((s) => s.review.state === "passed").length;
  const rejected = episode.shots.filter((s) => s.review.state === "rejected").length;
  const ids = episode.shots.map((s) => s.id);
  const lastShot = episode.shots[episode.shots.length - 1];
  const crossNext = lastShot?.next_shot;
  const hasEpBoost = !!(episode.edit?.boost_first || episode.edit?.boost_last);
  const gpu3Ep = episode.readiness?.owner === "gpu3";
  const openSeam = (from: string, to: string) => {
    setSeam({ from, to });
    setDrawer({ open: true, tab: "seam" });
  };

  return (
    <div className="episode-view">
      <header className="ep-head">
        <div className="ep-head-row">
          <h2>
            ep{String(episode.number).padStart(2, "0")} · {episode.title}
            {episode.high_intensity && <span className="hi-tag">🔴 高强度</span>}
            {episode.tag && <span className="tag">{episode.tag}</span>}
          </h2>
          <button className="btn-mini" onClick={() => setSynOpen((v) => !v)}>
            {synOpen ? "收起梗概" : "梗概"}
          </button>
          <span className={`review-count${passed === episode.shots.length ? " all" : ""}`}>
            审核 {passed}/{episode.shots.length}
            {rejected > 0 && <span className="bad"> · 打回 {rejected}</span>}
          </span>
          <span className="grow" />
          <button className="btn" disabled={gpu3Ep} onClick={() => requestBatch(ids, "image", true)} title={gpu3Ep ? GPU3_EP : "只跑缺首帧的镜头"}>
            整集出首帧
          </button>
          <button className="btn" disabled={gpu3Ep} onClick={() => requestBatch(ids, "last", true)} title={gpu3Ep ? GPU3_EP : "只跑缺尾帧的镜头（需先有首帧）"}>
            整集出尾帧
          </button>
          <button className="btn" disabled={gpu3Ep} onClick={() => requestBatch(ids, "video", true)} title={gpu3Ep ? GPU3_EP : "只跑缺视频的镜头"}>
            整集出视频
          </button>
          <button className="btn" onClick={() => st.setReviewMode(true)} title="按顺序串播（审片模式）">
            串播
          </button>
          <button className={`btn${hasEpBoost ? " on" : ""}`} onClick={() => setBoostOpen((v) => !v)} title="本集导演加强（作用于本集全部镜头）">
            本集导演加强{hasEpBoost ? " ●" : ""}
          </button>
          <button className="btn-mini" onClick={() => setMulti(new Set(ids))} title={`选中本集 ${episode.shots.length} 镜（之后可批量操作）`}>
            全选
          </button>
        </div>
        <SopStageBar sop={sop} error={sopError} ownerOpen={ownerOpen} onOwner={() => setOwnerOpen((v) => !v)} />
        {ownerOpen && sop && <OwnerPanel actions={sop.owner_actions} />}
        <EpisodeReadinessBar ep={episode} />
        {synOpen && <p className="synopsis">{episode.synopsis}</p>}
        {boostOpen && <EpisodeBoost ep={episode} />}
        <EpisodeMusic ep={episode} />
        <div className="ep-looks">
          <span className="muted">本集造型：</span>
          <EpisodeLooks ep={episode} />
          {hlChar && <span className="muted small">（已高亮，点再次取消）</span>}
        </div>
      </header>

      <SelectionBar />

      {listMode ? (
        <ShotTable ep={episode} />
      ) : (
        <div className="ep-rows">
          {episode.shots.map((s, i) => {
            const next = episode.shots[i + 1] ?? (crossNext ? summaryById.get(crossNext) : undefined);
            const seam = next ? seamState(s, next) : null;
            const check = next && next.id.split("-")[0] === s.id.split("-")[0] ? seamCheck(next) : undefined;
            return (
              <Fragment key={s.id}>
                <ShotRow
                  s={s}
                  detail={details[s.id]}
                  job={latest.get(s.id)}
                  selected={s.id === sel}
                  inMulti={multi.has(s.id)}
                  dim={!matchFilter(filter, s, latest.get(s.id))}
                  hlChar={hlChar}
                  compact={density === "compact"}
                  sop={sop?.shots.find((x) => x.id === s.id)}
                  onClick={(e) => select(s.id, { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey })}
                />
                {next && seam && (
                  <button className={`seam3 seam-${seam.state}`} onClick={() => openSeam(s.id, next.id)} title={`${seam.title}
点击打开接缝对比`}>
                    <i />
                    <span>
                      {s.id.split("-")[1]} 尾帧 → {next.id === crossNext ? next.id : next.id.split("-")[1]} 首帧 ·{" "}
                      {check ? (
                        <b className={`r-${check.level}`}>
                          衔接检查：{check.ok ? (check.level === "warn" ? `有提醒 — ${check.reason}` : "通过") : check.level === "warn" ? check.reason : `不通过 — ${check.reason}`}
                        </b>
                      ) : (
                        SEAM_TEXT[seam.state]
                      )}
                    </span>
                    <i />
                  </button>
                )}
              </Fragment>
            );
          })}
        </div>
      )}
      <div className="legend muted">
        点图片全屏查看（←/→ 翻版本、A/B 对比、设为当前）· 改提示词在右侧检查器，「重出」后新版本自动出现在对比位 · Ctrl/Shift 点击多选 · T 列表 · \ 收起检查器 · ? 全部快捷键
      </div>
    </div>
  );
}
