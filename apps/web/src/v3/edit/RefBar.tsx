// fredw-92/W4b：本镜参考条（spec §6.2，精修模式首尾帧上方）；点卡片打开外壳的参考切换浮层（RefSwitchPanel.tsx）。
// 只能选资产库里已有的资产；改集默认需项目方本人勾选（by=owner）。不做成人 / 内容限制。
import { thumb } from "../../thumb";

import type { CharacterBrief, ShotSummary } from "../../types";
import { useUi } from "../ui.helpers";
import { type CharRefState } from "../api_v1";

import { useSceneLabel } from "../sceneLabel";
import { SRC_TAG, sceneEff, useRefLook, useShotRefs } from "./RefBar.helpers";

function CharRefCard({ c, onOpen }: { c: CharRefState; onOpen: () => void }) {
  const lk = useRefLook(c);
  return (
    <button className="v3e-refcard" onClick={onOpen} title={`${c.name} · ${lk.title}${lk.url && !lk.own ? "（这个形象还没有自己的图，显示角色主图）" : ""}
点开切换形象 / 单件 / 借用`}>
      {lk.url ? <img src={thumb(lk.url, 120) ?? lk.url} alt="" /> : <span className="th ini">{initial(c.name)}</span>}
      <span className="tx">
        <b>{c.name}</b>
        <small>{lk.title}</small>
      </span>
      {SRC_TAG[c.source] && <i className="tag">{SRC_TAG[c.source]}</i>}
    </button>
  );
}

/** 没图的人物用名字首字做头像（v3.1 §2.6：不留大空块） */
const initial = (name?: string | null) => (name ?? "?").trim().slice(0, 1) || "?";

export function RefBar({ shot }: { shot: ShotSummary }) {
  const r = useShotRefs(shot.id);
  const ui = useUi();
  const open = (target: string) => ui.openRefSwitch(shot.id, target === "__scene" ? { kind: "scene" } : { kind: "character", id: target });
  const v1 = r.data;
  const sc = v1 ? sceneEff(v1.scene) : null;
  const scName = useSceneLabel(sc?.name ?? null); // 名字表到了会重渲染
  return (
    <div className="v3e-refbar">
      <span className="t" title="出这一镜首帧 / 尾帧时会用到的参考图（点卡片可以换）">将使用的参考图</span>
      {v1
        ? v1.characters.map((c) => <CharRefCard key={c.id} c={c} onOpen={() => open(c.id)} />)
        : shot.characters.map((c: CharacterBrief) => (
            <button key={c.character} className="v3e-refcard" onClick={() => open(c.character)} title="点开切换（后端就绪后可用）">
              {c.face_url ? <img src={thumb(c.face_url, 120) ?? c.face_url} alt="" /> : <span className="th ini">{initial(c.name)}</span>}
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
        {v1 && sceneEff(v1.scene).url ? <img src={thumb(sceneEff(v1.scene).url!, 120) ?? sceneEff(v1.scene).url!} alt="" /> : <span className="th ini scene">景</span>}
        <span className="tx">
          <b>场景</b>
          <small title={sc?.name ?? undefined}>{sc ? scName : "底图"}</small>
        </span>
        {v1?.scene?.source && SRC_TAG[v1.scene.source] && <i className="tag">{SRC_TAG[v1.scene.source]}</i>}
      </button>
      {r.notReady && <span className="nr">切换：后端未就绪（W5 /refs）</span>}
      {r.error && <span className="nr err">{r.error}</span>}
    </div>
  );
}
