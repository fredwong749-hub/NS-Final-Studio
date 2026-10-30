// fredw-92/U3：资产页「场景」页签（项目方新需求），接 GET /api/assets/scenes（S-back）。
// 场景卡：底图大图（没有 → “未生成底图” + “生成底图”）、名称、时段、出现集数 / 镜数、变体（主底图 / 机位…）、定稿状态；
// 点开用同一个 AssetDrawer（kind = scene，参考用途 空间 / 风格 / 色彩 / 道具）。接口未上线 → “后端未就绪”。
import { useEffect, useState } from "react";
import type { LightEpisode } from "../api_v1_pages";
import { loadScenes, plateUrl, sceneName, sceneNotReady, timeLabel, variantLabel, type SceneView } from "./scenes_api";

function status(s: SceneView): { t: string; k: "ok" | "warn" | "" } {
  const p = s.plate;
  if (!p) return { t: "", k: "" };
  if (p.s2_gate_ok || p.plate_status === "owner_confirmed") return { t: "项目方已确认", k: "ok" };
  if (p.locked) return { t: "已定稿", k: "ok" };
  if (p.url) return { t: "候选 · 未定稿", k: "warn" };
  return { t: "", k: "" };
}

export default function ScenesTab({ onOpen }: { eps?: LightEpisode[] | null; onOpen: (s: SceneView, label: string) => void }) {
  const [list, setList] = useState<SceneView[] | null>(null);
  const [err, setErr] = useState<{ t: string; notReady: boolean } | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    let alive = true;
    loadScenes()
      .then((r) => alive && setList(r))
      .catch((e) => alive && setErr({ t: String((e as Error)?.message ?? e), notReady: sceneNotReady(e) }));
    return () => {
      alive = false;
    };
  }, []);

  if (err)
    return err.notReady ? (
      <div className="v3p-notready">后端未就绪：GET /api/assets/scenes 还没生效（场景接口已写好，等 API 重启后显示）。</div>
    ) : (
      <p className="v3p-err">{err.t}</p>
    );
  if (!list) return <p className="v3p-muted">加载场景…</p>;
  const shown = list.filter((s) => !q || `${sceneName(s)} ${s.scene_id} ${s.description?.space ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  const nPlate = list.filter((s) => plateUrl(s)).length;
  const nLocked = list.filter((s) => s.plate?.locked || s.plate?.s2_gate_ok).length;

  return (
    <>
      <div className="v3p-scenebar">
        <b>{list.length} 个场景</b>
        <span className="v3p-muted">
          有底图 {nPlate} · 已定稿 {nLocked} · 未生成 {list.length - nPlate}
        </span>
        <span className="grow" />
        <input className="v3p-scenesearch" placeholder="按名字筛选" value={q} onChange={(e) => setQ(e.target.value)} aria-label="按名字筛选场景" />
      </div>
      {!shown.length && <p className="v3p-muted">{list.length ? "没有符合的场景。" : "还没有场景。"}</p>}
      <div className="v3p-scenes">
        {shown.map((s) => {
          const url = plateUrl(s);
          const name = sceneName(s);
          const st = status(s);
          const label = `场景 · ${name}`;
          const times = s.description?.times?.length ? s.description.times : s.description?.time_of_day ? [s.description.time_of_day] : [];
          const vars = (s.variants ?? []).filter((v) => v.variant !== "main");
          const eps = s.episodes ?? [];
          return (
            <div key={s.scene_id} className="v3p-scene">
              {url ? (
                <button className="v3p-scene-img" onClick={() => onOpen(s, label)} title={`${name} · 点开编辑`}>
                  <img src={url} alt="" loading="lazy" />
                  {st.t && <span className={`v3p-badge v3p-scene-st ${st.k}`}>{st.t}</span>}
                </button>
              ) : (
                <div className="v3p-scene-img none">
                  <span className="v3p-scene-none">未生成底图</span>
                  <button className="btn-mini v3p-scene-gen" onClick={() => onOpen(s, label)}>生成底图</button>
                </div>
              )}
              <div className="v3p-scene-meta">
                <b title={s.scene_id}>{name}</b>
                <span className="v3p-muted">
                  出现 {s.episode_count ?? eps.length} 集 · {s.shot_count ?? 0} 镜
                  {eps.length ? `（第 ${eps[0]}${eps.length > 1 ? `–${eps[eps.length - 1]}` : ""} 集）` : ""}
                </span>
                {(times.length > 0 || vars.length > 0) && (
                  <div className="v3p-scene-vars">
                    {times.map((t) => (
                      <span key={`t:${t}`} className="v3p-badge" title="时段">{timeLabel(t)}</span>
                    ))}
                    {vars.map((v) => (
                      <span key={v.variant} className={`v3p-badge${v.locked ? " ok" : ""}`} title={v.locked ? "已定稿" : "候选"}>
                        {variantLabel(v.variant)}
                        {v.locked ? " ✓" : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              {url && (
                <div className="v3p-look-act">
                  <button className="btn-mini" onClick={() => onOpen(s, label)}>编辑 / 定稿</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
