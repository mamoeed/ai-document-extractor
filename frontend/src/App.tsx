import { Component, useEffect, useState, type ErrorInfo, type ReactNode } from "react";
import { clearSession, getSession, onUnauthorized } from "./api";
import { LoginPage } from "./components/LoginPage";
import { MainPage } from "./components/MainPage";

export function App() {
  const [session, setSession] = useState(getSession());
  const [notice, setNotice] = useState<string | undefined>();

  useEffect(() => {
    onUnauthorized(() => {
      setSession(null);
      setNotice("Your session has expired - please sign in again.");
    });
  }, []);

  if (!session) {
    return (
      <LoginPage
        notice={notice}
        onLoggedIn={() => {
          setSession(getSession());
          setNotice(undefined);
        }}
      />
    );
  }
  return (
    <ErrorBoundary>
      <MainPage
        username={session.username}
        onLogout={() => {
          clearSession();
          setSession(null);
          setNotice("You have been signed out.");
        }}
      />
    </ErrorBoundary>
  );
}

/** Shows render errors (with stack) instead of a blank page. */
class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null; stack: string }> {
  state = { error: null as Error | null, stack: "" };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI crashed", error, info);
    this.setState({ stack: `${error.stack ?? ""}\n\nComponent stack:${info.componentStack ?? ""}` });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="content">
        <div className="error-box">
          <h2>Something went wrong in the page</h2>
          <p>{this.state.error.message}</p>
          <button className="button" onClick={() => window.location.reload()}>
            Reload
          </button>
          <pre className="traceback">{this.state.stack}</pre>
        </div>
      </div>
    );
  }
}
