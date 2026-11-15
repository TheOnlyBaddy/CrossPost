/**
 * Read dimensions and duration in the browser, before uploading anything.
 *
 * This is the "reject at the picker" check — it costs nothing and saves the
 * user a pointless upload. It cannot see codecs, so the server still runs
 * ffprobe as the authority on H.264/AAC.
 */

export interface ClientProbe {
  width: number;
  height: number;
  duration: number;
}

export function probeVideo(file: File): Promise<ClientProbe> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;

    const cleanup = () => URL.revokeObjectURL(url);

    video.onloadedmetadata = () => {
      const probe = {
        width: video.videoWidth,
        height: video.videoHeight,
        duration: video.duration,
      };
      cleanup();
      if (!probe.width || !probe.height || !Number.isFinite(probe.duration)) {
        reject(new Error("Could not read that file as a video."));
        return;
      }
      resolve(probe);
    };

    video.onerror = () => {
      cleanup();
      reject(new Error("Could not read that file as a video."));
    };

    video.src = url;
  });
}

const TARGET_ASPECT = 9 / 16;
const ASPECT_TOLERANCE = 0.02;

/** Mirrors the server's v1 gate for everything the browser can actually see. */
export function checkClientSide(
  probe: ClientProbe,
  limits: { maxDurationSeconds: number; minDurationSeconds: number },
): string[] {
  const problems: string[] = [];

  if (probe.height <= probe.width) {
    problems.push(
      `v1 takes vertical video only. This is ${probe.width}x${probe.height}.`,
    );
  } else {
    const aspect = probe.width / probe.height;
    if (Math.abs(aspect - TARGET_ASPECT) > ASPECT_TOLERANCE) {
      problems.push(
        `Aspect ratio must be 9:16. This is ${probe.width}x${probe.height}.`,
      );
    }
  }

  if (probe.duration > limits.maxDurationSeconds) {
    problems.push(
      `v1 takes clips under ${limits.maxDurationSeconds}s. This is ${probe.duration.toFixed(1)}s.`,
    );
  } else if (probe.duration < limits.minDurationSeconds) {
    problems.push(
      `Instagram rejects clips under ${limits.minDurationSeconds}s. This is ${probe.duration.toFixed(1)}s.`,
    );
  }

  return problems;
}
