/**
 * FT Strategy UI — API client
 *
 * Wraps Next.js fetch into typed, auth-aware calls.
 * Uses same {success, data} / {success, error} envelope as existing api.ts.
 * Auth token sourced from Supabase via useAuth().
 */

import type {
  FtStrategy,
  FtStrategyRun,
  BacktestResult,
  FtCapabilities,
  FtOrient,
  OrientEntry,
  CreateFtStrategyRequest,
  RefineRequest,
  FtStrategyEvent,
  FtStrategyExperiment,
  FtStrategyReport,
  FtStrategyInsight,
} from "@/types/ft-strategy";

const BASE = (process.env.NEXT_PUBLIC_API_BASE || "").replace(/\/$/, "");

// ─── Low-level fetch ───────────────────────────────────────────────────────

async function ftFetch<T>(
  path: string,
  opts?: RequestInit & { token?: string }
): Promise<T> {
  const { token, ...init } = opts ?? {};
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    let details: unknown | undefined;
    try {
      const body = await res.json();
      details = body?.details;
    } catch {
      // ignore parse failure
    }
    const msg = details
      ? JSON.stringify(details)
      : `HTTP ${res.status} ${res.statusText}`;
    throw new Error(msg);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ─── Capabilities (no auth) ────────────────────────────────────────────────

export async function getCapabilities(): Promise<FtCapabilities> {
  return ftFetch<FtCapabilities>("/api/ft-strategy/capabilities");
}

// ─── Orient (no auth — orient is per-user, auth optional) ────────────────

export async function getOrient(token?: string): Promise<FtOrient> {
  return ftFetch<FtOrient>("/api/ft-strategy/orient", { token });
}

export async function getStrategyOrient(
  id: string,
  token?: string
): Promise<OrientEntry> {
  return ftFetch<OrientEntry>(`/api/ft-strategy/${id}/orient`, { token });
}

// ─── Strategy CRUD ────────────────────────────────────────────────────────

export async function listStrategies(
  userId: string,
  token: string,
  opts?: { status?: string; limit?: number }
): Promise<FtStrategy[]> {
  const params = new URLSearchParams({ user_id: userId });
  if (opts?.status) params.set("status", opts.status);
  if (opts?.limit) params.set("limit", String(opts.limit));
  return ftFetch<FtStrategy[]>(`/api/ft-strategies?${params}`, { token });
}

export async function getStrategy(
  id: string,
  token: string
): Promise<FtStrategy> {
  return ftFetch<FtStrategy>(`/api/ft-strategies/${id}`, { token });
}

export async function createStrategy(
  body: CreateFtStrategyRequest,
  token: string
): Promise<FtStrategy> {
  return ftFetch<FtStrategy>("/api/ft-strategies", {
    method: "POST",
    body: JSON.stringify(body),
    token,
  });
}

export async function deleteStrategy(
  id: string,
  token: string
): Promise<void> {
  await ftFetch<void>(`/api/ft-strategies/${id}`, { method: "DELETE", token });
}

// ─── Jobs ────────────────────────────────────────────────────────────────

export async function getJobs(
  id: string,
  token: string
): Promise<FtStrategyRun[]> {
  return ftFetch<FtStrategyRun[]>(
    `/api/ft-strategies/${id}/jobs`,
    { token }
  );
}

// ─── Refine ─────────────────────────────────────────────────────────────

export async function refineStrategy(
  id: string,
  body: RefineRequest,
  token: string
): Promise<FtStrategy> {
  return ftFetch<FtStrategy>(`/api/ft-strategies/${id}/refine`, {
    method: "POST",
    body: JSON.stringify(body),
    token,
  });
}

// ─── Backtest Report ────────────────────────────────────────────────────

export async function getBacktestReport(
  id: string,
  token: string
): Promise<BacktestResult> {
  return ftFetch<BacktestResult>(
    `/api/ft-strategies/${id}/backtest-report`,
    { token }
  );
}

// ─── Deploy ─────────────────────────────────────────────────────────────

export async function deployStrategy(
  id: string,
  token: string
): Promise<{ pr_url: string; status: string }> {
  return ftFetch<{ pr_url: string; status: string }>(
    `/api/ft-strategies/${id}/deploy`,
    { method: "POST", token }
  );
}

// ─── History ────────────────────────────────────────────────────────────

export async function getStrategyHistory(
  id: string,
  token: string
): Promise<{
  events: FtStrategyEvent[];
  experiments: FtStrategyExperiment[];
  reports: FtStrategyReport[];
  insights: FtStrategyInsight[];
}> {
  return ftFetch(
    `/api/ft-strategies/${id}/history`,
    { token }
  );
}

// ─── Preflight ──────────────────────────────────────────────────────────

export async function runPreflight(
  id: string,
  token: string
): Promise<{ passed: boolean; items: { check: string; passed: boolean; detail?: string }[] }> {
  return ftFetch(
    `/api/ft-strategies/${id}/preflight`,
    { method: "POST", token }
  );
}
