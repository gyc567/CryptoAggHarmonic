"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  createVibeSession,
  sendVibeMessage,
  pollVibeEvents,
  cancelVibeRun,
} from "@/lib/api-vibe";
import {
  vibeChatReducer,
  initialState,
} from "@/lib/vibe/event-reducer";
import type { VibeMessage, VibeSession } from "@/types/vibe";

// localStorage keys are namespaced by userId so that switching accounts in the
// same browser does not leak cached sessions/messages across users.
const SESSIONS_KEY = (userId: string) => `pyharmonics:vibe:sessions:${userId}`;
const MESSAGES_KEY = (userId: string, sessionId: string) =>
  `pyharmonics:vibe:messages:${userId}:${sessionId}`;

function readSessions(userId: string): VibeSession[] {
  if (typeof window === "undefined" || !userId) return [];
  try {
    return JSON.parse(localStorage.getItem(SESSIONS_KEY(userId)) || "[]");
  } catch {
    return [];
  }
}

function writeSessions(userId: string, sessions: VibeSession[]) {
  if (typeof window === "undefined" || !userId) return;
  localStorage.setItem(SESSIONS_KEY(userId), JSON.stringify(sessions));
}

function readMessages(userId: string, sessionId: string): VibeMessage[] {
  if (typeof window === "undefined" || !userId) return [];
  try {
    return JSON.parse(
      localStorage.getItem(MESSAGES_KEY(userId, sessionId)) || "[]"
    );
  } catch {
    return [];
  }
}

function writeMessages(
  userId: string,
  sessionId: string,
  messages: VibeMessage[]
) {
  if (typeof window === "undefined" || !userId) return;
  localStorage.setItem(
    MESSAGES_KEY(userId, sessionId),
    JSON.stringify(messages)
  );
}

interface UseVibeOptions {
  getToken: () => Promise<string | null>;
  userId?: string;
}

