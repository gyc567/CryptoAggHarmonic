"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error?: Error;
}

export function isChunkError(error?: Error): boolean {
  if (!error) return false;
  return (
    error.name === "ChunkLoadError" ||
    /Loading chunk .* failed/i.test(error.message) ||
    /Loading CSS chunk .* failed/i.test(error.message)
  );
}

/**
 * Error boundary that catches chunk loading failures and offers a page reload.
 *
 * Keeps the concern isolated: the boundary only handles ChunkLoadError and
 * delegates all other errors to a minimal fallback or re-throws them.
 */
export class ChunkErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error): State {
    if (!isChunkError(error)) {
      // Only handle chunk load errors here; let other boundaries handle the rest.
      throw error;
    }
    return { hasError: true, error };
  }

  componentDidCatch(error: Error): void {
    // eslint-disable-next-line no-console
    console.warn("Chunk load error caught:", error.message);
  }

  render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    if (this.props.fallback) {
      return this.props.fallback;
    }

    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
        <h2 className="text-xl font-semibold">页面加载失败</h2>
        <p className="text-muted-foreground max-w-md">
          静态资源加载超时，请点击下方按钮重新加载页面。
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground hover:bg-primary/90"
        >
          重新加载
        </button>
      </div>
    );
  }
}
