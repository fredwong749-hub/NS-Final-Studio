// fredw-92/UXF2（审查 #25 / #29）：“用卡”下拉——写卡名和它现在在做什么；
// “出图优先 / 视频优先”只是偏好说明；默认“自动”（后端按任务类型挑空闲的卡）。忙的、被 LoRA 训练锁着的卡排到后面并写明。
// fredw-92/UXF4（审查 N5 / N7）：卡名统一 cardName()（“gpu33·卡0”），技术细节悬停；“自动”写后端 pick_lane 的结果和理由。
import { autoLane, autoWhy, cardName, cardTip, laneState, useLanes, type LaneInfo, type LanePick } from "./lanes";
import { fmtSec } from "./state";

interface Props {
  value: LanePick;
  onChange: (v: LanePick) => void;
  /** 这次要跑的是出图还是出视频（决定“自动”会落到哪、哪条道算偏好） */
  kind: "image" | "video";
  /** 视频帧数：放不下的道不列 */
  frames?: number | null;
  className?: string;
  /** 下拉下面写一行“这张卡现在 …”（默认写） */
  hint?: boolean;
}

const busyRank = (l: LaneInfo) => (!l.reachable ? 3 : l.lock || !l.ok ? 2 : l.load_s ? 1 : 0);

export function LaneSelect({ value, onChange, kind, frames, className, hint = true }: Props) {
  const { lanes } = useLanes();
  const list = (lanes ?? []).filter((l) => !(kind === "video" && frames && l.max_frames && l.max_frames < frames));
  const sorted = [...list].sort((a, b) => busyRank(a) - busyRank(b) || Number(kind === "image" ? b.image_pref : a.image_pref) - Number(kind === "image" ? a.image_pref : b.image_pref));
  const auto = autoLane(kind, lanes, frames);
  const known = value === "auto" || list.some((l) => String(l.gpu) === String(value));
  const chosen = value === "auto" ? auto : list.find((l) => String(l.gpu) === String(value)) ?? null;
  const pref = (l: LaneInfo) => (l.image_pref ? "出图卡" : "视频优先");
  // UXF5（审查 N18）：下拉里只放短名（1280 宽也不截），“为什么选这张”写在下拉下面一行 / 悬停
  const autoWhyText = auto ? `自动会用 ${cardName(auto.gpu)}：${autoWhy(kind, auto, lanes)}` : null;
  const autoText = auto
    ? `自动（${cardName(auto.gpu)}）`
    : lanes && kind === "video" && frames
      ? `自动（没有能出 ${frames} 帧的卡）`
      : "自动（挑空闲的卡）";
  return (
    <span className={`v3e-lane ${className ?? ""}`} title={chosen ? cardTip(chosen.gpu) : undefined}>
      <select
        value={String(value)}
        aria-label="用哪张卡"
        title={value === "auto" ? autoWhyText ?? autoText : chosen ? cardTip(chosen.gpu) : undefined}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "auto" ? "auto" : /^\d+$/.test(v) ? Number(v) : v);
        }}
      >
        <option value="auto">{autoText}</option>
        {sorted.map((l) => (
          <option key={String(l.gpu)} value={String(l.gpu)} disabled={!l.reachable} title={cardTip(l.gpu)}>
            {cardName(l.gpu)} · {pref(l)} · {laneState(l)}
          </option>
        ))}
        {!known && <option value={String(value)}>{cardName(value)}（道表里没有）</option>}
      </select>
      {hint && value === "auto" && autoWhyText && !(chosen && (chosen.lock || chosen.load_s > 0 || !chosen.reachable)) && <small className="v3e-lanehint">{autoWhyText}</small>}
      {hint && chosen && (chosen.lock || chosen.load_s > 0 || !chosen.reachable) && (
        <small className={`v3e-lanehint ${chosen.lock || !chosen.reachable ? "warn" : ""}`}>
          {cardName(chosen.gpu)}：{laneState(chosen)}
          {chosen.load_s > 0 ? `，前面约 ${fmtSec(chosen.load_s)} 的活` : ""}
          {chosen.lock ? "，任务会排在训练后面，可能要等很久" : ""}
        </small>
      )}
    </span>
  );
}

