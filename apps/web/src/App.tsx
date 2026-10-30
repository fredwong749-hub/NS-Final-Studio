import { lazy, Suspense } from "react";
import { ConfirmDialog, HelpDialog, Palette, RejectDialog, Toasts } from "./components/Dialogs";
import { Drawer } from "./components/Drawer";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { EpisodeList } from "./components/EpisodeList";
import { EpisodeView } from "./components/EpisodeView";
import { Inspector } from "./components/Inspector";
import { OverviewGrid } from "./components/OverviewGrid";
import { ReviewMode } from "./components/ReviewMode";
import { Viewer } from "./components/Viewer";
import { TopBar } from "./components/TopBar";
import { nextUnreviewed, useKeymap } from "./keymap";
import { StudioProvider, useStudio } from "./store";

// 节点画布是次要视图，按需加载（规范 C1）
const NodeView = lazy(() => import("./components/NodeView"));
const AssetsView = lazy(() => import("./components/AssetsView"));

function Shell() {
  const st = useStudio();
  useKeymap(st);
  const { episodes, loadError, view, refreshEpisodes, inspectorHidden } = st;

  if (!episodes)
    return (
      <div className="boot">
        {loadError ? (
          <>
            <p>连不上后端（/api/episodes）：{loadError}</p>
            <p className="muted">确认 API 已启动：uv run uvicorn ns_api.app:app --port 8800</p>
            <button className="btn" onClick={() => void refreshEpisodes()}>
              重试
            </button>
          </>
        ) : (
          "加载中…"
        )}
      </div>
    );

  return (
    <div className="app">
      <TopBar />
      <div className={`workspace${view === "assets" || inspectorHidden ? " no-insp" : ""}${view === "assets" ? " assets-mode" : ""}`}>
        {view !== "assets" && <EpisodeList />}
        <main className="main">
          {loadError && <div className="banner bad">刷新失败：{loadError}</div>}
          <ErrorBoundary name="主视图">
            {view === "overview" && <OverviewGrid />}
            {view === "episode" && <EpisodeView />}
            {view === "assets" && (
              <Suspense fallback={<div className="empty">加载资产页…</div>}>
                <AssetsView />
              </Suspense>
            )}
            {view === "nodes" && (
              <Suspense fallback={<div className="empty">加载节点画布…</div>}>
                <NodeView />
              </Suspense>
            )}
          </ErrorBoundary>
        </main>
        {view !== "assets" && !inspectorHidden && (
          <ErrorBoundary name="检查器">
            <Inspector />
          </ErrorBoundary>
        )}
      </div>
      <ErrorBoundary name="底部抽屉">
        <Drawer />
      </ErrorBoundary>
      <ErrorBoundary name="审片模式">
        <ReviewMode />
      </ErrorBoundary>
      <ErrorBoundary name="全屏看图">
        <Viewer />
      </ErrorBoundary>
      <ConfirmDialog />
      <RejectDialog
        onDone={() => {
          if (!st.reviewMode) return;
          const n = nextUnreviewed(st);
          if (n) st.select(n);
        }}
      />
      <HelpDialog />
      <Palette />
      <Toasts />
    </div>
  );
}

export default function App() {
  return (
    <StudioProvider>
      <Shell />
    </StudioProvider>
  );
}
