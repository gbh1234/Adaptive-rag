import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Frontend rendering failed", error, info.componentStack);
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;

    return (
      <main className="fatal-error" role="alert">
        <h1>页面暂时无法显示</h1>
        <p>请刷新页面重试。已保存的本地对话会在刷新后恢复。</p>
        <button onClick={() => window.location.reload()}>刷新页面</button>
      </main>
    );
  }
}
