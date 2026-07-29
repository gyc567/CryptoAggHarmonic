import type {
  AnalysisData,
  AnalyzeRequest,
  ApiError,
  ApiFailure,
  ApiResponse,
  FieldError,
  MarketsResponse,
} from "@/types";

const BASE = process.env.NEXT_PUBLIC_BACKEND_API_BASE || "http://127.0.0.1:5000";

/**
 * Build an ApiError from a parsed backend error body, falling back to a
 * generic shape when the body is missing or doesn't match the L3 contract.
 *
 * The backend's :class:`ErrorResponse` carries an `error` envelope plus an
 * optional `details: list[FieldError]` populated on 422 (parseable but
 * semantically rejected). 4xx responses without `details` get a `null`
 * details array so consumers can branch on `error.details` reliably.
 */
function toApiError(body: unknown, status: number): ApiError {
  const fallback: ApiError = {
    code: "HTTP_ERROR",
    message: `HTTP ${status}`,
    retryable: status >= 500,
    status,
    details: undefined,
  };
  if (!body || typeof body !== "object") return fallback;
  const obj = body as Record<string, unknown>;
  const err = obj.error as Record<string, unknown> | undefined;
  if (!err || typeof err !== "object") return fallback;
  const code = typeof err.code === "string" ? err.code : fallback.code;
  const message = typeof err.message === "string" ? err.message : fallback.message;
  const retryable = typeof err.retryable === "boolean" ? err.retryable : fallback.retryable;
  const requestId = typeof err.request_id === "string" ? err.request_id : undefined;
  const rawDetails = Array.isArray(obj.details) ? (obj.details as unknown[]) : undefined;
  const details = rawDetails
    ?.filter((d): d is Record<string, unknown> => !!d && typeof d === "object")
    .map<FieldError>((d) => ({
      loc: typeof d.loc === "string" ? d.loc : Array.isArray(d.loc) ? d.loc.map(String).join(".") : "",
      msg: typeof d.msg === "string" ? d.msg : "",
      type: typeof d.type === "string" ? d.type : "",
    }));
  return {
    code,
    message,
    retryable,
    status,
    request_id: requestId,
    details: details && details.length > 0 ? details : undefined,
  };
}

/**
 * Single-shot request wrapper. Always returns the parsed JSON envelope
 * (or an ApiFailure with the parsed error details) instead of throwing
 * for HTTP error codes. Network failures still throw so the hook can
 * surface a distinct "offline" UX.
 */
export async function request<T>(
  path: string,
  token: string | null,
  init?: RequestInit
): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "network error";
    const failure: ApiFailure = {
      success: false,
      error: { code: "NETWORK", message: msg, retryable: true, status: 0 },
    };
    return failure;
  }
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { raw: text };
    }
  }
  if (!res.ok) {
    const error = toApiError(body, res.status);
    const failure: ApiFailure = { success: false, error };
    return failure;
  }
  // Backend wraps success in {success: true, data: ...}; unwrap so callers
  // can treat success uniformly. If the body is not wrapped, fall back to
  // using it as-is (covers endpoints that haven't migrated yet).
  if (body && typeof body === "object" && "success" in body && "data" in body) {
    return body as ApiResponse<T>;
  }
  return { success: true, data: body as T };
}

export async function analyze(token: string | null, payload: AnalyzeRequest): Promise<ApiResponse<AnalysisData>> {
  return request<AnalysisData>("/api/analyze", token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getMarkets(token: string | null): Promise<ApiResponse<MarketsResponse>> {
  return request<MarketsResponse>("/api/markets", token);
}

export async function getHistory(token: string | null): Promise<ApiResponse<unknown>> {
  return request<unknown>("/api/history", token);
}

export async function getAnalysis(token: string | null, id: string): Promise<ApiResponse<unknown>> {
  return request<unknown>(`/api/analysis/${id}`, token);
}

export async function appendLocalHistory(item: { id: string; [key: string]: unknown }) {
  try {
    const stored = localStorage.getItem("ph_history");
    const history: unknown[] = stored ? JSON.parse(stored) : [];
    history.unshift(item);
    localStorage.setItem("ph_history", JSON.stringify(history.slice(0, 50)));
  } catch {
    // no-op in SSR
  }
}