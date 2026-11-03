import { lazy, Suspense, useEffect, useState } from "react";
import { ConfirmDialog, HelpDialog, Palette, Toasts } from "./components/Dialogs";
import { Drawer } from "./components/Drawer";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { ReviewMode } from "./components/ReviewMode";
import { Viewer } from "./components/Viewer";
import { useKeymap } from "./keymap";
import { StudioProvider, useStudio } from "./store";
import { useHash } from "./projects/route";
import { CanvasV3 } from "./v3/Canvas";
import { SopProvider } from "./v3/sop";
import { TopBarV3, EpisodeScope } from "./v3/TopBarV3";
import { pageOf, type V3Page } from "./v3/TopBarV3.helpers";
import { UiProvider } from "./v3/ui";
import { MaterialsDrawerHost } from "./v3/MaterialsDrawer";
import "./v3/v3.css";
import { Brand } from "./ds/Brand";
import { UndoHost } from "./ds/Undo";
import "./ds/live.css";
import "./v3/breathe.css"; // UIRSI r43 K-UI-048：全站“正在渲染”呼吸灯
import { StaleBanner } from "./v3/StaleBanner"; // UIRSI r45 页面过期检测（L-103）
import "./v3/slide.css"; // UIRSI r45 · L-113 正片 B（总览纸框 + 审片页纸框）——开关 html.ui-slide，已被 L-114 取代、隔离保留
import "./v3/ownerqueue.css"; // UIRSI2 L-116 待你看（顶栏入口 + 机签通过灰字；队列页）
import "./v3/film.css"; // UIRSI r46 · L-114 电影胶片 A——开关 html.ui-film（?ui=film）
import { applyUiStyle } from "./v3/uiStyle";
applyUiStyle();
window.addEventListener("hashchange", () => applyUiStyle());
import { LiveBridge } from "./v3/LiveBridge";
import { FeedbackHost } from "./v3/FeedbackLayer"; // UIRSI2 反馈模式：高亮 / 点选 / 弹框 / 列表抽屉
import { NotFound, PageIntro } from "./v3/PageIntro"; // W5 UIUX：每页顶部一句话 + 404

// fredw-92/W4a：v3 新页面（W4c），挂在 #/script-create、#/models、#/assets
const V3_PAGE_COMP: Record<V3Page, ReturnType<typeof lazy>> = {
  "#/script-create": lazy(() => import("./v3/pages/ScriptFlowPage")), // UX6（D5）：① 创作 + ② 导入 合成一页
  "#/models": lazy(() => import("./v3/pages/ModelsPage")),
  "#/cut": lazy(() => import("./v3/pages/CutPage")), // UX5（D1）：⑤ 成片页
  // NAVFLOW-F 11-03（项目方 L-146：“#/assets 这里很多 v1 半成品也没有了”）：#/assets 换回资产中心（人物页 / 造型 / 单品 / 场景 / 声音 / 图像编辑器），
  // 后端 character-hub 已按当前剧（primary）取人物和资产包；只读的资产包清单页（V2AssetsPage）保留为资产中心左栏“资产包清单”（?type=pack）
  "#/assets": lazy(() => import("./v3/assets/AssetCenter")),
  "#/assets-v1": lazy(() => import("./v3/assets/AssetCenter")), // 旧地址保留（有人收藏过），同一个页面
  "#/trash": lazy(() => import("./v3/pages/TrashRoute")), // EDITDEL 回收站
  "#/audit": lazy(() => import("./v3/pages/AuditRoute")), // 操作记录（独立页）
  "#/script-ab": lazy(() => import("./v3/pages/ScriptABPage")), // 回退补回：剧本 A/B 对比
  "#/settings": lazy(() => import("./v3/pages/ProjectSettingsPage")), // 回退补回：项目设置（旧项目向导）
  "#/script-chat": lazy(() => import("./v3/chat/ChatRoute")), // 回退补回：写作对话框
  "#/overview": lazy(() => import("./v3/pages/SeasonPage")), // 项目方 11-01：全剧总览（快捷键 1）
  "#/sound": lazy(() => import("./v3/pages/SoundPage")), // UIRSI B4：声音一级页（音色 · 旁白 · 对白 · 配乐）
  "#/image-edit": lazy(() => import("./v3/pages/ImageEditPage")), // FILMUI 图像工坊 P1（②资产下的标签；docs/master/EDITOR_INTEGRATION.md）
  "#/frames": lazy(() => import("./v3/pages/FramesPage")), // ASSETUX 1b：“出图”页（全部集 × 每镜首尾帧）
  "#/videos": lazy(() => import("./v3/pages/VideosPage")), // NAVIA：“视频”页（全部集 × 每镜视频状态）
  "#/v1-library": lazy(() => import("./v3/pages/V1Library")), // NAVIA：Version 1 视频库（只读；主导航只显示 V2）
  "#/queue": lazy(() => import("./v3/pages/OwnerQueuePage")), // UIRSI2 L-116：待你看阵列（顶栏常驻入口）
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
          后台地址 127.0.0.1:8800。一直连不上就告诉总调度“后台没响应”，由他重启（不用你敲命令）。
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
  const hash = useHash();
  const page = pageOf(hash);
  // W5 UIUX：#/ 开头但不是任何页面的地址 = 404（以前会静默掉进画布，看不出打错了）。#/、#/? 仍是画布；#/projects、#/inbox 由 Root 自动跳转
  const unknown = !page && /^#\/[^?]/.test(hash) && !/^#\/(projects|inbox)(\/|\?|$)/.test(hash);

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
  const body = unknown ? (
    <NotFound hash={hash} />
  ) : Page ? (
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
      <StaleBanner />
      <TopBarV3 page={page} />
      {!unknown && <PageIntro page={page} />}
      {!unknown && (!page || page === "#/cut" || page === "#/videos" || page === "#/frames") && <EpisodeScope page={page} />}
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
      {/* W5 UIUX 11-03（L-123）：“打回”弹框已摘掉——全站只有“用这张 / 修改”，没有任何入口再打开它（store.setRejectFor 只被置空） */}
      <HelpDialog />
      <ErrorBoundary name="资料清单">
        <MaterialsDrawerHost />
      </ErrorBoundary>
      <Palette />
      <Toasts />
      <UndoHost />
      <LiveBridge />
      <ErrorBoundary name="反馈模式">
        <FeedbackHost />
      </ErrorBoundary>
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
