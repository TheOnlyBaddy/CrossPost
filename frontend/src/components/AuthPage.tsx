import { useState } from "react";

import { ApiError, logIn, signUp } from "../api";
import { GoogleIcon, PlatformIcon } from "./icons";

/**
 * Sign in or create an account. One form, two modes — they ask for the same
 * two things, so a second page would only be a second place to get lost in.
 */
export function AuthPage({
  onSignedIn,
  setup,
}: {
  onSignedIn: () => void;
  setup: { youtubeCredentials: boolean; metaCredentials: boolean };
}) {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const signingUp = mode === "up";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      if (signingUp) await signUp(email.trim(), password);
      else await logIn(email.trim(), password);
      onSignedIn();
    } catch (err) {
      setProblem(
        err instanceof ApiError ? err.message : "Something went wrong. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <div className="auth-card card">
        <div className="auth-head">
          <img src="/favicon.svg" alt="" width={36} height={36} />
          <h1>Cross Post</h1>
          <p>Upload a video once, publish it to YouTube, Instagram and Facebook</p>
        </div>

        <div className="segmented auth-switch">
          <button
            type="button"
            aria-pressed={!signingUp}
            onClick={() => {
              setMode("in");
              setProblem(null);
            }}
          >
            Sign in
          </button>
          <button
            type="button"
            aria-pressed={signingUp}
            onClick={() => {
              setMode("up");
              setProblem(null);
            }}
          >
            Create account
          </button>
        </div>

        <div className="stack">
          <a
            className={`btn btn-block ${setup.youtubeCredentials ? "" : "disabled"}`}
            href={setup.youtubeCredentials ? "/api/login/google" : undefined}
          >
            <GoogleIcon />
            Continue with Google
          </a>
          <a
            className={`btn btn-block ${setup.metaCredentials ? "" : "disabled"}`}
            href={setup.metaCredentials ? "/api/login/meta" : undefined}
          >
            <PlatformIcon platform="facebook" small />
            Continue with Facebook
          </a>
        </div>

        <div className="or">or</div>

        <form className="auth-form" onSubmit={submit}>
          <label className="field">
            <span className="label">Email</span>
            <input
              className="input"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>

          <label className="field">
            <span className="label">Password</span>
            <input
              className="input"
              type="password"
              autoComplete={signingUp ? "new-password" : "current-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            {signingUp && <span className="hint">At least 8 characters</span>}
          </label>

          {problem && (
            <ul className="problem-list">
              <li>{problem}</li>
            </ul>
          )}

          <button
            type="submit"
            className="btn btn-primary btn-block"
            disabled={busy || !email.trim() || !password}
          >
            {busy ? "Working…" : signingUp ? "Create account" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
