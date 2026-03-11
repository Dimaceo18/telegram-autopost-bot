# -*- coding: utf-8 -*-
import os
import re
import html
import time
import hashlib
import json
import logging
import signal
import sys
import functools
from io import BytesIO
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import requests
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# Новые импорты для автоматической выгрузки
import threading
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz


# =========================
# Logging setup
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# =========================
# ENV
# =========================
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
SUGGEST_URL = (os.getenv("SUGGEST_URL") or "").strip()

# Настройки автоматической выгрузки
AUTO_NEWS_CHAT_ID = os.getenv("AUTO_NEWS_CHAT_ID")  # ID чата для авто-выгрузки
AUTO_NEWS_TIMEZONE = os.getenv("AUTO_NEWS_TIMEZONE", "Europe/Minsk")
NEWS_BATCH_SIZE = 20  # Количество новостей в одной выгрузке
NEWS_MORE_SIZE = 10   # Сколько еще подгружать

if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set (Render -> Environment -> BOT_TOKEN)")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN must not contain spaces")
if not CHANNEL or CHANNEL == "@":
    raise RuntimeError("CHANNEL_USERNAME is not set (Render -> Environment -> CHANNEL_USERNAME)")

if not SUGGEST_URL and BOT_USERNAME:
    SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"

# Constants
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
CACHE_TTL = 3600  # 1 hour
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

# Новый шаблон FDR_POST
FDR_POST_PURPLE_COLOR = (122, 58, 240)  # Фиолетовый цвет как в сторис
FDR_POST_PLATE_HEIGHT_PCT = 0.15  # Высота фиолетовой плашки


# =========================
# UI BUTTONS
# =========================
BTN_POST = "📝 Оформить пост"
BTN_NEWS = "📰 Получить новости"
BTN_GET_NEWS_MANUAL = "📰 Выгрузить новости сейчас"

def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(BTN_POST), KeyboardButton(BTN_NEWS))
    kb.row(KeyboardButton(BTN_GET_NEWS_MANUAL))
    return kb


# =========================
# FONTS / CARD
# =========================
FONT_MN = "CaviarDreams.ttf"
FONT_CHP = "Montserrat-Black.ttf"
FONT_AM = "IntroInline.ttf"
FONT_MONTSERRAT_BLACK = "Montserrat-Black.ttf"

FOOTER_TEXT = "MINSK NEWS"

TARGET_W, TARGET_H = 750, 938
STORY_W = 720
STORY_H = 1280

MN_TITLE_ZONE_PCT = 0.23
CHP_GRADIENT_PCT = 0.48
AM_TOP_BLUR_PCT = 0.20
AM_BLUR_RADIUS = 18
AM_BLUR_BLEND = 0.50


# =========================
# NEWS
# =========================
NEWS_FIRST_BATCH = 20
NEWS_MORE_BATCH = 10
NEWS_CACHE_TTL_SEC = 10 * 60
NEWS_PER_SOURCE_CAP = 6

NEWS_SOURCES = [
    {
        "id": "onliner",
        "name": "Onliner",
        "kind": "rss",
        "url": "https://www.onliner.by/feed",
        "limit": 80
    },
    {
        "id": "sputnik",
        "name": "Sputnik",
        "kind": "rss",
        "url": "https://sputnik.by/export/rss2/index.xml",
        "limit": 80
    },
    {
        "id": "telegraf",
        "name": "Telegraf",
        "kind": "rss",
        "url": "https://telegraf.news/feed/",
        "limit": 80
    },
    {
        "id": "tochka",
        "name": "Tochka",
        "kind": "html_og",
        "start_urls": ["https://tochka.by/articles/"],
        "domain": "tochka.by",
        "include_patterns": [r"^/articles/[^/]+/[^/]+/?$"],
        "limit": 40,
    },
    {
        "id": "smartpress",
        "name": "Smartpress",
        "kind": "html_og",
        "start_urls": ["https://smartpress.by/", "https://smartpress.by/news/"],
        "domain": "smartpress.by",
        "exclude_patterns": [r"/about/", r"/projects/", r"/authors?/", r"/news/page/", r"/search/"],
        "limit": 40,
    },
    {
        "id": "sb",
        "name": "SB.by",
        "kind": "html_og",
        "start_urls": ["https://www.sb.by/news/", "https://www.sb.by/articles/"],
        "domain": "www.sb.by",
        "exclude_patterns": [r"/video/", r"/photo/", r"/news/page/", r"/authors?/"],
        "limit": 40,
    },
    {
        "id": "minsknews",
        "name": "Minsknews",
        "kind": "html_og",
        "start_urls": ["https://minsknews.by/"],
        "domain": "minsknews.by",
        "exclude_patterns": [r"/page/", r"/category/", r"/tag/", r"/author/"],
        "limit": 40,
    },
    {
        "id": "mlyn",
        "name": "Mlyn",
        "kind": "html_og",
        "start_urls": ["https://mlyn.by/"],
        "domain": "mlyn.by",
        "exclude_patterns": [r"/page/", r"/category/", r"/tag/", r"/author/"],
        "limit": 40,
    },
    {
        "id": "ont",
        "name": "ONT",
        "kind": "html_og",
        "start_urls": ["https://ont.by/news", "https://ont.by/"],
        "domain": "ont.by",
        "exclude_patterns": [r"/tv-program/", r"/projects/", r"/video/", r"/news/page/"],
        "limit": 40,
    },
]

# =========================
# BOT + SESSION with retries
# =========================
bot = telebot.TeleBot(TOKEN)

SESSION = requests.Session()
retry_strategy = Retry(
    total=MAX_RETRIES,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=20,
    pool_maxsize=20
)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
})

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

user_state: Dict[int, Dict] = {}


# =========================
# Graceful shutdown
# =========================
def signal_handler(sig, frame):
    logger.info("Shutting down gracefully...")
    bot.stop_polling()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# =========================
# Helper decorators
# =========================
def retry_on_error(max_retries=MAX_RETRIES):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if i == max_retries - 1:
                        logger.error(f"Failed after {max_retries} retries: {e}")
                        raise
                    logger.warning(f"Retry {i + 1}/{max_retries} for {func.__name__}: {e}")
                    time.sleep(1 * (i + 1))
            return None
        return wrapper
    return decorator


def validate_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except Exception:
        return False


def check_file_size(file_bytes: bytes) -> bool:
    return len(file_bytes) <= MAX_FILE_SIZE


# =========================
# Caching
# =========================
@functools.lru_cache(maxsize=100)
def get_cached_image(url: str) -> bytes:
    if not validate_url(url):
        raise ValueError(f"Invalid URL: {url}")
    return http_get_bytes(url)


# =========================
# Helpers
# =========================
def is_admin(msg_or_call) -> bool:
    return True


@retry_on_error()
def http_get(url: str, timeout: int = REQUEST_TIMEOUT) -> str:
    if not validate_url(url):
        raise ValueError(f"Invalid URL: {url}")
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


@retry_on_error()
def http_get_bytes(url: str, timeout: int = REQUEST_TIMEOUT) -> bytes:
    if not validate_url(url):
        raise ValueError(f"Invalid URL: {url}")
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def normalize_url(base: str, href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base, href)


def extract_source_url(text: str) -> str:
    m = URL_RE.search(text or "")
    return m.group(1) if m else ""


def ensure_fonts():
    fonts = [FONT_MN, FONT_CHP, FONT_AM, FONT_MONTSERRAT_BLACK]
    for font in fonts:
        if not os.path.exists(font):
            raise RuntimeError(f"Font not found: {font}. Please place it next to bot.py")


def warn_if_too_small(chat_id, photo_bytes: bytes):
    try:
        im = Image.open(BytesIO(photo_bytes))
        if im.width < 900 or im.height < 1100:
            bot.send_message(
                chat_id,
                "⚠️ Фото маленького разрешения. Лучше присылать больше (от 1080×1350 и выше), "
                "чтобы текст был максимально чёткий."
            )
    except Exception as e:
        logger.error(f"Error checking image size: {e}")


def clear_state(user_id: int):
    if user_id in user_state:
        template = user_state[user_id].get("template", "MN")
        user_state[user_id] = {"template": template, "step": "idle"}
        logger.info(f"Cleared state for user {user_id}")


def edit_or_send(chat_id, text, message_id=None, **kwargs):
    if message_id:
        try:
            return bot.edit_message_text(text, chat_id, message_id, **kwargs)
        except Exception as e:
            logger.warning(f"Could not edit message: {e}")
            return bot.send_message(chat_id, text, **kwargs)
    return bot.send_message(chat_id, text, **kwargs)


# =========================
# Date parsing + last 24h
# =========================
def parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()

    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception as e:
        logger.debug(f"Failed to parse date: {s}, error: {e}")
        return None


def is_last_24h(dt_utc: Optional[datetime]) -> bool:
    if not dt_utc:
        return False
    now = datetime.now(timezone.utc)
    return dt_utc >= now - timedelta(hours=24)


# =========================
# News parsers
# =========================
def extract_og_meta(page_html: str) -> Dict[str, str]:
    try:
        soup = BeautifulSoup(page_html, "lxml")
    except Exception:
        soup = BeautifulSoup(page_html, "html.parser")

    def meta_value(*keys: str) -> str:
        for key in keys:
            tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
            if tag and tag.get("content"):
                return html.unescape(tag.get("content").strip())
        return ""

    title = meta_value("og:title", "twitter:title")
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    return {
        "title": title,
        "desc": meta_value("og:description", "description", "twitter:description"),
        "image": meta_value("og:image", "twitter:image"),
    }


