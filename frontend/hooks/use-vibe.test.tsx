import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  cancelVibeRun,
  createVibeSession,
  listVibeSessions,
  pollVibeEvents,
  sendVibeMessage,
} from "@/lib/api-vibe";
import type { VibeSession } from "@/types/vibe";
import { useVibe } from "./use-vibe";

vi.mock("@/lib/api-vibe", () => ({
  cancelVibeRun: vi.fn(),
  createVibeSession: vi.fn(),
  listVibeSessions: vi.fn(),
  pollVibeEvents: vi.fn(),
  sendVibeMessage: vi.fn(),
}));

const USER_ID = "user-1";
const SESSIONS_KEY = `pyharmonics:vibe:sessions:${USER_ID}`;

function session(id: string): VibeSession {
  return {
    id,
    user_id: USER_ID,
    title: null,
    status: "active",
    context: {},
    summary: null,
    message_count: 0,
    last_message_at: null,
    created_at: "2026-08-01T12:00:00.000Z",
    updated_at: "2026-08-01T12:00:00.000Z",
  };
}

describe("useVibe session recovery", () => {
  const getToken = vi.fn(async () => "token");

  beforeEach(() => {
    vi.resetAllMocks();
    window.localStorage.clear();
    getToken.mockResolvedValue("token");
    vi.mocked(listVibeSessions).mockResolvedValue({
      success: true,
      data: { items: [], total: 0 },
    });
    vi.mocked(pollVibeEvents).mockResolvedValue({
      success: true,
      data: { run_id: "run-1", status: "completed", events: [], has_more: false },
    });
    vi.mocked(cancelVibeRun).mockResolvedValue({
      success: true,
      data: { id: "run-1", status: "cancelled" },
    });
  });

  it("removes a locally cached session that no longer exists on the server", async () => {
    const stale = session("stale-session");
    window.localStorage.setItem(SESSIONS_KEY, JSON.stringify([stale]));

    const { result } = renderHook(() => useVibe({ getToken, userId: USER_ID }));

    await waitFor(() => expect(result.current.initialized).toBe(true));

    expect(listVibeSessions).toHaveBeenCalledWith("token");
    expect(result.current.sessions).toEqual([]);
    expect(result.current.currentSessionId).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(SESSIONS_KEY) || "null")).toEqual([]);
  });

  it("replaces a session and retries once when it disappears before send", async () => {
    const stale = session("stale-session");
    const replacement = session("replacement-session");
    window.localStorage.setItem(SESSIONS_KEY, JSON.stringify([stale]));
    vi.mocked(listVibeSessions).mockResolvedValue({
      success: true,
      data: { items: [stale], total: 1 },
    });
    vi.mocked(sendVibeMessage)
      .mockResolvedValueOnce({
        success: false,
        error: {
          code: "NOT_FOUND",
          message: "会话不存在",
          retryable: false,
          status: 404,
        },
      })
      .mockResolvedValueOnce({
        success: true,
        data: { run_id: "run-1", status: "running" },
      });
    vi.mocked(createVibeSession).mockResolvedValue({
      success: true,
      data: replacement,
    });

    const { result } = renderHook(() => useVibe({ getToken, userId: USER_ID }));
    await waitFor(() => expect(result.current.currentSessionId).toBe(stale.id));

    await act(async () => {
      await result.current.sendMessage("分析 BTCUSDT 4h");
    });

    expect(sendVibeMessage).toHaveBeenNthCalledWith(
      1,
      "token",
      stale.id,
      { content: "分析 BTCUSDT 4h" }
    );
    expect(sendVibeMessage).toHaveBeenNthCalledWith(
      2,
      "token",
      replacement.id,
      { content: "分析 BTCUSDT 4h" }
    );
    expect(result.current.currentSessionId).toBe(replacement.id);
    expect(result.current.messages).toEqual([
      expect.objectContaining({
        role: "user",
        session_id: replacement.id,
        content: "分析 BTCUSDT 4h",
      }),
    ]);
    expect(result.current.error).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(SESSIONS_KEY) || "null")).toEqual([
      replacement,
    ]);
  });
});
