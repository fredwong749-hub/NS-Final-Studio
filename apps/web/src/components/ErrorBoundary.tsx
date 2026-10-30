import { Component, type ReactNode } from "react";

/** 局部出错（例如后端契约变了）只影响这一块，不让整页白屏 */
export class ErrorBoundary extends Component<{ name: string; children: ReactNode }, { err: Error | null }> {
  state = { err: null as Error | null };
  static getDerivedStateFromError(err: Error) {
    return { err };
  }
  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="pad bad">
        {this.props.name}出错：{this.state.err.message}
        <div>
          <button className="btn-mini" onClick={() => this.setState({ err: null })}>
            重试
          </button>
        </div>
      </div>
    );
  }
}