export function useVibe({ getToken, userId }: UseVibeOptions) {
  const [state, dispatch] = useReducer(vibeChatReducer, initialState);
  const [sessions, setSessions] = useState<VibeSession[]>([]);
  const sessionsRef = useRef<VibeSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [initialized, setInitialized] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const runningRef = useRef(false);
  const currentRunIdRef = useRef<string | null | undefined>(null);

  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  // Keep a mutable ref of the current run id so the unmount cleanup can cancel
  // the latest backend run without re-registering the effect on every render.
  useEffect(() => {
    currentRunIdRef.current = state.currentRunId;
  }, [state.currentRunId]);

  // Cancel the backend run if the component unmounts while a run is active.
  useEffect(() => {
    return () => {
      if (!runningRef.current) return;
      const runId = currentRunIdRef.current;
      if (runId) {
        getToken().then((token) => {
          if (token) cancelVibeRun(token, runId).catch(() => {});
        });
      }
      if (pollRef.current) {
        clearTimeout(pollRef.current);
        pollRef.current = null;
      }
      runningRef.current = false;
    };
  }, [getToken]);

  // Initialize sessions from localStorage for the current user.
  useEffect(() => {
    if (!userId) {
      setInitialized(true);
      return;
    }
    const stored = readSessions(userId);
    setSessions(stored);
    if (stored.length > 0) {
      const latest = stored[0];
      setCurrentSessionId(latest.id);
      dispatch({ type: "RESET" });
      const msgs = readMessages(userId, latest.id);
      msgs.forEach((msg) => dispatch({ type: "ADD_MESSAGE", message: msg }));
    }
    setInitialized(true);
  }, [userId]);

  // Persist messages whenever they change.
  useEffect(() => {
    if (userId && currentSessionId && state.messages.length > 0) {
      writeMessages(userId, currentSessionId, state.messages);
    }
  }, [userId, state.messages, currentSessionId]);

  const createSession = useCallback(
    async (title?: string) => {
      const token = await getToken();
      if (!token) return;

      const res = await createVibeSession(token, {
        title,
        context: { default_market: "binance", default_symbol: "BTCUSDT" },
      });

      if ("data" in res) {
        const session = res.data;
        const next = [session, ...sessionsRef.current];
        setSessions(next);
        if (userId) writeSessions(userId, next);
        setCurrentSessionId(session.id);
        dispatch({ type: "RESET" });
        return session;
      }
      return undefined;
    },
    [getToken, userId]
  );

  const loadSession = useCallback(
    (sessionId: string) => {
      setCurrentSessionId(sessionId);
      dispatch({ type: "RESET" });
      if (!userId) return;
      const msgs = readMessages(userId, sessionId);
      msgs.forEach((msg) => dispatch({ type: "ADD_MESSAGE", message: msg }));
    },
    [userId]
  );

  const startPolling = useCallback((token: string, runId: string) => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
    }

    let lastEventId: string | undefined;
    let emptyCount = 0;
    let active = false;

    const tick = async () => {
      if (active) return;
      active = true;
      const res = await pollVibeEvents(token, runId, lastEventId);
      active = false;

      if ("error" in res) {
        dispatch({
          type: "SET_ERROR",
          error: res.error,
        });
        runningRef.current = false;
        pollRef.current = null;
        return;
      }

      const { events, status } = res.data;
      let shouldStop = false;
      if (events.length === 0) {
        emptyCount += 1;
      } else {
        emptyCount = 0;
        events.forEach((event) => {
          dispatch({ type: "APPEND_EVENT", event });
          lastEventId = event.event_id;
        });
      }

      if (
        status === "completed" ||
        status === "failed" ||
        status === "cancelled" ||
        emptyCount > 120 // 60 seconds timeout
      ) {
        shouldStop = true;
        runningRef.current = false;
        if (status === "completed") {
          dispatch({
            type: "APPEND_EVENT",
            event: {
              event_id: `done-${runId}`,
              run_id: runId,
              type: "done",
            },
          });
        }
      }

      if (!shouldStop) {
        pollRef.current = setTimeout(tick, 500);
      } else {
        pollRef.current = null;
      }
    };

    pollRef.current = setTimeout(tick, 500);
  }, []);

  const sendMessage = useCallback(
    async (content: string) => {
      if (runningRef.current) {
        dispatch({
          type: "SET_ERROR",
          error: { code: "RUN_IN_PROGRESS", message: "当前有运行在进行中，请等待或停止", retryable: false },
        });
        return;
      }

      const token = await getToken();
      if (!token) {
        dispatch({
          type: "SET_ERROR",
          error: { code: "UNAUTHORIZED", message: "请先登录", retryable: false },
        });
        return;
      }

      runningRef.current = true;
      let sessionId = currentSessionId;
      if (!sessionId) {
        const session = await createSession();
        if (!session) {
          runningRef.current = false;
          return;
        }
        sessionId = session.id;
      }

      const userMessage: VibeMessage = {
        id: `user-${Date.now()}`,
        session_id: sessionId,
        role: "user",
        content,
        created_at: new Date().toISOString(),
      };
      dispatch({ type: "ADD_MESSAGE", message: userMessage });

      const res = await sendVibeMessage(token, sessionId, { content });
      if ("error" in res) {
        runningRef.current = false;
        dispatch({ type: "SET_ERROR", error: res.error });
        return;
      }

      const { run_id } = res.data;
      dispatch({ type: "START_RUN", runId: run_id });
      startPolling(token, run_id);
    },
    [getToken, currentSessionId, createSession, startPolling]
  );

  useEffect(() => {
    return () => {
      if (pollRef.current) {
        clearTimeout(pollRef.current);
      }
    };
  }, []);

  const stopRun = useCallback(async () => {
    if (pollRef.current) {
      clearTimeout(pollRef.current);
      pollRef.current = null;
    }

    const runId = state.currentRunId;
    if (runId) {
      const token = await getToken();
      if (token) {
        await cancelVibeRun(token, runId).catch(() => {
          // Best-effort cancellation; local state is still cleaned up.
        });
      }
    }

    runningRef.current = false;
    dispatch({
      type: "APPEND_EVENT",
      event: {
        event_id: `stop-${Date.now()}`,
        run_id: state.currentRunId || "",
        type: "done",
      },
    });
  }, [state.currentRunId, getToken]);

  return {
    sessions,
    currentSessionId,
    messages: state.messages,
    loading: state.loading,
    error: state.error,
    initialized,
    createSession,
    loadSession,
    sendMessage,
    stopRun,
  };
}
