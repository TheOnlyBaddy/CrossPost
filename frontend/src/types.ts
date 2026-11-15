export type Platform = "youtube" | "instagram" | "facebook";

export type TargetState =
  | "scheduled"
  | "pending"
  | "uploading"
  | "processing"
  | "done"
  | "failed"
  | "not_configured"
  | "canceled";

export const PLATFORM_LABELS: Record<Platform, string> = {
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
};

export const ALL_PLATFORMS: Platform[] = ["youtube", "instagram", "facebook"];

export const TERMINAL_STATES: TargetState[] = [
  "done",
  "failed",
  "not_configured",
  "canceled",
];

/** Actively being worked on — poll quickly while any target is here. */
export const IN_FLIGHT_STATES: TargetState[] = [
  "pending",
  "uploading",
  "processing",
];

export const RETRYABLE_STATES: TargetState[] = ["failed", "not_configured"];

export const CANCELABLE_STATES: TargetState[] = ["scheduled"];

export interface Target {
  platform: Platform;
  state: TargetState;
  url: string | null;
  externalId: string | null;
  error: string | null;
  updatedAt: string;
}

export interface Post {
  id: string;
  createdAt: string;
  /** Canonical UTC ISO. For "post now" this is the creation time. */
  scheduledAt: string;
  canceledAt: string | null;
  title: string;
  caption: string;
  filename: string;
  targets: Target[];
  warnings?: string[];
}

export function isUpcoming(post: Post): boolean {
  return post.targets.some((t) => t.state === "scheduled");
}

export interface Connection {
  platform: Platform;
  connected: boolean;
  displayName: string | null;
  externalId: string | null;
}

export interface User {
  id: string;
  email: string;
}

export interface Health {
  ok: boolean;
  /** null until signed in. Everything below `connections` is per user. */
  user: User | null;
  setup: {
    youtubeCredentials: boolean;
    metaCredentials: boolean;
    tokenEncryptionKey: boolean;
    ffprobe: boolean;
    publicBaseUrl: string;
    publicBaseUrlIsHttps: boolean;
    instagramCanFetchMedia: boolean;
    youtubePrivacyStatus: string;
    schedulerPollSeconds: number;
    schedulerMaxCatchupMinutes: number;
  };
  connections: Connection[];
  limits: {
    maxDurationSeconds: number;
    minDurationSeconds: number;
    maxTitleChars: number;
    maxCaptionChars: number;
  };
}

export interface MetaPage {
  id: string;
  name: string | null;
  instagramId: string | null;
  instagramUsername: string | null;
}
