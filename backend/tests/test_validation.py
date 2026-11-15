import pytest

from app.validation import (
    VideoProbe,
    check_text,
    check_v1_constraints,
    parse_ffprobe_json,
)


def vertical(**overrides) -> VideoProbe:
    """A file that should pass: 1080x1920, 30s, H.264 + AAC."""
    base = dict(
        width=1080, height=1920, duration_s=30.0, video_codec="h264", audio_codec="aac"
    )
    base.update(overrides)
    return VideoProbe(**base)


class TestV1Constraints:
    def test_accepts_canonical_vertical_clip(self):
        report = check_v1_constraints(vertical())
        assert report.ok
        assert report.warnings == []

    def test_rejects_landscape(self):
        report = check_v1_constraints(vertical(width=1920, height=1080))
        assert not report.ok
        assert "vertical" in report.problems[0]

    def test_rejects_square(self):
        report = check_v1_constraints(vertical(width=1080, height=1080))
        assert not report.ok

    @pytest.mark.parametrize("w,h", [(720, 1280), (1080, 1920), (540, 960)])
    def test_accepts_any_9_16_resolution(self, w, h):
        assert check_v1_constraints(vertical(width=w, height=h)).ok

    def test_rejects_portrait_but_wrong_aspect(self):
        # 4:5, a common Instagram feed ratio — portrait, but not 9:16.
        report = check_v1_constraints(vertical(width=1080, height=1350))
        assert not report.ok
        assert "9:16" in report.problems[0]

    def test_rejects_too_long(self):
        report = check_v1_constraints(vertical(duration_s=61.0))
        assert not report.ok
        assert "under 60s" in report.problems[0]

    def test_accepts_exactly_max_duration(self):
        assert check_v1_constraints(vertical(duration_s=60.0)).ok

    def test_rejects_too_short_for_instagram(self):
        report = check_v1_constraints(vertical(duration_s=1.5))
        assert not report.ok
        assert "Instagram" in report.problems[0]

    def test_rejects_non_h264_video(self):
        report = check_v1_constraints(vertical(video_codec="hevc"))
        assert not report.ok
        assert "H.264" in report.problems[0]

    def test_accepts_avc1_as_h264(self):
        assert check_v1_constraints(vertical(video_codec="avc1")).ok

    def test_rejects_non_aac_audio(self):
        report = check_v1_constraints(vertical(audio_codec="mp3"))
        assert not report.ok
        assert "AAC" in report.problems[0]

    def test_warns_but_allows_silent_video(self):
        report = check_v1_constraints(vertical(audio_codec=None))
        assert report.ok
        assert len(report.warnings) == 1
        assert "No audio track" in report.warnings[0]

    def test_reports_every_problem_at_once(self):
        # One round trip should surface everything wrong with the file.
        report = check_v1_constraints(
            vertical(width=1920, height=1080, duration_s=120.0, video_codec="hevc")
        )
        assert len(report.problems) == 3

    def test_unreadable_dimensions_short_circuit(self):
        report = check_v1_constraints(vertical(width=0, height=0))
        assert not report.ok
        assert len(report.problems) == 1


class TestTextConstraints:
    def test_accepts_normal_text(self):
        assert check_text("A title", "A caption").ok

    def test_requires_title_for_youtube(self):
        report = check_text("   ", "A caption")
        assert not report.ok
        assert "YouTube requires a title" in report.problems[0]

    def test_rejects_overlong_title(self):
        report = check_text("x" * 101, "")
        assert not report.ok

    def test_accepts_title_at_limit(self):
        assert check_text("x" * 100, "").ok

    def test_warns_on_overlong_caption_without_blocking(self):
        report = check_text("Title", "x" * 3000)
        assert report.ok  # a warning, not a block
        assert "truncated" in report.warnings[0]


class TestFfprobeParsing:
    def test_parses_streams_and_duration(self):
        payload = """
        {"streams": [
            {"codec_type": "video", "codec_name": "h264",
             "width": 1080, "height": 1920, "duration": "28.5"},
            {"codec_type": "audio", "codec_name": "aac"}
        ], "format": {"duration": "28.5"}}
        """
        probe = parse_ffprobe_json(payload)
        assert probe == VideoProbe(1080, 1920, 28.5, "h264", "aac")

    def test_falls_back_to_format_duration(self):
        payload = """
        {"streams": [{"codec_type": "video", "codec_name": "h264",
                      "width": 1080, "height": 1920}],
         "format": {"duration": "12.0"}}
        """
        probe = parse_ffprobe_json(payload)
        assert probe is not None
        assert probe.duration_s == 12.0
        assert probe.audio_codec is None

    def test_returns_none_without_video_stream(self):
        assert parse_ffprobe_json('{"streams": [{"codec_type": "audio"}]}') is None

    def test_returns_none_on_garbage(self):
        assert parse_ffprobe_json("not json") is None
