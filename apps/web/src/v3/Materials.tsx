// PREP（2026-10-31）：出片前资料闸门的行内标——GET /api/episodes/{ep}/readiness（ns_api/material_readiness.py）。
// 缺资料（人物表 / 族裔 / 造型行 / 场景行 + 定稿底图 / 身份参考 / 衔接 / 时长 / H3 …）= 红“资料不全 N”，整集出片不出这镜；
// 资料都在但对不上（H3 锚点句、说话人写法…）= 黄“对不上 N”，只提示。悬停看清单。只读，不改任何内容。
import { useEffect, useState } from "react";
import { load, type Item, type ShotMat } from "./Materials.helpers";
export type { EpMat, Item, ShotMat } from "./Materials.helpers";

const epOf = (shotId: string) => Number(/^ep(\d+)-/.exec(shotId)?.[1] ?? NaN);

export function MaterialsBadge({ shotId }: { shotId: string }) {
  const [m, setM] = useState<{ ep: Item[]; s: ShotMat } | null>(null);
  useEffect(() => {
    let alive = true;
    const ep = epOf(shotId);
    if (!Number.isFinite(ep)) return;
    void load(ep).then((d) => {
      const s = d?.shots.find((x) => x.id === shotId);
      if (alive && d && s) setM({ ep: d.episode_items, s });
    });
    return () => {
      alive = false;
    };
  }, [shotId]);
  if (!m) return null;
  const miss = [...m.ep, ...m.s.missing];
  const conf = m.s.conflicts;
  const line = (i: Item) => `· ${i.label}：${i.reason}（${i.who}）`;
  if (miss.length) {
    const title =
      `资料不全，整集出片不出这镜（项目方单镜手动出会带提醒）：\n${miss.map(line).join("\n")}` +
      (conf.length ? `\n\n对不上（只提示）：\n${conf.map(line).join("\n")}` : "");
    return (
      <span className="sb-badge" title={title}>
        资料不全 {miss.length}
      </span>
    );
  }
  if (!conf.length) return null;
  return (
    <span
      className="sb-badge"
      style={{ color: "var(--c-warn-text)", background: "color-mix(in srgb, var(--c-warn) 14%, transparent)", borderColor: "color-mix(in srgb, var(--c-warn) 55%, transparent)" }}
      title={`资料齐，但有对不上的地方（只提示，不拦）：\n${conf.map(line).join("\n")}`}
    >
      对不上 {conf.length}
    </span>
  );
}
