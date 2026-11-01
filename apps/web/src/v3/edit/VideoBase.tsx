// fredw-92/PF：视频“基底”（项目方原话：Pika H3 Flex 下载体验一下，画面可以选择基底）。
// 选项来自 GET /api/video-bases（config/render_quality.json video_bases）；读不到时用内置两项。
// VideoBasePicker：“改参数重渲”里的一行（UX4：标题改“出片方式（视频基底）”，默认项说明改人话）；VideoBaseChip：版本链 / 参数里显示这一版用的基底（老版本无记录 = 官方）。

import { takeBaseId, useVideoBases, DEFAULT_VIDEO_BASE, PLAIN, configDefault } from "./VideoBase.helpers";

export function VideoBasePicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const list = useVideoBases();
  const cur = list.find((x) => x.id === value);
  return (
    <div className="v3e-fld wide">
      <span>
        出片方式
        <small>
          {PLAIN[value]?.what ?? cur?.hint ?? cur?.label ?? value}
          {value === configDefault ? "（默认）" : ""}。提示词和种子不变。
        </small>
      </span>
      <div className="v3e-seg sm">
        {list.map((b) => (
          <button key={b.id} className={value === b.id ? "on" : ""} onClick={() => onChange(b.id)} title={b.label ?? undefined}>
            {PLAIN[b.id]?.name ?? b.short ?? b.label ?? b.id}
            {b.id === configDefault ? "（默认）" : ""}
          </button>
        ))}
      </div>
    </div>
  );
}

export function VideoBaseChip({ p }: { p: { base?: string | null } | null | undefined }) {
  const list = useVideoBases();
  const id = takeBaseId(p);
  const b = list.find((x) => x.id === id);
  return (
    <span className={`v3e-chip${id !== DEFAULT_VIDEO_BASE ? " warn" : ""}`} title={b?.label ?? id}>
      {PLAIN[id]?.name ?? b?.short ?? b?.label ?? id}
    </span>
  );
}
