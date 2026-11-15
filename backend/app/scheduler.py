"""The publish worker.

One loop, owned by the FastAPI process, that claims due targets from SQLite
and publishes them. It replaces the earlier BackgroundTasks approach, and in
doing so fixes two things at once:

  - posts can be scheduled for later, and
  - work survives a restart, because the queue is a database table rather
    than in-process state.

"Post now" is not a special case: it is a post scheduled for now. The route
nudges the loop so there is no poll-interval delay, but it travels the same
path as everything else.

Publishing is blocking (the Google client and httpx are both synchronous), so
each target runs in a worker thread and the loop stays responsive.

Single process only. If this ever runs on more than one replica, two loops
would claim different targets of the same post — the claim is per target, so
that is safe — but moving to a real queue would be the better answer.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .config import Settings
from .models import Platform, PublishResult, TargetState
from .publishing import publish_one
from .store import Store, to_utc_iso

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopping = False

    # --- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        recovered = self.store.recover_interrupted()
        if recovered["requeued"] or recovered["interrupted"]:
            log.info(
                "Recovered from previous run: %d requeued, %d marked interrupted",
                recovered["requeued"],
                recovered["interrupted"],
            )
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="crosspost-scheduler")
        log.info(
            "Scheduler started (poll every %ss, catch-up window %s min)",
            self.settings.scheduler_poll_seconds,
            self.settings.scheduler_max_catchup_minutes,
        )

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def nudge(self) -> None:
        """Wake the loop now, instead of waiting for the next poll."""
        self._wake.set()

    # --- loop -----------------------------------------------------------

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self.run_due()
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("Scheduler tick failed")

            try:
                await asyncio.wait_for(
                    self._wake.wait(), timeout=self.settings.scheduler_poll_seconds
                )
            except asyncio.TimeoutError:
                pass
            self._wake.clear()

    async def run_due(self) -> int:
        """Publish everything that is due. Returns how many targets ran."""
        now = datetime.now(timezone.utc)
        claimed = self.store.claim_due_targets(to_utc_iso(now))
        if not claimed:
            return 0

        for post_id, platform, _user_id in claimed:
            if self._is_too_late(post_id, now):
                self._mark_missed(post_id, platform)
                continue
            # Blocking network work: keep it off the event loop.
            await asyncio.to_thread(
                publish_one, self.store, self.settings, post_id, platform
            )
        return len(claimed)

    # --- missed windows -------------------------------------------------

    def _is_too_late(self, post_id: str, now: datetime) -> bool:
        """Don't silently publish something that was due days ago.

        If the machine was asleep over a scheduled time, posting a week-old
        video without warning is worse than surfacing it and letting the user
        decide. The window is configurable; 0 disables the check.
        """
        limit = self.settings.scheduler_max_catchup_minutes
        if limit <= 0:
            return False

        post = self.store.get_post(post_id)
        if post is None:
            return False

        try:
            scheduled = datetime.fromisoformat(post["scheduledAt"])
        except ValueError:
            return False
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)

        return now - scheduled > timedelta(minutes=limit)

    def _mark_missed(self, post_id: str, platform: Platform) -> None:
        minutes = self.settings.scheduler_max_catchup_minutes
        log.warning("post=%s platform=%s missed its window", post_id, platform.value)
        self.store.set_target_result(
            post_id,
            platform,
            PublishResult(
                state=TargetState.FAILED,
                error=(
                    f"Missed its scheduled time by more than {minutes} minutes — "
                    "was the server running? Retry to publish it now."
                ),
            ),
        )
