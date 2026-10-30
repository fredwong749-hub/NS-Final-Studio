// fredw-92/W4a + v3.1 U1：左栏默认 56 px 头像条（审片 / 精修都收起，展开会记住）；展开为紧凑角色行 + 场景（无底图的合并一行）
import { useStudio } from "../store";
import type { CharacterBrief, Episode } from "../types";
import { sceneOf } from "./status";
import { useUi } from "./ui";

export interface CharAgg {
  c: CharacterBrief;
  letters: string[];
  shots: string[];
}

export function aggChars(ep: Episode): CharAgg[] {
  const m = new Map<string, CharAgg>();
  for (const s of ep.shots)
    for (const c of s.characters) {
      const a = m.get(c.character) ?? { c, letters: [], shots: [] };
      const l = c.look_label || c.look_name;
      if (l && !a.letters.includes(l)) a.letters.push(l);
      a.shots.push(s.id);
      if (!a.c.face_url && c.face_url) a.c = c;
      m.set(c.character, a);
    }
  return [...m.values()];
}

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

/** 首字母徽标：A/B/C；“默认”显示 A */
export const letterOf = (c: CharacterBrief) => (c.look_label || "A").slice(0, 2);

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
              {a.c.face_url ? <img src={a.c.face_url} alt="" /> : <span>{a.c.name.slice(0, 1)}</span>}
              <b>{letters(a)}</b>
            </span>
            <small>{a.c.name}</small>
          </button>
        ))}
        {scenes.size > 0 && <i className="v3-rail-sep" />}
        {withPlate.map(([name, e]) => (
          <button key={name} className={`v3-scene-mini${curScene === name ? " here" : ""}`} title={`${name}：${ranges(e.ids)}`} onClick={() => clickScene(name, e.ids)}>
            {e.plate?.url ? <img src={e.plate.url} alt="" /> : null}
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

  return (
    <aside className="v3-rail">
      <div className="v3-rail-h">
        <span>本集角色</span>
        <button className="v3-icon sm" onClick={() => ui.setRailCollapsed(true)} title="收成头像条，给列表让宽度">
          «
        </button>
      </div>
      <div className="v3-rail-scroll">
        {chars.length === 0 && <p className="v3-muted small">本集没有出场角色</p>}
        {chars.map((a) => {
          const here = inShot.has(a.c.character);
          return (
            <button
              key={a.c.character}
              className={`v3-char${here ? " here" : cur ? " away" : ""}${hlChar === a.c.character ? " hl" : ""}`}
              onClick={() => clickChar(a.c.character)}
              onDoubleClick={() => openAssets({ character: a.c.character, lookId: a.c.look_id })}
              title={title(a)}
            >
              <span className="v3-char-img">{a.c.face_url ? <img src={a.c.face_url} alt="" loading="lazy" /> : <span>{a.c.name.slice(0, 1)}</span>}</span>
              <span className="v3-char-txt">
                <b>{a.c.name}</b>
                <small>
                  {a.c.look_name}
                  {a.c.d_state ? ` · ${a.c.d_state}` : ""} · {a.shots.length} 镜
                </small>
              </span>
              <i className="v3-letter">{letters(a)}</i>
            </button>
          );
        })}
        <div className="v3-rail-h sub">
          <span>本集场景</span>
          <span className="v3-muted">{scenes.size} 个</span>
        </div>
        {scenes.size === 0 && <p className="v3-muted small">剧本没有写地点</p>}
        {withPlate.length > 0 && (
          <div className="v3-scenes">
            {withPlate.map(([name, e]) => (
              <button key={name} className={`v3-scene${curScene === name ? " here" : ""}`} onClick={() => clickScene(name, e.ids)} title={`${name}
${ranges(e.ids)} · ${e.ids.length} 镜`}>
                {e.plate?.url ? <img src={e.plate.url} alt="" loading="lazy" /> : <span className="v3-scene-ph">底图</span>}
                <b>{name}</b>
                <small>
                  {ranges(e.ids)} · {e.ids.length} 镜
                </small>
              </button>
            ))}
          </div>
        )}
        {noPlate.length > 0 && (
          <details className="v3-noplate">
            <summary title={noPlateTitle}>场景 {noPlate.length} 个（无底图）</summary>
            {noPlate.map(([name, e]) => (
              <button key={name} className={curScene === name ? "here" : ""} onClick={() => clickScene(name, e.ids)} title={name}>
                <span>{name}</span>
                <small>{ranges(e.ids)}</small>
              </button>
            ))}
          </details>
        )}
      </div>
    </aside>
  );
}
