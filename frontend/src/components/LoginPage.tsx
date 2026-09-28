import { useState, type FormEvent } from "react";
import { ApiError, api, setSession } from "../api";
import { ErrorDetails } from "./Toasts";

export function LoginPage({ notice, onLoggedIn }: { notice?: string; onLoggedIn: (username: string) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(username, password);
      setSession(result.access_token, result.username);
      onLoggedIn(result.username);
    } catch (err) {
      setError(err instanceof ApiError ? err : new ApiError({ status: 0, detail: String(err) }));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <h1>PO Extractor</h1>
        <p className="muted">Purchase order extraction &amp; master-data matching</p>
        {notice && <div className="notice">{notice}</div>}
        <label>
          Username
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus required />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && (
          <div className="form-error">
            {error.detail}
            <ErrorDetails error={error} />
          </div>
        )}
        <button className="button primary" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
