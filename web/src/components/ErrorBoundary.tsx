import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = {
  children: ReactNode;
  /** When this changes while the boundary is showing its fallback, the children are tried again. */
  resetKey?: unknown;
  /** What to show instead of the children after a render failure; `reset` tries the children again. */
  fallback?: (reset: () => void) => ReactNode;
  /** Called when the boundary resets, by `reset` or by a new `resetKey`. */
  onReset?: () => void;
};

/** Keeps a rendering bug from blanking the whole app. */
export class ErrorBoundary extends Component<Props, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("render failed", error, info.componentStack);
  }

  componentDidUpdate(prev: Props): void {
    if (this.state.failed && !Object.is(prev.resetKey, this.props.resetKey)) this.reset();
  }

  reset = (): void => {
    this.setState({ failed: false });
    this.props.onReset?.();
  };

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    if (this.props.fallback) return this.props.fallback(this.reset);
    return (
      <div className="state" role="alert">
        <p>Something went wrong on this page.</p>
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}

/** The fallback for one page: the shell around it stays usable. */
export function pageFallback(reset: () => void): ReactNode {
  return (
    <div className="page-error" role="alert">
      <p>This page hit a problem.</p>
      <div className="page-error-actions">
        <button type="button" className="btn btn-primary" onClick={reset}>
          Try again
        </button>
        <button type="button" className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    </div>
  );
}
