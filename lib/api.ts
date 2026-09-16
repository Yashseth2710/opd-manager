const BASE = "/api/v1";

export type ApiError = {
  code: string;
  message: string;
  fields?: Record<string, string>;
};

export class ApiFailure extends Error {
  readonly code: string;
  readonly status: number;
  readonly fields?: Record<string, string>;

  constructor(status: number, error: ApiError) {
    super(error.message);
    this.name = "ApiFailure";
    this.code = error.code;
    this.status = status;
    this.fields = error.fields;
  }
}

type Envelope<T> = { success: true; data: T } | { success: false; error: ApiError };

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
