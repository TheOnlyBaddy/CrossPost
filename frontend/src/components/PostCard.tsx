import { useState } from "react";

import { cancelPost, retryTarget } from "../api";
import { formatAbsolute, formatRelative } from "../datetime";
import {
  ALL_PLATFORMS,
  CANCELABLE_STATES,
  PLATFORM_LABELS,
  RETRYABLE_STATES,
  isUpcoming,
  type Platform,
  type Post,
  type TargetState,
} from "../types";
import { ExternalIcon, PlatformIcon, RetryIcon, StateIcon } from "./icons";

const STATE_LABELS: Record<TargetState, string> = {
  scheduled: "Scheduled",
  pending: "Queued",
  uploading: "Uploading",
  processing: "Processing",
  done: "Live",
  failed: "Failed",
  not_configured: "Not set up",
  canceled: "Canceled",
};

/**
 * Every platform gets its own row, its own error, and its own retry button.
 *
 * Partial success is the normal case here — YouTube succeeding while Instagram
 * fails is routine — so there is deliberately no single combined status for
 * the post as a whole.
 */
export function PostCard({ post, onChanged }: { post: Post; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);

  const upcoming = isUpcoming(post);
  const cancelable = post.targets.some((t) => CANCELABLE_STATES.includes(t.state));

  // The API returns targets alphabetically; show them in the same order as the
  // picker above so the eye does not have to re-learn the list per card.
  const orderedTargets = [...post.targets].sort(
    (a, b) =>
      ALL_PLATFORMS.indexOf(a.platform) - ALL_PLATFORMS.indexOf(b.platform),
  );

  async function handleRetry(platform: Platform) {
    setBusy(platform);
    try {
      await retryTarget(post.id, platform);
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  async function handleCancel() {
    setBusy("cancel");
    try {
      await cancelPost(post.id);
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  return (
    <article className={`card post ${upcoming ? "upcoming" : ""}`}>
      <header className="post-head">
        <h3 className="post-title">{post.title}</h3>
        <div className="post-when">
          <time dateTime={post.scheduledAt}>{formatAbsolute(post.scheduledAt)}</time>
          {upcoming && (
            <span className="relative">{formatRelative(post.scheduledAt)}</span>
          )}
        </div>
        {cancelable && (
          <button
            className="btn btn-ghost btn-sm"
            disabled={busy !== null}
            onClick={handleCancel}
          >
            {busy === "cancel" ? "Cancelling…" : "Cancel"}
          </button>
        )}
      </header>

      <ul className="target-list">
        {orderedTargets.map((target) => (
          <li key={target.platform}>
            <div className="target-main">
              <PlatformIcon platform={target.platform} small />
              <span className="target-name">{PLATFORM_LABELS[target.platform]}</span>
              <span className={`badge ${target.state}`}>
                <StateIcon state={target.state} />
                {STATE_LABELS[target.state]}
              </span>
              <span className="spacer" />
              {target.url && (
                <a
                  className="btn btn-ghost btn-sm"
                  href={target.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  View <ExternalIcon />
                </a>
              )}
              {RETRYABLE_STATES.includes(target.state) && (
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={busy !== null}
                  onClick={() => handleRetry(target.platform)}
                >
                  <RetryIcon size={13} />
                  {busy === target.platform ? "Retrying…" : "Retry"}
                </button>
              )}
            </div>
            {target.error && <p className="target-error">{target.error}</p>}
          </li>
        ))}
      </ul>
    </article>
  );
}
