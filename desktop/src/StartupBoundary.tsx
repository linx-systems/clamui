import { Component, useEffect, type ErrorInfo, type ReactNode } from "react";

import { _ } from "./i18n";
import { bootMark, reportFrontend, reportFrontendReady } from "./startup";

/** Plain-text description of a failure, safe to show and to log. */
export function describeFailure(error: unknown, componentStack = ""): string {
  const base =
    error instanceof Error ? `${error.name}: ${error.message}\n${error.stack ?? ""}` : String(error);
  return componentStack ? `${base}\nComponent stack:${componentStack}` : base;
}

/** Visible replacement for a window that would otherwise stay blank. */
export function StartupFailure({ details }: { details: string }) {
  return (
    <main className="startup-error">
      <section className="card" aria-labelledby="startup-error-title">
        <h1 id="startup-error-title">{_("ClamUI could not start")}</h1>
        <pre className="startup-error-details">{details}</pre>
        <button className="button primary" type="button" onClick={() => window.location.reload()}>
          {_("Retry")}
        </button>
      </section>
    </main>
  );
}

interface BoundaryState {
  details: string | null;
}

/** Catches render errors that would otherwise unmount the whole tree and leave a blank window. */
export class StartupBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  state: BoundaryState = { details: null };

  static getDerivedStateFromError(error: unknown): BoundaryState {
    return { details: describeFailure(error) };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    const details = describeFailure(error, info.componentStack ?? "");
    bootMark("render error");
    this.setState({ details });
    void reportFrontend("render", details);
  }

  render(): ReactNode {
    return this.state.details === null ? this.props.children : <StartupFailure details={this.state.details} />;
  }
}

/** Renders nothing; tells the native watchdog the interface mounted. */
export function StartupReady(): null {
  useEffect(() => {
    bootMark("mounted");
    void reportFrontendReady();
  }, []);
  return null;
}
