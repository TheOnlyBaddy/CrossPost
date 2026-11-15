import { useCallback, useEffect, useState } from "react";

import { getHealth, listPosts, logOut } from "./api";
import { AuthPage } from "./components/AuthPage";
import { Composer } from "./components/Composer";
import { ConnectPage } from "./components/ConnectPage";
import { Connections } from "./components/Connections";
import { PostCard } from "./components/PostCard";
import { SetupBanner } from "./components/SetupBanner";
import { InboxIcon } from "./components/icons";
import { IN_FLIGHT_STATES, isUpcoming, type Health, type Post } from "./types";

/** While something is uploading, keep up with it. */
const ACTIVE_POLL_MS = 3000;
/** While something is merely waiting for its slot, check in occasionally. */
const IDLE_POLL_MS = 30000;
/** How close to its slot a post has to be to earn the fast cadence. */
const IMMINENT_MS = 120000;

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [posts, setPosts] = useState<Post[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [showPagePicker, setShowPagePicker] = useState(false);
  // Set once you choose to go to the composer with nothing connected, so the
  // connect step does not reappear on the next refresh.
  const [skippedConnect, setSkippedConnect] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const nextHealth = await getHealth();
      setHealth(nextHealth);
      setPosts(nextHealth.user ? await listPosts() : []);
      setError(null);
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message} — is the backend running on :8000?`
          : String(err),
      );
    }
  }, []);

  // Read the OAuth redirect back from the backend, then clean the URL so a
  // refresh does not re-show the message.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    const oauthError = params.get("error");

    const signedIn = params.get("signedIn");
    if (signedIn) setFlash(`Signed in with ${signedIn}`);

    if (connected) {
      setFlash(`Connected ${connected}.`);
      if (params.get("next") === "choose-page") setShowPagePicker(true);
    }
    if (oauthError) setError(oauthError);

    if (connected || oauthError || signedIn) {
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!flash) return;
    const id = window.setTimeout(() => setFlash(null), 6000);
    return () => window.clearTimeout(id);
  }, [flash]);

  const upcoming = posts
    .filter(isUpcoming)
    .sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt));
  const history = posts.filter((post) => !isUpcoming(post));

  const inFlight = posts.some((post) =>
    post.targets.some((target) => IN_FLIGHT_STATES.includes(target.state)),
  );
  // Something about to fire needs the fast cadence too, otherwise its
  // countdown sits visibly stale between refreshes.
  const msToSoonest = upcoming.length
    ? new Date(upcoming[0].scheduledAt).getTime() - Date.now()
    : Number.POSITIVE_INFINITY;
  const imminent = msToSoonest < IMMINENT_MS;

  const pollMs =
    inFlight || imminent
      ? ACTIVE_POLL_MS
      : upcoming.length > 0
        ? IDLE_POLL_MS
        : null;

  useEffect(() => {
    if (pollMs === null) return;
    const id = window.setInterval(() => void refresh(), pollMs);
    return () => window.clearInterval(id);
  }, [pollMs, refresh]);

  const status = error
    ? { tone: "", text: "Backend unreachable" }
    : inFlight
      ? { tone: "busy", text: "Publishing…" }
      : upcoming.length > 0
        ? { tone: "live", text: `${upcoming.length} scheduled` }
        : { tone: "live", text: "Ready" };

  if (health === null) {
    return (
      <main className="layout">
        <div className="skeleton" />
      </main>
    );
  }

  if (health.user === null) {
    return (
      <AuthPage onSignedIn={() => void refresh()} setup={health.setup} />
    );
  }

  const anyConnected = health.connections.some((c) => c.connected);
  if (!anyConnected && !skippedConnect) {
    return (
      <ConnectPage
        health={health}
        showPagePicker={showPagePicker}
        onChanged={() => {
          setShowPagePicker(false);
          void refresh();
        }}
        onSkip={() => setSkippedConnect(true)}
      />
    );
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <img className="brand-mark" src="/favicon.svg" alt="" width={30} height={30} />
            <div>
              <div className="brand-name">Cross Post</div>
              <span className="brand-tag">Upload once, publish everywhere</span>
            </div>
          </div>
          <div className="bar-right">
            <span className="status-pill">
              <span className={`pulse ${status.tone}`} aria-hidden="true" />
              {status.text}
            </span>
            <span className="who">{health.user.email}</span>
            <button
              className="btn btn-ghost btn-sm"
              onClick={async () => {
                await logOut();
                setPosts([]);
                setSkippedConnect(false);
                void refresh();
              }}
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="layout">
        <div className="col-main">
          <Composer
            health={health}
            onPosted={(post) => {
              setPosts((current) => [post, ...current]);
              if (post.warnings?.length) setFlash(post.warnings.join(" "));
            }}
          />

          {upcoming.length > 0 && (
            <section>
              <div className="section-head">
                <span className="section-title">Scheduled</span>
                <span className="count">{upcoming.length}</span>
              </div>
              {upcoming.map((post) => (
                <PostCard key={post.id} post={post} onChanged={() => void refresh()} />
              ))}
            </section>
          )}

          <section>
            <div className="section-head">
              <span className="section-title">Recent</span>
              {history.length > 0 && <span className="count">{history.length}</span>}
            </div>
            {history.length === 0 ? (
              <div className="empty">
                <span className="icon">
                  <InboxIcon />
                </span>
                <p>Nothing posted yet</p>
              </div>
            ) : (
              history.map((post) => (
                <PostCard key={post.id} post={post} onChanged={() => void refresh()} />
              ))
            )}
          </section>
        </div>

        <aside className="col-side">
          <Connections
            health={health}
            showPagePicker={showPagePicker}
            onChanged={() => {
              setShowPagePicker(false);
              void refresh();
            }}
          />
          <SetupBanner health={health} />
        </aside>
      </main>

      <div className="toasts" role="status" aria-live="polite">
        {flash && <div className="toast ok">{flash}</div>}
        {error && <div className="toast err">{error}</div>}
      </div>
    </>
  );
}
