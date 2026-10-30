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
import { nextUnreviewed, useKeymap } from "./keymap";
import { StudioProvider, useStudio } from "./store";
import { useHash } from "./projects/route";
import { CanvasV3 } from "./v3/Canvas";
import { SopProvider } from "./v3/sop";
import { pageOf, TopBarV3, type V3Page } from "./v3/TopBarV3";
import { UiProvider } from "./v3/ui";
import "./v3/v3.css";

// 节点画布是次要视图，按需加载（规范 C1）
const NodeView = lazy(() => import("./components/NodeView"));
const AssetsView = lazy(() => import("./components/AssetsView"));
const ImportView = lazy(() => import("./components/ImportView"));
const PeoplePage = lazy(() => import("./components/PeoplePage")); // 人物管理（fredw-25）
const ScriptAB = lazy(() => import("./components/ScriptAB")); // 剧本 A/B 对比（fredw-92）
// fredw-92/W4a：v3 新页面（W4c），挂在 #/script-create、#/models、#/assets
const V3_PAGE_COMP: Record<V3Page, ReturnType<typeof lazy>> = {
  "#/script-create": lazy(() => import("./v3/pages/ScriptCreatePage")),
  "#/models": lazy(() => import("./v3/pages/ModelsPage")),
  "#/assets": lazy(() => import("./v3/pages/AssetsPage")),
};
/** 整页视图：不显示集列表与检查器 */
const FULL_PAGE = new Set(["assets", "import", "people", "ab"]);

function Shell() {
  const st = useStudio();
  useKeymap(st);
  const { episodes, loadError, view, refreshEpisodes, inspectorHidden, classic } = st;
  const page = pageOf(useHash());

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

  // fredw-92/W4a：v3——新页面（#/…）与分镜画布（审片 / 精修）用新顶栏；旧版镜头行 + 检查器从“工具”菜单进入
  const v3Canvas = !page && view === "episode" && !classic;
  const Page = page ? V3_PAGE_COMP[page] : null;
  const body = Page ? (
    <main className="v3-page">
      <ErrorBoundary name="页面">
        <Suspense fallback={<div className="empty">加载中…</div>}>
          <Page />
        </Suspense>
      </ErrorBoundary>
    </main>
  ) : v3Canvas ? (
    <ErrorBoundary name="分镜画布">
      <CanvasV3 />
    </ErrorBoundary>
  ) : null;

  return (
    <div className={`app${body ? " v3-app" : ""}`}>
      <TopBarV3 page={page} />
      {body}
      {!body && <div className={`workspace${FULL_PAGE.has(view) || inspectorHidden ? " no-insp" : ""}${FULL_PAGE.has(view) ? " assets-mode" : ""}`}>
        {!FULL_PAGE.has(view) && <EpisodeList />}
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
            {view === "import" && (
              <Suspense fallback={<div className="empty">加载剧本导入…</div>}>
                <ImportView />
              </Suspense>
            )}
            {view === "people" && (
              <Suspense fallback={<div className="empty">加载人物管理…</div>}>
                <PeoplePage />
              </Suspense>
            )}
            {view === "ab" && (
              <Suspense fallback={<div className="empty">加载剧本 A/B…</div>}>
                <ScriptAB />
              </Suspense>
            )}
            {view === "nodes" && (
              <Suspense fallback={<div className="empty">加载节点画布…</div>}>
                <NodeView />
              </Suspense>
            )}
          </ErrorBoundary>
        </main>
        {!FULL_PAGE.has(view) && !inspectorHidden && (
          <ErrorBoundary name="检查器">
            <Inspector />
          </ErrorBoundary>
        )}
      </div>}
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
      <SopProvider>
        <UiProvider>
          <Shell />
        </UiProvider>
      </SopProvider>
    </StudioProvider>
  );
}
