// Customer API client (Detailed Design 4.1): same-origin `/api/v1`, session cookie, CSRF
// header on unsafe methods, and the error body `{error: {code, message, details}}`.

const BASE = "/api/v1";
const CSRF_COOKIE = "__Host-tl_csrf";
const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
  }

  /** True when a higher plan unlocks this (403 `plan_required`, FR-SUB-12). */
  get needsUpgrade(): boolean {
    return this.code === "plan_required";
  }
}

function csrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${CSRF_COOKIE}=`));
  return hit ? decodeURIComponent(hit.slice(CSRF_COOKIE.length + 1)) : null;
}

export type Query = Record<string, string | number | boolean | string[] | null | undefined>;

export function queryString(query: Query = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
    else params.append(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

export async function api<T>(
  path: string,
  options: { method?: string; query?: Query; body?: unknown } = {},
): Promise<T> {
  const method = options.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (UNSAFE.has(method)) {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  const res = await fetch(`${BASE}${path}${queryString(options.query)}`, {
    method,
    headers,
    credentials: "same-origin",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(
      res.status,
      err.code ?? "http_error",
      err.message ?? res.statusText,
      err.details,
    );
  }
  return data as T;
}
