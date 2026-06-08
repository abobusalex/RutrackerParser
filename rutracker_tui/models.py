from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Forum:
    id: int
    title: str
    url: str
    category: str | None = None
    parent_id: int | None = None
    topics_count: int | None = None
    posts_count: int | None = None


@dataclass(slots=True)
class TopicSummary:
    id: int
    forum_id: int | None
    title: str
    url: str
    size_text: str | None = None
    size_bytes: int | None = None
    seeders: int | None = None
    leechers: int | None = None
    downloads: int | None = None
    registered_at: str | None = None


@dataclass(slots=True)
class TopicFile:
    path: str
    size_text: str | None = None
    size_bytes: int | None = None
    order_index: int = 0


@dataclass(slots=True)
class TopicDetails:
    id: int
    title: str
    url: str
    forum_id: int | None = None
    description: str | None = None
    magnet: str | None = None
    registered_at: str | None = None
    size_text: str | None = None
    size_bytes: int | None = None
    seeders: int | None = None
    leechers: int | None = None
    downloads: int | None = None
    first_image_url: str | None = None
    first_image_ascii: str | None = None
    files: list[TopicFile] | None = None
