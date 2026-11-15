import { useEffect, useRef, useState } from "react";

import { ApiError, createPost } from "../api";
import { earliestSelectable, localInputToUtcIso } from "../datetime";
import { checkClientSide, probeVideo, type ClientProbe } from "../probeVideo";
import {
  ALL_PLATFORMS,
  PLATFORM_LABELS,
  type Health,
  type Platform,
  type Post,
} from "../types";
import { PlatformIcon, UploadIcon } from "./icons";

interface Props {
  health: Health;
  onPosted: (post: Post) => void;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

export function Composer({ health, onPosted }: Props) {
  const { limits } = health;

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [probe, setProbe] = useState<ClientProbe | null>(null);
  const [fileProblems, setFileProblems] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [targets, setTargets] = useState<Platform[]>(ALL_PLATFORMS);
  const [when, setWhen] = useState<"now" | "later">("now");
  const [scheduledLocal, setScheduledLocal] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // The preview URL outlives the probe, so it gets its own lifecycle.
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  async function handleFile(selected: File | null) {
    setPreviewUrl((current) => {
      if (current) URL.revokeObjectURL(current);
      return selected ? URL.createObjectURL(selected) : null;
    });
    setFile(selected);
    setProbe(null);
    setFileProblems([]);
    setProblems([]);
    if (!selected) return;

    try {
      const result = await probeVideo(selected);
      setProbe(result);
      setFileProblems(checkClientSide(result, limits));
    } catch (err) {
      setFileProblems([err instanceof Error ? err.message : String(err)]);
    }
  }

  function clearFile() {
    void handleFile(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(event: React.DragEvent) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) void handleFile(dropped);
  }

  function toggleTarget(platform: Platform) {
    setTargets((current) =>
      current.includes(platform)
        ? current.filter((p) => p !== platform)
        : ALL_PLATFORMS.filter((p) => current.includes(p) || p === platform),
    );
  }

  const captionTooLong = caption.length > limits.maxCaptionChars;
  const titleTooLong = title.length > limits.maxTitleChars;

  const scheduledIso = when === "later" ? localInputToUtcIso(scheduledLocal) : "";
  const scheduleProblem =
    when === "later"
      ? !scheduledLocal
        ? "Pick a date and time."
        : !scheduledIso
          ? "That is not a valid date and time."
          : new Date(scheduledIso).getTime() <= Date.now()
            ? "That time has already passed."
            : null
      : null;

  const canSubmit =
    file !== null &&
    fileProblems.length === 0 &&
    title.trim().length > 0 &&
    !titleTooLong &&
    targets.length > 0 &&
    scheduleProblem === null &&
    progress === null;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file || !canSubmit) return;

