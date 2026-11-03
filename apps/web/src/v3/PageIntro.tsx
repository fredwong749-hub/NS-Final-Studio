// W5 UIUX 11-03（L-155）：每页顶部一句话“这页是什么、你在这能做什么”；未知地址 = 404 页（写明为什么、能去哪），不露命令行。
// 文案只在 v3/pageMap.ts 一处维护。
import { useStudio } from "../store";
import { PAGES, WHERE_ORDER, hrefOf, pageInfo, type PageInfo } from "./pageMap";
import type { V3Page } from "./TopBarV3.helpers";
import { useOwnerQueue } from "./ownerQueue";
import "./pageintro.css";

export function PageIntro({ page }: { page: V3Page | null }) {
  const p = pageInfo(page);
  const { q } = useOwnerQueue();
  if (!p) return null;
  const n = q?.count ?? 0;
  return (
    <p className="pg-intro" role="note" data-page={p.hash}>
      <b>{p.name}</b>
      <span>{p.intro}</span>
      {page !== "#/queue" && n > 0 ? (
        <a className="pg-intro-todo" href="#/queue" title="需要你动手的事都在待办里">
          有 {n} 件事等你处理 ›
        </a>
      ) : null}
    </p>
  );
}

/** 全部页面索引（设置页底部 / 404 页）：按入口分组，每行 = 页面名 + 一句话 + 从哪进 */
export function AllPages({ compact }: { compact?: boolean }) {
  const { epNum } = useStudio();
  return (
    <div className={`pg-all${compact ? " compact" : ""}`}>
      {WHERE_ORDER.map((w) => {
        const list = PAGES.filter((p) => p.where === w);
        if (!list.length) return null;
        return (
          <section key={w} aria-label={w}>
            <h3>{w}</h3>
            <ul>
              {list.map((p: PageInfo) => (
                <li key={p.hash}>
                  <a href={hrefOf(p, epNum)}>{p.name}</a>
                  {!compact && <span className="pg-all-intro">{p.intro}</span>}
                  <small>{p.path}</small>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

export function NotFound({ hash }: { hash: string }) {
  return (
    <main className="v3-page">
      <div className="v3p-page pg-404" role="alert">
        <h1>这个地址没有页面</h1>
        <p>
          你打开的是 <code>{decodeURIComponent(hash).slice(0, 60)}</code>。它可能是旧收藏、打错了，或者这一页已经搬到别处——功能都还在，只是换了入口。
        </p>
        <p className="pg-404-next">
          最常用的三个地方：<a href="#/overview">全剧总览</a>（现在在哪、卡在哪） · <a href="#/queue">待办</a>（要你做的事） · <a href="#/settings">设置</a>（全部页面）。
        </p>
        <AllPages compact />
      </div>
    </main>
  );
}
