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
    if (retired) history.replaceState(null, "", `${location.pathname}${location.search}#/script-create`), window.dispatchEvent(new HashChangeEvent("hashchange"));
  }, [retired]);
  return (
    <AuthGate>
      <App />
    </AuthGate>
  );
}
