// fredw-92/VB：视频“改参数重渲”里的“附加视频 LoRA”一行。
// 选项来自 GET /api/video-loras（config/render_quality.json optional_video_loras）；不选 = 不加。
// VBVR 等非商用许可的 LoRA 显示小标签（如“仅研究·非商用”）。
import { useEffect, useState } from "react";
import { apiV1, type OptionalVideoLora } from "../api_v1";

export interface ExtraLoraPick {
  name: string;
  strength: number;
}

export function ExtraVideoLoras({ value, onChange }: { value: ExtraLoraPick | null; onChange: (v: ExtraLoraPick | null) => void }) {
  const [list, setList] = useState<OptionalVideoLora[] | null>(null);
  const [range, setRange] = useState<[number, number]>([0, 1.5]);
  const [err, setErr] = useState("");

  useEffect(() => {
    let dead = false;
    apiV1
      .videoLoras()
      .then((r) => {
        if (dead) return;
        setList(r.loras ?? []);
        if (r.strength_range) setRange(r.strength_range);
      })
      .catch((e: Error) => !dead && (setList([]), setErr(e.message)));
    return () => {
      dead = true;
    };
  }, []);

  const cur = list?.find((x) => x.name === value?.name) ?? null;
  const [lo, hi] = cur?.strength_range ?? range;

  return (
    <div className="v3e-fld wide">
      <span>
        附加视频 LoRA
        <small>{err ? `读不到清单：${err}` : "串在 Turbo LoRA 之后；不选 = 不加"}</small>
      </span>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <select
          value={value?.name ?? ""}
          onChange={(e) => {
            const o = list?.find((x) => x.name === e.target.value);
            onChange(o ? { name: o.name, strength: o.recommended_strength ?? 0.7 } : null);
          }}
        >
          <option value="">不加</option>
          {(list ?? []).map((o) => (
            <option key={o.id} value={o.name}>
              {o.label ?? o.name}
              {o.tag ? ` 〔${o.tag}〕` : ""}
            </option>
          ))}
        </select>
        {cur?.tag && (
          <small className="warn" title={[cur.license, cur.usage].filter(Boolean).join(" · ")}>
            {cur.tag}
          </small>
        )}
        {value && (
          <>
            <input
              type="range"
              min={lo}
              max={hi}
              step={0.05}
              value={value.strength}
              onChange={(e) => onChange({ ...value, strength: Number(e.target.value) })}
              style={{ flex: "1 1 160px", minWidth: 120 }}
            />
            <small>
              强度 {value.strength.toFixed(2)}
              {cur?.recommended_strength != null && `（建议 ${cur.recommended_strength}）`}
            </small>
          </>
        )}
      </div>
    </div>
  );
}
