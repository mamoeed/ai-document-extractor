import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError } from "../api";

interface Toast {
  id: number;
  kind: "error" | "success";
  title: string;
  message: string;
  error?: ApiError;
}

interface ToastApi {
  error: (title: string, err: unknown) => void;
  success: (title: string, message?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToasts(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToasts outside ToastProvider");
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setToasts((all) => all.filter((t) => t.id !== id)), []);

  const api = useMemo<ToastApi>(
    () => ({
      error: (title, err) => {
        const error = err instanceof ApiError ? err : undefined;
        const message = error ? error.detail : err instanceof Error ? err.message : String(err);
        console.error(title, err); // full object in the browser console for debugging
        setToasts((all) => [...all.slice(-4), { id: nextId.current++, kind: "error", title, message, error }]);
      },
      success: (title, message = "") => {
        const id = nextId.current++;
        setToasts((all) => [...all.slice(-4), { id, kind: "success", title, message }]);
        window.setTimeout(() => dismiss(id), 4000);
      },
    }),
    [dismiss],
  );

  // Surface otherwise-silent errors (debug aid): failed promises and script errors.
  useEffect(() => {
    const onRejection = (event: PromiseRejectionEvent) => api.error("Unexpected error", event.reason);
    const onError = (event: ErrorEvent) => api.error("Script error", event.error ?? event.message);
    window.addEventListener("unhandledrejection", onRejection);
    window.addEventListener("error", onError);
    return () => {
      window.removeEventListener("unhandledrejection", onRejection);
      window.removeEventListener("error", onError);
    };
  }, [api]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.kind}`}>
            <div className="toast-head">
              <strong>{toast.title}</strong>
              <button className="icon-button" onClick={() => dismiss(toast.id)} aria-label="Dismiss">
                ×
              </button>
            </div>
            {toast.message && <div className="toast-message">{toast.message}</div>}
            {toast.error && <ErrorDetails error={toast.error} />}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** Expandable technical details: HTTP status, error type, request id, validation errors, traceback. */
export function ErrorDetails({ error }: { error: ApiError }) {
  const hasMore = error.traceback || error.errors?.length || error.errorType || error.requestId;
  if (!hasMore) return null;
  return (
    <details className="error-details">
      <summary>Technical details</summary>
      <dl>
        <dt>HTTP status</dt>
        <dd>{error.status || "network"}</dd>
        {error.errorType && (
          <>
            <dt>Error type</dt>
            <dd>{error.errorType}</dd>
          </>
        )}
        {error.requestId && (
          <>
            <dt>Request id</dt>
            <dd>
              <code>{error.requestId}</code> <span className="muted">(grep the backend logs for it)</span>
            </dd>
          </>
        )}
      </dl>
      {error.errors && error.errors.length > 0 && (
        <ul className="validation-errors">
          {error.errors.map((e, i) => (
            <li key={i}>
              <code>{e.loc}</code>: {e.msg}
            </li>
          ))}
        </ul>
      )}
      {error.traceback && <pre className="traceback">{error.traceback}</pre>}
    </details>
  );
}
