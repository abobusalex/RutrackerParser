from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from .models import Forum, TopicDetails, TopicFile, TopicSummary


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS forums (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    topics_count INTEGER,
    posts_count INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    forum_id INTEGER,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT,
    magnet TEXT,
    registered_at TEXT,
    size_text TEXT,
    size_bytes INTEGER,
    seeders INTEGER,
    leechers INTEGER,
    downloads INTEGER,
    first_image_url TEXT,
    first_image_ascii TEXT,
    crawled_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(forum_id) REFERENCES forums(id)
);

CREATE TABLE IF NOT EXISTS topic_files (
    topic_id INTEGER NOT NULL,
    order_index INTEGER NOT NULL,
    path TEXT NOT NULL,
    size_text TEXT,
    size_bytes INTEGER,
    PRIMARY KEY(topic_id, order_index),
    FOREIGN KEY(topic_id) REFERENCES topics(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sync_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS topics_fts USING fts5(
    title,
    description,
    content='topics',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS topics_ai AFTER INSERT ON topics BEGIN
    INSERT INTO topics_fts(rowid, title, description)
    VALUES (new.id, new.title, coalesce(new.description, ''));
END;

CREATE TRIGGER IF NOT EXISTS topics_ad AFTER DELETE ON topics BEGIN
    INSERT INTO topics_fts(topics_fts, rowid, title, description)
    VALUES ('delete', old.id, old.title, coalesce(old.description, ''));
END;

CREATE TRIGGER IF NOT EXISTS topics_au AFTER UPDATE ON topics BEGIN
    INSERT INTO topics_fts(topics_fts, rowid, title, description)
    VALUES ('delete', old.id, old.title, coalesce(old.description, ''));
    INSERT INTO topics_fts(rowid, title, description)
    VALUES (new.id, new.title, coalesce(new.description, ''));
END;
"""


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def upsert_forums(self, forums: Iterable[Forum]) -> None:
        with self.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO forums(id, parent_id, title, url, topics_count, posts_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    parent_id=excluded.parent_id,
                    title=excluded.title,
                    url=excluded.url,
                    topics_count=excluded.topics_count,
                    posts_count=excluded.posts_count,
                    updated_at=CURRENT_TIMESTAMP
                """,
                [
                    (forum.id, forum.parent_id, forum.title, forum.url, forum.topics_count, forum.posts_count)
                    for forum in forums
                ],
            )

    def upsert_topic_summaries(self, topics: Iterable[TopicSummary]) -> None:
        rows = [
            (
                topic.id,
                topic.forum_id,
                topic.title,
                topic.url,
                topic.registered_at,
                topic.size_text,
                topic.size_bytes,
                topic.seeders,
                topic.leechers,
                topic.downloads,
            )
            for topic in topics
        ]
        if not rows:
            return
        with self.transaction() as conn:
            conn.executemany(
                """
                INSERT INTO topics(
                    id, forum_id, title, url, registered_at, size_text, size_bytes,
                    seeders, leechers, downloads, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    forum_id=coalesce(excluded.forum_id, topics.forum_id),
                    title=excluded.title,
                    url=excluded.url,
                    registered_at=coalesce(excluded.registered_at, topics.registered_at),
                    size_text=coalesce(excluded.size_text, topics.size_text),
                    size_bytes=coalesce(excluded.size_bytes, topics.size_bytes),
                    seeders=coalesce(excluded.seeders, topics.seeders),
                    leechers=coalesce(excluded.leechers, topics.leechers),
                    downloads=coalesce(excluded.downloads, topics.downloads),
                    updated_at=CURRENT_TIMESTAMP
                """,
                rows,
            )

    def upsert_topic_details(self, topic: TopicDetails) -> None:
        files = topic.files or []
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO topics(
                    id, forum_id, title, url, description, magnet, registered_at,
                    size_text, size_bytes, seeders, leechers, downloads,
                    first_image_url, first_image_ascii, crawled_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    forum_id=coalesce(excluded.forum_id, topics.forum_id),
                    title=excluded.title,
                    url=excluded.url,
                    description=coalesce(excluded.description, topics.description),
                    magnet=coalesce(excluded.magnet, topics.magnet),
                    registered_at=coalesce(excluded.registered_at, topics.registered_at),
                    size_text=coalesce(excluded.size_text, topics.size_text),
                    size_bytes=coalesce(excluded.size_bytes, topics.size_bytes),
                    seeders=coalesce(excluded.seeders, topics.seeders),
                    leechers=coalesce(excluded.leechers, topics.leechers),
                    downloads=coalesce(excluded.downloads, topics.downloads),
                    first_image_url=coalesce(excluded.first_image_url, topics.first_image_url),
                    first_image_ascii=coalesce(excluded.first_image_ascii, topics.first_image_ascii),
                    crawled_at=CURRENT_TIMESTAMP,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    topic.id,
                    topic.forum_id,
                    topic.title,
                    topic.url,
                    topic.description,
                    topic.magnet,
                    topic.registered_at,
                    topic.size_text,
                    topic.size_bytes,
                    topic.seeders,
                    topic.leechers,
                    topic.downloads,
                    topic.first_image_url,
                    topic.first_image_ascii,
                ),
            )
            conn.execute("DELETE FROM topic_files WHERE topic_id = ?", (topic.id,))
            conn.executemany(
                """
                INSERT INTO topic_files(topic_id, order_index, path, size_text, size_bytes)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (topic.id, item.order_index, item.path, item.size_text, item.size_bytes)
                    for item in files
                ],
            )

    def search_topics(
        self,
        query: str = "",
        min_seeders: int | None = None,
        max_size_bytes: int | None = None,
        magnet_only: bool = False,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        conditions = []
        params: list[object] = []
        join = ""
        if query.strip():
            join = "JOIN topics_fts ON topics_fts.rowid = topics.id"
            conditions.append("topics_fts MATCH ?")
            params.append(_fts_query(query))
        if min_seeders is not None:
            conditions.append("coalesce(seeders, 0) >= ?")
            params.append(min_seeders)
        if max_size_bytes is not None:
            conditions.append("(size_bytes IS NULL OR size_bytes <= ?)")
            params.append(max_size_bytes)
        if magnet_only:
            conditions.append("magnet IS NOT NULL")
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        return list(
            self._conn.execute(
                f"""
                SELECT topics.*, forums.title AS forum_title
                FROM topics
                LEFT JOIN forums ON forums.id = topics.forum_id
                {join}
                {where}
                ORDER BY coalesce(seeders, 0) DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            )
        )

    def get_topic(self, topic_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            """
            SELECT topics.*, forums.title AS forum_title
            FROM topics
            LEFT JOIN forums ON forums.id = topics.forum_id
            WHERE topics.id = ?
            """,
            (topic_id,),
        ).fetchone()

    def list_forums(self, limit: int = 100) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                """
                SELECT forums.*, count(topics.id) AS indexed_topics
                FROM forums
                LEFT JOIN topics ON topics.forum_id = forums.id
                GROUP BY forums.id
                ORDER BY coalesce(forums.topics_count, indexed_topics, 0) DESC, forums.title
                LIMIT ?
                """,
                (limit,),
            )
        )

    def topic_files(self, topic_id: int) -> list[TopicFile]:
        rows = self._conn.execute(
            """
            SELECT path, size_text, size_bytes, order_index
            FROM topic_files
            WHERE topic_id = ?
            ORDER BY order_index
            """,
            (topic_id,),
        )
        return [
            TopicFile(
                path=row["path"],
                size_text=row["size_text"],
                size_bytes=row["size_bytes"],
                order_index=row["order_index"],
            )
            for row in rows
        ]

    def stats(self) -> dict[str, int]:
        row = self._conn.execute(
            """
            SELECT
                (SELECT count(*) FROM forums) AS forums,
                (SELECT count(*) FROM topics) AS topics,
                (SELECT count(*) FROM topics WHERE crawled_at IS NOT NULL) AS crawled_topics,
                (SELECT count(*) FROM topic_files) AS files,
                (SELECT count(*) FROM topics WHERE magnet IS NOT NULL) AS magnets
            """
        ).fetchone()
        return dict(row)

    def is_empty(self) -> bool:
        stats = self.stats()
        return stats["forums"] == 0 and stats["topics"] == 0


def _fts_query(query: str) -> str:
    tokens = [token.replace('"', "") for token in query.split() if token.strip()]
    return " ".join(f'"{token}"*' for token in tokens) if tokens else '""'
