from ..config import Settings
from ..models import Platform
from ..store import Store
from .base import Publisher, PublishRequest
from .facebook import FacebookPublisher
from .instagram import InstagramPublisher
from .youtube import YouTubePublisher

__all__ = [
    "Publisher",
    "PublishRequest",
    "get_publisher",
    "FacebookPublisher",
    "InstagramPublisher",
    "YouTubePublisher",
]


def get_publisher(platform: Platform, settings: Settings, store: Store) -> Publisher:
    match platform:
        case Platform.YOUTUBE:
            return YouTubePublisher(settings, store)
        case Platform.INSTAGRAM:
            return InstagramPublisher(settings, store)
        case Platform.FACEBOOK:
            return FacebookPublisher(settings, store)
    raise ValueError(f"No publisher for {platform}")
