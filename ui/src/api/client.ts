// Shared fetch wrapper for every API call the SPA makes.
//
// Auth model (see app/routers/auth.py):
//   - Access tokens are short-lived JWTs (15 min), held only in memory by
//     AuthContext and attached here as `Authorization: Bearer <token>`.
//   - A 401 means the access token is missing/expired. On a 401 this
//     wrapper attempts exactly one POST /auth/ui-refresh (which relies on
//     the httpOnly refresh_token cookie sent automatically by the browser)
//     and retries the original request once with the new token. If the
//     refresh also fails, every in-flight/future call gives up and the
//     caller (AuthContext) is signaled to clear state and redirect to
//     /login.
//   - A 403 means the authenticated user's role is too low for this
//     action — never retried, surfaced to the caller as-is (RoleGate/UI
//     hiding is cosmetic; this is the real boundary).
//
// This module holds no React state itself — AuthContext registers callbacks
// so client.ts can read the current token and trigger a refresh/logout
// without importing React context machinery here.

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface AuthHooks {
  getAccessToken: () => string | null;
  // Performs POST /auth/ui-refresh, updates in-memory state on success,
  // and returns the new access token — or null if refresh failed.
  refreshAccessToken: () => Promise<string | null>;
  // Clears in-memory auth state and redirects to /login.
  onAuthFailure: () => void;
}

let authHooks: AuthHooks | null = null;

export function registerAuthHooks(hooks: AuthHooks): void {
  authHooks = hooks;
}

// FastAPI's default error shape is {"detail": "..."} for a plain string, or
// {"detail": [{"loc": [...], "msg": "...", "type": "..."}]} for pydantic
// validation errors (422). Normalize both into a single display string.
export function extractErrorMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => {
        if (
          entry &&
          typeof entry === "object" &&
          "msg" in entry &&
          typeof (entry as { msg: unknown }).msg === "string"
        ) {
          const loc =
            "loc" in entry && Array.isArray((entry as { loc: unknown[] }).loc)
              ? (entry as { loc: unknown[] }).loc.filter((p) => p !== "body").join(".")
              : undefined;
          return loc ? `${loc}: ${(entry as { msg: string }).msg}` : (entry as { msg: string }).msg;
        }
        return JSON.stringify(entry);
      })
      .join("; ");
  }
  if (detail && typeof detail === "object" && "detail" in detail) {
    return extractErrorMessage((detail as { detail: unknown }).detail);
  }
  return "request failed";
}

// Every resource module defines its own concrete "ListXParams" interface
// (e.g. ListJobsParams) with no index signature, and passes it straight
// through as `query`. TypeScript never considers a named interface
// assignable to a Record/mapped-type *value* position unless it has a
// matching index signature — no amount of generic constraining at the call
// site changes that, since the constraint check happens at the same
// structural boundary. So `query` is typed as `object` here (not
// Record<string, ...>): the actual key/value walk happens at runtime via
// Object.entries, which works identically regardless of the static type,
// and each resource module's exported params interface remains the single
// source of truth for what fields exist.
interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  // Query params are appended as ?key=value, skipping null/undefined/"".
  query?: object;
  // Set when the caller sends form-encoded data (only ui-login today).
  form?: URLSearchParams;
  // Skip attaching a bearer token (unused today — every non-auth endpoint
  // requires auth — but kept for completeness/symmetry).
  skipAuth?: boolean;
}

function buildUrl(path: string, query?: object): string {
  const url = new URL(path, window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query as Record<string, unknown>)) {
      if (value !== null && value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.pathname + url.search;
}

async function rawRequest(path: string, options: RequestOptions, token: string | null): Promise<Response> {
  const headers: Record<string, string> = {};
  if (!options.skipAuth && token) {
    headers.Authorization = `Bearer ${token}`;
  }

  let body: BodyInit | undefined;
  if (options.form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    body = options.form;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  return fetch(buildUrl(path, options.query), {
    method: options.method ?? "GET",
    headers,
    body,
    // Same-origin app; cookies (the httpOnly refresh_token) are sent
    // automatically for same-origin requests without needing
    // credentials: "include", but set it explicitly so the dev-server
    // proxy path (different port, but same-origin-shaped) behaves
    // identically to production.
    credentials: "same-origin",
  });
}

/**
 * Performs an authenticated request and returns the parsed JSON body.
 * On 401, attempts one silent refresh + retry; on repeated failure,
 * triggers onAuthFailure() and throws.
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = authHooks?.getAccessToken() ?? null;
  let response = await rawRequest(path, options, token);

  if (response.status === 401 && !options.skipAuth && authHooks) {
    const newToken = await authHooks.refreshAccessToken();
    if (newToken) {
      response = await rawRequest(path, options, newToken);
    }
  }

  if (response.status === 401 && !options.skipAuth) {
    authHooks?.onAuthFailure();
    throw new ApiError(401, "session expired", "session expired");
  }

  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      // No JSON body (e.g. a 502 from an upstream proxy) — fall back to
      // status text.
      detail = response.statusText;
    }
    const message = extractErrorMessage(detail && typeof detail === "object" && "detail" in detail ? (detail as { detail: unknown }).detail : detail);
    throw new ApiError(response.status, detail, message);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/**
 * Like apiRequest, but returns the raw Response — used for endpoints that
 * return non-JSON bodies (the GPG key export, the audit-log CSV export).
 * Still carries the same 401-refresh-retry-once logic.
 */
export async function apiRequestRaw(path: string, options: RequestOptions = {}): Promise<Response> {
  const token = authHooks?.getAccessToken() ?? null;
  let response = await rawRequest(path, options, token);

  if (response.status === 401 && !options.skipAuth && authHooks) {
    const newToken = await authHooks.refreshAccessToken();
    if (newToken) {
      response = await rawRequest(path, options, newToken);
    }
  }

  if (response.status === 401 && !options.skipAuth) {
    authHooks?.onAuthFailure();
    throw new ApiError(401, "session expired", "session expired");
  }

  if (!response.ok) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = response.statusText;
    }
    const message = extractErrorMessage(detail && typeof detail === "object" && "detail" in detail ? (detail as { detail: unknown }).detail : detail);
    throw new ApiError(response.status, detail, message);
  }

  return response;
}

// Each resource module (repositories.ts, jobs.ts, ...) declares its own
// concrete "ListXParams" interface with no index signature — that's the
// natural, readable shape for a typed params object, and call sites
// shouldn't need to add an index signature or cast just to pass one
// through here. `object` accepts any such interface; the runtime behavior
// (Object.entries + String(value), see buildUrl above) works identically
// regardless of the nominal type.
export const api = {
  get: <T, Q extends object = object>(path: string, query?: Q) => apiRequest<T>(path, { method: "GET", query }),
  post: <T, Q extends object = object>(path: string, body?: unknown, query?: Q) =>
    apiRequest<T>(path, { method: "POST", body, query }),
  put: <T, Q extends object = object>(path: string, body?: unknown, query?: Q) =>
    apiRequest<T>(path, { method: "PUT", body, query }),
  delete: <T, Q extends object = object>(path: string, query?: Q) => apiRequest<T>(path, { method: "DELETE", query }),
};
