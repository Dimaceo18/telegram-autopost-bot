# tochka_parser.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://tochka.by"
LIST_URL = "https://tochka.by/articles/"


@dataclass
class ArticlePreview:
    title: str
    url: str
    image: Optional[str] = None
    published_at: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class ArticleFull:
    title: str
    url: str
    image: Optional[str]
    published_at: Optional[str]
    text: str
    lead: Optional[str] = None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


def _get_html(url: str, timeout: int = 20) -> str:
    s = _session()
    r = s.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def _abs(url: Optional[str], base: str) -> Optional[str]:
    if not url:
        return None
    return urljoin(base, url)


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_ld_json(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    data: List[Dict[str, Any]] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            raw = tag.get_text(strip=True)
            if not raw:
                continue
            obj = json.loads(raw)
            if isinstance(obj, list):
                data.extend([x for x in obj if isinstance(x, dict)])
            elif isinstance(obj, dict):
                data.append(obj)
        except Exception:
            continue
    return data


def _pick_article_schema(ld: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for obj in ld:
        t = obj.get("@type")
        if isinstance(t, list):
            if any(x in ("NewsArticle", "Article") for x in t):
                return obj
        if t in ("NewsArticle", "Article"):
            return obj
    return None


def fetch_article_meta(url: str) -> Dict[str, Optional[str]]:
    html = _get_html(url)
    soup = BeautifulSoup(html, "html.parser")

    def mprop(prop: str) -> Optional[str]:
        tag = soup.find("meta", property=prop)
        return tag["content"].strip() if tag and tag.get("content") else None

    def mname(name: str) -> Optional[str]:
        tag = soup.find("meta", attrs={"name": name})
        return tag["content"].strip() if tag and tag.get("content") else None

    title = mprop("og:title") or (soup.title.get_text(strip=True) if soup.title else None)
    image = _abs(mprop("og:image"), url)
    desc = mprop("og:description") or mname("description")

    ld = _extract_ld_json(soup)
    schema = _pick_article_schema(ld)
    published_at = None
    if schema:
        published_at = schema.get("datePublished") or schema.get("dateModified")

    if not published_at:
        t = soup.find("time", attrs={"datetime": True})
        if t:
            published_at = t.get("datetime")

    return {
        "title": title,
        "image": image,
        "description": desc,
        "published_at": published_at,
    }


def parse_list(max_items: int = 20) -> List[ArticlePreview]:
    html = _get_html(LIST_URL)
    soup = BeautifulSoup(html, "html.parser")

    found: List[ArticlePreview] = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        abs_url = urljoin(LIST_URL, href)
        p = urlparse(abs_url)

        if p.netloc and p.netloc != urlparse(BASE).netloc:
            continue

        # https://tochka.by/articles/<section>/<slug>/
        if re.search(r"^/articles/[^/]+/[^/]+/?$", p.path):
            url = urljoin(BASE, p.path)
            if url in seen:
                continue
            seen.add(url)

            title = a.get_text(" ", strip=True)
            if not title:
                title = a.get("title") or a.get("aria-label") or ""
            found.append(ArticlePreview(title=title.strip() or "Без заголовка", url=url))

        if len(found) >= max_items:
            break

    enriched: List[ArticlePreview] = []
    for item in found[:max_items]:
        try:
            meta = fetch_article_meta(item.url)
            enriched.append(ArticlePreview(
                title=meta.get("title") or item.title,
                url=item.url,
                image=meta.get("image"),
                published_at=meta.get("published_at"),
                summary=meta.get("description"),
            ))
        except Exception:
            enriched.append(item)

    return enriched


def fetch_article_full(url: str) -> ArticleFull:
    html = _get_html(url)
    soup = BeautifulSoup(html, "html.parser")

    meta = fetch_article_meta(url)
    ld = _extract_ld_json(soup)
    schema = _pick_article_schema(ld)

    lead = None
    text = ""

    if schema:
        lead = schema.get("description") or meta.get("description")
        body = schema.get("articleBody")
        if isinstance(body, str) and body.strip():
            text = body.strip()

    if not text:
        article_tag = soup.find("article")
        root = article_tag if article_tag else soup

        # попробуем найти “контентный” контейнер
        candidates = []
        for cls in ("article__content", "article-content", "content", "post__content", "text"):
            c = root.find(class_=re.compile(rf"\b{re.escape(cls)}\b"))
            if c:
                candidates.append(c)
        container = candidates[0] if candidates else root

        parts = []
        for el in container.find_all(["p", "li", "blockquote"], recursive=True):
            t = el.get_text(" ", strip=True)
            if not t:
                continue
            if len(t) < 25 and re.search(r"(подпис|реклама|читайте|смотрите)", t.lower()):
                continue
            parts.append(t)

        text = "\n\n".join(parts)

    text = _clean_text(text)
    if not text:
        text = meta.get("description") or ""

    return ArticleFull(
        title=meta.get("title") or "Без заголовка",
        url=url,
        image=meta.get("image"),
        published_at=meta.get("published_at"),
        lead=lead or meta.get("description"),
        text=text,
    )
