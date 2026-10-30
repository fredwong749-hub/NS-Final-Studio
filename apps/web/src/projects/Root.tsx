// T42：顶层路由。#/projects…、#/inbox → 项目 / 新建剧向导 / 待办 / 看板（按需加载）；其余 → 原画布 App。
import { lazy, Suspense } from "react";
import App from "../App";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { isProjectsRoute, useHash } from "./route";

const ProjectsApp = lazy(() => import("./ProjectsApp"));
const ChatApp = lazy(() => import("../chat/ChatApp")); // T58 剧本创作对话框 #/script-chat

export default function Root() {
  const hash = useHash();
  if (hash.startsWith("#/script-chat"))
    return (
      <Suspense fallback={<div className="boot">加载中…</div>}>
        <ErrorBoundary name="剧本创作">
          <ChatApp hash={hash} />
        </ErrorBoundary>
      </Suspense>
    );
  if (isProjectsRoute(hash))
    return (
      <Suspense fallback={<div className="boot">加载中…</div>}>
        <ProjectsApp />
      </Suspense>
    );
  return <App />;
}
