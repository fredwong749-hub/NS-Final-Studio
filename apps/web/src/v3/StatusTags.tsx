// UIRSI r40：镜头状态彩色标签（全剧总览每格、画布 / 审片每行同一口径）+ 图例。数据与口径见 StatusTags.helpers.ts。
import "./shotstatus.css";
import { TAG_HELP, TAG_ORDER, TAG_WORD, tagsTitle, type ShotStatusTags, type TagKind } from "./StatusTags.helpers";

/** 主标签（最严重的一个）；悬停列出全部状态 */
export function MainTag({ st, size = "sm" }: { st: ShotStatusTags | null | undefined; size?: "xs" | "sm" }) {
  if (!st?.main) return null;
  const n = new Set(st.tags.map((t) => t.kind)).size;
  return (
    <span className={`stag k-${st.main} ${size}`} title={tagsTitle(st)} data-stag={st.main}>
      {TAG_WORD[st.main]}
      {n > 1 ? <em>+{n - 1}</em> : null}
    </span>
  );
}

/** 图例（全剧总览顶部）：每类一个色块 + 一句话；点一类 = 只看带这类状态的镜（再点一次取消） */
export function TagLegend({ counts, on, onPick }: { counts?: Partial<Record<TagKind, number>>; on?: TagKind | null; onPick?: (k: TagKind | null) => void }) {
  return (
    <div className="stag-legend" role="group" aria-label="镜头状态颜色说明">
      {TAG_ORDER.map((k) => (
        <button
          key={k}
          type="button"
          className={`stag k-${k} sm${on === k ? " on" : ""}`}
          title={TAG_HELP[k] + (onPick ? "（点一下只看这些镜，再点取消）" : "")}
          onClick={onPick ? () => onPick(on === k ? null : k) : undefined}
          aria-pressed={onPick ? on === k : undefined}
        >
          {TAG_WORD[k]}
          {counts ? <em>{counts[k] ?? 0}</em> : null}
        </button>
      ))}
    </div>
  );
}

/** 集标题行的汇总（“过期 3 · 待重出 5 · 看图没过 2”），点数字筛这些镜 */
export function TagCounts({ counts, on, onPick }: { counts: Partial<Record<TagKind, number>>; on?: TagKind | null; onPick: (k: TagKind | null) => void }) {
  const ks = TAG_ORDER.filter((k) => (counts[k] ?? 0) > 0 && k !== "ok");
  if (!ks.length) return null;
  return (
    <span className="stag-counts">
      {ks.map((k) => (
        <button key={k} type="button" className={`stag-n k-${k}${on === k ? " on" : ""}`} onClick={() => onPick(on === k ? null : k)} title={`${TAG_HELP[k]}；点一下只看这 ${counts[k]} 镜，再点取消`}>
          {TAG_WORD[k]} {counts[k]}
        </button>
      ))}
    </span>
  );
}