    setProblems([]);
    setProgress(0);
    try {
      const post = await createPost(
        { file, title, caption, targets, scheduledAt: scheduledIso },
        setProgress,
      );
      onPosted(post);
      clearFile();
      setTitle("");
      setCaption("");
      setTargets(ALL_PLATFORMS);
      setWhen("now");
      setScheduledLocal("");
    } catch (err) {
      setProblems(
        err instanceof ApiError && err.problems.length
          ? err.problems
          : [err instanceof Error ? err.message : String(err)],
      );
    } finally {
      setProgress(null);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <span className="card-title">New post</span>
        <span className="count">
          {targets.length} {targets.length === 1 ? "platform" : "platforms"}
        </span>
      </div>

      <form className="card-body" onSubmit={submit}>
        <div className="field">
          <span className="label">Video</span>

          {!file ? (
            <div
              className={`dropzone${dragging ? " dragging" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <input
                ref={inputRef}
                type="file"
                accept="video/mp4,video/quicktime"
                onChange={(e) => void handleFile(e.target.files?.[0] ?? null)}
              />
              <span className="icon">
                <UploadIcon />
              </span>
              <span className="primary-text">Drop a video, or click to choose</span>
              <span className="secondary-text">
                Vertical 9:16 MP4, H.264 + AAC, {limits.minDurationSeconds}–
                {limits.maxDurationSeconds}s — the one format all three platforms take
                without transcoding
              </span>
            </div>
          ) : (
            <div className="preview">
              {previewUrl && <video src={previewUrl} muted playsInline preload="metadata" />}
              <div className="preview-meta">
                <span className="preview-name">{file.name}</span>
                <div className="chips">
                  {probe && (
                    <>
                      <span className="chip">
                        {probe.width}×{probe.height}
                      </span>
                      <span className="chip">{formatDuration(probe.duration)}</span>
                    </>
                  )}
                  <span className="chip">{formatBytes(file.size)}</span>
                  {probe && fileProblems.length === 0 && (
                    <span className="chip good">Ready</span>
                  )}
                </div>
              </div>
              <button type="button" className="btn btn-ghost btn-sm" onClick={clearFile}>
                Remove
              </button>
            </div>
          )}
        </div>

        {fileProblems.length > 0 && (
          <ul className="problem-list">
            {fileProblems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}

        <label className="field">
          <span className="label">
            Title
            <span className={titleTooLong ? "counter over" : "counter"}>
              {title.length}/{limits.maxTitleChars}
            </span>
          </span>
          <input
            className="input"
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Used as the YouTube title"
          />
          <span className="hint">
            YouTube requires a title. Instagram and Facebook do not use it.
          </span>
        </label>

        <label className="field">
          <span className="label">
            Caption
            <span className={captionTooLong ? "counter over" : "counter"}>
              {caption.length}/{limits.maxCaptionChars}
            </span>
          </span>
          <textarea
            className="textarea"
            rows={4}
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder="YouTube description, Instagram caption, Facebook post text"
          />
          {captionTooLong && (
            <span className="warning-text">
              Over Instagram&rsquo;s {limits.maxCaptionChars}-character limit, so it
              will be truncated there. YouTube and Facebook keep the full text.
            </span>
          )}
        </label>

        <fieldset className="field">
          <span className="label">Post to</span>
          <div className="pf-toggles">
            {ALL_PLATFORMS.map((platform) => {
              const on = targets.includes(platform);
              return (
                <label
                  key={platform}
                  className={`pf-toggle${on ? " on" : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => toggleTarget(platform)}
                  />
                  <PlatformIcon platform={platform} small />
                  {PLATFORM_LABELS[platform]}
                </label>
              );
            })}
          </div>
        </fieldset>

        <fieldset className="field">
          <span className="label">When</span>
          <div className="segmented">
            <button
              type="button"
              aria-pressed={when === "now"}
              onClick={() => setWhen("now")}
            >
              Post now
            </button>
            <button
              type="button"
              aria-pressed={when === "later"}
              onClick={() => {
                setWhen("later");
                if (!scheduledLocal) setScheduledLocal(earliestSelectable());
              }}
            >
              Schedule
            </button>
          </div>

          {when === "later" && (
            <>
              <div style={{ marginTop: 12 }}>
                <input
                  className="datetime"
                  type="datetime-local"
                  value={scheduledLocal}
                  min={earliestSelectable()}
                  onChange={(e) => setScheduledLocal(e.target.value)}
                />
              </div>
              <span className="hint">
                Your local time ({Intl.DateTimeFormat().resolvedOptions().timeZone}).
                Stored in UTC. The server must be running at that moment — if it
                misses the slot by more than{" "}
                {health.setup.schedulerMaxCatchupMinutes} minutes the post fails
                rather than going out late.
              </span>
            </>
          )}

          {scheduleProblem && <span className="warning-text">{scheduleProblem}</span>}
        </fieldset>

        {problems.length > 0 && (
          <ul className="problem-list">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        )}

        {progress !== null && (
          <div className="progress">
            <div className="bar" style={{ width: `${Math.round(progress * 100)}%` }} />
            <span>{Math.round(progress * 100)}% uploaded</span>
          </div>
        )}

        <button type="submit" className="btn btn-primary btn-block" disabled={!canSubmit}>
          {progress !== null
            ? "Uploading…"
            : when === "later"
              ? `Schedule for ${targets.length} ${targets.length === 1 ? "platform" : "platforms"}`
              : `Post to ${targets.length} ${targets.length === 1 ? "platform" : "platforms"}`}
        </button>
      </form>
    </section>
  );
}
