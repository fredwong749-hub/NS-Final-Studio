import type { LookTag } from "../util";
import { lookTagTitle } from "./LookStrip.helpers";

export function LookStrip({
  tags,
  highlight,
  onPick,
  empty = "无出场角色",
}: {
  tags: LookTag[] | undefined;
  highlight?: string | null;
  onPick?: (character: string) => void;
  empty?: string;
}) {
  if (!tags) return <div className="look-strip muted">造型…</div>;
  if (!tags.length) return <div className="look-strip muted">{empty}</div>;
  return (
    <div className="look-strip">
      {tags.map((t) => {
        const err = t.conflicts.some((c) => c.severity === "error");
        const warn = !err && t.conflicts.length > 0;
        return (
          <span
            key={t.character}
            className={[
              "look-tag",
              t.override ? "lt-override" : "lt-inherit",
              t.changed ? "lt-changed" : "",
              err ? "lt-conflict" : warn ? "lt-warn" : "",
              highlight === t.character ? "lt-hl" : "",
            ].join(" ")}
            title={lookTagTitle(t)}
            onClick={onPick ? (e) => (e.stopPropagation(), onPick(t.character)) : undefined}
          >
            {t.label}
            {t.override && <b className="lt-mark">改</b>}
          </span>
        );
      })}
    </div>
  );
}
