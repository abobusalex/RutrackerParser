from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .config import BASE_URL
from .models import Forum, TopicDetails, TopicFile, TopicSummary


SIZE_RE = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>Б|B|KB|КБ|KiB|MB|МБ|MiB|GB|ГБ|GiB|TB|ТБ|TiB)",
    re.IGNORECASE,
)
INT_RE = re.compile(r"\d+")
DATE_HINT_RE = re.compile(
    r"((?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4})(?:\s+\d{1,2}:\d{2})?|"
    r"(?:\d{1,2}\s+[а-яёa-z]{3,12}\s+\d{4})(?:\s+\d{1,2}:\d{2})?)",
    re.IGNORECASE,
)


def absolute_url(href: str, base_url: str = BASE_URL) -> str:
    return urljoin(base_url, unescape(href.strip()))


def query_int(url: str, key: str) -> int | None:
    values = parse_qs(urlparse(url).query).get(key)
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def text_of(node: Tag | None) -> str:
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def parse_int(value: str | None) -> int | None:
    if not value:
        return None
    match = INT_RE.search(value.replace("\xa0", ""))
    return int(match.group()) if match else None


def parse_size(value: str | None) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    match = SIZE_RE.search(value.replace("\xa0", " "))
    if not match:
        return None, None
    number = float(match.group("num").replace(",", "."))
    unit = match.group("unit").lower()
    multipliers = {
        "b": 1,
        "б": 1,
        "kb": 1024,
        "кб": 1024,
        "kib": 1024,
        "mb": 1024**2,
        "мб": 1024**2,
        "mib": 1024**2,
        "gb": 1024**3,
        "гб": 1024**3,
        "gib": 1024**3,
        "tb": 1024**4,
        "тб": 1024**4,
        "tib": 1024**4,
    }
    size_text = f"{match.group('num')} {match.group('unit')}"
    return size_text, int(number * multipliers[unit])


def extract_date_hint(text: str) -> str | None:
    match = DATE_HINT_RE.search(text)
    return match.group(1) if match else None


def parse_forums(html: str, base_url: str = BASE_URL) -> list[Forum]:
    soup = BeautifulSoup(html, "html.parser")
    forums: dict[int, Forum] = {}
    for link in soup.select('a[href*="viewforum.php?f="]'):
        href = link.get("href")
        if not href:
            continue
        url = absolute_url(href, base_url)
        forum_id = query_int(url, "f")
        title = text_of(link)
        if forum_id is None or not title:
            continue
        row = link.find_parent("tr")
        row_text = text_of(row)
        numbers = [int(item) for item in INT_RE.findall(row_text)]
        topics_count = numbers[-2] if len(numbers) >= 2 else None
        posts_count = numbers[-1] if len(numbers) >= 1 else None
        forums[forum_id] = Forum(
            id=forum_id,
            title=title,
            url=url,
            topics_count=topics_count,
            posts_count=posts_count,
        )
    return list(forums.values())


def parse_forum_topics(html: str, forum_id: int | None, base_url: str = BASE_URL) -> list[TopicSummary]:
    soup = BeautifulSoup(html, "html.parser")
    topics: dict[int, TopicSummary] = {}
    for link in soup.select('a[href*="viewtopic.php?t="]'):
        href = link.get("href")
        if not href:
            continue
        url = absolute_url(href, base_url)
        topic_id = query_int(url, "t")
        title = text_of(link)
        if topic_id is None or not title:
            continue
        row = link.find_parent("tr")
        row_text = text_of(row)
        size_text, size_bytes = parse_size(row_text)
        seeders = _class_int(row, ("seed", "seedmed", "seedmedu")) if row else None
        leechers = _class_int(row, ("leech", "leechmed", "leechmedu")) if row else None
        downloads = _class_int(row, ("compl", "complete", "dl")) if row else None
        topics[topic_id] = TopicSummary(
            id=topic_id,
            forum_id=forum_id,
            title=title,
            url=url,
            size_text=size_text,
            size_bytes=size_bytes,
            seeders=seeders,
            leechers=leechers,
            downloads=downloads,
            registered_at=extract_date_hint(row_text),
        )
    return list(topics.values())


