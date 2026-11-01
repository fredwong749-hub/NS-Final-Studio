import { useState } from "react";
import { api } from "../api";
import { useStudio } from "../store";
import type { Episode, ShotSummary } from "../types";
import { matchFilter, shotLine } from "../util";
import { mediaChain } from "./ShotCard.helpers";

type Col = "first" | "last" | "people" | "expr" | "size" | "angle" | "move" | "lens" | "line" | "img" | "vid" | "status";
const COLS: [Col, string][] = [
  ["first", "首帧"],
  ["last", "尾帧"],
  ["people", "人物"],
  ["expr", "表情"],
  ["size", "景别"],
  ["angle", "机位"],
  ["move", "运镜"],
  ["lens", "焦段"],
  ["line", "对白"],
  ["img", "首帧提示词"],
  ["vid", "H3 提示词"],
  ["status", "状态"],
];
type CamKey = "size" | "angle" | "move" | "lens";

function loadCols(): Set<Col> {
  try {
    const v = localStorage.getItem("ns.listCols");
    if (v) return new Set(JSON.parse(v) as Col[]);
  } catch {
    /* ignore */
  }
  return new Set(COLS.map(([c]) => c));
}

/** 单元格就地编辑：回车保存，Esc 取消 */
function EditCell({ value, auto, onSave }: { value: string; auto: boolean; onSave: (v: string) => Promise<unknown> }) {
  const [v, setV] = useState<string | null>(null);
  if (v !== null)
    return (
      <input
        autoFocus
        className="cell-input"
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={() => setV(null)}
        onKeyDown={async (e) => {
          if (e.key === "Enter") {
            await onSave(v);
            setV(null);
          } else if (e.key === "Escape") setV(null);
        }}
      />
    );
  return (
    <span className={`cell-edit${auto ? " auto" : ""}${value ? "" : " unlabeled"}`} onClick={() => setV(value)} title="点击编辑">
      {value || "未标注"}
    </span>
  );
}

export function ShotTable({ ep }: { ep: Episode }) {
  const st = useStudio();
  const [cols, setCols] = useState<Set<Col>>(loadCols);
  const toggle = (c: Col) =>
    setCols((cur) => {
      const n = new Set(cur);
      if (n.has(c)) n.delete(c);
      else n.add(c);
      localStorage.setItem("ns.listCols", JSON.stringify([...n]));
      return n;
    });

  async function saveField(s: ShotSummary, field: "expression" | CamKey, v: string) {
    // 封板修复：拉详情失败要提示
    const d = st.details[s.id] ?? (await api.shot(s.id).catch((e: Error) => void st.notify(`${s.id} 加载失败：${e.message}`, "err")));
    if (!d) return false;
    if (field === "expression") return st.saveEdit(s.id, { ...d.edit, expression: v.trim() || null });
    // 运镜四字段拼成「景别，机位，运镜，焦段」写进 camera（后端按同一规则拆回）
    const cam = { size: s.camera.size, angle: s.camera.angle, move: s.camera.move, lens: s.camera.lens, [field]: v.trim() };
    const text = [cam.size, cam.angle, cam.move, cam.lens].filter(Boolean).join("，");
    return st.saveEdit(s.id, { ...d.edit, camera: text || null });
  }

  const on = (c: Col) => cols.has(c);
  return (
    <div className="shot-table-wrap">
      <div className="col-toggles">
        列：
        {COLS.map(([c, l]) => (
          <label key={c}>
            <input type="checkbox" checked={on(c)} onChange={() => toggle(c)} /> {l}
          </label>
        ))}
      </div>
      <table className="shot-table">
        <thead>
          <tr>
            <th>镜头</th>
            {COLS.filter(([c]) => on(c)).map(([c, l]) => (
              <th key={c} className={`col-${c}`}>
                {l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ep.shots.map((s) => {
            const line = shotLine(s);
            const job = st.latest.get(s.id);
            return (
              <tr
                key={s.id}
                className={`${s.id === st.sel ? "selected" : ""}${st.multi.has(s.id) ? " multi" : ""}${matchFilter(st.filter, s, job) ? "" : " dim"}`}
                onClick={(e) => st.select(s.id, { shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey })}
              >
                <td>
                  <b>{s.id}</b>
                  {s.has_boost && <span className="badge b-boost">加强</span>}
                </td>
                {on("first") && <td>{s.first_frame ? <img className="tbl-thumb" src={s.first_frame} alt="" /> : <span className="muted">无</span>}</td>}
                {on("last") && <td>{s.last_frame_target ? <img className="tbl-thumb" src={s.last_frame_target} alt="" /> : <span className="muted">无</span>}</td>}
                {on("people") && (
                  <td>
                    {s.characters.map((c) => (
                      <div key={c.character} className="tbl-person">
                        {c.face_url ? <img className="face-sm" src={c.face_url} alt="" /> : <span className="face-sm face-missing" />}
                        {c.name} <b className="look-letter">{c.look_label || c.look_name}</b> {c.d_state}
                      </div>
                    ))}
                  </td>
                )}
                {on("expr") && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <EditCell value={s.expression.text} auto={s.expression.source === "auto"} onSave={(v) => saveField(s, "expression", v)} />
                  </td>
                )}
                {(["size", "angle", "move", "lens"] as CamKey[]).map(
                  (k) =>
                    on(k) && (
                      <td key={k} onClick={(e) => e.stopPropagation()}>
                        <EditCell value={s.camera[k]} auto={s.camera.sources[k] === "auto"} onSave={(v) => saveField(s, k, v)} />
                      </td>
                    ),
                )}
                {on("line") && <td className="tbl-text">{line.text || <span className="muted">—</span>}</td>}
                {on("img") && (
                  <td className="tbl-text" title={s.image_prompt}>
                    <span className="clamp3">{s.image_prompt}</span>
                  </td>
                )}
                {on("vid") && (
                  <td className="tbl-text" title={s.h3_prompt ?? s.video_prompt}>
                    {/* 对齐句每镜都一样，列表里显示 H3 正文（integrated_multimodal_description） */}
                    <span className="clamp3">{s.h3_blocks?.body?.replace(/^\[Shot 1\]\s*/, "") || s.video_prompt}</span>
                  </td>
                )}
                {on("status") && (
                  <td>
                    <div className="chain">
                      {mediaChain(s, st.details[s.id], job).map(([k, c, t]) => (
                        <span key={k} className={`chain-cell c-${c}`} title={`${k}：${t}`}>
                          {k}
                        </span>
                      ))}
                    </div>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
