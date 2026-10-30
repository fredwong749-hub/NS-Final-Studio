import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { AUDIO_SOURCE_LABEL, EP_MUSIC_EXAMPLE, EP_MUSIC_HINT } from "../audio";
import { useStudio } from "../store";
import type { CharacterBrief, Episode, ShotSummary } from "../types";
import { laptopVideoEnabled, matchFilter } from "../util";
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

/** 本集配乐（E8）：默认取剧本 **配乐** 行的【BGM】英文提示。英文 → 本集各镜 H3 non_diegetic_music 的默认（镜头可覆盖）；中文 → 只给后期 */
const hasZh = (x: string) => /[一-鿿]/.test(x);
const musicRoute = (x: string) => (!x.trim() ? "none" : x.trim().toUpperCase() === "N/A" ? "na" : hasZh(x) ? "post" : "h3");
const ROUTE_LABEL: Record<string, [string, string, string]> = {
  h3: ["→ 进 H3", "chip-ok", "英文：作为本集各镜 H3 non_diegetic_music 的默认（镜头单独写了配乐的以镜头为准）"],
  post: ["→ 只给后期", "chip-warn", "含中文：不进 H3，只作后期混音提示；要进 H3 请写英文"],
  na: ["N/A · 不要配乐", "chip-dark", "N/A：本集各镜 H3 non_diegetic_music = N/A（镜头单独写了的以镜头为准）"],
  none: ["未设", "chip-warn", "还没有本集配乐：各镜 H3 non_diegetic_music 取镜头自己的或 N/A"],
};
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
        <span className="ep-music-k" title={EP_MUSIC_HINT}>🎵 本集配乐（H3 默认）</span>
        <span className={`chip ${src === "edit" ? "chip-accent" : src === "none" ? "chip-warn" : "chip-ok"}`}>
          {src === "script" ? "剧本【BGM】" : AUDIO_SOURCE_LABEL[src] ?? src}
        </span>
        {!!m?.text && (() => {
          const [l, c, why] = ROUTE_LABEL[musicRoute(m.text)];
          return (
            <span className={`chip ${c}`} title={why}>
              {l}
            </span>
          );
        })()}
        <span className={`ep-music-text${m?.text ? "" : " muted"}`} title={m?.raw ? `剧本配乐行原文：${m.raw}` : undefined}>
          {m?.text || "还没有：英文 1–3 句（乐器 / 速度 / 节奏 / 强弱）→ 本集各镜 H3 配乐默认"}
        </span>
        <button className="btn" onClick={() => setOpen((o) => !o)}>
          {open ? "收起" : "编辑"}
        </button>
      </div>
      {open && (
        <div className="ep-music-edit">
          <textarea rows={3} value={v} onChange={(e) => setV(e.target.value)} placeholder="Sparse piano notes at a slow tempo…" readOnly={!supported} />
          <div className="audio-hint">
            <span className={`chip ${ROUTE_LABEL[musicRoute(v)][1]}`}>{ROUTE_LABEL[musicRoute(v)][0]}</span> {ROUTE_LABEL[musicRoute(v)][2]}
            <br />
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
              保存本集配乐
            </button>
            <button
              className="btn"
              disabled={!supported || busy || src !== "edit"}
              onClick={() => void save(null)}
              title={m?.default ? `回到剧本：${m.default}` : "清除人工修改"}
            >
              恢复剧本默认
            </button>
            <span className="muted small">英文会改变本集各镜的 H3 视频提示词（镜头单独写了配乐的除外），不影响首尾帧；中文只给后期混音</span>
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
      {!!ep.explicit_hold_count && (
        <span className="chip chip-explicit" title={`本集 ${ep.explicit_hold_count} 镜露骨红标：项目方自行处理，画布不做自动动作`}>
          露骨红标 {ep.explicit_hold_count}
        </span>
      )}
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

/** T54-B / 调研 #2（小云雀“截取上一镜尾帧作下一镜首帧参考”）：同集、笔记本负责的镜头才给一键衔接 */
function canLink(left: ShotSummary, right: ShotSummary) {
  return left.owner !== "gpu3" && left.last_frame_source !== "gpu3" && left.id.split("-")[0] === right.id.split("-")[0];
}

/** 批量菜单项：名称 + 一行说明（禁用时说明写原因） */
function MenuItem({ label, sub, disabled, onClick }: { label: string; sub: string; disabled?: boolean; onClick: () => void }) {
  return (
    <button className="ep-menu-item" disabled={disabled} onClick={onClick}>
      <span>{label}</span>
      <small>{sub}</small>
    </button>
  );
}

/** T59：集头的小下拉（点外面关闭） */
function EpMenu({ label, disabled, disabledTitle, children }: { label: string; disabled?: boolean; disabledTitle?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    window.addEventListener("mousedown", off);
    return () => window.removeEventListener("mousedown", off);
  }, [open]);
  return (
    <div className="tb-menu" ref={ref}>
      <button className="btn quiet" disabled={disabled} title={disabled ? disabledTitle : undefined} onClick={() => setOpen((v) => !v)}>
        {label}
        <i className="tb-caret" />
      </button>
      {open && (
        <div className="tb-pop right" onClick={() => setOpen(false)}>
          {children}
        </div>
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
  const [infoOpen, setInfoOpen] = useState(false);
  const { sop, error: sopError } = useSopEpisode(episode?.number);
  if (!episode) return <div className="empty">请选择一集</div>;
  // T60：摘要先到、本集详情还在路上（通常 < 0.3 s）
  if (episode.light) return <div className="empty">加载第 {episode.number} 集…</div>;

  const passed = episode.shots.filter((s) => s.review.state === "passed").length;
  const rejected = episode.shots.filter((s) => s.review.state === "rejected").length;
  const ids = episode.shots.map((s) => s.id);
  const lastShot = episode.shots[episode.shots.length - 1];
  const crossNext = lastShot?.next_shot;
  const hasEpBoost = !!(episode.edit?.boost_first || episode.edit?.boost_last);
  const gpu3Ep = episode.readiness?.owner === "gpu3";
  // 批量出图菜单里每项要处理的镜头数（与 requestBatch 的 onlyMissing 判定一致）
  const missing = {
    image: episode.shots.filter((x) => !x.first_frame).length,
    last: episode.shots.filter((x) => x.first_frame && x.last_frame_take == null && x.last_supported).length,
    video: episode.shots.filter((x) => x.first_frame && !x.video).length,
  };
  const openSeam = (from: string, to: string) => {
    setSeam({ from, to });
    setDrawer({ open: true, tab: "seam" });
  };

  return (
    <div className="episode-view">
      {/* T59：集头只留 标题·梗概｜镜头索引｜批量出图▾｜串播｜本集信息▾；SOP / 就绪 / 加强 / 配乐收进「本集信息」 */}
      <header className="ep-head t59">
        <div className="eh-row">
          <div className="eh-title">
            <h2>
              <span className="eh-num">第 {episode.number} 集</span>
              <span className="eh-name" title={episode.title}>{episode.title}</span>
              {episode.high_intensity && <span className="eh-flag" title="高强度集">高强度</span>}
              {episode.tag && <span className="eh-flag">{episode.tag}</span>}
            </h2>
            <p className={`eh-syn${synOpen ? " open" : ""}`} onClick={() => setSynOpen((v) => !v)} title={synOpen ? "收起" : "展开梗概"}>
              {episode.synopsis}
            </p>
          </div>
          <span className="grow" />
          <div className="eh-index" role="tablist" aria-label="本集镜头">
            {episode.shots.map((s) => {
              const cls = s.review.state === "rejected" ? "bad" : !s.first_frame || (s.last_supported && !s.last_frame) ? "none" : s.video ? "ok" : "warn";
              return (
                <button key={s.id} role="tab" aria-selected={s.id === sel} className={s.id === sel ? "on" : ""} onClick={() => select(s.id)} title={`${s.id}：${s.video ? "有视频" : s.first_frame ? "有首帧" : "未出图"} · 审核 ${s.review.state}
← / → 切换镜头 · ↑ / ↓ 切换集`}>
                  <i className={`dot ${cls}`} />
                  {s.id.split("-")[1]}
                </button>
              );
            })}
          </div>
          <EpMenu label="批量出图">
            {/* 每项“名称 + 一行说明”：会处理几镜；禁用时说明直接写原因（不只在悬停里） */}
            <MenuItem
              label="整集出首帧"
              sub={gpu3Ep ? GPU3_EP : missing.image ? `补齐缺首帧的 ${missing.image} 镜` : "本集镜头都已有首帧"}
              disabled={gpu3Ep || !missing.image}
              onClick={() => requestBatch(ids, "image", true)}
            />
            <MenuItem
              label="整集出尾帧"
              sub={gpu3Ep ? GPU3_EP : missing.last ? `补齐缺尾帧的 ${missing.last} 镜（需先有首帧）` : "有首帧的镜头都已有尾帧"}
              disabled={gpu3Ep || !missing.last}
              onClick={() => requestBatch(ids, "last", true)}
            />
            <MenuItem
              label={laptopVideoEnabled() ? "整集出视频（本机·开发者）" : "整集出视频"}
              sub={missing.video ? `${laptopVideoEnabled() ? "本机出" : "发给 gpu3 出"}缺视频的 ${missing.video} 镜（需先有首帧）` : "有首帧的镜头都已有视频"}
              disabled={!missing.video}
              onClick={() => requestBatch(ids, "video", true)}
            />
            <i className="ep-menu-sep" />
            <MenuItem label="全选本集镜头" sub={`选中 ${episode.shots.length} 镜，之后在底部批量操作`} onClick={() => setMulti(new Set(ids))} />
          </EpMenu>
          <button className="eh-link" onClick={() => st.setReviewMode(true)} title="按顺序串播（审片模式，快捷键 R）">
            串播
          </button>
          <button className={`eh-link${infoOpen ? " on" : ""}`} onClick={() => setInfoOpen((v) => !v)} title="SOP 阶段、就绪、导演加强、配乐">
            本集信息{sop?.owner_actions?.length ? <b className="eh-count">{sop.owner_actions.length}</b> : null}
          </button>
        </div>
        <div className="eh-sub">
          <span className="eh-looks">
            <span className="eh-k" title="本集各角色用的造型；每镜用哪套见镜头行里的人物小图">本集造型</span>
            <EpisodeLooks ep={episode} />
          </span>
          <span className="grow" />
          {episode.readiness && (
            <span className={`status ${episode.readiness.ready === episode.readiness.total && episode.readiness.total > 0 ? "ok" : ""}`}>
              就绪 {episode.readiness.ready}/{episode.readiness.total}
            </span>
          )}
          <span className={`status ${rejected ? "bad" : passed === episode.shots.length ? "ok" : ""}`}>
            审核 {passed}/{episode.shots.length}
            {rejected > 0 && ` · 打回 ${rejected}`}
          </span>
          {hasEpBoost && <span className="status">本集加强已设</span>}
        </div>
        {infoOpen && (
          <div className="eh-info">
            <SopStageBar sop={sop} error={sopError} ownerOpen={ownerOpen} onOwner={() => setOwnerOpen((v) => !v)} />
            {ownerOpen && sop && <OwnerPanel actions={sop.owner_actions} />}
            <EpisodeReadinessBar ep={episode} />
            <div className="eh-info-row">
              <button className={`btn${hasEpBoost ? " on" : ""}`} onClick={() => setBoostOpen((v) => !v)} title="本集导演加强（作用于本集全部镜头）">
                本集导演加强{hasEpBoost ? "（已设）" : ""}
              </button>
            </div>
            {boostOpen && <EpisodeBoost ep={episode} />}
            <EpisodeMusic ep={episode} />
          </div>
        )}
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
                  <div className="seam3-wrap">
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
                  {seam.state === "none" && canLink(s, next) && details[s.id] && (
                    <button
                      className="seam-link"
                      onClick={() => void st.saveEdit(s.id, { ...details[s.id].edit, last_source: "next", last_frame: "next" })}
                      title={`把 ${s.id} 的目标尾帧设为 ${next.id} 的首帧：${s.id} 的视频会收在下一镜开头的画面上（可撤销 Ctrl+Z；需重出 ${s.id} 视频才生效）`}
                    >
                      ⛓ 衔接：尾帧 = 下一镜首帧
                    </button>
                  )}
                  </div>
                )}
              </Fragment>
            );
          })}
        </div>
      )}
      <div className="legend muted">
        点图片全屏查看（←/→ 翻版本、A/B 对比、设为当前）· 改提示词在右侧检查器「保存并重出」→ 新版本出现在图下版本条（标“新”）和对比位，点它 = A/B · Ctrl/Shift 点击多选 · T 列表 · \ 收起检查器 · ? 全部快捷键
      </div>
    </div>
  );
}
