// fredw-92/W4b：本镜参考条（spec §6.2，精修模式首尾帧上方）；点卡片打开外壳的参考切换浮层（RefSwitchPanel.tsx）。
// 只能选资产库里已有的资产；改集默认需项目方本人勾选（by=owner）。不做成人 / 内容限制。
import { useEffect, useState } from "react";
import type { CharacterBrief, ShotSummary } from "../../types";
import { useUi } from "../ui";
import { apiV1, isNotReady, opt, type CharRefState, type ShotRefsV1 } from "../api_v1";

type Load = { data: ShotRefsV1 | null; notReady: boolean; error: string | null; reload: () => void };

// F2：应用参考后通知所有参考条 / 面板重读（原来参考条只在换镜时读一次，应用后仍显示旧形象、没有“本镜改过”角标）
const refsSubs = new Set<() => void>();
export const bumpShotRefs = () => refsSubs.forEach((f) => f());

export function useShotRefs(shot: string): Load {
  const [st, setSt] = useState<Omit<Load, "reload">>({ data: null, notReady: false, error: null });
  const [k, setK] = useState(0);
  useEffect(() => {
    const f = () => setK((x) => x + 1);
    refsSubs.add(f);
    return () => void refsSubs.delete(f);
  }, []);
  useEffect(() => {
    let dead = false;
    apiV1.shotRefs(shot).then(
      (data) => !dead && setSt({ data, notReady: false, error: null }),
      (e) => !dead && setSt({ data: null, notReady: isNotReady(e), error: isNotReady(e) ? null : (e as Error).message }),
    );
    return () => {
      dead = true;
    };
  }, [shot, k]);
  return { ...st, reload: () => setK((x) => x + 1) };
}

export const SRC_TAG: Record<string, string> = { shot: "本镜改过", scene: "本场改过" };
export const imgOf = (c: CharRefState) => {
  const im = c.effective?.images?.[0];
  return typeof im === "string" ? im : im?.url ?? null;
};
export const lookName = (c: CharRefState) => {
  const l = (c.options?.looks ?? []).map(opt).find((o) => o.id === c.effective?.look);
  const nm = c.effective?.look_name ?? l?.name;
  return nm || l?.letter ? `形象 ${l?.letter ?? ""} ${nm ?? ""}`.replace(/\s+/g, " ").trim() : c.effective?.look ?? "集默认";
};
export const sceneEff = (s: ShotRefsV1["scene"]) => {
  const e = s?.effective;
  if (!e) return { name: "无底图", url: null as string | null, id: null as string | null };
  if (typeof e === "string") return { name: e === "none" ? "不用底图" : e, url: null, id: e };
  const id = e.plate_id ?? e.plate ?? e.id ?? null;
  return { name: e.name ?? (id === "none" ? "不用底图" : id) ?? "无底图", url: e.url ?? null, id };
};

/** 没图的人物用名字首字做头像（v3.1 §2.6：不留大空块） */
const initial = (name?: string | null) => (name ?? "?").trim().slice(0, 1) || "?";

export function RefBar({ shot }: { shot: ShotSummary }) {
  const r = useShotRefs(shot.id);
  const ui = useUi();
  const open = (target: string) => ui.openRefSwitch(shot.id, target === "__scene" ? { kind: "scene" } : { kind: "character", id: target });
  const v1 = r.data;
  return (
    <div className="v3e-refbar">
      <span className="t">本镜参考</span>
      {v1
        ? v1.characters.map((c) => (
            <button key={c.id} className="v3e-refcard" onClick={() => open(c.id)} title="点开切换形象 / 单件 / 借用">
              {imgOf(c) ? <img src={imgOf(c)!} alt="" /> : <span className="th ini">{initial(c.name)}</span>}
              <span className="tx">
                <b>{c.name}</b>
                <small>{lookName(c)}</small>
              </span>
              {SRC_TAG[c.source] && <i className="tag">{SRC_TAG[c.source]}</i>}
            </button>
          ))
        : shot.characters.map((c: CharacterBrief) => (
            <button key={c.character} className="v3e-refcard" onClick={() => open(c.character)} title="点开切换（后端就绪后可用）">
              {c.face_url ? <img src={c.face_url} alt="" /> : <span className="th ini">{initial(c.name)}</span>}
              <span className="tx">
                <b>
                  {c.name} {c.look_label && <em className="lt">{c.look_label}</em>}
                </b>
                <small>{c.look_name || "集默认"}</small>
              </span>
              {c.has_override && <i className="tag">本镜改过</i>}
            </button>
          ))}
      <button className="v3e-refcard scene" onClick={() => open("__scene")}>
        {v1 && sceneEff(v1.scene).url ? <img src={sceneEff(v1.scene).url!} alt="" /> : <span className="th ini scene">景</span>}
        <span className="tx">
          <b>场景</b>
          <small>{v1 ? sceneEff(v1.scene).name : "底图"}</small>
        </span>
        {v1?.scene?.source && SRC_TAG[v1.scene.source] && <i className="tag">{SRC_TAG[v1.scene.source]}</i>}
      </button>
      {r.notReady && <span className="nr">切换：后端未就绪（W5 /refs）</span>}
      {r.error && <span className="nr err">{r.error}</span>}
    </div>
  );
}