def parse_rss(url: str, source_name: str, limit: int = 80) -> List[Dict]:
    try:
        xml_text = http_get(url, timeout=REQUEST_TIMEOUT)
        root = ET.fromstring(xml_text)
    except Exception as e:
        logger.error(f"Failed to parse RSS {url}: {e}")
        return []

    out = []
    for item in root.findall(".//item"):
        try:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub = (item.findtext("pubDate") or "").strip() or (item.findtext("{http://purl.org/dc/elements/1.1/}date") or "").strip()

            image = ""
            enc = item.find("enclosure")
            if enc is not None and enc.get("url"):
                image = enc.get("url") or ""
            if not image:
                for child in item:
                    tag = (child.tag or "").lower()
                    if "content" in tag and child.get("url"):
                        image = child.get("url")
                        break

            dt = parse_dt(pub)

            if title and link:
                out.append({
                    "source": source_name,
                    "title": title,
                    "url": link,
                    "summary": html.unescape(re.sub(r"<[^>]+>", " ", desc)).strip(),
                    "image": image,
                    "published_raw": pub,
                    "dt_utc": dt.isoformat() if dt else "",
                })
        except Exception as e:
            logger.error(f"Error parsing RSS item: {e}")
            continue

        if len(out) >= limit:
            break
    return out


def _extract_dt_from_soup(soup: BeautifulSoup) -> Optional[datetime]:
    meta_keys = [
        "article:published_time", "article:modified_time", "og:updated_time",
        "pubdate", "publish-date", "date", "parsely-pub-date"
    ]
    for key in meta_keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            dt = parse_dt(tag.get("content") or "")
            if dt:
                return dt

    for tag in soup.find_all("time"):
        raw = tag.get("datetime") or tag.get_text(" ", strip=True)
        dt = parse_dt(raw or "")
        if dt:
            return dt

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        items = obj if isinstance(obj, list) else [obj]
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_dt = it.get("datePublished") or it.get("dateModified") or it.get("uploadDate")
            dt = parse_dt(raw_dt or "")
            if dt:
                return dt
    return None


def _extract_text_from_soup(soup: BeautifulSoup) -> str:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        items = obj if isinstance(obj, list) else [obj]
        for it in items:
            if isinstance(it, dict):
                body = it.get("articleBody")
                if isinstance(body, str) and body.strip():
                    return _clean_text(body)

    root = soup.find("article") or soup.find("main") or soup.body or soup
    parts = []
    for el in root.find_all(["p", "li", "blockquote"], recursive=True):
        t = el.get_text(" ", strip=True)
        if not t:
            continue
        low = t.lower()
        if len(t) < 35 and re.search(r"(подпис|реклама|читайте|смотрите|источник)", low):
            continue
        parts.append(t)
    return _clean_text("\n\n".join(parts))


