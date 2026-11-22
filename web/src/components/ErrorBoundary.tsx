import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "./ui";

import "../pages/settings.css";

type Props = {
  children: ReactNode;
  /** When this changes while the boundary is showing its fallback, the children are tried again. */
  resetKey?: unknown;
  /** What to show instead of the children after a render failure; `reset` tries the children again,
   * and `detail` names what broke (see `describeFailure`). */
  fallback?: (reset: () => void, detail?: string) => ReactNode;
  /** Called when the boundary resets, by `reset` or by a new `resetKey`. */
  onReset?: () => void;
};

/** Keeps a rendering bug from blanking the whole app. */
export class ErrorBoundary extends Component<Props, { failed: boolean; detail?: string }> {
  state: { failed: boolean; detail?: string } = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("render failed", error, info.componentStack);
    this.setState({ detail: describeFailure(error, info.componentStack) });
  }

  componentDidUpdate(prev: Props): void {
    if (this.state.failed && !Object.is(prev.resetKey, this.props.resetKey)) this.reset();
  }

  reset = (): void => {
    this.setState({ failed: false, detail: undefined });
    this.props.onReset?.();
  };

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    if (this.props.fallback) return this.props.fallback(this.reset, this.state.detail);
    return (
      <div className="state" role="alert">
        <p>Something went wrong on this page.</p>
        <Button onClick={() => window.location.reload()}>
          Reload
        </Button>
      </div>
    );
  }
}

/** What broke, short enough for a screenshot: the error's message and the innermost components it
 * was thrown in, e.g. "Cannot read properties of undefined (reading 'amount') · in Latest < Dashboard".
 * Production builds keep component names minified only when they are; ours are not mangled. */
export function describeFailure(error: unknown, componentStack?: string | null): string {
  const message = error instanceof Error ? error.message : String(error);
  const where = (componentStack ?? "")
    .split("\n")
    .map((line) => /^\s*(?:at\s+)?([A-Za-z_$][\w$]*)/.exec(line)?.[1])
    .filter((name): name is string => !!name && name !== "at")
    .slice(0, 3);
  return where.length ? `${message} · in ${where.join(" < ")}` : message;
}

/** The fallback for one page: the shell around it stays usable. The detail line says what broke, so a
 * screenshot from a phone is enough to find it. */
export function pageFallback(reset: () => void, detail?: string): ReactNode {
  return (
    <div className="page-error" role="alert">
      <p>This page hit a problem.</p>
      {detail && <p className="page-error-detail">{detail}</p>}
      <div className="page-error-actions">
        <Button variant="primary" onClick={reset}>
          Try again
        </Button>
        <Button onClick={() => window.location.reload()}>
          Reload
        </Button>
      </div>
    </div>
  );
}
