// UX5：统一资产卡（A §3.2）——所有类型共用：缩略图 + 类型 + 状态 | 名称 + 版本 | 所属 | 用在几集几镜 | 缺什么
import { thumb } from "../../thumb";
import { StatusTag } from "../../ds";
import { TYPE_NAME, type AssetCardData, type AssetType } from "./center";
import { usageText } from "./AssetCard.helpers";

const ICON: Record<AssetType, string> = {
  character: "人",
  look: "形",
  item: "衣",
  prop: "物",
  scene: "景",
  preset: "▦",
  vbase: "▶",
  vlora: "◇",
  lora: "◆",
  voice: "♪",
  template: "¶",
};
const RATIO: Partial<Record<AssetType, string>> = { character: "ac-r34", look: "ac-r34", scene: "ac-r169", item: "ac-r11", prop: "ac-r11" };

export function AssetCard({ c, on, showType, onOpen, onUsage }: { c: AssetCardData; on?: boolean; showType?: boolean; onOpen: () => void; onUsage?: () => void }) {
  const ratio = RATIO[c.type] ?? "ac-rnone";
  const use = usageText(c);
  return (
    <article className={`ac-card ${ratio}${c.thumb ? "" : " noimg"}${on ? " on" : ""}${c.status === "void" ? " void" : ""}`} data-uid={c.uid}>
      <button className="ac-card-hit" onClick={onOpen} title={`${TYPE_NAME[c.type]} · ${c.name}\n点开看详情、版本、哪些镜头在用`}>
        {ratio !== "ac-rnone" ? (
          <span className="ac-thumb">
            {c.thumb ? <img src={thumb(c.thumb, 360) ?? c.thumb} alt="" loading="lazy" decoding="async" /> : <span className="ac-ph">{c.type === "character" ? c.name.slice(0, 1) : ICON[c.type]}</span>}
            {c.face && <img className="ac-face" src={thumb(c.face, 120) ?? c.face} alt="" loading="lazy" title={c.statusNote ?? "身份参考（脸）"} />}
            <span className="ac-badges">
              {showType && <span className="ds-tag on-media">{TYPE_NAME[c.type]}</span>}
              <span className="grow" />
              <StatusTag s={c.status} />
            </span>
          </span>
        ) : (
          <span className="ac-icon-row">
            <span className="ac-icon" aria-hidden="true">
              {ICON[c.type]}
            </span>
            <StatusTag s={c.status} />
          </span>
        )}
        <span className="ac-meta">
          <span className="ac-name">
            <b>{c.name}</b>
            {c.version ? <small title={c.versions ? `共 ${c.versions} 版` : undefined}>v{c.version}</small> : null}
          </span>
          {(c.owner || c.sub) && (
            <span className="ac-sub">
              {c.owner && c.type !== "look" && <>{c.owner.name}</>}
              {c.owner && c.type !== "look" && c.sub && " · "}
              {c.sub}
            </span>
          )}
          {c.statusNote && !c.owner && !c.sub && <span className="ac-sub">{c.statusNote}</span>}
          {c.missing?.length ? (
            <span className="ac-miss" title={`缺：${c.missing.join("、")}`}>
              缺 {c.missing.length > 1 ? `${c.missing.length} 项` : c.missing[0]}
            </span>
          ) : null}
        </span>
      </button>
      <span className="ac-foot">
        {use ? (
          onUsage ? (
            <button className="ac-use" onClick={onUsage} title="哪些镜头在用（反查）">
              {use} ›
            </button>
          ) : (
            <span className="ac-use plain">{use}</span>
          )
        ) : (
          <span className="ac-use plain">—</span>
        )}
      </span>
    </article>
  );
}
