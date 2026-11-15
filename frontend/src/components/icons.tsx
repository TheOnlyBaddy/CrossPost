import { PLATFORM_LABELS, type Platform, type TargetState } from "../types";

/** Brand glyphs, drawn in currentColor so the wrapper controls the tint. */
const PLATFORM_PATHS: Record<Platform, string> = {
  youtube:
    "M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2C0 8.1 0 12 0 12s0 3.9.5 5.8a3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1C24 15.9 24 12 24 12s0-3.9-.5-5.8zM9.5 15.6V8.4l6.3 3.6-6.3 3.6z",
  instagram:
    "M12 2.2c3.2 0 3.6 0 4.9.1 1.2.1 1.8.2 2.2.4.6.2 1 .5 1.4.9.4.4.7.8.9 1.4.2.4.4 1 .4 2.2.1 1.3.1 1.7.1 4.9s0 3.6-.1 4.9c-.1 1.2-.2 1.8-.4 2.2-.2.6-.5 1-.9 1.4-.4.4-.8.7-1.4.9-.4.2-1 .4-2.2.4-1.3.1-1.7.1-4.9.1s-3.6 0-4.9-.1c-1.2-.1-1.8-.2-2.2-.4-.6-.2-1-.5-1.4-.9-.4-.4-.7-.8-.9-1.4-.2-.4-.4-1-.4-2.2-.1-1.3-.1-1.7-.1-4.9s0-3.6.1-4.9c.1-1.2.2-1.8.4-2.2.2-.6.5-1 .9-1.4.4-.4.8-.7 1.4-.9.4-.2 1-.4 2.2-.4 1.3-.1 1.7-.1 4.9-.1zm0 1.8c-3.1 0-3.5 0-4.8.1-.9 0-1.4.2-1.7.3-.4.2-.7.4-1 .7-.3.3-.5.6-.7 1-.1.3-.3.8-.3 1.7-.1 1.3-.1 1.7-.1 4.8s0 3.5.1 4.8c0 .9.2 1.4.3 1.7.2.4.4.7.7 1 .3.3.6.5 1 .7.3.1.8.3 1.7.3 1.3.1 1.7.1 4.8.1s3.5 0 4.8-.1c.9 0 1.4-.2 1.7-.3.4-.2.7-.4 1-.7.3-.3.5-.6.7-1 .1-.3.3-.8.3-1.7.1-1.3.1-1.7.1-4.8s0-3.5-.1-4.8c0-.9-.2-1.4-.3-1.7-.2-.4-.4-.7-.7-1-.3-.3-.6-.5-1-.7-.3-.1-.8-.3-1.7-.3-1.3-.1-1.7-.1-4.8-.1zm0 3.1a4.9 4.9 0 1 1 0 9.8 4.9 4.9 0 0 1 0-9.8zm0 8.1a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zm6.2-8.3a1.1 1.1 0 1 1-2.3 0 1.1 1.1 0 0 1 2.3 0z",
  facebook:
    "M24 12a12 12 0 1 0-13.9 11.9v-8.4H7.1V12h3V9.4c0-3 1.8-4.6 4.5-4.6 1.3 0 2.7.2 2.7.2v2.9h-1.5c-1.5 0-1.9.9-1.9 1.8V12h3.3l-.5 3.5h-2.8v8.4A12 12 0 0 0 24 12z",
};

export function PlatformIcon({
  platform,
  small = false,
}: {
  platform: Platform;
  small?: boolean;
}) {
  return (
    <span
      className={`pf pf-${platform}${small ? " pf-sm" : ""}`}
      title={PLATFORM_LABELS[platform]}
    >
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d={PLATFORM_PATHS[platform]} />
      </svg>
    </span>
  );
}

/**
 * One line-icon set: 24-unit grid, 1.5 stroke, currentColor. Everything that
 * is not a brand mark is drawn here so there is a single visual voice and a
 * single place to change it.
 */
const line = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function Glyph({
  size = 16,
  children,
}: {
  size?: number;
  children: React.ReactNode;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      {...line}
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const UploadIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <path d="M12 15V4m0 0L8 8m4-4 4 4" />
    <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
  </Glyph>
);

export const InboxIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <path d="M3 13h4l1.5 3h7L17 13h4" />
    <path d="M4.5 5.5h15L21 13v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4z" />
  </Glyph>
);

export const ExternalIcon = ({ size = 14 }: { size?: number }) => (
  <Glyph size={size}>
    <path d="M14 4h6v6M20 4l-8 8" />
    <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
  </Glyph>
);

export const ClockIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3 1.8" />
  </Glyph>
);

export const CheckIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M8.5 12.2l2.4 2.3 4.6-4.8" />
  </Glyph>
);

export const AlertIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <path d="M12 4.8 3.6 19h16.8L12 4.8z" />
    <path d="M12 10v3.6" />
    <path d="M12 16.4h.01" />
  </Glyph>
);

export const PlugIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <path d="M9 3.5v5M15 3.5v5" />
    <path d="M6.5 8.5h11v2.8a5.5 5.5 0 0 1-11 0V8.5z" />
    <path d="M12 16.8v3.7" />
  </Glyph>
);

export const ArrowUpIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 16V8.5m0 0L9 11.5M12 8.5l3 3" />
  </Glyph>
);

export const SpinnerIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <path d="M12 3.5v3.2M12 17.3v3.2M3.5 12h3.2M17.3 12h3.2M6 6l2.3 2.3M15.7 15.7 18 18M18 6l-2.3 2.3M8.3 15.7 6 18" />
  </Glyph>
);

export const SlashIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M6.8 17.2 17.2 6.8" />
  </Glyph>
);

export const TrashIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <path d="M4.5 7h15M9.5 7V4.8h5V7M7 7l.8 12.2h8.4L17 7" />
  </Glyph>
);

export const RetryIcon = ({ size }: { size?: number }) => (
  <Glyph size={size}>
    <path d="M20 12a8 8 0 1 1-2.6-5.9" />
    <path d="M20 4.5V9h-4.5" />
  </Glyph>
);

/** Google's own mark, in its own colours — this is sign-in, not YouTube. */
export function GoogleIcon({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path
        fill="#4285F4"
        d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.2 0 5.9-1.1 7.9-2.9l-3.9-3c-1.1.7-2.4 1.2-4 1.2-3.1 0-5.7-2.1-6.6-4.9H1.4v3.1A12 12 0 0 0 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.4 14.4a7.2 7.2 0 0 1 0-4.6V6.7H1.4a12 12 0 0 0 0 10.8l4-3.1z"
      />
      <path
        fill="#EA4335"
        d="M12 4.8c1.8 0 3.3.6 4.5 1.8l3.4-3.4A12 12 0 0 0 1.4 6.7l4 3.1C6.3 7 8.9 4.8 12 4.8z"
      />
    </svg>
  );
}

/** The glyph that belongs to each publish state, so a row reads at a glance. */
const STATE_GLYPHS: Record<
  TargetState,
  (p: { size?: number }) => React.ReactElement
> = {
  scheduled: ClockIcon,
  pending: ClockIcon,
  uploading: ArrowUpIcon,
  processing: SpinnerIcon,
  done: CheckIcon,
  failed: AlertIcon,
  not_configured: PlugIcon,
  canceled: SlashIcon,
};

export function StateIcon({
  state,
  size = 14,
}: {
  state: TargetState;
  size?: number;
}) {
  const Icon = STATE_GLYPHS[state];
  return <Icon size={size} />;
}
