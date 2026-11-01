// fredw-92/W4a + v3.1 U1：左栏默认 56 px 头像条（审片 / 精修都收起，展开会记住）；展开为紧凑角色行 + 场景（无底图的合并一行）
import { thumb } from "../thumb";
import { useState } from "react";
import { useStudio } from "../store";
import type { Episode } from "../types";
import { sceneOf } from "./status";
import { useUi } from "./ui.helpers";

import { type CharAgg, aggChars, letterOf } from "./LeftRail.helpers";
const short = (id: string) => id.split("-")[1];
function ranges(ids: string[]): string {
  const ns = ids.map((x) => Number(short(x).slice(1))).sort((a, b) => a - b);
  const out: string[] = [];
  for (let i = 0; i < ns.length; ) {
    let j = i;
    while (j + 1 < ns.length && ns[j + 1] === ns[j] + 1) j++;
    out.push(i === j ? `S${ns[i]}` : `S${ns[i]}–S${ns[j]}`);
    i = j + 1;
  }
  return out.join("、");
}

/** 场景底图：visual_spec.scene.plate（字符串路径 / {url}）；没有返回 null */
function plateOf(d: { visual_spec?: Record<string, unknown> | null } | undefined): { url: string | null } | null {
  const v = d?.visual_spec?.scene as unknown;
  if (!v || typeof v !== "object") return null;
  const p = (v as Record<string, unknown>).plate as unknown;
  if (!p) return null;
  if (typeof p === "string") return { url: /^(\/|https?:)/.test(p) ? p : null };
  if (typeof p === "object") {
    const u = (p as Record<string, unknown>).url;
    return { url: typeof u === "string" ? u : null };
  }
  return null;
}

