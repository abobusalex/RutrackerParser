from __future__ import annotations

import asyncio
import os
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from .config import AppConfig
from .image_ascii import image_bytes_to_ascii
from .models import Forum, TopicSummary
from .parser import parse_forum_topics, parse_forums, parse_pagination_urls, parse_topic_details, query_int
from .storage import Storage


LogCallback = Callable[[str], None | Awaitable[None]]


@dataclass(slots=True)
class SyncOptions:
    db_path: Path
    base_url: str
    workers: int = 8
    delay: float = 0.7
    max_forums: int | None = None
    max_topics: int | None = None
    include_images: bool = True
    username: str | None = None
    password: str | None = None
    retries: int = 3
    retry_backoff: float = 2.0


class RutrackerCrawler:
    def __init__(self, options: SyncOptions, log: LogCallback | None = None):
        self.options = options
        self.log = log
        self.storage = Storage(options.db_path)
        self._seen_forum_pages: set[str] = set()
        self._seen_topics: set[int] = set()
        self._topic_count = 0

    async def close(self) -> None:
        self.storage.close()

    async def run(self) -> None:
        headers = {"User-Agent": AppConfig().user_agent}
        timeout = httpx.Timeout(AppConfig().request_timeout)
        limits = httpx.Limits(max_connections=self.options.workers + 2)
        async with httpx.AsyncClient(headers=headers, timeout=timeout, limits=limits, follow_redirects=True) as client:
            if self.options.username and self.options.password:
                await self._login(client)
            index_url = self.options.base_url.rstrip("/") + "/index.php"
            await self._log("🌐 Загружаю карту форумов")
            index_html = await self._fetch_text(client, index_url)
            forums = parse_forums(index_html, self.options.base_url)
            if self.options.max_forums:
                forums = forums[: self.options.max_forums]
            self.storage.upsert_forums(forums)
            await self._log(f"🗺️ Форумов найдено: {len(forums)}")
            await self._crawl_forums(client, forums)

    async def _crawl_forums(self, client: httpx.AsyncClient, forums: list[Forum]) -> None:
        topic_queue: asyncio.Queue[TopicSummary] = asyncio.Queue()
        workers = [
            asyncio.create_task(self._topic_worker(client, topic_queue, index + 1))
            for index in range(self.options.workers)
        ]
        try:
            for forum in forums:
                if self.options.max_topics and self._topic_count >= self.options.max_topics:
                    break
                await self._crawl_forum(client, forum, topic_queue)
            await topic_queue.join()
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    async def _crawl_forum(
        self,
        client: httpx.AsyncClient,
        forum: Forum,
        topic_queue: asyncio.Queue[TopicSummary],
    ) -> None:
        queue = deque([forum.url])
        while queue:
            if self.options.max_topics and self._topic_count >= self.options.max_topics:
                return
            url = queue.popleft()
            if url in self._seen_forum_pages:
                continue
            self._seen_forum_pages.add(url)
            await self._log(f"📚 {forum.title}: {url}")
            try:
                html = await self._fetch_text(client, url)
            except httpx.HTTPStatusError as exc:
                await self._log(f"⚠️ Форум пропущен: {_http_error_message(exc)}")
                continue
            except httpx.HTTPError as exc:
                await self._log(f"⚠️ Форум пропущен из-за сетевой ошибки: {exc}")
                continue
            pages = parse_pagination_urls(html, self.options.base_url)
            for page in pages:
                if query_int(page, "f") == forum.id and page not in self._seen_forum_pages:
                    queue.append(page)
            topics = parse_forum_topics(html, forum.id, self.options.base_url)
            self.storage.upsert_topic_summaries(topics)
            for topic in topics:
                if topic.id in self._seen_topics:
                    continue
                if self.options.max_topics and self._topic_count >= self.options.max_topics:
                    break
                self._seen_topics.add(topic.id)
                self._topic_count += 1
                await topic_queue.put(topic)

    async def _topic_worker(
        self,
        client: httpx.AsyncClient,
        queue: asyncio.Queue[TopicSummary],
        worker_id: int,
    ) -> None:
        while True:
            topic = await queue.get()
            try:
                await asyncio.sleep(self.options.delay)
                await self._crawl_topic(client, topic, worker_id)
            finally:
                queue.task_done()

    async def _crawl_topic(
        self,
        client: httpx.AsyncClient,
        topic: TopicSummary,
        worker_id: int,
    ) -> None:
        try:
            html = await self._fetch_text(client, topic.url)
            details = parse_topic_details(html, topic.url, topic.forum_id, self.options.base_url)
            if self.options.include_images and details.first_image_url:
                details.first_image_ascii = await self._fetch_ascii(client, details.first_image_url)
            self.storage.upsert_topic_details(details)
            magnet_mark = "🧲" if details.magnet else "▫️"
            await self._log(f"{magnet_mark} W{worker_id}: {details.title[:80]}")
        except httpx.HTTPStatusError as exc:
            await self._log(f"⚠️ W{worker_id}: topic {topic.id} не разобран: {_http_error_message(exc)}")
        except Exception as exc:
            await self._log(f"⚠️ W{worker_id}: topic {topic.id} не разобран: {exc}")

    async def _login(self, client: httpx.AsyncClient) -> None:
        await self._log("🔐 Пробую авторизоваться")
        login_url = self.options.base_url.rstrip("/") + "/login.php"
        data = {
            "login_username": self.options.username,
            "login_password": self.options.password,
            "login": "Вход",
        }
        response = await client.post(login_url, data=data)
        response.raise_for_status()
        await self._log("✅ Авторизация отправлена")

    async def _fetch_text(self, client: httpx.AsyncClient, url: str) -> str:
        response = await self._get_with_retries(client, url)
        response.encoding = response.encoding or "utf-8"
        return response.text

    async def _fetch_ascii(self, client: httpx.AsyncClient, url: str) -> str | None:
        try:
            response = await self._get_with_retries(client, url)
            content_type = response.headers.get("content-type", "")
            if "image" not in content_type:
                return None
            return image_bytes_to_ascii(response.content)
        except Exception as exc:
            await self._log(f"🖼️ ASCII не получился: {exc}")
            return None

    async def _get_with_retries(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.options.retries + 1):
            try:
                response = await client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if not _retryable_status(status_code) or attempt >= self.options.retries:
                    raise
                await self._log(
                    f"⏳ HTTP {status_code} на {url}; повтор {attempt + 1}/{self.options.retries}"
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.options.retries:
                    raise
                await self._log(f"⏳ Сеть капризничает: {exc}; повтор {attempt + 1}/{self.options.retries}")
            await asyncio.sleep(self.options.retry_backoff * (attempt + 1))
        if last_error:
            raise last_error
        raise RuntimeError(f"Не удалось загрузить {url}")

    async def _log(self, message: str) -> None:
        if self.log is None:
            return
        result = self.log(message)
        if asyncio.iscoroutine(result):
            await result


def options_from_env(db_path: Path, base_url: str, workers: int, delay: float) -> SyncOptions:
    return SyncOptions(
        db_path=db_path,
        base_url=base_url,
        workers=workers,
        delay=delay,
        username=os.getenv("RUTRACKER_USERNAME"),
        password=os.getenv("RUTRACKER_PASSWORD"),
    )


def _retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429, 500, 502, 503, 504, 521, 522, 523, 524}


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    status_code = exc.response.status_code
    url = str(exc.request.url)
    if status_code == 521:
        return f"HTTP 521 — сайт/Cloudflare временно не принимает запрос ({url})"
    if status_code == 429:
        return f"HTTP 429 — rate limit, увеличь --delay и уменьши --workers ({url})"
    return f"HTTP {status_code} при загрузке {url}"
