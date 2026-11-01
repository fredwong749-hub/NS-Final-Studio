import { lazy, Suspense, useEffect, useState } from "react";
import { ConfirmDialog, HelpDialog, Palette, RejectDialog, Toasts } from "./components/Dialogs";
import { Drawer } from "./components/Drawer";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ReviewMode } from "./components/ReviewMode";
import { Viewer } from "./components/Viewer";
import { nextUnreviewed, useKeymap } from "./keymap";
import { StudioProvider, useStudio } from "./store";
import { useHash } from "./projects/route";
import { CanvasV3 } from "./v3/Canvas";
import { SopProvider } from "./v3/sop";
import { TopBarV3 } from "./v3/TopBarV3";
import { pageOf, type V3Page } from "./v3/TopBarV3.helpers";
import { UiProvider } from "./v3/ui";
import { MaterialsDrawerHost } from "./v3/MaterialsDrawer";
import "./v3/v3.css";
import { Brand } from "./ds/Brand";
import { UndoHost } from "./ds/Undo";
import "./ds/live.css";
import { LiveBridge } from "./v3/LiveBridge";

// fredw-92/W4a：v3 新页面（W4c），挂在 #/script-create、#/models、#/assets
const V3_PAGE_COMP: Record<V3Page, ReturnType<typeof lazy>> = {
  "#/script-create": lazy(() => import("./v3/pages/ScriptFlowPage")), // UX6（D5）：① 创作 + ② 导入 合成一页
  "#/models": lazy(() => import("./v3/pages/ModelsPage")),
  "#/cut": lazy(() => import("./v3/pages/CutPage")), // UX5（D1）：⑤ 成片页
  "#/assets": lazy(() => import("./v3/assets/AssetCenter")), // UX5：资产中心（角色详情仍复用 v3/pages/AssetsPage）
  "#/trash": lazy(() => import("./v3/pages/TrashRoute")), // EDITDEL 回收站
  "#/audit": lazy(() => import("./v3/pages/AuditRoute")), // 操作记录（独立页）
  "#/script-ab": lazy(() => import("./v3/pages/ScriptABPage")), // 回退补回：剧本 A/B 对比
  "#/settings": lazy(() => import("./v3/pages/ProjectSettingsPage")), // 回退补回：项目设置（旧项目向导）
  "#/script-chat": lazy(() => import("./v3/chat/ChatRoute")), // 回退补回：写作对话框
  "#/overview": lazy(() => import("./v3/pages/SeasonPage")), // 项目方 11-01：全剧总览（快捷键 1）
  "#/sound": lazy(() => import("./v3/pages/SoundPage")), // UIRSI B4：声音一级页（音色 · 旁白 · 对白 · 配乐）
};
/** UX4（R8）：后台没响应的提示——人话 + 自动重连计次 + 折叠的技术细节 */
function BootError({ err, retry, slim }: { err: string; retry: () => Promise<unknown> | void; slim?: boolean }) {
  const [n, setN] = useState(1);
  useEffect(() => {
    const t = setInterval(() => {
      setN((x) => x + 1);
      void retry();
    }, 5000);
    return () => clearInterval(t);
  }, [retry]);
  return (
    <div className={slim ? "boot-err slim" : "boot-err"} role="alert">
      {!slim && <Brand mode="full" size={28} className="boot-brand" />}
      <b>后台服务没响应，正在自动重连（第 {n} 次）</b>
      {!slim && <p className="muted">不用操作，服务恢复后页面会自己出来。已经点过的出图、视频任务不会丢。</p>}
      {!slim && (
        <p className="muted">
          {/* UX5（D3）：画布读不到集列表时别只剩一行字——给出不依赖集列表、现在就能打开的页面 */}
          不等也行，这几页现在就能开：<a href="#/script-create">新建剧本</a> · <a href="#/assets">资产中心</a> · <a href="#/models">模型与 API</a>
        </p>
      )}
      {slim && <span className="muted">本页能显示的部分照常显示，读不到的那块会单独写“读不到”。</span>}
      <button className="btn" onClick={() => (setN((x) => x + 1), void retry())}>
        现在重试
      </button>
      <details className="boot-tech">
        <summary>技术细节</summary>
        <p>请求 /api/episodes 失败：{err}</p>
        <p>
          后台地址 127.0.0.1:8800。手动启动：<code>uv run uvicorn ns_api.app:app --port 8800</code>
        </p>
      </details>
    </div>
  );
}

/** 首屏读集列表时的进度（UIAUDIT r8：首屏 36–84 秒只写“加载中”不行）：已等几秒 + 在读什么 + 不确定进度的流动条 */
function BootProgress() {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setSec((x) => x + 1), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <span className="boot-load" role="status" aria-live="polite">
      <Brand mode="full" size={28} />
      <span>正在读全剧的集与镜头（{sec} 秒）</span>
      <span className="sp-track boot-bar" aria-hidden>
        <i className="sp-run" style={{ left: "0%", width: "100%" }} />
      </span>
      <small className="muted">{sec < 15 ? "通常十几秒；后台正在算每镜的状态" : sec < 60 ? "后台在忙（出图 / 出视频同时在跑），再等一会儿" : "比平时慢很多；页面会自己出来，不用刷新"}</small>
    </span>
  );
}

function Shell() {
  const st = useStudio();
  useKeymap(st);
  const { episodes, loadError, refreshEpisodes } = st;
  const page = pageOf(useHash());

  // UX4（审查 R8）：连不上后台时写人话、自动重连并计次；命令行收进“技术细节”。
  // 资产 / 模型 / 剧本创作等独立页面不依赖集列表：照常显示页面，只在顶部挂一条提示。
  if (!episodes && page && loadError) {
    const Pg = V3_PAGE_COMP[page];
    return (
      <div className="app v3-app">
        <BootError err={loadError} retry={refreshEpisodes} slim />
        <main className="v3-page">
          <ErrorBoundary name="页面">
            <Suspense fallback={<div className="empty">加载中…</div>}>
              <Pg />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    );
  }
  if (!episodes)
    return (
      <div className="boot">
        {loadError ? (
          <BootError err={loadError} retry={refreshEpisodes} />
        ) : (
          <BootProgress />
        )}
      </div>
    );

  // UIRSI 重构：只有一个外壳——新页面（#/…）或分镜画布（审片 / 精修）。旧镜头行 + 检查器、旧总览、旧资产库、人物管理、节点画布已下线。
  const Page = page ? V3_PAGE_COMP[page] : null;
  const body = Page ? (
    <main className="v3-page">
      <ErrorBoundary name="页面">
        <Suspense fallback={<div className="empty">加载中…</div>}>
          <Page />
        </Suspense>
      </ErrorBoundary>
    </main>
  ) : (
    <ErrorBoundary name="分镜画布">
      <CanvasV3 />
    </ErrorBoundary>
  );

  return (
    <div className="app v3-app">
      <TopBarV3 page={page} />
      {body}
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
      <ErrorBoundary name="资料清单">
        <MaterialsDrawerHost />
      </ErrorBoundary>
      <Palette />
      <Toasts />
      <UndoHost />
      <LiveBridge />
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
