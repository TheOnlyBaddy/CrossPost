import type { Health } from "../types";
import { AlertIcon } from "./icons";

interface Item {
  /** What is wrong, in four or five words you can scan. */
  lead: string;
  /** The exact setting and what to do about it. */
  detail: string;
  severity: "blocker" | "warning";
}

/**
 * Says out loud what is not wired up yet, instead of letting the user find out
 * via an opaque platform error three API calls deep.
 *
 * Each row leads with the consequence and keeps the variable names underneath,
 * so the card scans as a list of problems rather than a wall of .env trivia.
 */
export function SetupBanner({ health }: { health: Health }) {
  const { setup } = health;
  const items: Item[] = [];

  if (!setup.tokenEncryptionKey) {
    items.push({
      lead: "No accounts can be connected",
      detail: "TOKEN_ENCRYPTION_KEY is not set in .env",
      severity: "blocker",
    });
  }
  if (!setup.youtubeCredentials) {
    items.push({
      lead: "YouTube unavailable",
      detail: "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in .env",
      severity: "blocker",
    });
  }
  if (!setup.metaCredentials) {
    items.push({
      lead: "Instagram and Facebook unavailable",
      detail: "META_APP_ID / META_APP_SECRET are not set in .env",
      severity: "blocker",
    });
  }
  if (!setup.instagramCanFetchMedia) {
    items.push({
      lead: "Instagram cannot reach your video",
      detail:
        `PUBLIC_BASE_URL is ${setup.publicBaseUrl}. Instagram fetches the video ` +
        "from that URL rather than accepting bytes, so it has to be public " +
        "HTTPS — use a Cloudflare Tunnel or ngrok in development",
      severity: "blocker",
    });
  }
  if (!setup.ffprobe) {
    items.push({
      lead: "Format checked in the browser only",
      detail:
        "ffprobe is not installed. Install ffmpeg for the authoritative codec check",
      severity: "warning",
    });
  }
  if (setup.youtubePrivacyStatus !== "public") {
    items.push({
      lead: `YouTube uploads will be ${setup.youtubePrivacyStatus}`,
      detail:
        "Change YOUTUBE_PRIVACY_STATUS once you know where you stand on the API compliance audit",
      severity: "warning",
    });
  }

  if (items.length === 0) return null;

  const blockers = items.filter((i) => i.severity === "blocker").length;

  return (
    <section className="card">
      <div className="card-head">
        <span className="card-title">Setup</span>
        <span className={`badge ${blockers ? "failed" : "not_configured"}`}>
          <AlertIcon size={13} />
          {blockers ? `${blockers} blocking` : "Warnings"}
        </span>
      </div>
      <div className="card-body">
        <ul className="setup-list">
          {items.map((item) => (
            <li key={item.lead} className={item.severity}>
              <span className="ico">
                <AlertIcon size={14} />
              </span>
              <span className="setup-text">
                <span className="lead">{item.lead}</span>
                <span className="detail">{item.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
