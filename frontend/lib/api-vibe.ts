/**
 * API wrapper for the vibe (conversational agent) endpoints.
 *
 * Backend: app/api/vibe_routes.py
 *   POST   /api/vibe/sessions                  auth required, JSON body
 *   GET    /api/vibe/sessions                  auth required, query params
 *   GET    /api/vibe/sessions/<id>             auth required
 *   DELETE /api/vibe/sessions/<id>             auth required
 *   POST   /api/vibe/sessions/<id>/messages    auth required, JSON body
 *   GET    /api/vibe/runs/<id>                 auth required
 *   GET    /api/vibe/runs/<id>/events          auth required, query params
 *   DELETE /api/vibe/runs/<id>                 auth required
 *   GET    /api/vibe/runs/<id>/trace           auth required
 *   POST   /api/vibe/tools/<tool_name>         auth required, JSON body
 *
 * Schema source of truth: app/domain/vibe_schemas.py and the helper
 * models in app/domain/vibe.py (VibeSession, VibeRun, VibeEvent, ...).
 *
 * This file was missing from the original commit that introduced
 * ``hooks/use-vibe.ts`` — the hook imported a non-existent module,
 * which surfaced as a Next.js dev compile error and broke ``/vibe``
 * (and consequently every page because Next.js fails the whole
 * webpack graph when any route's import cannot be resolved).
 */

import { request } from "@/lib/api";
import type { ApiResponse } from "@/types";
import type {
  CreateSessionRequest,
  PollEventsResponse,
  SendMessageRequest,
  SendMessageResponse,
  VibeSession,
} from "@/types/vibe";

// --- Sessions --------------------------------------------------------------

export function createVibeSession(
  token: string | null,
  payload: CreateSessionRequest
): Promise<ApiResponse<VibeSession>> {
  return request<VibeSession>("/api/vibe/sessions", token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listVibeSessions(
  token: string | null,
  params: { limit?: number; offset?: number } = {}
): Promise<ApiResponse<{ items: VibeSession[]; total: number }>> {
  const usp = new URLSearchParams();
  if (params.limit !== undefined) usp.set("limit", String(params.limit));
  if (params.offset !== undefined) usp.set("offset", String(params.offset));
  const qs = usp.toString();
  return request<{ items: VibeSession[]; total: number }>(
    `/api/vibe/sessions${qs ? `?${qs}` : ""}`,
    token
  );
}

export function getVibeSession(
  token: string | null,
  sessionId: string
): Promise<ApiResponse<VibeSession>> {
  return request<VibeSession>(`/api/vibe/sessions/${sessionId}`, token);
}

export function deleteVibeSession(
  token: string | null,
  sessionId: string
): Promise<ApiResponse<{ id: string; status: string }>> {
  return request<{ id: string; status: string }>(
    `/api/vibe/sessions/${sessionId}`,
    token,
    { method: "DELETE" }
  );
}

// --- Messages / Runs -------------------------------------------------------

export function sendVibeMessage(
  token: string | null,
  sessionId: string,
  payload: SendMessageRequest
): Promise<ApiResponse<SendMessageResponse>> {
  return request<SendMessageResponse>(
    `/api/vibe/sessions/${sessionId}/messages`,
    token,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );
}

export function pollVibeEvents(
  token: string | null,
  runId: string,
  afterEventId?: string
): Promise<ApiResponse<PollEventsResponse>> {
  const usp = new URLSearchParams();
  if (afterEventId) usp.set("after", afterEventId);
  const qs = usp.toString();
  return request<PollEventsResponse>(
    `/api/vibe/runs/${runId}/events${qs ? `?${qs}` : ""}`,
    token
  );
}

export function cancelVibeRun(
  token: string | null,
  runId: string
): Promise<ApiResponse<{ id: string; status: string }>> {
  return request<{ id: string; status: string }>(
    `/api/vibe/runs/${runId}`,
    token,
    { method: "DELETE" }
  );
}