export function LeftRail({ ep }: { ep: Episode }) {
  const st = useStudio();
  const ui = useUi();
  const { sel, details, hlChar, setHlChar, openAssets, canvasMode, summaryById } = st;
  const cur = sel ? summaryById.get(sel) : undefined;
  const chars = aggChars(ep);
  const inShot = new Set(cur?.characters.map((c) => c.character) ?? []);
  // 场景：按详情里的 visual_spec.scene 归组（剧本没写地点的镜头不列）；有底图的占卡位，无底图的合并成一行（v3.1 §1.2）
  const scenes = new Map<string, { ids: string[]; plate: { url: string | null } | null }>();
  for (const s of ep.shots) {
    const sc = sceneOf(details[s.id]);
    if (!sc) continue;
    const e = scenes.get(sc) ?? { ids: [], plate: null };
    e.ids.push(s.id);
    e.plate = e.plate ?? plateOf(details[s.id]);
    scenes.set(sc, e);
  }
  const withPlate = [...scenes.entries()].filter(([, e]) => e.plate);
  const noPlate = [...scenes.entries()].filter(([, e]) => !e.plate);
  const curScene = cur ? sceneOf(details[cur.id]) : null;
  const [lib, setLibS] = useState<Lib>(readLib);
  const setLib = (p: Partial<Lib>) =>
    setLibS((o) => {
      const n = { ...o, ...p };
      try {
        sessionStorage.setItem("ns.v3.lib", JSON.stringify({ tab: n.tab, scope: n.scope }));
      } catch {
        /* 隐私模式 */
      }
      return n;
    });
  const clickChar = (id: string) => {
    if (canvasMode === "edit" && cur && inShot.has(id)) ui.openRefSwitch(cur.id, { kind: "character", id });
    else setHlChar(hlChar === id ? null : id);
  };
  const clickScene = (name: string, ids: string[]) =>
    canvasMode === "edit" && cur && curScene === name ? ui.openRefSwitch(cur.id, { kind: "scene" }) : st.select(ids[0]);
  const title = (a: CharAgg) =>
    `${a.c.name} · 形象 ${a.letters.length ? a.letters.join(" / ") : letterOf(a.c)}${a.c.d_state ? ` · ${a.c.d_state}` : ""}
出现 ${a.shots.length} 镜：${ranges(a.shots)}
${canvasMode === "edit" ? "点击：切换本镜参考" : "点击：高亮出场镜头"}；双击：打开资产页`;
  const letters = (a: CharAgg) => (a.letters.length > 1 ? a.letters.map((l) => l.slice(0, 1)).join("/") : letterOf(a.c));
  const noPlateTitle = `无底图的场景（${noPlate.length} 个）：
${noPlate.map(([n, e]) => `${n}：${ranges(e.ids)}`).join("\n")}`;

  if (ui.railMini)
    return (
      <aside className="v3-rail mini">
        <button className="v3-icon" onClick={() => ui.setRailCollapsed(false)} title="展开左栏（会记住）">
          »
        </button>
        {chars.map((a) => (
          <button
            key={a.c.character}
            className={`v3-ava${inShot.has(a.c.character) ? " here" : ""}${hlChar === a.c.character ? " hl" : ""}`}
            onClick={() => clickChar(a.c.character)}
            onDoubleClick={() => openAssets({ character: a.c.character, lookId: a.c.look_id })}
            title={title(a)}
          >
            <span className="v3-ava-img">
              {a.c.face_url ? <img src={thumb(a.c.face_url, 120) ?? a.c.face_url} alt="" data-zoom-label={`${a.c.name} · 造型${letters(a)} · 身份脸`} /> : <span>{a.c.name.slice(0, 1)}</span>}
              <b>{letters(a)}</b>
            </span>
            <small>{a.c.name}</small>
          </button>
        ))}
        {scenes.size > 0 && <i className="v3-rail-sep" />}
        {withPlate.map(([name, e]) => (
          <button key={name} className={`v3-scene-mini${curScene === name ? " here" : ""}`} title={`${name}：${ranges(e.ids)}`} onClick={() => clickScene(name, e.ids)}>
            {e.plate?.url ? <img src={thumb(e.plate.url, 240) ?? e.plate.url} alt="" data-zoom-label={`场景 · ${name} · 底图`} /> : null}
            <span>{ranges(e.ids).split("、")[0]}</span>
          </button>
        ))}
        {noPlate.length > 0 && (
          <button className="v3-scene-mini none" title={noPlateTitle} onClick={() => ui.setRailCollapsed(false)}>
            <span>场景 {noPlate.length}</span>
            <span>无底图</span>
          </button>
        )}
      </aside>
    );

  // UX4（小云雀 #7）：展开态 = 常驻“资产库”——角色 / 场景两个标签（带数量）+ 搜索 + 本集 / 全剧；
  // 卡片：角色是头像 + 名字 + 形象 · 出现镜数（全剧：共 N 个形象），场景是 16:9 底图卡 + 用到的镜头。
  // 点卡：精修里是“换这一镜的参考”（本镜在用的卡标“本镜”），审片里是高亮出场镜头；双击开资产页。
  const q = lib.q.trim();
  const hit = (t: string) => !q || t.toLowerCase().includes(q.toLowerCase());
  const epChars = chars.filter((a) => hit(a.c.name) || a.letters.some(hit));
  const allChars = (st.catalog?.characters ?? [])
    .map((c) => ({ c, looks: (st.catalog?.looks ?? []).filter((l) => l.character === c.id), here: chars.find((a) => a.c.character === c.id) }))
    .filter((x) => hit(x.c.name));
  const sceneRows = [...scenes.entries()].filter(([n]) => hit(n));
  const nChar = lib.scope === "all" ? allChars.length : epChars.length;
  return (
    <aside className="v3-rail v3-lib">
      <div className="v3-rail-h">
        <b className="v3-lib-title">资产库</b>
        <button className="v3-icon sm" onClick={() => ui.setRailCollapsed(true)} title="收成头像条，给列表让宽度（会记住）">
          «
        </button>
      </div>
      <div className="v3-lib-tabs" role="tablist">
        <button role="tab" className={lib.tab === "char" ? "on" : ""} onClick={() => setLib({ tab: "char" })}>
          角色 <i>{nChar}</i>
        </button>
        <button role="tab" className={lib.tab === "scene" ? "on" : ""} onClick={() => setLib({ tab: "scene" })}>
          场景 <i>{sceneRows.length}</i>
        </button>
      </div>
      <div className="v3-lib-tools">
        <input className="v3-lib-search" type="search" placeholder={lib.tab === "char" ? "搜角色 / 形象" : "搜场景"} value={lib.q} onChange={(e) => setLib({ q: e.target.value })} />
        {lib.tab === "char" && (
          <div className="v3-lib-scope" role="group" aria-label="范围">
            <button className={lib.scope === "ep" ? "on" : ""} onClick={() => setLib({ scope: "ep" })} title="只列本集出场的角色">
              本集
            </button>
            <button className={lib.scope === "all" ? "on" : ""} onClick={() => setLib({ scope: "all" })} title="全剧角色（资产库里登记的全部）">
              全剧
            </button>
          </div>
        )}
      </div>
      {canvasMode === "edit" && cur && <p className="v3-lib-hint">点标“本镜”的卡 = 换 {short(cur.id)} 的参考</p>}
      <div className="v3-rail-scroll">
        {lib.tab === "char" && lib.scope === "ep" && (
          <>
            {chars.length === 0 && <Empty icon="人" text="本集还没有出场角色" sub="剧本导入后，人物表里的角色会出现在这里" />}
            {chars.length > 0 && epChars.length === 0 && <Empty icon="⌕" text={`没有匹配“${q}”的角色`} />}
            {epChars.map((a) => {
              const here = inShot.has(a.c.character);
              return (
                <button
                  key={a.c.character}
                  className={`v3-char${here ? " here" : cur ? " away" : ""}${hlChar === a.c.character ? " hl" : ""}`}
                  onClick={() => clickChar(a.c.character)}
                  onDoubleClick={() => openAssets({ character: a.c.character, lookId: a.c.look_id })}
                  title={title(a)}
                >
                  <span className="v3-char-img">{a.c.face_url ? <img src={thumb(a.c.face_url, 120) ?? a.c.face_url} alt="" loading="lazy" data-zoom-label={`${a.c.name} · 造型${letterOf(a.c)} · 身份脸`} /> : <span>{a.c.name.slice(0, 1)}</span>}</span>
                  <span className="v3-char-txt">
                    <b>{a.c.name}</b>
                    <small>
                      {a.c.look_name}
                      {a.c.d_state ? ` · ${a.c.d_state}` : ""} · {a.shots.length} 镜
                    </small>
                  </span>
                  {here && canvasMode === "edit" ? <i className="v3-lib-here">本镜</i> : <i className="v3-letter">{letters(a)}</i>}
                </button>
              );
            })}
          </>
        )}
        {lib.tab === "char" && lib.scope === "all" && (
          <>
            {!st.catalog && <Empty icon="…" text="正在读资产库…" />}
            {st.catalog && allChars.length === 0 && <Empty icon="⌕" text={q ? `没有匹配“${q}”的角色` : "资产库里还没有角色"} sub={q ? undefined : "在“资产（角色·场景）”页新建"} />}
            {allChars.map(({ c, looks, here }) => (
              <button
                key={c.id}
                className={`v3-char${here ? "" : " off"}`}
                onClick={() => openAssets({ character: c.id, lookId: c.default_look_id ?? undefined })}
                title={`${c.name} · 共 ${looks.length} 个形象${here ? ` · 本集出场 ${here.shots.length} 镜` : " · 本集没出场"}\n点击：在资产页打开`}
              >
                <span className="v3-char-img">{here?.c.face_url ? <img src={thumb(here.c.face_url, 120) ?? here.c.face_url} alt="" loading="lazy" data-zoom-label={`${here.c.name} · 造型${letterOf(here.c)} · 身份脸`} /> : <span>{c.name.slice(0, 1)}</span>}</span>
                <span className="v3-char-txt">
                  <b>{c.name}</b>
                  <small>
                    共 {looks.length} 个形象{here ? ` · 本集 ${here.shots.length} 镜` : " · 本集没出场"}
                  </small>
                </span>
                <i className="v3-lib-go">↗</i>
              </button>
            ))}
          </>
        )}
        {lib.tab === "scene" && (
          <>
            {scenes.size === 0 && <Empty icon="景" text="本集剧本没有写地点" sub="分镜里写了场景行后会自动归组到这里" />}
            {scenes.size > 0 && sceneRows.length === 0 && <Empty icon="⌕" text={`没有匹配“${q}”的场景`} />}
            <div className="v3-scenes">
              {sceneRows.map(([name, e]) => (
                <button
                  key={name}
                  className={`v3-scene${curScene === name ? " here" : ""}${e.plate ? "" : " noplate"}`}
                  onClick={() => clickScene(name, e.ids)}
                  title={`${name}\n${ranges(e.ids)} · ${e.ids.length} 镜${e.plate ? "" : " · 还没有定稿底图"}`}
                >
                  <span className="v3-scene-thumb">
                    {e.plate?.url ? <img src={thumb(e.plate.url, 240) ?? e.plate.url} alt="" loading="lazy" data-zoom-label={`场景 · ${name} · 底图`} /> : <span className="v3-scene-ph">无底图</span>}
                    {curScene === name && canvasMode === "edit" && <i className="v3-lib-here">本镜</i>}
                  </span>
                  <b>{name}</b>
                  <small>
                    {ranges(e.ids)} · {e.ids.length} 镜
                  </small>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}

/** UX4（小云雀 #10）：空状态 = 一个圆角图标 + 一句“现在是什么情况 / 下一步做什么” */
export function Empty({ icon, text, sub }: { icon: string; text: string; sub?: string }) {
  return (
    <div className="v3-empty">
      <i aria-hidden="true">{icon}</i>
      <b>{text}</b>
      {sub && <small>{sub}</small>}
    </div>
  );
}

type Lib = { tab: "char" | "scene"; scope: "ep" | "all"; q: string };
function readLib(): Lib {
  try {
    const v = JSON.parse(sessionStorage.getItem("ns.v3.lib") || "{}");
    return { tab: v.tab === "scene" ? "scene" : "char", scope: v.scope === "all" ? "all" : "ep", q: "" };
  } catch {
    return { tab: "char", scope: "ep", q: "" };
  }
}
