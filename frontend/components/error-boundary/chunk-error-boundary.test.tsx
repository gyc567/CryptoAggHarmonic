import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ChunkErrorBoundary, isChunkError } from "./chunk-error-boundary";

const ThrowChunkError = ({ shouldThrow }: { shouldThrow: boolean }) => {
  if (shouldThrow) {
    const err = new Error("Loading chunk app/layout failed. (timeout: ...layout.js)");
    err.name = "ChunkLoadError";
    throw err;
  }
  return <div data-testid="child">Child content</div>;
};

const ThrowOtherError = ({ shouldThrow }: { shouldThrow: boolean }) => {
  if (shouldThrow) {
    throw new Error("Unexpected error");
  }
  return <div data-testid="child">Child content</div>;
};

describe("isChunkError", () => {
  it("returns false for undefined", () => {
    expect(isChunkError(undefined)).toBe(false);
  });

  it("returns true for ChunkLoadError name", () => {
    const err = new Error("Loading chunk app/layout failed");
    err.name = "ChunkLoadError";
    expect(isChunkError(err)).toBe(true);
  });

  it("returns true for JS chunk message", () => {
    const err = new Error("Loading chunk app/layout failed. (timeout)");
    expect(isChunkError(err)).toBe(true);
  });

  it("returns true for CSS chunk message", () => {
    const err = new Error("Loading CSS chunk app/layout failed");
    expect(isChunkError(err)).toBe(true);
  });

  it("returns false for unrelated errors", () => {
    expect(isChunkError(new Error("Network error"))).toBe(false);
  });
});

describe("ChunkErrorBoundary", () => {
  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders children when there is no error", () => {
    render(
      <ChunkErrorBoundary>
        <ThrowChunkError shouldThrow={false} />
      </ChunkErrorBoundary>
    );
    expect(screen.getByTestId("child")).toHaveTextContent("Child content");
  });

  it("renders default fallback and reloads on chunk load error", () => {
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", {
      value: { reload: reloadSpy },
      writable: true,
    });

    render(
      <ChunkErrorBoundary>
        <ThrowChunkError shouldThrow={true} />
      </ChunkErrorBoundary>
    );

    expect(screen.getByText("页面加载失败")).toBeInTheDocument();
    fireEvent.click(screen.getByText("重新加载"));
    expect(reloadSpy).toHaveBeenCalled();
  });

  it("renders custom fallback when provided", () => {
    render(
      <ChunkErrorBoundary fallback={<div data-testid="custom">Custom fallback</div>}>
        <ThrowChunkError shouldThrow={true} />
      </ChunkErrorBoundary>
    );

    expect(screen.getByTestId("custom")).toHaveTextContent("Custom fallback");
  });

  it("re-throws non-chunk errors", () => {
    // React logs uncaught errors in tests; suppress them for this assertion.
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() =>
      render(
        <ChunkErrorBoundary>
          <ThrowOtherError shouldThrow={true} />
        </ChunkErrorBoundary>
      )
    ).toThrow("Unexpected error");

    consoleError.mockRestore();
  });

  it("detects CSS chunk errors by message", () => {
    const reloadSpy = vi.fn();
    Object.defineProperty(window, "location", {
      value: { reload: reloadSpy },
      writable: true,
    });

    const ThrowCssChunkError = ({ shouldThrow }: { shouldThrow: boolean }) => {
      if (shouldThrow) {
        const err = new Error("Loading CSS chunk app/layout failed");
        throw err;
      }
      return <div>Child</div>;
    };

    render(
      <ChunkErrorBoundary>
        <ThrowCssChunkError shouldThrow={true} />
      </ChunkErrorBoundary>
    );

    expect(screen.getByText("页面加载失败")).toBeInTheDocument();
  });
});
