// 回退补回（归档 EpisodeView 的 EpisodeBoost / EpisodeMusic / EpisodeReadinessBar + EpisodeList 露骨红标 + “全选本集”）：
// 画布集头“本集设置 ▾”——本集导演加强（首帧 / 尾帧，作用于本集全部镜头）、本集配乐（英文 → 各镜视频提示词配乐默认）、
// 衔接表（相邻镜头尾帧 / 首帧拼图）、露骨红标数、全选本集镜头。
import { useEffect, useState } from "react";
import { useStudio } from "../store";
import type { Episode } from "../types";
import { Pop } from "./widgets";
import "./episode_settings.css";

export function EpisodeSettings({ ep }: { ep: Episode }) {
  const st = useStudio();
  const [first, setFirst] = useState(ep.edit?.boost_first ?? "");
  const [last, setLast] = useState(ep.edit?.boost_last ?? "");
  const [music, setMusic] = useState(ep.music?.text ?? "");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setFirst(ep.edit?.boost_first ?? "");
    setLast(ep.edit?.boost_last ?? "");
    setMusic(ep.music?.text ?? "");
  }, [ep.number, ep.edit?.boost_first, ep.edit?.boost_last, ep.music?.text]);
  const boostDirty = first !== (ep.edit?.boost_first ?? "") || last !== (ep.edit?.boost_last ?? "");
  const musicSrc = ep.music?.source ?? "none";
  const canMusic = ep.audio_supported?.episode_music ?? true;
  const r = ep.readiness;
  const hold = ep.explicit_hold_count ?? 0;
  const run = async (f: () => Promise<boolean>) => {
    setBusy(true);
    await f();
    setBusy(false);
  };
  return (
    <>
      {hold > 0 && (
        <span className="es-hold" title={`本集 ${hold} 镜露骨红标：项目方自行处理，系统不做自动动作`}>
          露骨红标 {hold}
        </span>
      )}
      <button className="v3-btn sm" onClick={() => st.setMulti(new Set(ep.shots.map((s) => s.id)))} title="选中本集全部镜头（之后用片段条批量出图 / 出视频 / 审片）">
        全选本集
      </button>
      <Pop label="本集设置 ▾" btnClass="v3-btn sm" align="right" title="本集导演加强、本集配乐、衔接表">
        {() => (
          <div className="es-box" onClick={(e) => e.stopPropagation()}>
            <section>
              <h4>本集导演加强</h4>
              <p className="es-hint">作用于本集全部 {ep.shots.length} 镜；保存后旧版本标“本集加强已改”，不会自动重出</p>
              <label>
                <span>首帧加强</span>
                <textarea rows={2} value={first} onChange={(e) => setFirst(e.target.value)} />
              </label>
              <label>
                <span>尾帧加强</span>
                <textarea rows={2} value={last} onChange={(e) => setLast(e.target.value)} />
              </label>
              <button className="v3-btn sm primary" disabled={!boostDirty || busy} title={busy ? "正在保存" : !boostDirty ? "还没改：在上面两个框里写了才能保存" : "保存本集加强"} onClick={() => void run(() => st.saveEpisodeEdit(ep.number, { boost_first: first || null, boost_last: last || null }))}>
                保存本集加强
              </button>
            </section>
            <section>
              <h4>
                本集配乐<small>{musicSrc === "edit" ? "改过" : musicSrc === "script" ? "剧本原文" : musicSrc === "none" ? "还没有" : musicSrc}</small>
              </h4>
              <p className="es-hint">英文 1–3 句（乐器 / 速度 / 节奏 / 强弱）= 本集各镜视频提示词里配乐的默认（镜头单独写了的除外）；中文只给后期混音</p>
              <textarea rows={3} value={music} onChange={(e) => setMusic(e.target.value)} readOnly={!canMusic} placeholder="Sparse piano notes at a slow tempo…" />
              {ep.music?.raw && <p className="es-hint">剧本配乐行原文：{ep.music.raw}</p>}
              <div className="es-btns">
                <button className="v3-btn sm primary" disabled={!canMusic || busy || music === (ep.music?.text ?? "")} title={!canMusic ? "后台还不支持改本集配乐" : busy ? "正在保存" : music === (ep.music?.text ?? "") ? "还没改：改了上面的配乐描述才能保存" : "保存本集配乐"} onClick={() => void run(() => st.saveEpisodeEdit(ep.number, { music: music.trim() || null }))}>
                  保存本集配乐
                </button>
                <button className="v3-btn sm" disabled={!canMusic || busy || musicSrc !== "edit"} onClick={() => void run(() => st.saveEpisodeEdit(ep.number, { music: null }))} title={!canMusic ? "后台还不支持改本集配乐" : musicSrc !== "edit" ? "现在用的就是剧本默认，没有人工修改可恢复" : ep.music?.default ? `回到剧本：${ep.music.default}` : "清除人工修改"}>
                  恢复剧本默认
                </button>
                <a className="v3-btn sm" href={`#/sound?tab=bgm&ep=${ep.number}`}>
                  听本集配乐
                </a>
              </div>
            </section>
            <section>
              <h4>衔接表{r ? <small>就绪 {r.ready}/{r.total} 镜</small> : null}</h4>
              {r?.continuity_sheet ? (
                <a className="es-sheet" href={r.continuity_sheet} target="_blank" rel="noreferrer" title="相邻镜头“上一镜尾帧 / 下一镜首帧”拼图">
                  <img src={r.continuity_sheet} alt="衔接表" />
                </a>
              ) : (
                <p className="es-hint">衔接表还没生成（整集合成前生成：相邻镜头尾帧 / 首帧拼图）。单个接缝可以点画布两行之间的“衔接”标记看。</p>
              )}
            </section>
          </div>
        )}
      </Pop>
    </>
  );
}
