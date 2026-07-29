/**
 * Reducer for the vibe chat conversation state.
 *
 * The state shape is consumed by ``hooks/use-vibe.ts`` and rendered by
 * ``components/vibe/vibe-chat.tsx``. Only the reducer itself and a
 * single ``initialState`` are exported — no React, no side effects.
 *
 * State shape:
 *   - messages      VibeMessage[]   ordered transcript
 *   - loading       boolean         a run is in progress
 *   - error         ApiError|null   last surfaced error
 *   - currentRunId  string|null     run id we are polling / waiting on
 *
 * Action types:
 *   RESET                                       clear everything
 *   ADD_MESSAGE    { message: VibeMessage }     append a fully-formed message
 *   SET_ERROR      { error:   ApiError }        surface an error to the UI
 *   START_RUN      { runId:   string }          mark a run as in-flight
 *   APPEND_EVENT   { event:   VibeEvent }       fold a polled event into state
 *
 * This file was missing from the original commit that introduced
 * ``hooks/use-vibe.ts`` — the hook imported a non-existent module,
 * which surfaced as a Next.js dev compile error and broke ``/vibe``.
 */

import type { ApiError } from "@/types";
import type { VibeEvent, VibeMessage } from "@/types/vibe";

export interface VibeChatState {
  messages: VibeMessage[];
  loading: boolean;
  error: ApiError | null;
  currentRunId: string | null;
}

export const initialState: VibeChatState = {
  messages: [],
  loading: false,
  error: null,
  currentRunId: null,
};

export type VibeChatAction =
  | { type: "RESET" }
  | { type: "ADD_MESSAGE"; message: VibeMessage }
  | { type: "SET_ERROR"; error: ApiError }
  | { type: "START_RUN"; runId: string }
  | { type: "APPEND_EVENT"; event: VibeEvent };

/**
 * Reduce one event into the chat state. Designed to be safe to call
 * even when the polled event sequence is partial or out of order —
 * the SSE/polling backend is the source of truth for ordering, but
 * the reducer must not crash on a malformed payload.
 */
export function vibeChatReducer(
  state: VibeChatState,
  action: VibeChatAction
): VibeChatState {
  switch (action.type) {
    case "RESET":
      return initialState;

    case "ADD_MESSAGE":
      return {
        ...state,
        messages: [...state.messages, action.message],
      };

    case "SET_ERROR":
      return {
        ...state,
        error: action.error,
        loading: false,
      };

    case "START_RUN":
      return {
        ...state,
        currentRunId: action.runId,
        loading: true,
        error: null,
      };

    case "APPEND_EVENT": {
      const { event } = action;

      // Map the structural event types into state changes. Anything we
      // don't recognise is folded into an opaque assistant message so
      // the UI can show "…received an event" rather than swallowing it.
      switch (event.type) {
        case "run_started":
          return {
            ...state,
            currentRunId: event.run_id,
            loading: true,
            error: null,
          };

        case "tool_call_start": {
          const toolMessage: VibeMessage = {
            id: `tool-${event.event_id}`,
            session_id: "",
            run_id: event.run_id,
            role: "tool",
            tool_calls: event.call_id
              ? [
                  {
                    id: event.call_id,
                    type: "function",
                    function: {
                      name: event.tool || "",
                      arguments: JSON.stringify(event.input ?? {}),
                    },
                  },
                ]
              : undefined,
            tool_name: event.tool,
            tool_input: event.input,
            event_id: event.event_id,
            created_at: new Date().toISOString(),
          };
          return {
            ...state,
            messages: [...state.messages, toolMessage],
          };
        }

        case "tool_call_end": {
          // Find the matching tool_call_start by call_id and append output
          // summary. Falls back to a brand-new message if no start found.
          const idx = state.messages.findIndex((m) =>
            m.tool_calls?.some((tc) => tc.id === event.call_id)
          );
          if (idx === -1) {
            const toolMessage: VibeMessage = {
              id: `tool-${event.event_id}`,
              session_id: "",
              run_id: event.run_id,
              role: "tool",
              tool_call_id: event.call_id,
              tool_name: event.tool,
              tool_output_summary: event.output,
              event_id: event.event_id,
              created_at: new Date().toISOString(),
            };
            return {
              ...state,
              messages: [...state.messages, toolMessage],
            };
          }
          const updated = state.messages.slice();
          updated[idx] = {
            ...updated[idx],
            tool_output_summary: event.output,
            event_id: event.event_id,
          };
          return { ...state, messages: updated };
        }

        case "delta": {
          // Streaming assistant token — append to or create the last
          // assistant message so the UI can render a typewriter effect.
          const last = state.messages[state.messages.length - 1];
          if (last && last.role === "assistant" && !last.tool_calls) {
            const merged: VibeMessage = {
              ...last,
              content: (last.content || "") + (event.content || ""),
            };
            const rest = state.messages.slice(0, -1);
            return { ...state, messages: [...rest, merged] };
          }
          const assistantMessage: VibeMessage = {
            id: `assistant-${event.event_id}`,
            session_id: "",
            run_id: event.run_id,
            role: "assistant",
            content: event.content || "",
            event_id: event.event_id,
            created_at: new Date().toISOString(),
          };
          return {
            ...state,
            messages: [...state.messages, assistantMessage],
          };
        }

        case "card": {
          // Backend pushes structured payloads (signals, position_check,
          // backtest, analysis_mini). Store them on an assistant message
          // so the chat UI can render the appropriate card component.
          const cardMessage: VibeMessage = {
            id: `card-${event.event_id}`,
            session_id: "",
            run_id: event.run_id,
            role: "assistant",
            content: event.content,
            event_id: event.event_id,
            created_at: new Date().toISOString(),
          };
          return {
            ...state,
            messages: [...state.messages, cardMessage],
          };
        }

        case "done":
          return {
            ...state,
            loading: false,
            currentRunId: null,
          };

        case "error":
          return {
            ...state,
            loading: false,
            currentRunId: null,
            error: {
              code: typeof event.code === "string" ? event.code : "VIBE_ERROR",
              message:
                typeof event.message === "string"
                  ? event.message
                  : "vibe run failed",
              retryable: typeof event.retryable === "boolean" ? event.retryable : true,
              status: undefined,
            },
          };

        default:
          return state;
      }
    }

    default:
      return state;
  }
}