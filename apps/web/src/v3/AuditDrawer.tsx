// 操作记录（登录后的每个写操作自动记下：谁、什么时候、做了什么、对哪个对象、结果）。数据：GET /api/audit。
import { useEffect, useState } from "react";
import { Drawer, LoadError, Skel } from "../ds";
import { humanObj, humanPath, useAuditNames } from "./auditWords";

type Item = { at: string; user: string | null; role: string; method: string; path: string; obj?: Record<string, unknown>; status: number };
const WORDS: [RegExp, string][] = [
  [/story-images\/pick/, "挑设定图"],
  [/script-inbox\/import/, "导入剧本"],
  [/sop\/owner-decision/, "拍板（待你决定）"],
  [/revisions\/.+\/set-current/, "回到某一版"],
  [/deps\/keep/, "保留旧版"],
  [/frame-jobs|video-jobs|produce/, "出图 / 出视频"],
  [/review|pass|reject/, "审片"],
  [/lock|unlock/, "定稿"],
  [/auth\/(setup|login)/, "登录"],
];
// UIPIXEL：认不出的接口不再直接显示路径（路径在 title 和“技术详情”里，一个字段不丢）
const what = (p: string) => humanPath(p) ?? WORDS.find(([r]) => r.test(p))?.[1] ?? "其他操作"; // 细的（带对象名）优先，旧的粗分类兜底

export function AuditDrawer({ onClose }: { onClose: () => void }) {
  return (
    <Drawer title="操作记录" onClose={onClose} wide>
      <AuditTable />
    </Drawer>
  );
}

export function AuditTable() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useAuditNames();
  useEffect(() => {
    fetch("/api/audit?limit=300")
      .then(async (r) => (r.ok ? r.json() : Promise.reject(new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`))))
      .then((d: { items: Item[] }) => setItems(d.items), (e: Error) => setErr(e.message));
  }, []);
  return (
    <>
      {err && <LoadError what="操作记录" err={err} />}
      {!items && !err && <Skel h={240} />}
      {items && (
        <table className="audit-tbl">
          <thead>
            <tr>
              <th>时间</th>
              <th>谁</th>
              <th>做了什么</th>
              <th>对象</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            {items.map((x, i) => (
              <tr key={i} className={x.status >= 400 ? "bad" : ""}>
                <td>{x.at.replace("T", " ").slice(5, 19)}</td>
                <td>{x.user ?? "系统 / 未登录"}</td>
                <td title={`${x.method} ${x.path}`}>{what(x.path)}</td>
                <td className="ds-small audit-obj">
                  {(() => {
                    const h = humanObj(x.obj);
                    return (
                      <>
                        {h.text && <span title={h.raw}>{h.text}</span>}
                        <details className="audit-raw">
                          <summary>技术详情</summary>
                          <code>
                            {x.method} {x.path}
                            {h.raw ? ` · ${h.raw}` : ""}
                            {x.role ? ` · role=${x.role}` : ""}
                          </code>
                        </details>
                      </>
                    );
                  })()}
                </td>
                <td>{x.status >= 400 ? `没成功（${x.status}）` : "成功"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
