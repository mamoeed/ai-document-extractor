import type { FileDetail, FileSummary, Health, Json } from "./types";

const TOKEN_KEY = "po_token";
const USER_KEY = "po_user";

// JWT kept in memory, mirrored to sessionStorage so a page reload keeps the session.
let token: string | null = sessionStorage.getItem(TOKEN_KEY);
let unauthorizedHandler: (() => void) | null = null;

export function getSession(): { token: string; username: string } | null {
  const username = sessionStorage.getItem(USER_KEY);
  return token && username ? { token, username } : null;
}

export function setSession(newToken: string, username: string): void {
  token = newToken;
  sessionStorage.setItem(TOKEN_KEY, newToken);
  sessionStorage.setItem(USER_KEY, username);
}

export function clearSession(): void {
  token = null;
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
}

export function onUnauthorized(handler: () => void): void {
  unauthorizedHandler = handler;
}

export interface ValidationErrorItem {
  loc: string;
  msg: string;
  type?: string;
}

/** Error with everything the backend told us (traceback only in DEBUG mode). */
export class ApiError extends Error {
  status: number;
  detail: string;
  errorType?: string;
  requestId?: string;
  traceback?: string;
  errors?: ValidationErrorItem[];
  file?: FileDetail;

  constructor(init: {
    status: number;
    detail: string;
    errorType?: string;
    requestId?: string;
    traceback?: string;
    errors?: ValidationErrorItem[];
    file?: FileDetail;
  }) {
    super(init.detail);
    this.name = "ApiError";
    Object.assign(this, init);
    this.status = init.status;
    this.detail = init.detail;
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID") ?? undefined;
  const text = await response.text();
  try {
    const body = JSON.parse(text);
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : Array.isArray(body.detail)
          ? body.detail.map((d: { msg?: string }) => d.msg).join("; ")
          : `HTTP ${response.status}`;
    return new ApiError({
      status: response.status,
      detail,
      errorType: body.error_type,
      requestId: body.request_id ?? requestId,
      traceback: body.traceback,
      errors: body.errors,
      file: body.file,
    });
  } catch {
    // Not JSON: usually nginx (413 body too large, 502 backend down, 504 timeout).
    const hints: Record<number, string> = {
      413: "File too large for the proxy (nginx client_max_body_size)",
      502: "Backend unreachable - is the backend container running? (docker compose logs backend)",
      504: "Backend timed out - the model call took too long (see VLM_TIMEOUT_S / nginx proxy_read_timeout)",
    };
    return new ApiError({
      status: response.status,
      detail: hints[response.status] ?? `HTTP ${response.status} ${response.statusText}`,
      requestId,
      traceback: text ? text.slice(0, 2000) : undefined,
    });
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers });
  } catch (err) {
    throw new ApiError({ status: 0, detail: `Network error: ${(err as Error).message}` });
  }
  if (!response.ok) {
    const error = await toApiError(response);
    if (response.status === 401 && path !== "/auth/login") {
      clearSession();
      unauthorizedHandler?.();
    }
    throw error;
  }
  if (response.headers.get("content-type")?.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.blob()) as T;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; username: string }>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),
  // 503 still carries the JSON body describing which check failed.
  health: async (): Promise<Health> => {
    const response = await fetch("/api/health");
    try {
      return (await response.json()) as Health;
    } catch {
      throw new Error(`HTTP ${response.status} - backend unreachable?`);
    }
  },
  listFiles: () => request<FileSummary[]>("/files"),
  getFile: (id: string) => request<FileDetail>(`/files/${id}`),
  uploadFile: (file: File) => {
    const form = new FormData();
    form.append("file", file, file.name);
    return request<FileDetail>("/files", { method: "POST", body: form });
  },
  review: (id: string, order: Json) =>
    request<FileDetail>(`/files/${id}/review`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order }),
    }),
  originalBlob: (id: string) => request<Blob>(`/files/${id}/original`),
  deleteFile: (id: string) => request<unknown>(`/files/${id}`, { method: "DELETE" }),
};
