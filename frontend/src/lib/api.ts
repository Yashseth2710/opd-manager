const BASE = "/api/v1";

export type ClinicChoice = { slug: string; name: string };

export type ApiError = {
  code: string;
  message: string;
  fields?: Record<string, string>;
  choices?: ClinicChoice[];
  retry_after_seconds?: number;
};

export class ApiFailure extends Error {
  readonly code: string;
  readonly status: number;
  readonly fields?: Record<string, string>;
  readonly choices?: ClinicChoice[];
  readonly retryAfterSeconds?: number;

  constructor(status: number, error: ApiError) {
    super(error.message);
    this.name = "ApiFailure";
    this.code = error.code;
    this.status = status;
    this.fields = error.fields;
    this.choices = error.choices;
    this.retryAfterSeconds = error.retry_after_seconds;
  }
}

type Envelope<T> = { success: true; data: T } | { success: false; error: ApiError };

/**
 * One refresh at a time. Several queries failing together would otherwise
 * each try to rotate the token, and only the first would succeed: the rest
 * would present a token that had just been spent, which the server reads as
 * a replay and answers by ending every session in the family.
 */
let refreshing: Promise<boolean> | null = null;

function refreshOnce(): Promise<boolean> {
  refreshing ??= fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

const NEVER_RETRIED = ["/auth/login", "/auth/refresh", "/auth/logout", "/auth/register"];

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await send<T>(path, init);
  } catch (error) {
    const expired =
      error instanceof ApiFailure &&
      error.status === 401 &&
      !NEVER_RETRIED.some((endpoint) => path.startsWith(endpoint));

    if (!expired) throw error;
    if (!(await refreshOnce())) throw error;
    return send<T>(path, init);
  }
}

async function send<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    // The request never reached a server: offline, DNS, connection refused.
    throw new ApiFailure(0, {
      code: "NETWORK_UNREACHABLE",
      message: "Could not reach the server. Check your connection and try again.",
    });
  }

  let body: Envelope<T>;
  try {
    body = (await response.json()) as Envelope<T>;
  } catch {
    // A non-JSON body almost always means something upstream answered
    // instead of the API: a proxy error page, a gateway timeout.
    throw new ApiFailure(response.status, {
      code: response.ok ? "INTERNAL_ERROR" : "SERVICE_UNAVAILABLE",
      message: response.ok
        ? "The server sent a response we could not read."
        : "The API is not responding right now. Try again in a moment.",
    });
  }

  if (!response.ok || !body.success) {
    const error = "error" in body ? body.error : null;
    throw new ApiFailure(
      response.status,
      error ?? { code: "INTERNAL_ERROR", message: "Something went wrong." },
    );
  }

  return body.data;
}

export function post<T>(path: string, payload: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(payload) });
}
