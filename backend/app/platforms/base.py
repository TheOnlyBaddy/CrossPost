from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models import Platform, PublishResult


@dataclass(frozen=True)
class PublishRequest:
    post_id: str
    # Whose connected account to publish with.
    user_id: str
    title: str
    caption: str
    video_path: Path
    # Publicly reachable URL for the same file. Instagram fetches from this
    # rather than accepting bytes, so it must be reachable from the internet.
    public_url: str


class Publisher(Protocol):
    platform: Platform

    def publish(self, req: PublishRequest) -> PublishResult: ...