def _valid_same_domain(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.lower()
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


def _path_allowed(path: str, include_patterns: Optional[List[str]], exclude_patterns: Optional[List[str]]) -> bool:
    path = path or "/"
    if exclude_patterns:
        for pat in exclude_patterns:
            if re.search(pat, path, re.IGNORECASE):
                return False
    if include_patterns:
        return any(re.search(pat, path, re.IGNORECASE) for pat in include_patterns)

    if path in {"", "/"}:
        return False
    if re.search(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|mp4)$", path, re.IGNORECASE):
        return False
    if any(x in path.lower() for x in ["/tag/", "/tags/", "/author/", "/authors/", "/category/", "/page/", "/search/"]):
        return False

    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return True
    slug = parts[-1] if parts else ""
    return bool(re.search(r"[a-zа-яё0-9-]{12,}", slug, re.IGNORECASE))


def _candidate_links_from_page(start_url: str, page_html: str, domain: str,
                               include_patterns: Optional[List[str]] = None,
                               exclude_patterns: Optional[List[str]] = None,
                               max_candidates: int = 80) -> List[Tuple[str, str]]:
    try:
        soup = BeautifulSoup(page_html, "lxml")
    except Exception:
        soup = BeautifulSoup(page_html, "html.parser")

    out: List[Tuple[str, str]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        try:
            href = normalize_url(start_url, a.get("href") or "")
            if not href:
                continue
            href = href.split("#", 1)[0]
            parsed = urlparse(href)
            if not parsed.scheme.startswith("http"):
                continue
            if not _valid_same_domain(href, domain):
                continue
            if not _path_allowed(parsed.path, include_patterns, exclude_patterns):
                continue

            anchor = a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or ""
            anchor = re.sub(r"\s+", " ", anchor).strip()
            if len(anchor) < 10 and not include_patterns:
                continue
            key = parsed.scheme + "://" + parsed.netloc + parsed.path.rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            out.append((href, anchor))
            if len(out) >= max_candidates:
                break
        except Exception as e:
            logger.error(f"Error processing link: {e}")
            continue
    return out


def parse_html_og_source(source: Dict, limit: int = 40) -> List[Dict]:
    start_urls = source.get("start_urls") or [source.get("url")]
    domain = source.get("domain") or urlparse(start_urls[0]).netloc
    include_patterns = source.get("include_patterns")
    exclude_patterns = source.get("exclude_patterns")
    max_candidates = min(max(limit * 6, 40), 140)

    candidates: List[Tuple[str, str]] = []
    seen = set()
    for start_url in start_urls:
        try:
            page_html = http_get(start_url, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            logger.error(f"[NEWS-ERROR] {source['name']} start={start_url} error={e}")
            continue

        for href, anchor in _candidate_links_from_page(
            start_url, page_html, domain,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            max_candidates=max_candidates,
        ):
            if href in seen:
                continue
            seen.add(href)
            candidates.append((href, anchor))
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    out = []
    used = set()
    for href, anchor in candidates:
        try:
            art_html = http_get(href, timeout=REQUEST_TIMEOUT)
            try:
                soup = BeautifulSoup(art_html, "lxml")
            except Exception:
                soup = BeautifulSoup(art_html, "html.parser")

            og = extract_og_meta(art_html)
            title = (og.get("title") or anchor or "").strip()
            title = re.sub(r"\s+", " ", title)
            if not title or len(title) < 12:
                continue

            text = _extract_text_from_soup(soup)
            dt = _extract_dt_from_soup(soup)
            img = normalize_url(href, og.get("image") or "") if og.get("image") else ""
            summary = (og.get("desc") or text[:400] or "").strip()

            if len(text) < 120 and not og.get("desc"):
                continue

            canon = href.rstrip("/")
            if canon in used:
                continue
            used.add(canon)
            out.append({
                "source": source["name"],
                "title": title,
                "url": href,
                "summary": summary,
                "image": img,
                "published_raw": dt.isoformat() if dt else "",
                "dt_utc": dt.isoformat() if dt else "",
                "full_text": text,
            })
            if len(out) >= limit:
                break
        except Exception as e:
            logger.error(f"[NEWS-ERROR] {source['name']} article={href} error={e}")
            continue
    return out


def fetch_article_full_text_generic(url: str) -> str:
    try:
        page_html = http_get(url, timeout=REQUEST_TIMEOUT)
        try:
            soup = BeautifulSoup(page_html, "lxml")
        except Exception:
            soup = BeautifulSoup(page_html, "html.parser")
        return _extract_text_from_soup(soup)
    except Exception as e:
        logger.error(f"Failed to fetch article text from {url}: {e}")
        return ""


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_all_news_last24h() -> List[Dict]:
    merged: List[Dict] = []
    by_url = set()

    for src in NEWS_SOURCES:
        kind = src["kind"]
        try:
            if kind == "rss":
                items = parse_rss(src["url"], src["name"], limit=src.get("limit", 80))
            elif kind == "html_og":
                items = parse_html_og_source(src, limit=src.get("limit", 40))
            else:
                items = []
            logger.info(f"[NEWS] {src['name']} | kind={kind} | items={len(items)}")
        except Exception as e:
            logger.error(f"[NEWS-ERROR] {src['name']} | kind={kind} | error={e}")
            items = []

        for it in items:
            u = it.get("url", "")
            if not u or u in by_url:
                continue
            by_url.add(u)
            dt = parse_dt(it.get("dt_utc") or "") or parse_dt(it.get("published_raw") or "")
            it["_dt"] = dt
            merged.append(it)

    last24 = [it for it in merged if is_last_24h(it.get("_dt"))]
    nodt = [it for it in merged if it.get("_dt") is None]
    base = last24 if len(last24) >= 10 else (last24 + nodt)

    base.sort(
        key=lambda x: (x.get("_dt") is not None, x.get("_dt") or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True
    )

    counts = {}
    diversified = []
    for it in base:
        src_name = it.get("source", "")
        counts[src_name] = counts.get(src_name, 0)
        if counts[src_name] >= NEWS_PER_SOURCE_CAP:
            continue
        counts[src_name] += 1
        diversified.append(it)

    if len(diversified) < 80:
        for it in base:
            if it in diversified:
                continue
            diversified.append(it)

    return diversified


# =========================
# Caption formatting
# =========================
RU_STOP = {
    "и", "в", "во", "на", "но", "а", "что", "это", "как", "к", "по", "из", "за", "для", "с", "со", "у", "от", "до",
    "при", "без", "над", "под", "же", "ли", "то", "не", "ни", "да", "нет", "уже", "еще", "ещё", "там", "тут",
    "снова", "будет", "начнут", "начал", "началась", "начался", "начали", "может", "могут", "нужно", "надо"
}

CATEGORY_RULES = [
    ("🚨", ["дтп", "авар", "пожар", "взрыв", "происшеств", "чп", "полици", "милици", "ранен", "пострад"]),
    ("✈️", ["белавиа", "рейс", "аэропорт", "самолет", "самолёт", "полет", "полёт", "оаэ", "дуба", "ави"]),
    ("🚇", ["метро", "станци", "маршрут", "автобус", "троллейбус", "трамвай", "дорог", "пробк"]),
    ("💳", ["банк", "технобанк", "карта", "налог", "tax free", "global blue", "выплат", "платеж", "платёж"]),
    ("🏷️", ["скидк", "распрод", "акци", "дешев", "бесплат", "купон", "sale", "%"]),
    ("🎫", ["концерт", "афиша", "выставк", "фестиваль", "событи", "матч", "театр", "кино"]),
    ("🌦️", ["погод", "шторм", "ветер", "снег", "дожд", "мороз", "жара"]),
    ("🏥", ["больниц", "врач", "здоров", "вакцин", "грипп", "ковид", "covid"]),
    ("🏛️", ["власт", "закон", "указ", "постанов", "министер", "исполком"]),
]


def pick_category_emoji(title: str, body: str) -> str:
    text = (title + " " + body).lower()
    for emoji_, keys in CATEGORY_RULES:
        for k in keys:
            if k in text:
                return emoji_
    return "📰"


def pick_keywords(title: str, body: str, max_words: int = 6):
    txt = (title + " " + body).lower()
    nums = re.findall(r"\b\d+[.,]?\d*\b|[%₽$€]|byn|usd|eur|rub", txt, flags=re.IGNORECASE)
    words = re.findall(r"[а-яёa-z]{4,}", txt, flags=re.IGNORECASE)

    candidates = []
    for w in words:
        wl = w.strip().lower()
        if wl in RU_STOP:
            continue
        if len(wl) >= 7:
            candidates.append(wl)

    seen, out = set(), []
    for w in nums + candidates:
        w2 = w.lower()
        if w2 in seen:
            continue
        seen.add(w2)
        out.append(w)
        if len(out) >= max_words:
            break
    return out


def highlight_keywords_html(text: str, keywords):
    safe = html.escape(text or "")
    for kw in keywords:
        kw_safe = html.escape(kw)
        if not kw_safe.strip():
            continue
        if re.match(r"^[а-яёa-z0-9]+$", kw, flags=re.IGNORECASE):
            pattern = re.compile(rf"(?<![а-яёa-z0-9])({re.escape(kw_safe)})(?![а-яёa-z0-9])", re.IGNORECASE)
        else:
            pattern = re.compile(rf"({re.escape(kw_safe)})", re.IGNORECASE)
        safe = pattern.sub(r"<b>\1</b>", safe)
    return safe


def build_caption_html(title: str, body: str) -> str:
    emoji_ = pick_category_emoji(title, body)
    keywords = pick_keywords(title, body)
    title_safe = html.escape((title or "").strip())
    body_high = highlight_keywords_html((body or "").strip(), keywords)
    return f"<b>{emoji_} {title_safe}</b>\n\n{body_high}".strip()


# =========================
# Telegram download
# =========================
def tg_file_bytes(file_id: str) -> bytes:
    try:
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        r = SESSION.get(file_url, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.error(f"Failed to download file {file_id}: {e}")
        raise


# =========================
# Wrapping + drawing
# =========================
def text_width(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.FreeTypeFont) -> int:
    bb = draw.textbbox((0, 0), s, font=font)
    return bb[2] - bb[0]


def wrap_no_truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                     max_width: int, max_lines: int = 6) -> Tuple[List[str], bool]:
    words = [w for w in (text or "").split() if w.strip()]
    if not words:
        return [""], True

    lines: List[str] = []
    cur = ""
    i = 0

    while i < len(words):
        w = words[i]
        test = (cur + " " + w).strip()
        if text_width(draw, test, font) <= max_width:
            cur = test
            i += 1
        else:
            if not cur:
                return [words[i]], False
            lines.append(cur)
            cur = ""
            if len(lines) >= max_lines:
                return lines, False

    if cur:
        lines.append(cur)

    if len(lines) > max_lines:
        return lines[:max_lines], False

    return lines, True


def crop_to_4x5(img: Image.Image) -> Image.Image:
    w, h = img.size
    target_ratio = 4 / 5
    cur_ratio = w / h
    if cur_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        return img.crop((0, top, w, top + new_h))


def apply_bottom_gradient(img: Image.Image, height_pct: float, max_alpha: int = 220) -> Image.Image:
    w, h = img.size
    gh = int(h * height_pct)
    if gh <= 0:
        return img

    overlay_alpha = Image.new("L", (w, h), 0)
    grad = Image.new("L", (1, gh), 0)
    for y in range(gh):
        a = int(max_alpha * (y / max(1, gh - 1)))
        grad.putpixel((0, y), a)
    grad = grad.resize((w, gh))
    overlay_alpha.paste(grad, (0, h - gh))

    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    base = img.convert("RGBA")
    overlay = Image.composite(black, Image.new("RGBA", (w, h), (0, 0, 0, 0)), overlay_alpha)
    out = Image.alpha_composite(base, overlay)
    return out.convert("RGB")


def fit_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    safe_w: int,
    max_block_h: int,
    max_lines: int = 6,
    start_size: int = 90,
    min_size: int = 16,
    line_spacing_ratio: float = 0.22,
) -> Tuple[ImageFont.FreeTypeFont, List[str], List[int], int, int]:
    text = (text or "").strip()
    if not text:
        text = " "

    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines, ok = wrap_no_truncate(draw, text, font, safe_w, max_lines=max_lines)
        spacing = int(size * line_spacing_ratio)

        heights = []
        total_h = 0
        max_w = 0
        for ln in lines:
            bb = draw.textbbox((0, 0), ln, font=font)
            lw = bb[2] - bb[0]
            lh = bb[3] - bb[1]
            heights.append(lh)
            total_h += lh
            max_w = max(max_w, lw)
        total_h += spacing * (len(lines) - 1)

        if ok and max_w <= safe_w and total_h <= max_block_h:
            return font, lines, heights, spacing, total_h

        size -= 2

    font = ImageFont.truetype(font_path, min_size)
    lines, _ = wrap_no_truncate(draw, text, font, safe_w, max_lines=max_lines)
    spacing = int(min_size * line_spacing_ratio)
    heights = []
    total_h = 0
    for ln in lines:
        bb = draw.textbbox((0, 0), ln, font=font)
        lh = bb[3] - bb[1]
        heights.append(lh)
        total_h += lh
    total_h += spacing * (len(lines) - 1)
    return font, lines, heights, spacing, total_h


# =========================
# Cards
# =========================
def make_card_mn(photo_bytes: bytes, title_text: str) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)

    img = ImageEnhance.Brightness(img).enhance(0.55)
    draw = ImageDraw.Draw(img)

    margin_x = int(img.width * 0.06)
    margin_top = int(img.height * 0.06)
    margin_bottom = int(img.height * 0.07)

    safe_w = img.width - 2 * margin_x

    footer_size = max(24, int(img.height * 0.034))
    footer_font = ImageFont.truetype(FONT_MN, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    footer_x = (img.width - footer_w) // 2

    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    text = (title_text or "").strip().upper()

    font, lines, heights, spacing, _total_h = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_MN,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(img.height * 0.11),
        min_size=16,
        line_spacing_ratio=0.22
    )

    block_w = 0
    for ln in lines:
        block_w = max(block_w, text_width(draw, ln, font))
    block_x = (img.width - block_w) // 2
    block_x = max(margin_x, block_x)

    y = margin_top
    for i, ln in enumerate(lines):
        draw.text((block_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing

    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_chp(photo_bytes: bytes, title_text: str) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)

    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    draw = ImageDraw.Draw(img)

    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    safe_w = img.width - 2 * margin_x

    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    text = (title_text or "").strip().upper()

    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_CHP,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(img.height * 0.11),
        min_size=16,
        line_spacing_ratio=0.22
    )

    y = img.height - margin_bottom - total_h
    for i, ln in enumerate(lines):
        draw.text((margin_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def apply_top_blur_band(img: Image.Image, band_pct: float = AM_TOP_BLUR_PCT, radius: int = AM_BLUR_RADIUS, blend: float = AM_BLUR_BLEND) -> Image.Image:
    w, h = img.size
    band_h = max(1, int(h * band_pct))
    base = img.convert("RGB")

    top = base.crop((0, 0, w, band_h))
    blurred = top.filter(ImageFilter.GaussianBlur(radius=radius))
    mixed = Image.blend(top, blurred, blend)

    overlay = Image.new("RGBA", (w, band_h), (0, 0, 0, 95))
    mixed_rgba = mixed.convert("RGBA")
    final_band = Image.alpha_composite(mixed_rgba, overlay).convert("RGB")

    out = base.copy()
    out.paste(final_band, (0, 0))
    return out


def make_card_am(photo_bytes: bytes, title_text: str) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
    img = apply_top_blur_band(img)

    draw = ImageDraw.Draw(img)

    margin_x = int(img.width * 0.055)
    band_h = int(img.height * AM_TOP_BLUR_PCT)
    safe_w = img.width - 2 * margin_x
    text = (title_text or "").strip().upper()

    text_zone_top = int(band_h * 0.12)
    text_zone_bottom = int(band_h * 0.12)
    text_zone_h = max(1, band_h - text_zone_top - text_zone_bottom)

    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_AM,
        safe_w=safe_w,
        max_block_h=text_zone_h,
        max_lines=3,
        start_size=int(img.height * 0.060),
        min_size=20,
        line_spacing_ratio=0.16
    )

    y = text_zone_top + max(0, (text_zone_h - total_h) // 2)
    for i, ln in enumerate(lines):
        lw = text_width(draw, ln, font)
        x = (img.width - lw) // 2
        draw.text((x, y), ln, font=font, fill="white")
        y += heights[i] + spacing

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def fit_cover(im: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = im.size
    scale = max(target_w / src_w, target_h / src_h)
    nw, nh = int(src_w * scale), int(src_h * scale)
    resized = im.resize((nw, nh), Image.LANCZOS)
    left = max(0, (nw - target_w) // 2)
    top = max(0, (nh - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def save_jpeg_to_bytes(im: Image.Image, quality: int = 92) -> BytesIO:
    bio = BytesIO()
    im.convert("RGB").save(bio, format="JPEG", quality=quality, optimize=True)
    bio.seek(0)
    return bio


def _wrap_text_preserve_paragraphs(draw, text, font, max_w):
    paragraphs = [p.strip() for p in (text or "").replace("\r", "\n").split("\n")]

    all_lines = []
    for i, p in enumerate(paragraphs):
        if not p:
            if all_lines and all_lines[-1] != "":
                all_lines.append("")
            continue

        words = p.split()
        if not words:
            continue

        current = words[0]
        for word in words[1:]:
            test = current + " " + word
            bbox = draw.textbbox((0, 0), test, font=font)
            if (bbox[2] - bbox[0]) <= max_w:
                current = test
            else:
                all_lines.append(current)
                current = word
        all_lines.append(current)

        if i < len(paragraphs) - 1:
            all_lines.append("")

    while all_lines and all_lines[-1] == "":
        all_lines.pop()

    return all_lines


def _draw_story_text(
    draw,
    text,
    box,
    font,
    fill=(255, 255, 255),
    align="center",
    valign="center",
    line_gap=10,
    paragraph_gap_extra=10
):
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1

    lines = _wrap_text_preserve_paragraphs(draw, text, font, max_w)
    if not lines:
        return

    bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_h = bbox[3] - bbox[1]

    total_h = 0
    for idx, line in enumerate(lines):
        if line == "":
            total_h += line_gap + paragraph_gap_extra
        else:
            total_h += line_h
            if idx < len(lines) - 1:
                total_h += line_gap

    if valign == "top":
        y = y1
    else:
        y = y1 + max(0, (max_h - total_h) // 2)

    for idx, line in enumerate(lines):
        if line == "":
            y += paragraph_gap_extra
            continue

        line_bbox = draw.textbbox((0, 0), line, font=font)
        line_w = line_bbox[2] - line_bbox[0]

        if align == "center":
            x = x1 + (max_w - line_w) // 2
        elif align == "left":
            x = x1
        else:
            x = x2 - line_w

        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
        if idx < len(lines) - 1:
            y += line_gap


def _fit_story_text(
    draw,
    text,
    box,
    min_size,
    max_size,
    line_gap_ratio=0.18,
    paragraph_gap_ratio=0.35
):
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1

    selected_font = ImageFont.truetype(FONT_MONTSERRAT_BLACK, min_size)
    selected_gap = 8
    selected_paragraph_gap = 12

    for size in range(max_size, min_size - 1, -1):
        font = ImageFont.truetype(FONT_MONTSERRAT_BLACK, size)
        lines = _wrap_text_preserve_paragraphs(draw, text, font, max_w)
        if not lines:
            continue

        bbox = draw.textbbox((0, 0), "Ag", font=font)
        line_h = bbox[3] - bbox[1]
        gap = max(4, int(line_h * line_gap_ratio))
        paragraph_gap = max(gap + 2, int(line_h * paragraph_gap_ratio))

        total_h = 0
        max_line_w = 0

        for idx, line in enumerate(lines):
            if line == "":
                total_h += paragraph_gap
                continue

            lb = draw.textbbox((0, 0), line, font=font)
            lw = lb[2] - lb[0]
            max_line_w = max(max_line_w, lw)

            total_h += line_h
            if idx < len(lines) - 1:
                total_h += gap

        if total_h <= max_h and max_line_w <= max_w:
            selected_font = font
            selected_gap = gap
            selected_paragraph_gap = paragraph_gap
            break

    return selected_font, selected_gap, selected_paragraph_gap


def make_card_fdr_story(photo_bytes: bytes, title: str, body_text: str) -> BytesIO:
    ensure_fonts()

    canvas = Image.new("RGB", (STORY_W, STORY_H), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    photo_h = 410
    header_h = 220

    photo = Image.open(BytesIO(photo_bytes)).convert("RGB")
    story_photo = fit_cover(photo, STORY_W, photo_h)
    canvas.paste(story_photo, (0, 0))

    purple_color = (122, 58, 240)
    canvas.paste(Image.new("RGB", (STORY_W, header_h), purple_color), (0, photo_h))

    draw.rectangle([0, photo_h + header_h, STORY_W, STORY_H], fill=(0, 0, 0))

    padding = 34

    header_box = (
        padding,
        photo_h + padding,
        STORY_W - padding,
        photo_h + header_h - padding
    )

    body_box = (
        padding,
        photo_h + header_h + padding,
        STORY_W - padding,
        STORY_H - padding
    )

    title_font, title_gap, title_paragraph_gap = _fit_story_text(
        draw,
        title,
        header_box,
        min_size=28,
        max_size=54,
        line_gap_ratio=0.08,
        paragraph_gap_ratio=0.18
    )

    _draw_story_text(
        draw,
        title,
        header_box,
        title_font,
        fill=(255, 255, 255),
        align="center",
        valign="center",
        line_gap=title_gap,
        paragraph_gap_extra=title_paragraph_gap
    )

    body_font, body_gap, body_paragraph_gap = _fit_story_text(
        draw,
        body_text,
        body_box,
        min_size=14,
        max_size=30,
        line_gap_ratio=0.10,
        paragraph_gap_ratio=0.32
    )

    _draw_story_text(
        draw,
        body_text,
        body_box,
        body_font,
        fill=(255, 255, 255),
        align="left",
        valign="top",
        line_gap=body_gap,
        paragraph_gap_extra=body_paragraph_gap
    )

    return save_jpeg_to_bytes(canvas)


def make_card_fdr_post(photo_bytes: bytes, title_text: str, highlight_phrase: str) -> BytesIO:
    """
    Шаблон "Пост ФДР" - как ЧП ВМ, но с фиолетовой плашкой для указанной фразы
    """
    ensure_fonts()

    # Базовая обработка фото как в ЧП ВМ
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    
    draw = ImageDraw.Draw(img)
    
    # Рассчитываем размеры
    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    
    # Рисуем фиолетовую плашку
    plate_height = int(img.height * FDR_POST_PLATE_HEIGHT_PCT)
    plate_y = img.height - margin_bottom - plate_height
    
    # Рисуем прямоугольник с фиолетовым цветом
    draw.rectangle(
        [0, plate_y, img.width, plate_y + plate_height],
        fill=FDR_POST_PURPLE_COLOR
    )
    
    # Подготавливаем выделенную фразу
    highlight_text = (highlight_phrase or "").strip().upper()
    if not highlight_text:
        # Если фраза не указана, берем первую строку заголовка
        highlight_text = (title_text or "").strip().upper().split('\n')[0]
    
    # Подбираем шрифт для текста на плашке
    plate_safe_w = img.width - 2 * margin_x
    
    # Пробуем разные размеры шрифта
    plate_font_size = min(58, int(plate_height * 0.6))
    plate_font = ImageFont.truetype(FONT_CHP, plate_font_size)
    
    # Проверяем, помещается ли текст в одну строку
    text_bbox = draw.textbbox((0, 0), highlight_text, font=plate_font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    # Если не помещается в одну строку, пробуем уменьшить шрифт
    if text_width > plate_safe_w:
        # Уменьшаем шрифт пока не поместится
        while text_width > plate_safe_w and plate_font_size > 24:
            plate_font_size -= 2
            plate_font = ImageFont.truetype(FONT_CHP, plate_font_size)
            text_bbox = draw.textbbox((0, 0), highlight_text, font=plate_font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
    
    # Рисуем текст на плашке по центру
    text_x = (img.width - text_width) // 2
    text_y = plate_y + (plate_height - text_height) // 2
    
    # Добавляем небольшую тень для лучшей читаемости
    shadow_offset = 2
    draw.text((text_x + shadow_offset, text_y + shadow_offset), 
              highlight_text, font=plate_font, fill=(0, 0, 0, 128))
    draw.text((text_x, text_y), highlight_text, font=plate_font, fill="white")
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card(photo_bytes: bytes, title_text: str, template: str, body_text: str = "", highlight_phrase: str = "") -> BytesIO:
    if template == "CHP":
        return make_card_chp(photo_bytes, title_text)
    if template == "AM":
        return make_card_am(photo_bytes, title_text)
    if template == "FDR_STORY":
        return make_card_fdr_story(photo_bytes, title_text, body_text)
    if template == "FDR_POST":
        return make_card_fdr_post(photo_bytes, title_text, highlight_phrase)
    return make_card_mn(photo_bytes, title_text)


# =========================
# Keyboards
# =========================
def template_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📰 МН", callback_data="tpl:MN"),
        InlineKeyboardButton("🚨 ЧП ВМ", callback_data="tpl:CHP"),
    )
    kb.row(
        InlineKeyboardButton("✨ АМ", callback_data="tpl:AM"),
        InlineKeyboardButton("📱 Сторис ФДР", callback_data="tpl:FDR_STORY"),
    )
    kb.row(
        InlineKeyboardButton("💜 Пост ФДР", callback_data="tpl:FDR_POST")
    )
    return kb


def preview_kb(source_url: str):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("✏️ Изменить текст", callback_data="edit_body"),
    )
    kb.row(
        InlineKeyboardButton("✏️ Изменить заголовок", callback_data="edit_title"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel"),
    )
    if source_url:
        kb.row(InlineKeyboardButton("Источник", url=source_url))
    if SUGGEST_URL:
        kb.row(InlineKeyboardButton("Предложить новость", url=SUGGEST_URL))
    return kb


def channel_kb():
    kb = InlineKeyboardMarkup()
    if SUGGEST_URL:
        kb.row(InlineKeyboardButton("Предложить новость", url=SUGGEST_URL))
    return kb


def news_item_kb(key: str, link: str):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Оформить", callback_data=f"nfmt:{key}"),
        InlineKeyboardButton("🗑 Пропустить", callback_data=f"nskip:{key}")
    )
    kb.row(InlineKeyboardButton("🔗 Источник", url=link))
    return kb


def news_more_kb():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton(f"➕ Показать ещё {NEWS_MORE_BATCH}", callback_data="nmore"))
    kb.row(InlineKeyboardButton("🔄 Обновить", callback_data="nrefresh"))
    return kb


# =========================
# NEWS cache per user
# =========================
def get_news_cache(uid: int) -> Optional[Dict]:
    st = user_state.get(uid) or {}
    cache = st.get("news_cache")
    if not cache:
        return None
    if time.time() - cache.get("ts", 0) > NEWS_CACHE_TTL_SEC:
        return None
    return cache


def set_news_cache(uid: int, items: List[Dict]):
    st = user_state.get(uid) or {}
    st["news_cache"] = {"ts": time.time(), "items": items, "pos": 0, "by_key": {}}
    user_state[uid] = st


def item_key(title: str, url: str) -> str:
    return hashlib.sha256(f"{title}|{url}".encode("utf-8")).hexdigest()[:16]


# =========================
# Класс для автоматической выгрузки новостей
# =========================
class NewsAutoPublisher:
    def __init__(self, bot_instance, chat_id):
        self.bot = bot_instance
        self.chat_id = chat_id
        self.scheduler = BackgroundScheduler(timezone=pytz.timezone(AUTO_NEWS_TIMEZONE))
        self.setup_schedule()
        
    def setup_schedule(self):
        """Настройка расписания выгрузок"""
        # Выгрузка в 09:00, 13:00, 16:00, 20:00
        schedule_times = [
            (9, 0),   # 09:00
            (13, 0),  # 13:00
            (16, 0),  # 16:00
            (20, 0),  # 20:00
        ]
        
        for hour, minute in schedule_times:
            self.scheduler.add_job(
                self.publish_news_digest,
                CronTrigger(hour=hour, minute=minute),
                id=f"news_{hour}_{minute}",
                replace_existing=True
            )
            logger.info(f"Scheduled news digest at {hour:02d}:{minute:02d}")
            
    def start(self):
        """Запуск планировщика"""
        if self.chat_id:
            self.scheduler.start()
            logger.info(f"News auto-publisher started for chat {self.chat_id}")
            # Отправляем сообщение о запуске
            try:
                self.bot.send_message(
                    self.chat_id,
                    "🤖 Автоматическая выгрузка новостей запущена!\n"
                    "📅 Расписание: 09:00, 13:00, 16:00, 20:00\n"
                    "📰 Количество: 20 новостей в выгрузке",
                    reply_markup=main_menu_kb()
                )
            except Exception as e:
                logger.error(f"Failed to send startup message: {e}")
        else:
            logger.warning("AUTO_NEWS_CHAT_ID not set, auto-news disabled")
            
    def stop(self):
        """Остановка планировщика"""
        self.scheduler.shutdown()
        logger.info("News auto-publisher stopped")
        
    def publish_news_digest(self, manual=False):
        """Публикация дайджеста новостей"""
        try:
            logger.info(f"Starting news digest publication (manual={manual})")
            
            # Собираем новости
            items = fetch_all_news_last24h()
            
            if not items:
                msg = "😕 За последние 24 часа новостей не найдено"
                if manual:
                    self.bot.send_message(self.chat_id, msg, reply_markup=main_menu_kb())
                else:
                    self.bot.send_message(self.chat_id, msg)
                return
            
            # Отправляем заголовок дайджеста
            current_time = datetime.now(pytz.timezone(AUTO_NEWS_TIMEZONE))
            digest_type = "🔄 Ручная выгрузка" if manual else "⏰ Автоматическая выгрузка"
            
            header = (
                f"{digest_type}\n"
                f"📰 <b>Новостной дайджест</b>\n"
                f"🕐 {current_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"📊 Всего новостей за 24ч: {len(items)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )
            
            if manual:
                self.bot.send_message(
                    self.chat_id, 
                    header, 
                    parse_mode="HTML",
                    reply_markup=main_menu_kb()
                )
            else:
                self.bot.send_message(self.chat_id, header, parse_mode="HTML")
            
            # Сохраняем все новости в кэш для этого чата
            cache_key = f"news_cache_{self.chat_id}"
            user_state[cache_key] = {
                "items": items,
                "current_index": 0,
                "by_key": {}
            }
            
            # Отправляем первую порцию новостей
            self._send_news_batch(self.chat_id, 0, NEWS_BATCH_SIZE, manual)
            
            logger.info(f"News digest published successfully, total items: {len(items)}")
            
        except Exception as e:
            logger.error(f"Failed to publish news digest: {e}")
            error_msg = f"❌ Ошибка при выгрузке новостей: {str(e)[:100]}"
            try:
                self.bot.send_message(self.chat_id, error_msg, reply_markup=main_menu_kb())
            except:
                pass
    
    def _send_news_batch(self, chat_id, start_idx, count, manual=False):
        """Отправка порции новостей"""
        cache_key = f"news_cache_{chat_id}"
        cache = user_state.get(cache_key)
        
        if not cache:
            return
            
        items = cache["items"]
        end_idx = min(start_idx + count, len(items))
        by_key = cache.get("by_key", {})
        
        for i in range(start_idx, end_idx):
            item = items[i]
            title = item.get("title", "Без названия")
            url = item.get("url", "#")
            source = item.get("source", "")
            
            # Создаем ключ для новости
            key = item_key(title, url)
            by_key[key] = item
            
            # Формируем сообщение с заголовком и ссылкой
            msg = (
                f"<b>{html.escape(title)}</b>\n"
                f"📰 {html.escape(source)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )
            
            # Создаем клавиатуру с кнопками
            kb = InlineKeyboardMarkup()
            kb.row(
                InlineKeyboardButton("📖 Читать полностью", callback_data=f"read_full:{key}"),
                InlineKeyboardButton("🔗 Источник", url=url)
            )
            
            # Отправляем сообщение
            self.bot.send_message(
                chat_id,
                msg,
                parse_mode="HTML",
                reply_markup=kb,
                disable_web_page_preview=True
            )
            
            # Небольшая задержка между сообщениями
            time.sleep(0.3)
        
        # Обновляем кэш
        cache["current_index"] = end_idx
        cache["by_key"] = by_key
        user_state[cache_key] = cache
        
        # Если есть еще новости, показываем кнопку "Загрузить еще"
        if end_idx < len(items):
            more_kb = InlineKeyboardMarkup()
            more_kb.row(
                InlineKeyboardButton(
                    f"📥 Загрузить еще {NEWS_MORE_SIZE}", 
                    callback_data=f"load_more:{chat_id}"
                )
            )
            
            remaining = len(items) - end_idx
            msg = f"📊 Показано {end_idx} из {len(items)} новостей\nОсталось: {remaining}"
            
            self.bot.send_message(chat_id, msg, reply_markup=more_kb)
        else:
            self.bot.send_message(
                chat_id, 
                "✅ Все новости загружены!",
                reply_markup=main_menu_kb()
            )


# =========================
# Обработчики для новостей
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("read_full:"))
def on_read_full_news(c):
    """Обработчик кнопки 'Читать полностью'"""
    uid = c.from_user.id
    key = c.data.split(":", 1)[1]
    
    # Ищем новость в кэше
    cache_key = f"news_cache_{c.message.chat.id}"
    cache = user_state.get(cache_key)
    
    if not cache:
        bot.answer_callback_query(c.id, "Новость не найдена. Запустите выгрузку заново.", show_alert=True)
        return
    
    item = cache.get("by_key", {}).get(key)
    if not item:
        bot.answer_callback_query(c.id, "Новость устарела. Запустите выгрузку заново.", show_alert=True)
        return
    
    try:
        # Получаем полный текст и изображение
        title = item.get("title", "")
        full_text = item.get("full_text", "")
        
        # Если нет полного текста, пробуем загрузить
        if not full_text:
            full_text = fetch_article_full_text_generic(item.get("url", ""))
        
        # Получаем изображение
        image_url = item.get("image", "")
        photo_bytes = None
        
        if image_url:
            try:
                photo_bytes = get_cached_image(image_url)
            except Exception as e:
                logger.error(f"Failed to fetch image: {e}")
        
        # Очищаем текст
        clean_text = _clean_text(full_text) if full_text else "Полный текст не найден"
        
        # Отправляем уведомление о начале загрузки
        bot.send_message(c.message.chat.id, "⏳ Загружаю полный текст и фото...")
        
        # Отправляем фото, если есть
        if photo_bytes and check_file_size(photo_bytes):
            try:
                bot.send_photo(
                    c.message.chat.id,
                    photo=photo_bytes,
                    caption=f"<b>{html.escape(title)}</b>",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending photo: {e}")
                bot.send_message(
                    c.message.chat.id,
                    f"<b>{html.escape(title)}</b>",
                    parse_mode="HTML"
                )
        else:
            bot.send_message(
                c.message.chat.id,
                f"<b>{html.escape(title)}</b>",
                parse_mode="HTML"
            )
        
        # Отправляем полный текст
        # Разбиваем на части если текст очень длинный
        if len(clean_text) <= 4000:
            bot.send_message(c.message.chat.id, clean_text, parse_mode="HTML")
        else:
            # Разбиваем на части по 4000 символов
            text_parts = []
            remaining = clean_text
            while remaining:
                if len(remaining) <= 4000:
                    text_parts.append(remaining)
                    break
                else:
                    # Ищем место для разрыва
                    split_point = remaining[:4000].rfind('\n\n')
                    if split_point == -1:
                        split_point = remaining[:4000].rfind('. ')
                    if split_point == -1:
                        split_point = 4000
                    
                    text_parts.append(remaining[:split_point])
                    remaining = remaining[split_point:].lstrip()
            
            # Отправляем все части
            for i, part in enumerate(text_parts):
                if i == 0:
                    bot.send_message(c.message.chat.id, part, parse_mode="HTML")
                else:
                    bot.send_message(
                        c.message.chat.id,
                        f"<i>Продолжение ({i+1}/{len(text_parts)}):</i>\n\n{part}",
                        parse_mode="HTML"
                    )
        
        bot.answer_callback_query(c.id, "✅ Готово")
        
    except Exception as e:
        logger.error(f"Error sending full news: {e}")
        bot.answer_callback_query(c.id, "Ошибка при загрузке", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("load_more:"))
def on_load_more(c):
    """Обработчик кнопки 'Загрузить еще'"""
    chat_id = int(c.data.split(":", 1)[1])
    
    cache_key = f"news_cache_{chat_id}"
    cache = user_state.get(cache_key)
    
    if not cache:
        bot.answer_callback_query(c.id, "Кэш не найден. Запустите выгрузку заново.", show_alert=True)
        return
    
    current_idx = cache.get("current_index", 0)
    
    # Отправляем следующую порцию
    news_publisher._send_news_batch(chat_id, current_idx, NEWS_MORE_SIZE, manual=True)
    
    bot.answer_callback_query(c.id, f"Загружаю еще {NEWS_MORE_SIZE} новостей...")


# =========================
# Обработчик ручной выгрузки
# =========================
@bot.message_handler(func=lambda message: message.text == BTN_GET_NEWS_MANUAL)
def cmd_manual_news(message):
    """Ручной запуск выгрузки новостей"""
    uid = message.from_user.id
    
    # Проверяем, есть ли авто-выгрузка для этого чата
    if str(uid) != str(AUTO_NEWS_CHAT_ID):
        # Если это не тот чат, просто запускаем обычную выгрузку
        cmd_news(message)
        return
    
    bot.send_message(
        message.chat.id,
        "🔄 Запускаю ручную выгрузку новостей...",
        reply_markup=main_menu_kb()
    )
    
    # Запускаем выгрузку
    news_publisher.publish_news_digest(manual=True)


# =========================
# Template selection handler
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("tpl:"))
def on_tpl(c):
    uid = c.from_user.id
    tpl = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    st["template"] = tpl
    
    if tpl == "FDR_POST":
        st["step"] = "waiting_photo_fdr_post"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
        bot.send_message(
            c.message.chat.id,
            "💜 Выбран шаблон <b>Пост ФДР</b>\n\n"
            "📸 Пришли фото для поста.\n\n"
            "<i>Дальше нужно будет:</i>\n"
            "1️⃣ Отправить полный заголовок\n"
            "2️⃣ Отправить фразу для фиолетовой плашки\n"
            "3️⃣ Отправить основной текст",
            parse_mode="HTML"
        )
    else:
        if st.get("step") in {"waiting_template", None}:
            st["step"] = "waiting_photo"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок ✅")
        
        tpl_names = {
            'MN': 'МН',
            'CHP': 'ЧП ВМ',
            'AM': 'АМ',
            'FDR_STORY': 'Сторис ФДР'
        }
        tpl_name = tpl_names.get(tpl, tpl)
        bot.send_message(c.message.chat.id, f"Шаблон выбран: {tpl_name}. Пришли фото 📷")


# =========================
# Commands
# =========================
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")
    st["step"] = "idle"
    user_state[uid] = st

    bot.send_message(message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())
    bot.send_message(
        message.chat.id,
        "Команды:\n"
        "• /post — оформить пост\n"
        "• /news — получить новости за 24 часа\n"
        "• /template — выбрать шаблон (МН / ЧП ВМ / АМ / Сторис ФДР / Пост ФДР)\n",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(commands=["template"])
def cmd_template(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_template"
    user_state[uid] = st
    bot.send_message(message.chat.id, "Выбери шаблон оформления:", reply_markup=template_kb())


@bot.message_handler(commands=["post"])
def cmd_post(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")
    st["step"] = "waiting_template"
    user_state[uid] = st
    bot.send_message(message.chat.id, "Выбери шаблон оформления:", reply_markup=template_kb())


@bot.message_handler(commands=["news"])
def cmd_news(message):
    """Обычная команда получения новостей"""
    uid = message.from_user.id
    
    # Если это чат с авто-выгрузкой, используем расширенную версию
    if str(uid) == str(AUTO_NEWS_CHAT_ID):
        cmd_manual_news(message)
        return
    
    # Старая логика для остальных пользователей
    bot.send_message(message.chat.id, "Собираю новости за 24 часа… 🧲", reply_markup=main_menu_kb())
    items = fetch_all_news_last24h()
    set_news_cache(uid, items)
    send_news_batch(message.chat.id, uid, NEWS_FIRST_BATCH)


def send_news_batch(chat_id: int, uid: int, batch: int):
    cache = get_news_cache(uid)
    if not cache:
        bot.send_message(chat_id, "Кэш пуст. Нажми «Получить новости» или /news.", reply_markup=main_menu_kb())
        return

    items = cache["items"]
    pos = int(cache.get("pos", 0))
    if pos >= len(items):
        bot.send_message(chat_id, "Больше новостей нет ✅", reply_markup=main_menu_kb())
        return

    end = min(pos + batch, len(items))
    by_key = cache.get("by_key") or {}

    for it in items[pos:end]:
        title = (it.get("title") or "").strip()
        link = (it.get("url") or "").strip()
        src = (it.get("source") or "").strip()
        if not title or not link:
            continue

        key = item_key(title, link)
        by_key[key] = it

        msg = f"<b>{html.escape(title)}</b>\n\n{html.escape(src)}"
        bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=news_item_kb(key, link))

    cache["pos"] = end
    cache["by_key"] = by_key
    user_state[uid]["news_cache"] = cache

    if end < len(items):
        bot.send_message(chat_id, "Хочешь ещё?", reply_markup=news_more_kb())
    else:
        bot.send_message(chat_id, "Это всё на сейчас ✅", reply_markup=main_menu_kb())


@bot.callback_query_handler(func=lambda c: c.data in {"nmore", "nrefresh"})
def on_news_nav(c):
    uid = c.from_user.id

    if c.data == "nrefresh":
        bot.answer_callback_query(c.id, "Обновляю…")
        items = fetch_all_news_last24h()
        set_news_cache(uid, items)
        send_news_batch(c.message.chat.id, uid, NEWS_FIRST_BATCH)
        return

    bot.answer_callback_query(c.id, "Ок")
    send_news_batch(c.message.chat.id, uid, NEWS_MORE_BATCH)


@bot.callback_query_handler(func=lambda c: c.data.startswith("nfmt:") or c.data.startswith("nskip:"))
def on_news_item_action(c):
    uid = c.from_user.id
    cache = get_news_cache(uid)
    if not cache:
        bot.answer_callback_query(c.id, "Сначала /news", show_alert=True)
        return

    action, key = c.data.split(":", 1)

    if action == "nskip":
        try:
            bot.edit_message_text("🗑 Пропущено.", c.message.chat.id, c.message.message_id)
        except Exception:
            pass
        bot.answer_callback_query(c.id, "Ок")
        return

    it = (cache.get("by_key") or {}).get(key)
    if not it:
        bot.answer_callback_query(c.id, "Не нашёл новость. Нажми /news ещё раз.", show_alert=True)
        return

    title = (it.get("title") or "").strip()
    link = (it.get("url") or "").strip()
    image_url = (it.get("image") or "").strip()
    source_name = (it.get("source") or "").strip()

    photo_bytes = b""
    if image_url:
        try:
            photo_bytes = get_cached_image(image_url)
        except Exception as e:
            logger.error(f"Failed to fetch image {image_url}: {e}")
            photo_bytes = b""

    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")
    st["title"] = title
    st["source_url"] = link

    auto_body = (it.get("full_text") or "").strip()
    if not auto_body and source_name.lower() in {"tochka", "smartpress", "sb.by", "mlyn", "ont", "minsknews"}:
        try:
            auto_body = fetch_article_full_text_generic(link)
        except Exception as e:
            logger.error(f"Failed to fetch article text: {e}")
            auto_body = ""

    if not photo_bytes:
        st["step"] = "waiting_photo"
        st["prefill_title"] = title
        st["prefill_source"] = link
        if auto_body:
            st["prefill_body"] = auto_body
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Нужно фото")
        bot.send_message(
            c.message.chat.id,
            "Для этой новости не смог взять картинку.\nПришли фото 📷, а заголовок я уже подставлю.",
            reply_markup=main_menu_kb()
        )
        return

    warn_if_too_small(c.message.chat.id, photo_bytes)
    st["photo_bytes"] = photo_bytes

    if st["template"] == "FDR_STORY":
        if auto_body:
            try:
                card = make_card(photo_bytes, title, st["template"], auto_body)
                st["card_bytes"] = card.getvalue()
                st["body_raw"] = auto_body
                st["step"] = "waiting_action"
                user_state[uid] = st

                caption = build_caption_html(st["title"], st["body_raw"])
                bot.send_photo(
                    chat_id=c.message.chat.id,
                    photo=BytesIO(st["card_bytes"]),
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=preview_kb(st.get("source_url", "")),
                )
                bot.answer_callback_query(c.id, "Оформил ✅")
                return
            except Exception as e:
                logger.error(f"Error creating card: {e}")
                bot.answer_callback_query(c.id, "Ошибка карточки", show_alert=True)
                bot.send_message(c.message.chat.id, f"Ошибка при создании карточки: {e}", reply_markup=main_menu_kb())
                return
        else:
            st["step"] = "waiting_body_fdr"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Нужен текст")
            bot.send_message(
                c.message.chat.id,
                "✅ Карточка с фото готова!\n\nТеперь отправь ОСНОВНОЙ ТЕКСТ для сторис:",
                reply_markup=main_menu_kb()
            )
            return

    try:
        card = make_card(photo_bytes, title, st["template"])
        st["card_bytes"] = card.getvalue()

        if auto_body:
            st["body_raw"] = auto_body
            st["step"] = "waiting_action"
            user_state[uid] = st

            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(
                chat_id=c.message.chat.id,
                photo=BytesIO(st["card_bytes"]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=preview_kb(st.get("source_url", "")),
            )
            bot.answer_callback_query(c.id, "Оформил ✅")
            return

        st["step"] = "waiting_body"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок ✅")
        bot.send_message(c.message.chat.id, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.", reply_markup=main_menu_kb())

    except Exception as e:
        logger.error(f"Error creating card: {e}")
        bot.answer_callback_query(c.id, "Ошибка карточки", show_alert=True)
        bot.send_message(c.message.chat.id, f"Ошибка при создании карточки: {e}", reply_markup=main_menu_kb())


# =========================
# Post flow
# =========================
@bot.message_handler(content_types=["photo"])
def on_photo(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")

    if st.get("step") == "waiting_template":
        bot.send_message(message.chat.id, "Сначала выбери шаблон:", reply_markup=template_kb())
        return

    # НОВЫЙ БЛОК: обработка для FDR_POST
    if st.get("step") == "waiting_photo_fdr_post":
        try:
            file_id = message.photo[-1].file_id
            photo_bytes = tg_file_bytes(file_id)

            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return

            warn_if_too_small(message.chat.id, photo_bytes)

            st["photo_bytes"] = photo_bytes
            st["step"] = "waiting_title_fdr_post"
            user_state[uid] = st

            bot.reply_to(
                message,
                "📸 Фото сохранено!\n\n"
                "Теперь отправь <b>ПОЛНЫЙ ЗАГОЛОВОК</b> поста:",
                parse_mode="HTML"
            )
            return
        except Exception as e:
            logger.error(f"Error processing photo for FDR_POST: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return

    try:
        file_id = message.photo[-1].file_id
        photo_bytes = tg_file_bytes(file_id)

        if not check_file_size(photo_bytes):
            bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
            return

        warn_if_too_small(message.chat.id, photo_bytes)

        st["photo_bytes"] = photo_bytes

        if st.get("prefill_title"):
            st["title"] = st["prefill_title"]
            st["source_url"] = st.get("prefill_source", "") or ""

            try:
                if st["template"] == "FDR_STORY":
                    if st.get("prefill_body"):
                        card = make_card(st["photo_bytes"], st["title"], st["template"], st["prefill_body"])
                        st["card_bytes"] = card.getvalue()
                        st["body_raw"] = st["prefill_body"]
                        st.pop("prefill_body", None)
                        st.pop("prefill_title", None)
                        st.pop("prefill_source", None)
                        st["step"] = "waiting_action"
                        user_state[uid] = st

                        caption = build_caption_html(st["title"], st["body_raw"])
                        bot.send_photo(
                            chat_id=message.chat.id,
                            photo=BytesIO(st["card_bytes"]),
                            caption=caption,
                            parse_mode="HTML",
                            reply_markup=preview_kb(st.get("source_url", "")),
                        )
                        bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")
                        return
                    else:
                        st["step"] = "waiting_body_fdr"
                        st.pop("prefill_title", None)
                        st.pop("prefill_source", None)
                        user_state[uid] = st
                        bot.reply_to(message, "Фото получено ✅ Заголовок уже есть. Теперь пришли ОСНОВНОЙ ТЕКСТ для сторис.")
                        return

                card = make_card(st["photo_bytes"], st["title"], st["template"])
                st["card_bytes"] = card.getvalue()

                if st.get("prefill_body"):
                    st["body_raw"] = st["prefill_body"]
                    st.pop("prefill_body", None)
                    st.pop("prefill_title", None)
                    st.pop("prefill_source", None)
                    st["step"] = "waiting_action"
                    user_state[uid] = st

                    caption = build_caption_html(st["title"], st["body_raw"])
                    bot.send_photo(
                        chat_id=message.chat.id,
                        photo=BytesIO(st["card_bytes"]),
                        caption=caption,
                        parse_mode="HTML",
                        reply_markup=preview_kb(st.get("source_url", "")),
                    )
                    bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")
                    return

                st["step"] = "waiting_body"
                st.pop("prefill_title", None)
                st.pop("prefill_source", None)
                user_state[uid] = st
                bot.reply_to(message, "Фото получено ✅ Заголовок уже есть. Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
            except Exception as e:
                logger.error(f"Error creating card: {e}")
                st["step"] = "waiting_photo"
                user_state[uid] = st
                bot.reply_to(message, f"Ошибка при создании карточки: {e}")
            return

        if st["template"] == "FDR_STORY":
            st["step"] = "waiting_title_fdr"
        else:
            st["step"] = "waiting_title"

        user_state[uid] = st
        bot.reply_to(message, "Фото получено ✅ Теперь отправь ЗАГОЛОВОК.")

    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")


@bot.message_handler(content_types=["document"])
def on_document(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")

    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        bot.reply_to(message, "Пришли картинку (JPG/PNG).")
        return

    try:
        photo_bytes = tg_file_bytes(doc.file_id)

        if not check_file_size(photo_bytes):
            bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
            return

        warn_if_too_small(message.chat.id, photo_bytes)

        st["photo_bytes"] = photo_bytes
        if st["template"] == "FDR_STORY":
            st["step"] = "waiting_title_fdr"
        else:
            st["step"] = "waiting_title"
        user_state[uid] = st
        bot.reply_to(message, "Картинка получена ✅ Теперь отправь ЗАГОЛОВОК.")

    except Exception as e:
        logger.error(f"Error processing document: {e}")
        bot.reply_to(message, f"❌ Ошибка при обработке документа: {e}")


@bot.message_handler(content_types=["text"])
def on_text(message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    st = user_state.get(uid) or {"template": "MN", "step": "idle"}

    if text == BTN_POST or text.lower() in {"оформить пост", "оформление поста"}:
        cmd_post(message)
        return

    if text == BTN_NEWS or text.lower() in {"получить новости", "новости", "дай новости"}:
        cmd_news(message)
        return

    if text == BTN_GET_NEWS_MANUAL:
        cmd_manual_news(message)
        return

    step = st.get("step")

    # НОВЫЙ БЛОК: получение заголовка для FDR_POST
    if step == "waiting_title_fdr_post":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым. Отправь текст:")
            return
        
        st["full_title"] = text
        st["step"] = "waiting_highlight_fdr_post"
        user_state[uid] = st
        
        bot.reply_to(
            message,
            f"✅ Заголовок сохранён!\n\n"
            f"<b>{html.escape(text)}</b>\n\n"
            f"🎯 Теперь отправь <b>ФРАЗУ</b>, которую нужно выделить фиолетовой плашкой:\n\n"
            f"<i>(можно скопировать часть заголовка или написать свою)</i>",
            parse_mode="HTML"
        )
        return

    # НОВЫЙ БЛОК: получение выделяемой фразы для FDR_POST
    if step == "waiting_highlight_fdr_post":
        if not text:
            bot.reply_to(message, "❌ Фраза не может быть пустой. Отправь текст:")
            return
        
        st["highlight_phrase"] = text
        st["step"] = "waiting_body_fdr_post"
        user_state[uid] = st
        
        # Сразу показываем превью с выделенной фразой
        try:
            card = make_card(
                st["photo_bytes"],
                st["full_title"],
                st["template"],
                highlight_phrase=st["highlight_phrase"]
            )
            st["card_bytes"] = card.getvalue()
            
            # Отправляем превью
            bot.send_photo(
                message.chat.id,
                photo=BytesIO(st["card_bytes"]),
                caption=(
                    f"💜 <b>Предпросмотр</b>\n\n"
                    f"Выделенная фраза: <b>{html.escape(text)}</b>\n\n"
                    f"Теперь отправь <b>ОСНОВНОЙ ТЕКСТ</b> поста:"
                ),
                parse_mode="HTML"
            )
            
        except Exception as e:
            logger.error(f"Error creating FDR_POST preview: {e}")
            bot.reply_to(
                message, 
                f"❌ Ошибка при создании превью: {e}\n\n"
                f"Попробуй отправить фразу ещё раз или начни заново с /post"
            )
            # Возвращаем на шаг выбора фразы
            st["step"] = "waiting_highlight_fdr_post"
            user_state[uid] = st
        return

    # НОВЫЙ БЛОК: получение основного текста для FDR_POST
    if step == "waiting_body_fdr_post":
        st["body_raw"] = text
        
        # Извлекаем ссылку из текста если есть
        body_src = extract_source_url(text)
        if body_src:
            st["source_url"] = body_src
        
        st["step"] = "waiting_action"
        user_state[uid] = st
        
        # Создаем финальную карточку
        try:
            card = make_card(
                st["photo_bytes"],
                st["full_title"],
                st["template"],
                body_text=st["body_raw"],
                highlight_phrase=st["highlight_phrase"]
            )
            
            caption = build_caption_html(st["full_title"], st["body_raw"])
            bot.send_photo(
                chat_id=message.chat.id,
                photo=BytesIO(card.getvalue()),
                caption=caption,
                parse_mode="HTML",
                reply_markup=preview_kb(st.get("source_url", "")),
            )
            bot.reply_to(
                message, 
                "✅ Пост готов! Нажми кнопку под превью для публикации.",
                reply_markup=main_menu_kb()
            )
        except Exception as e:
            logger.error(f"Error creating final FDR_POST card: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании финальной карточки: {e}")
        return

    if step == "waiting_title_fdr":
        st["title"] = text
        st["step"] = "waiting_body_fdr"
        user_state[uid] = st
        bot.reply_to(message, "Заголовок сохранен ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ для сторис.")
        return

    if step == "waiting_body_fdr":
        if not st.get("photo_bytes"):
            bot.reply_to(message, "❌ Фото потерялось. Начни заново с /post")
            clear_state(uid)
            return

        st["body_raw"] = text
        body_src = extract_source_url(text)
        if body_src:
            st["source_url"] = body_src

        try:
            card = make_card(
                st["photo_bytes"],
                st["title"],
                st.get("template", "FDR_STORY"),
                st["body_raw"]
            )
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st

            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(
                chat_id=message.chat.id,
                photo=BytesIO(st["card_bytes"]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=preview_kb(st.get("source_url", "")),
            )
            bot.reply_to(message, "Сторис готова ✅ Нажми кнопку.")
        except Exception as e:
            logger.error(f"Error creating story: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании сторис: {e}")
            st["step"] = "waiting_photo"
            user_state[uid] = st
        return

    if step == "waiting_title":
        st["title"] = text
        try:
            card = make_card(st["photo_bytes"], st["title"], st.get("template", "MN"))
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_body"
            user_state[uid] = st
            bot.reply_to(message, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
        except Exception as e:
            logger.error(f"Error creating card: {e}")
            st["step"] = "waiting_photo"
            user_state[uid] = st
            bot.reply_to(message, f"Ошибка при создании карточки: {e}")

    elif step == "waiting_body":
        st["body_raw"] = text
        body_src = extract_source_url(text)
        if body_src:
            st["source_url"] = body_src

        st["step"] = "waiting_action"
        user_state[uid] = st
        caption = build_caption_html(st["title"], st["body_raw"])
        bot.send_photo(
            chat_id=message.chat.id,
            photo=BytesIO(st["card_bytes"]),
            caption=caption,
            parse_mode="HTML",
            reply_markup=preview_kb(st.get("source_url", "")),
        )
        bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")

    elif step == "waiting_action":
        bot.reply_to(message, "Нажми кнопку под превью ✅✏️❌ (или выбери действие в меню снизу).", reply_markup=main_menu_kb())

    elif step == "waiting_template":
        bot.send_message(message.chat.id, "Выбери шаблон кнопками:", reply_markup=template_kb())

    else:
        user_state[uid] = st
        bot.send_message(message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())


@bot.callback_query_handler(func=lambda call: call.data in ["publish", "edit_body", "edit_title", "cancel"])
def on_action(call):
    uid = call.from_user.id
    st = user_state.get(uid)

    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(call.id, "Нет активного превью. Начни с «Оформить пост».")
        return

    if call.data == "publish":
        try:
            # Для FDR_POST используем full_title, для остальных title
            title_to_use = st["full_title"] if st.get("template") == "FDR_POST" and "full_title" in st else st.get("title", "")
            caption = build_caption_html(title_to_use, st["body_raw"])
            bot.send_photo(
                CHANNEL,
                BytesIO(st["card_bytes"]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=channel_kb()
            )
            bot.answer_callback_query(call.id, "Опубликовано ✅")
            bot.send_message(call.message.chat.id, "Готово ✅", reply_markup=main_menu_kb())
            tpl = st.get("template", "MN")
            user_state[uid] = {"step": "idle", "template": tpl}
        except Exception as e:
            logger.error(f"Error publishing: {e}")
            bot.answer_callback_query(call.id, "Ошибка публикации")
            bot.send_message(call.message.chat.id, f"Не смог опубликовать: {e}", reply_markup=main_menu_kb())

    elif call.data == "edit_body":
        if st.get("template") == "FDR_STORY":
            st["step"] = "waiting_body_fdr"
            user_state[uid] = st
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(call.message.chat.id, "Пришли новый ОСНОВНОЙ ТЕКСТ для сторис.", reply_markup=main_menu_kb())
        elif st.get("template") == "FDR_POST":
            st["step"] = "waiting_body_fdr_post"
            user_state[uid] = st
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(call.message.chat.id, "Пришли новый ОСНОВНОЙ ТЕКСТ.", reply_markup=main_menu_kb())
        else:
            st["step"] = "waiting_body"
            user_state[uid] = st
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(call.message.chat.id, "Пришли новый ОСНОВНОЙ ТЕКСТ.", reply_markup=main_menu_kb())

    elif call.data == "edit_title":
        if st.get("template") == "FDR_STORY":
            st["step"] = "waiting_title_fdr"
            user_state[uid] = st
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(call.message.chat.id, "Пришли новый ЗАГОЛОВОК для сторис.", reply_markup=main_menu_kb())
        elif st.get("template") == "FDR_POST":
            st["step"] = "waiting_title_fdr_post"
            user_state[uid] = st
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(call.message.chat.id, "Пришли новый ПОЛНЫЙ ЗАГОЛОВОК.", reply_markup=main_menu_kb())
        else:
            st["step"] = "waiting_title"
            user_state[uid] = st
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(call.message.chat.id, "Пришли новый ЗАГОЛОВОК.", reply_markup=main_menu_kb())

    elif call.data == "cancel":
        bot.answer_callback_query(call.id, "Отменено")
        tpl = st.get("template", "MN")
        user_state[uid] = {"step": "idle", "template": tpl}
        bot.send_message(call.message.chat.id, "Отменил ❌", reply_markup=main_menu_kb())


# =========================
# Additional commands
# =========================
@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    stats = {
        "active_users": len(user_state),
        "cache_size": get_cached_image.cache_info().currsize if hasattr(get_cached_image, 'cache_info') else 0,
        "pool_connections": len(SESSION.adapters),
    }

    stats_text = "📊 Статистика:\n"
    for key, value in stats.items():
        stats_text += f"• {key}: {value}\n"

    bot.reply_to(message, stats_text)


@bot.message_handler(commands=["health"])
def cmd_health(message):
    health_data = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "fonts_loaded": all(os.path.exists(f) for f in [FONT_MN, FONT_CHP, FONT_AM, FONT_MONTSERRAT_BLACK]),
    }

    bot.reply_to(message, f"✅ Health check:\n{json.dumps(health_data, indent=2, ensure_ascii=False)}")


# =========================
# Создание экземпляра планировщика
# =========================
news_publisher = NewsAutoPublisher(bot, AUTO_NEWS_CHAT_ID)


# =========================
# Запуск бота
# =========================
if __name__ == "__main__":
    logger.info("Starting bot...")
    ensure_fonts()
    logger.info("Fonts loaded successfully")
    
    # Запускаем планировщик новостей
    if AUTO_NEWS_CHAT_ID:
        news_publisher.start()
    
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        # Останавливаем планировщик при падении бота
        if AUTO_NEWS_CHAT_ID:
            news_publisher.stop()
        raise
