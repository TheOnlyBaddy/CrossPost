"""Scheduling: parsing the requested time, claiming due work, cancelling,
recovering from a crash, and refusing to publish something far too late.

No network: with no credentials configured every platform resolves to
not_configured, which exercises the same path a real publish takes.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
import mongomock
from cryptography.fernet import Fernet

from app.config import Settings
from app.models import Platform, PublishResult, TargetState
from app.schedule_input import MAX_FUTURE, parse_schedule
from app.scheduler import Scheduler
from app.store import Store, to_utc_iso

NOW = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return to_utc_iso(moment)


@pytest.fixture
def store(tmp_path) -> Store:
    return Store("mongodb://test", "test", Fernet.generate_key().decode(), client=mongomock.MongoClient())


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        token_encryption_key=Fernet.generate_key().decode(),
        google_client_id="",
        google_client_secret="",
        meta_app_id="",
        meta_app_secret="",
        scheduler_max_catchup_minutes=60,
    )


def make_post(store, tmp_path, when: datetime, targets=None) -> str:
    return store.create_post(
        user_id="user-1",
        title="T",
        caption="C",
        filename="x.mp4",
        media_path=tmp_path / "x.mp4",
        targets=targets or [Platform.YOUTUBE],
        scheduled_at=iso(when),
    )


class TestParseSchedule:
    def test_empty_means_now(self):
        result = parse_schedule("", now=NOW)
        assert result.ok
        assert result.moment == NOW

    def test_literal_now(self):
        assert parse_schedule("now", now=NOW).moment == NOW

    def test_accepts_z_suffix(self):
        result = parse_schedule("2026-11-14T18:30:00Z", now=NOW)
        assert result.ok
        assert result.moment == datetime(2026, 11, 14, 18, 30, tzinfo=timezone.utc)

    def test_accepts_offset_suffix(self):
        result = parse_schedule("2026-11-14T18:30:00+00:00", now=NOW)
        assert result.ok
        assert result.moment == datetime(2026, 11, 14, 18, 30, tzinfo=timezone.utc)

    def test_converts_a_non_utc_offset(self):
        # 18:30+05:30 is 13:00 UTC.
        result = parse_schedule("2026-11-14T18:30:00+05:30", now=NOW)
        assert result.ok
        assert result.moment == datetime(2026, 11, 14, 13, 0, tzinfo=timezone.utc)

    def test_naive_input_is_treated_as_utc(self):
        result = parse_schedule("2026-11-14T18:30:00", now=NOW)
        assert result.ok
        assert result.moment == datetime(2026, 11, 14, 18, 30, tzinfo=timezone.utc)

    def test_rejects_the_past(self):
        result = parse_schedule(iso(NOW - timedelta(hours=1)), now=NOW)
        assert not result.ok
        assert "in the past" in result.problem

    def test_tolerates_slight_clock_skew(self):
        # A few seconds in the past is just "now", not an error.
        result = parse_schedule(iso(NOW - timedelta(seconds=30)), now=NOW)
        assert result.ok
        assert result.moment == NOW

    def test_rejects_absurdly_far_future(self):
        result = parse_schedule(iso(NOW + MAX_FUTURE + timedelta(days=1)), now=NOW)
        assert not result.ok
        assert "more than a year" in result.problem

    def test_rejects_garbage(self):
        result = parse_schedule("next tuesday-ish", now=NOW)
        assert not result.ok
        assert "Could not read" in result.problem


class TestClaiming:
    def test_claims_a_due_target(self, store, tmp_path):
        post_id = make_post(store, tmp_path, NOW - timedelta(minutes=1))
        claimed = store.claim_due_targets(iso(NOW))
        assert claimed == [(post_id, Platform.YOUTUBE, "user-1")]
        assert store.get_post(post_id)["targets"][0]["state"] == "pending"

    def test_leaves_a_future_target_alone(self, store, tmp_path):
        post_id = make_post(store, tmp_path, NOW + timedelta(hours=2))
        assert store.claim_due_targets(iso(NOW)) == []
        assert store.get_post(post_id)["targets"][0]["state"] == "scheduled"

    def test_never_claims_the_same_target_twice(self, store, tmp_path):
        """A slow publish must not be picked up again by the next tick."""
        make_post(store, tmp_path, NOW - timedelta(minutes=1))
        assert len(store.claim_due_targets(iso(NOW))) == 1
        assert store.claim_due_targets(iso(NOW)) == []

    def test_skips_canceled_posts(self, store, tmp_path):
        post_id = make_post(store, tmp_path, NOW - timedelta(minutes=1))
        store.cancel_post(post_id, "user-1")
        assert store.claim_due_targets(iso(NOW)) == []

    def test_claims_every_platform_of_a_due_post(self, store, tmp_path):
        make_post(
            store,
            tmp_path,
            NOW - timedelta(minutes=1),
            targets=[Platform.YOUTUBE, Platform.INSTAGRAM, Platform.FACEBOOK],
        )
        assert len(store.claim_due_targets(iso(NOW))) == 3

    def test_oldest_schedule_runs_first(self, store, tmp_path):
        later = make_post(store, tmp_path, NOW - timedelta(minutes=1))
        earlier = make_post(store, tmp_path, NOW - timedelta(hours=3))
        claimed = store.claim_due_targets(iso(NOW))
        assert [post_id for post_id, _, _ in claimed] == [earlier, later]

    def test_string_comparison_is_chronological(self, store, tmp_path):
        """Timestamps are compared as strings in SQL, so the canonical format
        has to sort the same way time does — including across a year change."""
        make_post(store, tmp_path, datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc))
        make_post(store, tmp_path, datetime(2027, 1, 1, 0, 1, tzinfo=timezone.utc))
        due_before_newyear = store.claim_due_targets(
            iso(datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc))
        )
        assert len(due_before_newyear) == 1


class TestCancel:
    def test_cancels_scheduled_targets(self, store, tmp_path):
        post_id = make_post(
            store, tmp_path, NOW + timedelta(hours=1), [Platform.YOUTUBE, Platform.INSTAGRAM]
        )
        assert store.cancel_post(post_id, "user-1") == 2
        post = store.get_post(post_id)
        assert all(t["state"] == "canceled" for t in post["targets"])
        assert post["canceledAt"] is not None

    def test_leaves_already_published_targets_alone(self, store, tmp_path):
        """You cannot unsend a video."""
        post_id = make_post(
            store, tmp_path, NOW, [Platform.YOUTUBE, Platform.INSTAGRAM]
        )
        store.set_target_result(
            post_id,
            Platform.YOUTUBE,
            PublishResult(state=TargetState.DONE, url="https://youtu.be/x"),
        )
        assert store.cancel_post(post_id, "user-1") == 1

        targets = {t["platform"]: t for t in store.get_post(post_id)["targets"]}
        assert targets["youtube"]["state"] == "done"
        assert targets["instagram"]["state"] == "canceled"


class TestCrashRecovery:
    def test_requeues_claimed_but_unstarted_work(self, store, tmp_path):
        post_id = make_post(store, tmp_path, NOW - timedelta(minutes=1))
        store.claim_due_targets(iso(NOW))  # -> pending

        assert store.recover_interrupted()["requeued"] == 1
        assert store.get_post(post_id)["targets"][0]["state"] == "scheduled"

    def test_fails_uploads_that_were_cut_off(self, store, tmp_path):
        """An interrupted upload may already have reached the platform, so it
        is surfaced rather than silently retried into a duplicate."""
        post_id = make_post(store, tmp_path, NOW)
        store.set_target_state(post_id, Platform.YOUTUBE, TargetState.UPLOADING)

        assert store.recover_interrupted()["interrupted"] == 1
        target = store.get_post(post_id)["targets"][0]
        assert target["state"] == "failed"
        assert "Interrupted by a restart" in target["error"]

    def test_leaves_finished_work_alone(self, store, tmp_path):
        post_id = make_post(store, tmp_path, NOW)
        store.set_target_result(
            post_id, Platform.YOUTUBE, PublishResult(state=TargetState.DONE)
        )
        recovered = store.recover_interrupted()
        assert recovered == {"requeued": 0, "interrupted": 0}
        assert store.get_post(post_id)["targets"][0]["state"] == "done"


class TestSchedulerRun:
    def test_publishes_due_work(self, store, settings, tmp_path):
        post_id = make_post(store, tmp_path, datetime.now(timezone.utc) - timedelta(seconds=5))
        scheduler = Scheduler(store, settings)

        assert asyncio.run(scheduler.run_due()) == 1
        target = store.get_post(post_id)["targets"][0]
        # No credentials configured, so this is how a real publish resolves.
        assert target["state"] == "not_configured"

    def test_ignores_future_work(self, store, settings, tmp_path):
        post_id = make_post(store, tmp_path, datetime.now(timezone.utc) + timedelta(hours=1))
        scheduler = Scheduler(store, settings)

        assert asyncio.run(scheduler.run_due()) == 0
        assert store.get_post(post_id)["targets"][0]["state"] == "scheduled"

    def test_refuses_to_publish_far_too_late(self, store, settings, tmp_path):
        """Laptop asleep over the scheduled time: surface it, don't post a
        day-old video without warning."""
        post_id = make_post(store, tmp_path, datetime.now(timezone.utc) - timedelta(hours=5))
        scheduler = Scheduler(store, settings)

        asyncio.run(scheduler.run_due())
        target = store.get_post(post_id)["targets"][0]
        assert target["state"] == "failed"
        assert "Missed its scheduled time" in target["error"]

    def test_catchup_window_can_be_disabled(self, store, tmp_path, settings):
        relaxed = settings.model_copy(update={"scheduler_max_catchup_minutes": 0})
        post_id = make_post(store, tmp_path, datetime.now(timezone.utc) - timedelta(days=3))
        scheduler = Scheduler(store, relaxed)

        asyncio.run(scheduler.run_due())
        assert store.get_post(post_id)["targets"][0]["state"] == "not_configured"

    def test_within_the_window_still_publishes(self, store, settings, tmp_path):
        post_id = make_post(store, tmp_path, datetime.now(timezone.utc) - timedelta(minutes=10))
        scheduler = Scheduler(store, settings)

        asyncio.run(scheduler.run_due())
        assert store.get_post(post_id)["targets"][0]["state"] == "not_configured"
