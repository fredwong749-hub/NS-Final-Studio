import { Component, type ReactNode } from "react";

/** 程序文件（按需加载的页面模块）没下载下来：网络抖动 / 开发服务器刚重启 / 新版本换了文件名 */
const isChunkError = (e: Error) => /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError/i.test(e.message);
const RELOAD_KEY = "ns.eb.autoReload";

/** 局部出错（例如后端契约变了）只影响这一块，不让整页白屏。
 *  UIMASTER（iter_024）：以前只显示英文原文 + “重试”；模块没加载下来时“重试”永远不成功。
 *  现在：说人话 + 一键解决；模块加载失败时自动整页重载一次（同一会话 30 秒内只自动一次，避免来回刷），技术细节折叠。 */
export class ErrorBoundary extends Component<{ name: string; children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) {
    return { err };
  }
  componentDidCatch(err: Error) {
    if (!isChunkError(err)) return;
    try {
      const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0);
      if (Date.now() - last > 30_000) {
        sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
        location.reload();
      }
    } catch {
      /* 无痕模式等拿不到 sessionStorage：不自动刷新，让人点按钮 */
    }
  }
  render() {
    const err = this.state.err;
    if (!err) return this.props.children;
    const chunk = isChunkError(err);
    return (
      <div className="pad bad" role="alert">
        <div>
          {chunk
            ? `${this.props.name}的程序文件没加载下来（多半是网络抖了一下，或刚换了新版本）。点“重新加载页面”就好。`
            : `${this.props.name}这一块出错了，其他部分不受影响。可以先点“重试”；还不行就“重新加载页面”。`}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          {!chunk && (
            <button className="btn-mini" onClick={() => this.setState({ err: null })}>
              重试
            </button>
          )}
          <button className="btn-mini" onClick={() => location.reload()}>
            重新加载页面
          </button>
        </div>
        <details style={{ marginTop: 8 }}>
          <summary>技术细节</summary>
          <code>{err.message}</code>
        </details>
      </div>
    );
  }
}