def parse_pagination_urls(html: str, base_url: str = BASE_URL) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = set()
    for link in soup.select('a[href*="start="], a[href*="viewforum.php?f="]'):
        href = link.get("href")
        if href:
            urls.add(absolute_url(href, base_url))
    return sorted(urls)


def parse_topic_details(html: str, url: str, forum_id: int | None = None, base_url: str = BASE_URL) -> TopicDetails:
    soup = BeautifulSoup(html, "html.parser")
    topic_id = query_int(url, "t")
    if topic_id is None:
        raise ValueError(f"Topic URL has no t= id: {url}")

    title = _topic_title(soup)
    first_post = _first_post(soup)
    first_post_text = text_of(first_post)
    all_text = text_of(soup)
    magnet = _magnet(soup)
    first_image = _first_image(first_post or soup, base_url)
    size_text, size_bytes = parse_size(all_text)
    files = _files(soup)

    return TopicDetails(
        id=topic_id,
        title=title or f"topic-{topic_id}",
        url=url,
        forum_id=forum_id,
        description=first_post_text or None,
        magnet=magnet,
        registered_at=_registered_at(all_text),
        size_text=size_text,
        size_bytes=size_bytes,
        seeders=_class_int(soup, ("seed", "seedmed", "seedmedu")),
        leechers=_class_int(soup, ("leech", "leechmed", "leechmedu")),
        downloads=_class_int(soup, ("compl", "complete", "dl")),
        first_image_url=first_image,
        files=files,
    )


def _topic_title(soup: BeautifulSoup) -> str | None:
    for selector in ("h1", ".maintitle", ".topic-title", "title"):
        value = text_of(soup.select_one(selector))
        if value:
            return value.replace(":: RuTracker.org", "").strip()
    return None


def _first_post(soup: BeautifulSoup) -> Tag | None:
    selectors = (
        ".post_wrap .post_body",
        ".post_body",
        "td.message",
        ".message",
        "#topic_main",
        ".topic",
    )
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            return node
    return None


def _magnet(soup: BeautifulSoup) -> str | None:
    link = soup.select_one('a[href^="magnet:"]')
    if link and link.get("href"):
        return unescape(link["href"])
    data_link = soup.select_one("[data-magnet]")
    if data_link and data_link.get("data-magnet"):
        return unescape(data_link["data-magnet"])
    text = str(soup)
    match = re.search(r"magnet:\?xt=urn:[^\"' <]+", text)
    return unescape(match.group(0)) if match else None


def _first_image(node: Tag | BeautifulSoup, base_url: str) -> str | None:
    for image in node.select("img"):
        src = image.get("src") or image.get("data-src")
        if src and not src.startswith("data:"):
            return absolute_url(src, base_url)
    return None


def _files(soup: BeautifulSoup) -> list[TopicFile]:
    containers = soup.select("#tor-filelist, .tor-filelist, .filelist, .files")
    if not containers:
        containers = soup.select("table")
    found: list[TopicFile] = []
    for container in containers:
        for row in container.select("tr, li"):
            row_text = text_of(row)
            size_text, size_bytes = parse_size(row_text)
            if not size_text:
                continue
            path = SIZE_RE.sub("", row_text).strip(" -—:\t")
            if path:
                found.append(TopicFile(path=path, size_text=size_text, size_bytes=size_bytes, order_index=len(found)))
    return found


def _registered_at(text: str) -> str | None:
    labels = ("зарегистр", "добавлен", "создан", "uploaded", "registered")
    lowered = text.lower()
    for label in labels:
        index = lowered.find(label)
        if index >= 0:
            hint = extract_date_hint(text[index : index + 160])
            if hint:
                return hint
    return extract_date_hint(text)


def _class_int(node: Tag | BeautifulSoup | None, class_hints: tuple[str, ...]) -> int | None:
    if node is None:
        return None
    for tag in node.find_all(True):
        classes = " ".join(tag.get("class", [])).lower()
        if any(hint in classes for hint in class_hints):
            value = parse_int(text_of(tag))
            if value is not None:
                return value
    return None
