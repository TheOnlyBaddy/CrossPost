import { useState } from "react";

import { disconnect, getMetaPages, selectMetaPage } from "../api";
import {
  ALL_PLATFORMS,
  PLATFORM_LABELS,
  type Health,
  type MetaPage,
  type Platform,
} from "../types";
import { PlatformIcon } from "./icons";

interface Props {
  health: Health;
  showPagePicker: boolean;
  onChanged: () => void;
}

export function Connections({ health, showPagePicker, onChanged }: Props) {
  const [pages, setPages] = useState<MetaPage[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const byPlatform = Object.fromEntries(
    health.connections.map((c) => [c.platform, c]),
  );
  const connectedCount = health.connections.filter((c) => c.connected).length;

  async function loadPages() {
    setBusy(true);
    setError(null);
    try {
      setPages(await getMetaPages());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function choosePage(pageId: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await selectMetaPage(pageId);
      setNotice(result.warning);
      setPages(null);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDisconnect(platform: Platform) {
    setBusy(true);
    try {
      await disconnect(platform);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <span className="card-title">Accounts</span>
        <span className="count">{connectedCount} of 3</span>
      </div>

      <div className="card-body">
        <ul className="conn-list">
          {ALL_PLATFORMS.map((platform) => {
            const conn = byPlatform[platform];
            return (
              <li
                key={platform}
                className={`conn-row${conn?.connected ? "" : " off"}`}
              >
                <PlatformIcon platform={platform} />
                <span className="meta">
                  <span className="name">{PLATFORM_LABELS[platform]}</span>
                  <span className={`sub${conn?.connected ? " ok" : ""}`}>
                    {conn?.connected
                      ? (conn.displayName ?? conn.externalId ?? "connected")
                      : "Not connected"}
                  </span>
                </span>
                {conn?.connected && (
                  <button
                    className="btn btn-ghost btn-sm"
                    disabled={busy}
                    onClick={() => handleDisconnect(platform)}
                  >
                    Disconnect
                  </button>
                )}
              </li>
            );
          })}
        </ul>

        <div className="stack">
          <a
            className={`btn btn-ghost btn-block ${health.setup.youtubeCredentials ? "" : "disabled"}`}
            href={
              health.setup.youtubeCredentials ? "/api/auth/youtube/start" : undefined
            }
          >
            Connect YouTube
          </a>
          <a
            className={`btn btn-ghost btn-block ${health.setup.metaCredentials ? "" : "disabled"}`}
            href={health.setup.metaCredentials ? "/api/auth/meta/start" : undefined}
          >
            Connect Facebook &amp; Instagram
          </a>
        </div>

        <span className="hint">
          One Meta login covers both — Instagram publishes through the Page it is
          linked to.
        </span>

        {(showPagePicker || pages) && (
          <div className="page-picker">
            <h3>Choose the Page to post from</h3>
            {!pages && (
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={loadPages}>
                {busy ? "Loading…" : "List my Pages"}
              </button>
            )}
            {pages?.length === 0 && (
              <ul className="problem-list">
                <li>
                  No Pages came back. You must be an admin of at least one Facebook
                  Page, and <code>pages_show_list</code> must have been granted.
                </li>
              </ul>
            )}
            {pages && pages.length > 0 && (
              <ul className="page-list">
                {pages.map((page) => (
                  <li key={page.id}>
                    <span className="meta">
                      <strong>{page.name ?? page.id}</strong>
                      <span className="sub">
                        {page.instagramUsername
                          ? `Instagram: @${page.instagramUsername}`
                          : "No Instagram account linked"}
                      </span>
                    </span>
                    <button
                      className="btn btn-primary btn-sm"
                      disabled={busy}
                      onClick={() => choosePage(page.id)}
                    >
                      Use
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {notice && <span className="warning-text">{notice}</span>}
        {error && (
          <ul className="problem-list" style={{ marginTop: 12 }}>
            <li>{error}</li>
          </ul>
        )}
      </div>
    </section>
  );
}
