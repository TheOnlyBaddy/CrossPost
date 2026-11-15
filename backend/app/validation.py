"""v1 format gate.

v1 deliberately accepts exactly one shape of file: a vertical 9:16 MP4,
H.264 + AAC, under 60 seconds. That is the one format that lands natively on
all three platforms with zero transcoding — YouTube Short, Instagram Reel,
Facebook Reel. Accepting anything else means owning an ffmpeg pipeline, which
is the single biggest source of scope creep in a project like this.

Reject at the picker, not three API calls deep.

The pure checks below take an already-probed description of the file, so they
are testable without ffmpeg installed. `probe_with_ffprobe` is the optional
authoritative path.
"""

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

TARGET_ASPECT = 9 / 16  # 0.5625
ASPECT_TOLERANCE = 0.02

MAX_DURATION_S = 60.0
MIN_DURATION_S = 3.0  # Instagram Reels minimum. TODO verify against Meta docs.

ALLOWED_VIDEO_CODECS = {"h264", "avc1"}
ALLOWED_AUDIO_CODECS = {"aac"}

MAX_TITLE_CHARS = 100  # YouTube title limit. TODO verify.
MAX_CAPTION_CHARS = 2200  # Instagram caption limit, the tightest of the three. TODO verify.


@dataclass(frozen=True)
class VideoProbe:
    width: int
    height: int
    duration_s: float
    video_codec: str
    audio_codec: str | None = None


@dataclass
class ValidationReport:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def check_v1_constraints(probe: VideoProbe) -> ValidationReport:
    report = ValidationReport()

    if probe.width <= 0 or probe.height <= 0:
        report.problems.append("Could not read the video dimensions.")
        return report

    if probe.height <= probe.width:
        report.problems.append(
            f"v1 takes vertical video only. This is {probe.width}x{probe.height}."
        )
    else:
        aspect = probe.width / probe.height
        if abs(aspect - TARGET_ASPECT) > ASPECT_TOLERANCE:
            report.problems.append(
                f"Aspect ratio must be 9:16. This is {probe.width}x{probe.height} "
                f"({aspect:.3f} vs {TARGET_ASPECT:.3f})."
            )

    if probe.duration_s > MAX_DURATION_S:
        report.problems.append(
            f"v1 takes clips under {MAX_DURATION_S:.0f}s. This is {probe.duration_s:.1f}s."
        )
    elif probe.duration_s < MIN_DURATION_S:
        report.problems.append(
            f"Instagram rejects clips under {MIN_DURATION_S:.0f}s. This is {probe.duration_s:.1f}s."
        )

    if probe.video_codec.lower() not in ALLOWED_VIDEO_CODECS:
        report.problems.append(
            f"Video codec must be H.264. This is '{probe.video_codec}'."
        )

    if probe.audio_codec is None:
        report.warnings.append(
            "No audio track. Some platforms reject silent video. TODO verify per platform."
        )
    elif probe.audio_codec.lower() not in ALLOWED_AUDIO_CODECS:
        report.problems.append(f"Audio codec must be AAC. This is '{probe.audio_codec}'.")

    return report


def check_text(title: str, caption: str) -> ValidationReport:
    report = ValidationReport()

    if not title.strip():
        report.problems.append("YouTube requires a title.")
    elif len(title) > MAX_TITLE_CHARS:
        report.problems.append(
            f"Title is {len(title)} characters; YouTube allows {MAX_TITLE_CHARS}."
        )

    if len(caption) > MAX_CAPTION_CHARS:
        report.warnings.append(
            f"Caption is {len(caption)} characters. Instagram allows about "
            f"{MAX_CAPTION_CHARS}, so it will be truncated there but kept in full "
            f"on YouTube and Facebook."
        )

    return report


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def probe_with_ffprobe(path: Path) -> VideoProbe | None:
    """Authoritative probe. Returns None if ffprobe is not installed."""
    if not ffprobe_available():
        return None

    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        return None

    return parse_ffprobe_json(proc.stdout)


def parse_ffprobe_json(payload: str) -> VideoProbe | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        return None

    duration = video.get("duration") or (data.get("format") or {}).get("duration") or 0

    return VideoProbe(
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        duration_s=float(duration),
        video_codec=str(video.get("codec_name") or ""),
        audio_codec=str(audio["codec_name"]) if audio and audio.get("codec_name") else None,
    )
