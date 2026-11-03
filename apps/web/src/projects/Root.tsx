// 顶层路由（UIRSI 重构 2026-10-31：只保留一个外壳）。
// 旧的 #/projects…（项目 / 新建剧向导 / 看板）、#/inbox（待办）已下线（代码归档到 data/_archive/20261031/code），打开这些旧地址一律跳到 ① 新建剧本。
// #/script-chat（写作对话：新对话 / 继续下一集）11-01 按项目方要求恢复（UIAUDIT F23），不再重定向。
import { useEffect } from "react";
import App from "../App";
import { useHash } from "./route";
import { AuthGate } from "./AuthGate";

const RETIRED = /^#\/(projects|inbox)(\/|\?|$)/;

export default function Root() {
  const hash = useHash();
  const retired = RETIRED.test(hash);
  useEffect(() => {
    // W5 UIUX 11-03：#/inbox 是旧“待办”地址 → 跳到现在的待办 #/queue（L-134）；#/projects → ① 剧本
    if (retired) history.replaceState(null, "", `${location.pathname}${location.search}${hash.startsWith("#/inbox") ? "#/queue" : "#/script-create"}`), window.dispatchEvent(new HashChangeEvent("hashchange"));
  }, [retired, hash]);
  // W5 UIUX 11-03：首页（不带 # 的 /）= 全剧总览，30 秒内看懂“现在在哪、卡在哪、要我做什么”；画布仍是 #/ 和 #epNN
  useEffect(() => {
    if (!hash || hash === "#") history.replaceState(null, "", `${location.pathname}${location.search}#/overview`), window.dispatchEvent(new HashChangeEvent("hashchange"));
  }, [hash]);
  return (
    <AuthGate>
      <App />
    </AuthGate>
  );
}
