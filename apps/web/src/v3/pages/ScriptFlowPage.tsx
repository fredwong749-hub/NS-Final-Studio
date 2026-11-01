// 剧本页（#/script-create）：① 新建剧本 → ② 导入（你确认）。只合 UI 入口与跳转，不改剧本内容、不改导入逻辑。
//   ① 新建剧本（UIRSI）：故事提纲 → 写作模型自动写 P1 故事线 → P2 大纲 → P3 剧本 → P4 分镜，每段可看 / 改 / 返修 → 送去导入
//   ② 导入：原“剧本导入”页（粘贴 / 上传 / 收件箱候选 → 校验 → 你确认后导入）
// 路由：#/script-create（= ①，可带 ?run=<id>）、#/script-create?tab=import（= ②）。旧的 /?view=import 也跳到 ②。
import { lazy, Suspense, useEffect, useState } from "react";
import { Skel } from "../../ds";
import NewScriptPage from "./NewScriptPage";
import "./script_flow.css";

const ImportView = lazy(() => import("../../components/ImportView"));

type Tab = "new" | "import";
const tabOf = (): Tab => (new URLSearchParams(location.hash.split("?")[1] ?? "").get("tab") === "import" ? "import" : "new");

export default function ScriptFlowPage() {
  const [tab, setTab] = useState<Tab>(tabOf);
  useEffect(() => {
    const on = () => setTab(tabOf());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = (t: Tab) => {
    location.hash = t === "import" ? "#/script-create?tab=import" : "#/script-create";
  };
  const steps: { id: Tab; n: string; label: string; sub: string }[] = [
    { id: "new", n: "①", label: "新建剧本", sub: "故事提纲 → 自动写故事线 · 大纲 · 剧本 · 分镜，每段可看可改" },
    { id: "import", n: "②", label: "导入", sub: "点“导入”换上新剧本（自动备份，可还原）" },
  ];
  return (
    <div className="sf-page">
      <nav className="sf-steps" aria-label="剧本流程">
        <b className="sf-title">剧本</b>
        {steps.map((s, i) => (
          <span key={s.id} className="sf-step-wrap">
            {i > 0 && <span className="sf-arrow" aria-hidden="true">→</span>}
            <button className={`sf-step${tab === s.id ? " on" : ""}`} onClick={() => go(s.id)} aria-current={tab === s.id ? "step" : undefined} title={s.sub}>
              <span className="sf-n">{s.n}</span>
              <span className="sf-l">{s.label}</span>
              <small>{s.sub}</small>
            </button>
          </span>
        ))}
        <span className="ds-grow" />
        <span className="ds-small ds-muted sf-note">系统只收发、校验格式，不评价内容；导入一律由你确认</span>
      </nav>
      {/^(chat|create)$/.test(new URLSearchParams(location.hash.split("?")[1] ?? "").get("tab") ?? "") && (
        <div className="sf-retired" role="status">“单集对话写作”已下线（并入 ① 新建剧本：提纲 → 自动写到分镜，每段可看可改）。旧会话的稿件仍在 ② 导入的候选里。</div>
      )}
      {tab === "new" ? (
        <NewScriptPage onGoImport={() => go("import")} />
      ) : (
        <div className="sf-import">
          <Suspense fallback={<Skel h={320} />}>
            <ImportView />
          </Suspense>
        </div>
      )}
    </div>
  );
}
