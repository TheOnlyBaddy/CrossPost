from dataclasses import dataclass
from enum import Enum


class Platform(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"


class TargetState(str, Enum):
    """State of one platform's leg of one post.

    Every platform is tracked independently. Partial success is the normal
    case, not the error case: YouTube succeeding while Instagram fails is
    routine, and the UI must never collapse these into one global status.

    Lifecycle:
        SCHEDULED -> PENDING -> UPLOADING -> PROCESSING -> DONE
                                          \\-> FAILED / NOT_CONFIGURED
        SCHEDULED -> CANCELED
    """

    SCHEDULED = "scheduled"  # waiting for its publish time
    PENDING = "pending"  # due, waiting for the worker to pick it up
    UPLOADING = "uploading"
    PROCESSING = "processing"  # accepted by the platform, still transcoding
    DONE = "done"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"  # no credentials / account not connected
    CANCELED = "canceled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            TargetState.DONE,
            TargetState.FAILED,
            TargetState.NOT_CONFIGURED,
            TargetState.CANCELED,
        )

    @property
    def is_retryable(self) -> bool:
        return self in (TargetState.FAILED, TargetState.NOT_CONFIGURED)

    @property
    def is_in_flight(self) -> bool:
        """Actively being worked on, so the UI should poll quickly."""
        return self in (
            TargetState.PENDING,
            TargetState.UPLOADING,
            TargetState.PROCESSING,
        )

    @property
    def is_cancelable(self) -> bool:
        return self is TargetState.SCHEDULED


@dataclass
class PublishResult:
    state: TargetState
    url: str | None = None
    external_id: str | None = None
    error: str | None = None
    # Full platform response body. These APIs fail with opaque codes; without
    # the raw response you are guessing.
    raw: str | None = None

    @classmethod
    def not_configured(cls, reason: str) -> "PublishResult":
        return cls(state=TargetState.NOT_CONFIGURED, error=reason)

    @classmethod
    def failed(cls, error: str, raw: str | None = None) -> "PublishResult":
        return cls(state=TargetState.FAILED, error=error, raw=raw)
