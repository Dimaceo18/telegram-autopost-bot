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
import fcntl
import atexit
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

# Импорты для видео
#import numpy as np
#from moviepy.editor import VideoFileClip

# Импорты для автоматической выгрузки
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz


# Проверка на единственный экземпляр
lock_file = '/tmp/bot_instance.lock'

def check_single_instance():
    try:
        fd = open(lock_file, 'w')
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        def unlock():
            try:
                fcntl.lockf(fd, fcntl.LOCK_UN)
                fd.close()
                if os.path.exists(lock_file):
                    os.unlink(lock_file)
            except:
                pass
        
        atexit.register(unlock)
        return True
    except IOError:
        return False

if not check_single_instance():
    print("Another instance is already running. Exiting.")
    sys.exit(1)


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
AUTO_NEWS_CHAT_ID = os.getenv("AUTO_NEWS_CHAT_ID")
AUTO_NEWS_TIMEZONE = os.getenv("AUTO_NEWS_TIMEZONE", "Europe/Minsk")
NEWS_BATCH_SIZE = 20
NEWS_MORE_SIZE = 10

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
MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_VIDEO_SIZE = 50 * 1024 * 1024  # 50 MB
CACHE_TTL = 3600
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

FDR_POST_PURPLE_COLOR = (122, 58, 240)
FDR_POST_PLATE_HEIGHT_PCT = 0.15
TEXT_POSITION_TOP = "top"
TEXT_POSITION_BOTTOM = "bottom"

# Константы для видео
VIDEO_TARGET_SIZE = (750, 938)  # Как у постов
VIDEO_FPS = 24
VIDEO_BITRATE = "2000k"


# =========================
# UI BUTTONS
# =========================
BTN_POST = "📝 Оформить пост"
BTN_NEWS = "📰 Получить новости"
BTN_GET_NEWS_MANUAL = "📰 Выгрузить новости сейчас"
BTN_ENHANCE = "✨ Улучшить качество"

def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(BTN_POST), KeyboardButton(BTN_NEWS))
    kb.row(KeyboardButton(BTN_GET_NEWS_MANUAL), KeyboardButton(BTN_ENHANCE))
    kb.row(KeyboardButton("🎥 Видео"), KeyboardButton("🎬 Видео в GIF"))
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
        "timeout": 60,
        "headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/"
        }
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
})

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

user_state: Dict[int, Dict] = {}


# =========================
# Graceful shutdown
# =========================
def signal_handler(sig, frame):
    logger.info("Shutting down gracefully...")
    if AUTO_NEWS_CHAT_ID and 'news_publisher' in globals():
        news_publisher.stop()
    bot.stop_polling()
    try:
        if os.path.exists(lock_file):
            os.unlink(lock_file)
    except:
        pass
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
def http_get(url: str, timeout: int = REQUEST_TIMEOUT, headers: dict = None) -> str:
    if not validate_url(url):
        raise ValueError(f"Invalid URL: {url}")
    try:
        request_headers = SESSION.headers.copy()
        if headers:
            request_headers.update(headers)
            
        r = SESSION.get(url, timeout=timeout, headers=request_headers)
        r.raise_for_status()
        return r.text
    except requests.exceptions.Timeout:
        logger.error(f"Timeout error for {url}")
        raise
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error for {url}")
        raise
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            logger.error(f"Access forbidden (403) for {url} - site is blocking requests")
            return ""
        raise
    except Exception as e:
        logger.error(f"HTTP error for {url}: {e}")
        raise


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


def _extract_article_text_from_soup(soup: BeautifulSoup) -> str:
    """Извлекает только чистый текст статьи"""
    
    # Удаляем все ненужные элементы
    for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'button', 'iframe', 'noscript']):
        tag.decompose()
    
    # Удаляем элементы по классам
    for tag in soup.find_all(class_=re.compile(
        r'(menu|sidebar|footer|header|comment|widget|banner|ad|social|share|related|popular|tags|copyright|newsletter|subscription|modal|popup|overlay|cookie|recommend|promo|teaser|adv)',
        re.I
    )):
        tag.decompose()
    
    # Ищем основной контент
    article = None
    
    # Приоритетные селекторы
    selectors = [
        {'selector': 'article', 'type': 'tag'},
        {'selector': 'main', 'type': 'tag'},
        {'selector': '.post-content', 'type': 'class'},
        {'selector': '.entry-content', 'type': 'class'},
        {'selector': '.article-content', 'type': 'class'},
        {'selector': '.news-text', 'type': 'class'},
        {'selector': '.article-text', 'type': 'class'},
        {'selector': '[itemprop="articleBody"]', 'type': 'attr'},
    ]
    
    for sel in selectors:
        if sel['type'] == 'class':
            article = soup.find(class_=re.compile(sel['selector'], re.I))
        elif sel['type'] == 'tag':
            article = soup.find(sel['selector'])
        elif sel['type'] == 'attr':
            article = soup.find(attrs={'itemprop': 'articleBody'})
        if article:
            break
    
    if not article:
        article = soup.body
    
    if not article:
        return ""
    
    # Собираем текст из параграфов
    paragraphs = []
    for p in article.find_all(['p'], recursive=True):
        text = p.get_text(strip=True)
        if not text or len(text) < 40:
            continue
        
        # Проверяем на рекламу
        low_text = text.lower()
        if any(x in low_text for x in ['читайте также', 'реклама', 'источник:', 'подпишись']):
            continue
        
        paragraphs.append(text)
    
    return '\n\n'.join(paragraphs)


def _extract_text_from_soup(soup: BeautifulSoup) -> str:
    return _extract_article_text_from_soup(soup)


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
    source_headers = source.get("headers", {})

    candidates: List[Tuple[str, str]] = []
    seen = set()
    
    for start_url in start_urls:
        try:
            timeout = source.get("timeout", REQUEST_TIMEOUT)
            page_html = http_get(start_url, timeout=timeout, headers=source_headers)
            
            if not page_html or len(page_html) < 1000:
                logger.warning(f"[NEWS-WARNING] {source['name']} returned too short content: {len(page_html)} chars")
                continue
                
        except requests.exceptions.Timeout:
            logger.error(f"[NEWS-ERROR] {source['name']} timeout for {start_url}")
            continue
        except requests.exceptions.ConnectionError:
            logger.error(f"[NEWS-ERROR] {source['name']} connection error for {start_url}")
            continue
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
            timeout = source.get("timeout", REQUEST_TIMEOUT)
            art_html = http_get(href, timeout=timeout, headers=source_headers)
            
            if not art_html or len(art_html) < 500:
                logger.warning(f"[NEWS-WARNING] {source['name']} article too short: {href}")
                continue
                
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
        except requests.exceptions.Timeout:
            logger.error(f"[NEWS-ERROR] {source['name']} timeout for article {href}")
            continue
        except Exception as e:
            logger.error(f"[NEWS-ERROR] {source['name']} article={href} error={e}")
            continue
    return out


def fetch_article_full_text_generic(url: str) -> str:
    """Получает только чистый текст статьи"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Referer': 'https://www.google.com/',
        }
        
        timeout = 45
        r = SESSION.get(url, timeout=timeout, headers=headers)
        r.raise_for_status()
        
        page_html = r.text
        
        if not page_html or len(page_html) < 500:
            return ""
        
        soup = BeautifulSoup(page_html, "lxml")
        return _extract_article_text_from_soup(soup)
        
    except Exception as e:
        logger.error(f"Failed to fetch article text from {url}: {e}")
        return ""


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# =========================
# Кнопки для выбора источников новостей
# =========================

SOURCE_NAMES = {
    "onliner": "Onliner",
    "sputnik": "Sputnik",
    "telegraf": "Telegraf",
    "tochka": "Tochka",
    "smartpress": "Smartpress",
    "minsknews": "Minsknews",
    "mlyn": "Mlyn",
    "ont": "ONT"
}

def news_sources_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for source_id, source_name in SOURCE_NAMES.items():
        buttons.append(InlineKeyboardButton(source_name, callback_data=f"src:{source_id}"))
    kb.add(*buttons)
    kb.row(
        InlineKeyboardButton("🌐 Собрать везде", callback_data="src:all"),
        InlineKeyboardButton("❌ Отмена", callback_data="src:cancel")
    )
    return kb

def save_sources_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Сохранить выбор", callback_data="src:save"),
        InlineKeyboardButton("🔄 Выбрать заново", callback_data="src:reset")
    )
    kb.row(
        InlineKeyboardButton("❌ Отмена", callback_data="src:cancel")
    )
    return kb


# =========================
# Функция для сбора новостей из выбранных источников
# =========================
def fetch_news_from_sources(source_ids: List[str]) -> List[Dict]:
    merged: List[Dict] = []
    by_url = set()
    
    selected_sources = [src for src in NEWS_SOURCES if src["id"] in source_ids]
    
    if not selected_sources:
        selected_sources = NEWS_SOURCES
    
    for src in selected_sources:
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

    return diversified


def fetch_all_news_last24h() -> List[Dict]:
    return fetch_news_from_sources(list(SOURCE_NAMES.keys()))


# =========================
# Caption formatting
# =========================
RU_STOP = {
    "и", "в", "во", "на", "но", "а", "что", "это", "как", "к", "по", "из", "за", "для", "с", "со", "у", "от", "до",
    "при", "без", "над", "под", "же", "ли", "то", "не", "ни", "да", "нет", "уже", "еще", "ещё", "там", "тут",
}

CATEGORY_RULES = [
    ("🚨", ["дтп", "авар", "пожар", "взрыв", "происшеств", "чп", "полици", "милици"]),
    ("✈️", ["белавиа", "рейс", "аэропорт", "самолет", "полет"]),
    ("🚇", ["метро", "станци", "маршрут", "автобус", "троллейбус", "трамвай"]),
    ("💳", ["банк", "технобанк", "карта", "налог", "выплат"]),
    ("🏷️", ["скидк", "распрод", "акци", "дешев", "бесплат"]),
    ("🎫", ["концерт", "афиша", "выставк", "фестиваль"]),
    ("🌦️", ["погод", "шторм", "ветер", "снег", "дожд"]),
    ("🏥", ["больниц", "врач", "здоров", "вакцин"]),
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
        if wl in RU_STOP or len(wl) < 7:
            continue
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


def build_caption_tg(full_text: str) -> str:
    paragraphs = full_text.strip().split('\n\n')
    if not paragraphs:
        return ""
    
    title = paragraphs[0].strip()
    title_safe = html.escape(title)
    
    body_parts = []
    for p in paragraphs[1:]:
        if p.strip():
            body_parts.append(html.escape(p.strip()))
    
    body_text = '\n\n'.join(body_parts) if body_parts else ""
    
    links = (
        "\n\n"
        "🔗 <a href='https://t.me/vestiminska'>Все новости Минска</a>\n"
        "📝 <a href='https://t.me/prishlinews_bot'>Прислать новость</a>"
    )
    
    return f"<b>{title_safe}</b>\n\n{body_text}{links}"


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
# Улучшение качества изображения
# =========================
def enhance_image_quality(image_bytes: bytes) -> BytesIO:
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        img = img.filter(ImageFilter.SMOOTH_MORE)
        enhancer_sharpness = ImageEnhance.Sharpness(img)
        img = enhancer_sharpness.enhance(1.30)
        enhancer_color = ImageEnhance.Color(img)
        img = enhancer_color.enhance(1.20)
        enhancer_contrast = ImageEnhance.Contrast(img)
        img = enhancer_contrast.enhance(1.20)
        enhancer_brightness = ImageEnhance.Brightness(img)
        img = enhancer_brightness.enhance(1.05)
        output = BytesIO()
        img.save(output, format="JPEG", quality=98, optimize=True)
        output.seek(0)
        return output
    except Exception as e:
        logger.error(f"Error enhancing image: {e}")
        raise


def enhance_image_quality_pro(image_bytes: bytes) -> BytesIO:
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        img = img.filter(ImageFilter.MedianFilter(size=3))
        for _ in range(2):
            enhancer_sharpness = ImageEnhance.Sharpness(img)
            img = enhancer_sharpness.enhance(1.20)
        enhancer_color = ImageEnhance.Color(img)
        img = enhancer_color.enhance(1.25)
        enhancer_contrast = ImageEnhance.Contrast(img)
        img = enhancer_contrast.enhance(1.25)
        enhancer_brightness = ImageEnhance.Brightness(img)
        img = enhancer_brightness.enhance(1.03)
        output = BytesIO()
        img.save(output, format="JPEG", quality=98, optimize=True)
        output.seek(0)
        return output
    except Exception as e:
        logger.error(f"Error enhancing image pro: {e}")
        return enhance_image_quality(image_bytes)


# =========================
# Функции для градиентов
# =========================
def apply_top_gradient(img: Image.Image, height_pct: float, max_alpha: int = 165) -> Image.Image:
    w, h = img.size
    gh = int(h * height_pct)
    if gh <= 0:
        return img

    overlay_alpha = Image.new("L", (w, h), 0)
    grad = Image.new("L", (1, gh), 0)
    for y in range(gh):
        a = int(max_alpha * (1 - y / max(1, gh - 1)))
        grad.putpixel((0, y), a)
    grad = grad.resize((w, gh))
    overlay_alpha.paste(grad, (0, 0))

    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    base = img.convert("RGBA")
    overlay = Image.composite(black, Image.new("RGBA", (w, h), (0, 0, 0, 0)), overlay_alpha)
    out = Image.alpha_composite(base, overlay)
    return out.convert("RGB")


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


def apply_bottom_gradient_soft(img: Image.Image, height_pct: float, max_alpha: int = 165) -> Image.Image:
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
def make_card_mn(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP) -> BytesIO:
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
    
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    text = (title_text or "").strip().upper()

    font, lines, heights, spacing, total_text_height = fit_text_block(
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

    if text_position == TEXT_POSITION_TOP:
        title_y = margin_top
        footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    else:
        title_y = img.height - margin_bottom - total_text_height - 10
        footer_y = 10

    y = title_y
    for i, ln in enumerate(lines):
        draw.text((block_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing

    footer_x = (img.width - footer_w) // 2
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_mn2(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.55)
    
    if text_position == TEXT_POSITION_TOP:
        img = apply_top_gradient(img, height_pct=CHP_GRADIENT_PCT * 0.75, max_alpha=165)
    else:
        img = apply_bottom_gradient_soft(img, height_pct=CHP_GRADIENT_PCT * 0.75, max_alpha=165)
    
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
    
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    text = (title_text or "").strip().upper()

    font, lines, heights, spacing, total_text_height = fit_text_block(
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

    if text_position == TEXT_POSITION_TOP:
        title_y = margin_top
        footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    else:
        title_y = img.height - margin_bottom - total_text_height - 10
        footer_y = 10

    y = title_y
    for i, ln in enumerate(lines):
        draw.text((block_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing

    footer_x = (img.width - footer_w) // 2
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
    for p in paragraphs:
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
        all_lines.append("")
    while all_lines and all_lines[-1] == "":
        all_lines.pop()
    return all_lines


def _draw_story_text(draw, text, box, font, fill=(255, 255, 255), align="center", valign="center",
                     line_gap=10, paragraph_gap_extra=10):
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1

    lines = _wrap_text_preserve_paragraphs(draw, text, font, max_w)
    if not lines:
        return

    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
    total_h = 0
    for line in lines:
        if line == "":
            total_h += paragraph_gap_extra
        else:
            total_h += line_h + line_gap

    if valign == "top":
        y = y1
    else:
        y = y1 + (max_h - total_h) // 2

    for line in lines:
        if line == "":
            y += paragraph_gap_extra
            continue
        line_w = font.getbbox(line)[2] - font.getbbox(line)[0]
        if align == "center":
            x = x1 + (max_w - line_w) // 2
        elif align == "left":
            x = x1
        else:
            x = x2 - line_w
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + line_gap


def _fit_story_text(draw, text, box, min_size, max_size, line_gap_ratio=0.18, paragraph_gap_ratio=0.35):
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

        line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
        gap = max(4, int(line_h * line_gap_ratio))
        paragraph_gap = max(gap + 2, int(line_h * paragraph_gap_ratio))

        total_h = 0
        max_line_w = 0
        for line in lines:
            if line == "":
                total_h += paragraph_gap
                continue
            lw = font.getbbox(line)[2] - font.getbbox(line)[0]
            max_line_w = max(max_line_w, lw)
            total_h += line_h + gap

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

    header_box = (padding, photo_h + padding, STORY_W - padding, photo_h + header_h - padding)
    body_box = (padding, photo_h + header_h + padding, STORY_W - padding, STORY_H - padding)

    title_font, title_gap, title_paragraph_gap = _fit_story_text(
        draw, title, header_box, min_size=28, max_size=54,
        line_gap_ratio=0.08, paragraph_gap_ratio=0.18
    )

    _draw_story_text(draw, title, header_box, title_font, fill=(255, 255, 255),
                     align="center", valign="center", line_gap=title_gap,
                     paragraph_gap_extra=title_paragraph_gap)

    body_font, body_gap, body_paragraph_gap = _fit_story_text(
        draw, body_text, body_box, min_size=14, max_size=30,
        line_gap_ratio=0.10, paragraph_gap_ratio=0.32
    )

    _draw_story_text(draw, body_text, body_box, body_font, fill=(255, 255, 255),
                     align="left", valign="top", line_gap=body_gap,
                     paragraph_gap_extra=body_paragraph_gap)

    return save_jpeg_to_bytes(canvas)


def make_card_fdr_post(photo_bytes: bytes, title_text: str, highlight_phrase: str) -> BytesIO:
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
    
    title_text_upper = title_text.strip().upper()
    highlight_phrase_upper = highlight_phrase.strip().upper()
    highlight_words = set(highlight_phrase_upper.split())
    
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=title_text_upper,
        font_path=FONT_CHP,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(img.height * 0.11),
        min_size=16,
        line_spacing_ratio=0.22
    )
    
    base_y = img.height - margin_bottom - total_h
    
    # Рисуем плашки
    y = base_y
    for line_idx, line in enumerate(lines):
        line_words = line.split()
        current_x = margin_x
        
        for word in line_words:
            word_bbox = draw.textbbox((current_x, y), word, font=font)
            word_x1, word_y1, word_x2, word_y2 = word_bbox
            
            if word in highlight_words:
                padding = 10
                draw.rectangle(
                    [word_x1 - padding, word_y1 - padding,
                     word_x2 + padding, word_y2 + padding],
                    fill=FDR_POST_PURPLE_COLOR
                )
            
            if word != line_words[-1]:
                space_width = text_width(draw, " ", font)
                current_x += text_width(draw, word, font) + space_width
            else:
                current_x += text_width(draw, word, font)
        
        y += heights[line_idx] + spacing
    
    # Рисуем текст
    y = base_y
    for line_idx, line in enumerate(lines):
        line_words = line.split()
        current_x = margin_x
        
        for word in line_words:
            draw.text((current_x, y), word, font=font, fill="white")
            if word != line_words[-1]:
                space_width = text_width(draw, " ", font)
                current_x += text_width(draw, word, font) + space_width
            else:
                current_x += text_width(draw, word, font)
        
        y += heights[line_idx] + spacing
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_mn_tg(photo_bytes: bytes, title_text: str) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
    
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    font_size = int(img.width * 0.08)
    font = ImageFont.truetype(FONT_MN, font_size)
    
    text_bbox = draw.textbbox((0, 0), FOOTER_TEXT, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    x = (img.width - text_width) // 2
    y = int(img.height * 0.2) - (text_height // 2)
    
    draw.text((x, y), FOOTER_TEXT, font=font, fill=(255, 255, 255, 38))
    
    result = Image.alpha_composite(img, overlay)
    result = result.convert("RGB")
    
    out = BytesIO()
    result.save(out, format="JPEG", quality=95, optimize=True)
    out.seek(0)
    return out


def make_card(photo_bytes: bytes, title_text: str, template: str, body_text: str = "", highlight_phrase: str = "", text_position: str = TEXT_POSITION_TOP) -> BytesIO:
    if template == "CHP":
        return make_card_chp(photo_bytes, title_text)
    if template == "AM":
        return make_card_am(photo_bytes, title_text)
    if template == "FDR_STORY":
        return make_card_fdr_story(photo_bytes, title_text, body_text)
    if template == "FDR_POST":
        return make_card_fdr_post(photo_bytes, title_text, highlight_phrase)
    if template == "MN_TG":
        return make_card_mn_tg(photo_bytes, title_text)
    if template == "MN2":
        return make_card_mn2(photo_bytes, title_text, text_position)
    return make_card_mn(photo_bytes, title_text, text_position)


# =========================
# Функции для обработки видео
# =========================
def apply_mn_style_to_frame(frame: np.ndarray, text: str, text_position: str = TEXT_POSITION_TOP) -> np.ndarray:
    img = Image.fromarray(frame).convert("RGB")
    img = img.resize(VIDEO_TARGET_SIZE, Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.55)
    
    draw = ImageDraw.Draw(img)
    
    margin_x = int(img.width * 0.06)
    margin_top = int(img.height * 0.06)
    margin_bottom = int(img.height * 0.07)
    safe_w = img.width - 2 * margin_x
    
    text_upper = text.strip().upper()
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    font, lines, heights, spacing, total_text_height = fit_text_block(
        draw=draw,
        text=text_upper,
        font_path=FONT_MN,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(img.height * 0.11),
        min_size=16,
        line_spacing_ratio=0.22
    )
    
    footer_size = max(24, int(img.height * 0.034))
    footer_font = ImageFont.truetype(FONT_MN, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    
    block_w = 0
    for ln in lines:
        block_w = max(block_w, text_width(draw, ln, font))
    block_x = (img.width - block_w) // 2
    block_x = max(margin_x, block_x)
    
    if text_position == TEXT_POSITION_TOP:
        title_y = margin_top
        footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    else:
        title_y = img.height - margin_bottom - total_text_height - 10
        footer_y = 10
    
    y = title_y
    for i, ln in enumerate(lines):
        draw.text((block_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing
    
    footer_x = (img.width - footer_w) // 2
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")
    
    return np.array(img)


def apply_chp_style_to_frame(frame: np.ndarray, text: str) -> np.ndarray:
    img = Image.fromarray(frame).convert("RGB")
    img = img.resize(VIDEO_TARGET_SIZE, Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    
    draw = ImageDraw.Draw(img)
    
    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    safe_w = img.width - 2 * margin_x
    
    text_upper = text.strip().upper()
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=text_upper,
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
    
    return np.array(img)


def apply_am_style_to_frame(frame: np.ndarray, text: str) -> np.ndarray:
    img = Image.fromarray(frame).convert("RGB")
    img = img.resize(VIDEO_TARGET_SIZE, Image.Resampling.LANCZOS)
    img = apply_top_blur_band(img)
    
    draw = ImageDraw.Draw(img)
    
    margin_x = int(img.width * 0.055)
    band_h = int(img.height * AM_TOP_BLUR_PCT)
    safe_w = img.width - 2 * margin_x
    
    text_upper = text.strip().upper()
    text_zone_top = int(band_h * 0.12)
    text_zone_bottom = int(band_h * 0.12)
    text_zone_h = max(1, band_h - text_zone_top - text_zone_bottom)
    
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=text_upper,
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
    
    return np.array(img)


def apply_fdr_post_style_to_frame(frame: np.ndarray, text: str, highlight_phrase: str) -> np.ndarray:
    img = Image.fromarray(frame).convert("RGB")
    img = img.resize(VIDEO_TARGET_SIZE, Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    
    draw = ImageDraw.Draw(img)
    
    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    safe_w = img.width - 2 * margin_x
    
    text_upper = text.strip().upper()
    highlight_upper = highlight_phrase.strip().upper()
    highlight_words = set(highlight_upper.split())
    
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=text_upper,
        font_path=FONT_CHP,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(img.height * 0.11),
        min_size=16,
        line_spacing_ratio=0.22
    )
    
    base_y = img.height - margin_bottom - total_h
    
    # Рисуем плашки
    y = base_y
    for line_idx, line in enumerate(lines):
        line_words = line.split()
        current_x = margin_x
        
        for word in line_words:
            word_bbox = draw.textbbox((current_x, y), word, font=font)
            word_x1, word_y1, word_x2, word_y2 = word_bbox
            
            if word in highlight_words:
                padding = 10
                draw.rectangle(
                    [word_x1 - padding, word_y1 - padding,
                     word_x2 + padding, word_y2 + padding],
                    fill=FDR_POST_PURPLE_COLOR
                )
            
            if word != line_words[-1]:
                space_width = text_width(draw, " ", font)
                current_x += text_width(draw, word, font) + space_width
            else:
                current_x += text_width(draw, word, font)
        
        y += heights[line_idx] + spacing
    
    # Рисуем текст
    y = base_y
    for line_idx, line in enumerate(lines):
        line_words = line.split()
        current_x = margin_x
        
        for word in line_words:
            draw.text((current_x, y), word, font=font, fill="white")
            if word != line_words[-1]:
                space_width = text_width(draw, " ", font)
                current_x += text_width(draw, word, font) + space_width
            else:
                current_x += text_width(draw, word, font)
        
        y += heights[line_idx] + spacing
    
    return np.array(img)


def apply_mn_tg_style_to_frame(frame: np.ndarray) -> np.ndarray:
    img = Image.fromarray(frame).convert("RGBA")
    
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    font_size = int(img.width * 0.08)
    font = ImageFont.truetype(FONT_MN, font_size)
    
    text_bbox = draw.textbbox((0, 0), FOOTER_TEXT, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    x = (img.width - text_width) // 2
    y = int(img.height * 0.2) - (text_height // 2)
    
    draw.text((x, y), FOOTER_TEXT, font=font, fill=(255, 255, 255, 38))
    
    result = Image.alpha_composite(img, overlay)
    return np.array(result.convert("RGB"))


def apply_mn2_style_to_frame(frame: np.ndarray, text: str, text_position: str = TEXT_POSITION_TOP) -> np.ndarray:
    img = Image.fromarray(frame).convert("RGB")
    img = img.resize(VIDEO_TARGET_SIZE, Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.55)
    
    if text_position == TEXT_POSITION_TOP:
        img = apply_top_gradient(img, height_pct=CHP_GRADIENT_PCT * 0.75, max_alpha=165)
    else:
        img = apply_bottom_gradient_soft(img, height_pct=CHP_GRADIENT_PCT * 0.75, max_alpha=165)
    
    draw = ImageDraw.Draw(img)
    
    margin_x = int(img.width * 0.06)
    margin_top = int(img.height * 0.06)
    margin_bottom = int(img.height * 0.07)
    safe_w = img.width - 2 * margin_x
    
    text_upper = text.strip().upper()
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    font, lines, heights, spacing, total_text_height = fit_text_block(
        draw=draw,
        text=text_upper,
        font_path=FONT_MN,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(img.height * 0.11),
        min_size=16,
        line_spacing_ratio=0.22
    )
    
    footer_size = max(24, int(img.height * 0.034))
    footer_font = ImageFont.truetype(FONT_MN, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    
    block_w = 0
    for ln in lines:
        block_w = max(block_w, text_width(draw, ln, font))
    block_x = (img.width - block_w) // 2
    block_x = max(margin_x, block_x)
    
    if text_position == TEXT_POSITION_TOP:
        title_y = margin_top
        footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    else:
        title_y = img.height - margin_bottom - total_text_height - 10
        footer_y = 10
    
    y = title_y
    for i, ln in enumerate(lines):
        draw.text((block_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing
    
    footer_x = (img.width - footer_w) // 2
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")
    
    return np.array(img)


def convert_video_to_gif(video_bytes: bytes, max_duration: int = 10, fps: int = 10) -> BytesIO:
    try:
        temp_input = "temp_video.mp4"
        temp_output = "temp_output.gif"
        
        with open(temp_input, 'wb') as f:
            f.write(video_bytes)
        
        clip = VideoFileClip(temp_input)
        
        if clip.duration > max_duration:
            clip = clip.subclip(0, max_duration)
        
        clip = clip.resize(height=360)
        clip.write_gif(temp_output, fps=fps, program='ffmpeg')
        
        with open(temp_output, 'rb') as f:
            gif_bytes = BytesIO(f.read())
        
        clip.close()
        os.remove(temp_input)
        os.remove(temp_output)
        
        gif_bytes.seek(0)
        return gif_bytes
        
    except Exception as e:
        logger.error(f"Error converting video to GIF: {e}")
        raise


def process_video_with_template(
    input_video: bytes,
    template: str,
    title: str = "",
    highlight_phrase: str = "",
    text_position: str = TEXT_POSITION_TOP
) -> BytesIO:
    try:
        temp_input = "temp_input.mp4"
        temp_output = "temp_output.mp4"
        
        with open(temp_input, 'wb') as f:
            f.write(input_video)
        
        clip = VideoFileClip(temp_input)
        
        if template == "MN":
            process_func = lambda f: apply_mn_style_to_frame(f, title, text_position)
        elif template == "CHP":
            process_func = lambda f: apply_chp_style_to_frame(f, title)
        elif template == "AM":
            process_func = lambda f: apply_am_style_to_frame(f, title)
        elif template == "FDR_POST":
            process_func = lambda f: apply_fdr_post_style_to_frame(f, title, highlight_phrase)
        elif template == "MN_TG":
            process_func = apply_mn_tg_style_to_frame
        elif template == "MN2":
            process_func = lambda f: apply_mn2_style_to_frame(f, title, text_position)
        else:
            process_func = lambda f: apply_mn_style_to_frame(f, title, text_position)
        
        processed_clip = clip.fl_image(process_func)
        
        if clip.audio:
            processed_clip = processed_clip.set_audio(clip.audio)
        
        processed_clip.write_videofile(
            temp_output,
            codec='libx264',
            audio_codec='aac',
            fps=VIDEO_FPS,
            bitrate=VIDEO_BITRATE,
            threads=4,
            preset='medium'
        )
        
        with open(temp_output, 'rb') as f:
            result = BytesIO(f.read())
        
        clip.close()
        processed_clip.close()
        os.remove(temp_input)
        os.remove(temp_output)
        
        result.seek(0)
        return result
        
    except Exception as e:
        logger.error(f"Error processing video with template {template}: {e}")
        raise


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
        InlineKeyboardButton("💜 Пост ФДР", callback_data="tpl:FDR_POST"),
        InlineKeyboardButton("📱 МН ТГ", callback_data="tpl:MN_TG"),
    )
    kb.row(
        InlineKeyboardButton("🆕 МН 2", callback_data="tpl:MN2"),
    )
    return kb


def video_menu_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎬 Видео в GIF", callback_data="video:gif"),
        InlineKeyboardButton("📝 Оформить видео", callback_data="video:edit"),
        InlineKeyboardButton("❌ Отмена", callback_data="video:cancel")
    )
    return kb


def video_template_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📰 МН", callback_data="video_tpl:MN"),
        InlineKeyboardButton("🚨 ЧП ВМ", callback_data="video_tpl:CHP"),
    )
    kb.row(
        InlineKeyboardButton("✨ АМ", callback_data="video_tpl:AM"),
        InlineKeyboardButton("💜 Пост ФДР", callback_data="video_tpl:FDR_POST"),
    )
    kb.row(
        InlineKeyboardButton("📱 МН ТГ", callback_data="video_tpl:MN_TG"),
        InlineKeyboardButton("🆕 МН 2", callback_data="video_tpl:MN2"),
    )
    kb.row(
        InlineKeyboardButton("❌ Отмена", callback_data="video_tpl:cancel")
    )
    return kb


def video_text_position_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⬆️ Сверху", callback_data="video_pos:top"),
        InlineKeyboardButton("⬇️ Снизу", callback_data="video_pos:bottom")
    )
    kb.row(
        InlineKeyboardButton("❌ Отмена", callback_data="video_pos:cancel")
    )
    return kb


def text_position_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⬆️ Сверху", callback_data="text_pos:top"),
        InlineKeyboardButton("⬇️ Снизу", callback_data="text_pos:bottom")
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
        schedule_times = [(9, 0), (13, 0), (16, 0), (20, 0)]
        for hour, minute in schedule_times:
            self.scheduler.add_job(
                self.publish_news_digest,
                CronTrigger(hour=hour, minute=minute),
                id=f"news_{hour}_{minute}",
                replace_existing=True
            )
            logger.info(f"Scheduled news digest at {hour:02d}:{minute:02d}")
            
    def start(self):
        if self.chat_id:
            self.scheduler.start()
            logger.info(f"News auto-publisher started for chat {self.chat_id}")
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
        self.scheduler.shutdown()
        logger.info("News auto-publisher stopped")
        
    def publish_news_digest(self, manual=False):
        try:
            logger.info(f"Starting news digest publication (manual={manual})")
            items = fetch_all_news_last24h()
            
            if not items:
                msg = "😕 За последние 24 часа новостей не найдено"
                if manual:
                    self.bot.send_message(self.chat_id, msg, reply_markup=main_menu_kb())
                else:
                    self.bot.send_message(self.chat_id, msg)
                return
            
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
                self.bot.send_message(self.chat_id, header, parse_mode="HTML", reply_markup=main_menu_kb())
            else:
                self.bot.send_message(self.chat_id, header, parse_mode="HTML")
            
            cache_key = f"news_cache_{self.chat_id}"
            user_state[cache_key] = {"items": items, "current_index": 0, "by_key": {}}
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
            
            key = item_key(title, url)
            by_key[key] = item
            
            msg = f"<b>{html.escape(title)}</b>\n📰 {html.escape(source)}\n━━━━━━━━━━━━━━━━━━━━━━"
            
            kb = InlineKeyboardMarkup()
            kb.row(
                InlineKeyboardButton("📖 Читать полностью", callback_data=f"read_full:{key}"),
                InlineKeyboardButton("🔗 Источник", url=url)
            )
            
            self.bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
            time.sleep(0.3)
        
        cache["current_index"] = end_idx
        cache["by_key"] = by_key
        user_state[cache_key] = cache
        
        if end_idx < len(items):
            more_kb = InlineKeyboardMarkup()
            more_kb.row(InlineKeyboardButton(f"📥 Загрузить еще {NEWS_MORE_SIZE}", callback_data=f"load_more:{chat_id}"))
            remaining = len(items) - end_idx
            msg = f"📊 Показано {end_idx} из {len(items)} новостей\nОсталось: {remaining}"
            self.bot.send_message(chat_id, msg, reply_markup=more_kb)
        else:
            self.bot.send_message(chat_id, "✅ Все новости загружены!", reply_markup=main_menu_kb())


# =========================
# Обработчики для новостей
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("read_full:"))
def on_read_full_news(c):
    uid = c.from_user.id
    key = c.data.split(":", 1)[1]
    
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
        title = item.get("title", "")
        full_text = item.get("full_text", "")
        image_url = item.get("image", "")
        source_url = item.get("url", "")
        
        if not full_text:
            full_text = fetch_article_full_text_generic(source_url)
            item["full_text"] = full_text
        
        bot.send_message(c.message.chat.id, "⏳ Загружаю полный текст и фото...")
        
        if image_url:
            try:
                photo_bytes = get_cached_image(image_url)
                if photo_bytes and check_file_size(photo_bytes):
                    bot.send_photo(c.message.chat.id, photo=photo_bytes, caption=f"<b>{html.escape(title)}</b>", parse_mode="HTML")
                else:
                    bot.send_message(c.message.chat.id, f"<b>{html.escape(title)}</b>", parse_mode="HTML")
            except Exception as e:
                logger.error(f"Error sending photo: {e}")
                bot.send_message(c.message.chat.id, f"<b>{html.escape(title)}</b>", parse_mode="HTML")
        else:
            bot.send_message(c.message.chat.id, f"<b>{html.escape(title)}</b>", parse_mode="HTML")
        
        if full_text:
            clean_text = _clean_text(full_text)
            if len(clean_text) <= 4000:
                bot.send_message(c.message.chat.id, clean_text, parse_mode="HTML")
            else:
                paragraphs = clean_text.split('\n\n')
                current_chunk = ""
                chunks = []
                for p in paragraphs:
                    if len(current_chunk) + len(p) + 2 < 4000:
                        if current_chunk:
                            current_chunk += "\n\n" + p
                        else:
                            current_chunk = p
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = p
                if current_chunk:
                    chunks.append(current_chunk)
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        bot.send_message(c.message.chat.id, chunk, parse_mode="HTML")
                    else:
                        bot.send_message(c.message.chat.id, f"<i>Продолжение ({i+1}/{len(chunks)}):</i>\n\n{chunk}", parse_mode="HTML")
        else:
            bot.send_message(c.message.chat.id, "❌ Текст статьи не найден")
        
        bot.answer_callback_query(c.id, "✅ Готово")
        
    except Exception as e:
        logger.error(f"Error sending full news: {e}")
        bot.answer_callback_query(c.id, "Ошибка при загрузке", show_alert=True)


@bot.callback_query_handler(func=lambda c: c.data.startswith("load_more:"))
def on_load_more(c):
    chat_id = int(c.data.split(":", 1)[1])
    cache_key = f"news_cache_{chat_id}"
    cache = user_state.get(cache_key)
    
    if not cache:
        bot.answer_callback_query(c.id, "Кэш не найден. Запустите выгрузку заново.", show_alert=True)
        return
    
    current_idx = cache.get("current_index", 0)
    news_publisher._send_news_batch(chat_id, current_idx, NEWS_MORE_SIZE, manual=True)
    bot.answer_callback_query(c.id, f"Загружаю еще {NEWS_MORE_SIZE} новостей...")


@bot.message_handler(func=lambda message: message.text == BTN_GET_NEWS_MANUAL)
def cmd_manual_news(message):
    uid = message.from_user.id
    if str(uid) != str(AUTO_NEWS_CHAT_ID):
        cmd_news(message)
        return
    
    bot.send_message(message.chat.id, "🔄 Запускаю ручную выгрузку новостей...", reply_markup=main_menu_kb())
    news_publisher.publish_news_digest(manual=True)


@bot.message_handler(func=lambda message: message.text == BTN_ENHANCE)
def cmd_enhance(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_enhance_photo"
    st["template"] = st.get("template", "MN")
    user_state[uid] = st
    
    bot.send_message(
        message.chat.id,
        "✨ Отправь фото, которое нужно улучшить.\n\n"
        "Я профессионально обработаю изображение:\n"
        "• 🔍 +30-40% резкости\n"
        "• 🎨 +20-25% насыщенности\n"
        "• 🌓 +20-25% контрастности\n"
        "• 🧹 Удаление шумов\n"
        "• 💡 HDR-эффект",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(func=lambda message: message.text == "🎥 Видео")
def cmd_video_menu(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "video_menu"
    user_state[uid] = st
    
    bot.send_message(message.chat.id, "🎥 Режим работы с видео\n\nВыбери действие:", reply_markup=video_menu_kb())


@bot.message_handler(func=lambda message: message.text == "🎬 Видео в GIF")
def cmd_video_to_gif(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_video_for_gif"
    user_state[uid] = st
    
    bot.send_message(
        message.chat.id,
        "🎬 Отправь видео (до 50 MB), и я конвертирую его в GIF.\n\n"
        "Видео будет обрезано до 10 секунд.",
        reply_markup=main_menu_kb()
    )


# =========================
# Команда /stop
# =========================
@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    uid = message.from_user.id
    if uid in user_state:
        template = user_state[uid].get("template", "MN")
        user_state[uid] = {"template": template, "step": "idle"}
        logger.info(f"Reset state for user {uid}")
    
    bot.send_message(message.chat.id, "🛑 Бот сброшен в исходное состояние.\nМожно начинать новую команду.", reply_markup=main_menu_kb())


# =========================
# Обработчик выбора источников
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("src:"))
def on_source_select(c):
    uid = c.from_user.id
    action = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    
    if action == "cancel":
        st.pop("news_step", None)
        st.pop("selected_sources", None)
        user_state[uid] = st
        try:
            bot.edit_message_text("❌ Выбор отменен", c.message.chat.id, c.message.message_id)
        except Exception as e:
            logger.warning(f"Could not edit message: {e}")
            bot.send_message(c.message.chat.id, "❌ Выбор отменен")
        bot.answer_callback_query(c.id, "Отменено")
        return
    
    if action == "save":
        selected = st.get("selected_sources", [])
        if not selected:
            bot.answer_callback_query(c.id, "❌ Выбери хотя бы один источник", show_alert=True)
            return
        
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except Exception as e:
            logger.warning(f"Could not delete message: {e}")
        
        bot.send_message(c.message.chat.id, f"🔍 Собираю новости из {len(selected)} источников...\nИсточники: {', '.join([SOURCE_NAMES.get(s, s) for s in selected])}", reply_markup=main_menu_kb())
        
        items = fetch_news_from_sources(selected)
        set_news_cache(uid, items)
        send_news_batch(c.message.chat.id, uid, NEWS_FIRST_BATCH)
        
        st.pop("news_step", None)
        st.pop("selected_sources", None)
        user_state[uid] = st
        bot.answer_callback_query(c.id, f"✅ Выбрано {len(selected)} источников")
        return
    
    if action == "reset":
        st["selected_sources"] = []
        user_state[uid] = st
        try:
            bot.edit_message_text("📰 Выбери источники новостей (можно несколько):\n\nПосле выбора нажми 'Сохранить выбор'", c.message.chat.id, c.message.message_id, reply_markup=news_sources_kb())
        except Exception as e:
            logger.warning(f"Could not edit message: {e}")
            bot.send_message(c.message.chat.id, "📰 Выбери источники новостей (можно несколько):\n\nПосле выбора нажми 'Сохранить выбор'", reply_markup=news_sources_kb())
        bot.answer_callback_query(c.id, "Выбор сброшен")
        return
    
    if action == "all":
        st["selected_sources"] = list(SOURCE_NAMES.keys())
        user_state[uid] = st
        selected_text = "✅ " + "\n✅ ".join([f"{SOURCE_NAMES[s]}" for s in st["selected_sources"]])
        try:
            bot.edit_message_text(f"📰 Выбраны все источники:\n\n{selected_text}\n\nНажми 'Сохранить выбор' для продолжения", c.message.chat.id, c.message.message_id, reply_markup=save_sources_kb())
        except Exception as e:
            logger.warning(f"Could not edit message: {e}")
            bot.send_message(c.message.chat.id, f"📰 Выбраны все источники:\n\n{selected_text}\n\nНажми 'Сохранить выбор' для продолжения", reply_markup=save_sources_kb())
        bot.answer_callback_query(c.id, f"✅ Выбрано {len(st['selected_sources'])} источников")
        return
    
    source_id = action
    if "selected_sources" not in st:
        st["selected_sources"] = []
    
    if source_id in st["selected_sources"]:
        st["selected_sources"].remove(source_id)
        status = "❌ убран"
    else:
        st["selected_sources"].append(source_id)
        status = "✅ добавлен"
    
    user_state[uid] = st
    
    if st["selected_sources"]:
        selected_text = "Текущий выбор:\n"
        for sid in SOURCE_NAMES.keys():
            if sid in st["selected_sources"]:
                selected_text += f"✅ {SOURCE_NAMES[sid]}\n"
            else:
                selected_text += f"❌ {SOURCE_NAMES[sid]}\n"
    else:
        selected_text = "Пока ничего не выбрано"
    
    try:
        bot.edit_message_text(f"📰 {SOURCE_NAMES.get(source_id, source_id)} {status}\n\n{selected_text}\nПродолжай выбирать или нажми 'Сохранить выбор'", c.message.chat.id, c.message.message_id, reply_markup=news_sources_kb())
    except Exception as e:
        logger.warning(f"Could not edit message: {e}")
        bot.send_message(c.message.chat.id, f"📰 {SOURCE_NAMES.get(source_id, source_id)} {status}\n\n{selected_text}\nПродолжай выбирать или нажми 'Сохранить выбор'", reply_markup=news_sources_kb())
    
    bot.answer_callback_query(c.id, f"{status}: {SOURCE_NAMES.get(source_id, source_id)}")


# =========================
# Обработчики видео
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("video:"))
def on_video_menu_callback(c):
    uid = c.from_user.id
    action = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    
    if action == "cancel":
        st.pop("step", None)
        user_state[uid] = st
        bot.edit_message_text("❌ Отменено", c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Отменено")
        
    elif action == "gif":
        st["step"] = "waiting_video_for_gif"
        user_state[uid] = st
        bot.edit_message_text("🎬 Отправь видео, и я конвертирую его в GIF.\n\nВидео будет обрезано до 10 секунд.", c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Ожидаю видео")
        
    elif action == "edit":
        st["step"] = "waiting_video_for_edit"
        user_state[uid] = st
        bot.edit_message_text("📝 Отправь видео для оформления.", c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Ожидаю видео")


@bot.callback_query_handler(func=lambda c: c.data.startswith("video_tpl:"))
def on_video_template_select(c):
    uid = c.from_user.id
    action = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    
    if action == "cancel":
        st.pop("step", None)
        st.pop("video_bytes", None)
        user_state[uid] = st
        bot.edit_message_text("❌ Оформление видео отменено", c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Отменено")
        return
    
    st["video_template"] = action
    user_state[uid] = st
    
    if action in ["MN", "MN2"]:
        bot.edit_message_text("📐 Выбери расположение текста:", c.message.chat.id, c.message.message_id, reply_markup=video_text_position_kb())
        bot.answer_callback_query(c.id, "Выбери позицию")
    
    elif action == "FDR_POST":
        st["step"] = "waiting_video_highlight"
        user_state[uid] = st
        bot.edit_message_text("💜 Отправь фразу, которую нужно выделить фиолетовой плашкой:", c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Ожидаю фразу")
    
    elif action == "MN_TG":
        processing_msg = bot.edit_message_text("⏳ Обрабатываю видео... Это может занять некоторое время.", c.message.chat.id, c.message.message_id)
        
        try:
            result = process_video_with_template(st["video_bytes"], action, title="")
            bot.send_video(c.message.chat.id, video=result, caption="📱 Видео в стиле МН ТГ")
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
        except Exception as e:
            logger.error(f"Error processing video: {e}")
            bot.edit_message_text(f"❌ Ошибка при обработке видео: {e}", c.message.chat.id, c.message.message_id)
        
        st.pop("step", None)
        st.pop("video_bytes", None)
        user_state[uid] = st
    
    else:
        st["step"] = "waiting_video_title"
        user_state[uid] = st
        bot.edit_message_text("📝 Отправь заголовок для видео:", c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Ожидаю заголовок")


@bot.callback_query_handler(func=lambda c: c.data.startswith("video_pos:"))
def on_video_position_select(c):
    uid = c.from_user.id
    action = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    
    if action == "cancel":
        st.pop("step", None)
        st.pop("video_bytes", None)
        st.pop("video_template", None)
        user_state[uid] = st
        bot.edit_message_text("❌ Оформление видео отменено", c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Отменено")
        return
    
    st["video_text_position"] = action
    st["step"] = "waiting_video_title"
    user_state[uid] = st
    bot.edit_message_text("📝 Отправь заголовок для видео:", c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id, "Ожидаю заголовок")


# =========================
# Template selection handler
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("tpl:"))
def on_tpl(c):
    uid = c.from_user.id
    tpl = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    st["template"] = tpl
    
    if tpl in ["MN", "MN2"]:
        st["step"] = "waiting_text_position"
        user_state[uid] = st
        bot.answer_callback_query(c.id, f"Шаблон {tpl} выбран ✅")
        template_name = "МН 2" if tpl == "MN2" else "МН"
        bot.send_message(c.message.chat.id, f"📰 Выбран шаблон <b>{template_name}</b>\n\nГде разместить текст?", parse_mode="HTML", reply_markup=text_position_kb())
    elif tpl == "FDR_POST":
        st["step"] = "waiting_photo_fdr_post"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
        bot.send_message(c.message.chat.id, "💜 Выбран шаблон <b>Пост ФДР</b>\n\n📸 Пришли фото для поста.\n\n<i>Дальше нужно будет:</i>\n1️⃣ Отправить полный заголовок\n2️⃣ Отправить фразу для фиолетовой плашки\n3️⃣ Отправить основной текст", parse_mode="HTML")
    elif tpl == "MN_TG":
        st["step"] = "waiting_photo_mn_tg"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Шаблон 'МН ТГ' выбран ✅")
        bot.send_message(c.message.chat.id, "📱 Выбран шаблон <b>МН ТГ</b>\n\n📸 Сначала пришли фото для поста.\n\n<i>После фото нужно будет отправить текст целиком.</i>\nПервый абзац автоматически станет жирным заголовком, остальное - основным текстом.", parse_mode="HTML")
    else:
        if st.get("step") in {"waiting_template", None}:
            st["step"] = "waiting_photo"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок ✅")
        tpl_names = {'CHP': 'ЧП ВМ', 'AM': 'АМ', 'FDR_STORY': 'Сторис ФДР'}
        tpl_name = tpl_names.get(tpl, tpl)
        bot.send_message(c.message.chat.id, f"Шаблон выбран: {tpl_name}. Пришли фото 📷")


@bot.callback_query_handler(func=lambda c: c.data.startswith("text_pos:"))
def on_text_position(c):
    uid = c.from_user.id
    position = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    
    st["text_position"] = position
    st["step"] = "waiting_photo"
    user_state[uid] = st
    
    position_text = "сверху" if position == "top" else "снизу"
    bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")
    bot.send_message(c.message.chat.id, f"Текст будет расположен <b>{position_text}</b> фотографии.\n\nТеперь пришли фото 📷", parse_mode="HTML")


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
        "• /template — выбрать шаблон (МН / ЧП ВМ / АМ / Сторис ФДР / Пост ФДР / МН ТГ / МН 2)\n"
        "• /stop — сбросить состояние бота\n\n"
        "🎥 Также доступна работа с видео:",
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
    uid = message.from_user.id
    if str(uid) == str(AUTO_NEWS_CHAT_ID):
        cmd_manual_news(message)
        return
    
    st = user_state.get(uid) or {}
    st["news_step"] = "choosing_sources"
    st["selected_sources"] = []
    user_state[uid] = st
    
    bot.send_message(message.chat.id, "📰 Выбери источники новостей (можно несколько):\n\n✅ - выбран\n❌ - не выбран\n\nПосле выбора нажми 'Сохранить выбор'", reply_markup=news_sources_kb())


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
        bot.send_message(c.message.chat.id, "Для этой новости не смог взять картинку.\nПришли фото 📷, а заголовок я уже подставлю.", reply_markup=main_menu_kb())
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
                bot.send_photo(chat_id=c.message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb(st.get("source_url", "")))
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
            bot.send_message(c.message.chat.id, "✅ Карточка с фото готова!\n\nТеперь отправь ОСНОВНОЙ ТЕКСТ для сторис.", reply_markup=main_menu_kb())
            return

    try:
        if st["template"] in ["MN", "MN2"]:
            card = make_card(photo_bytes, title, st["template"], text_position=st.get("text_position", TEXT_POSITION_TOP))
        else:
            card = make_card(photo_bytes, title, st["template"])
        st["card_bytes"] = card.getvalue()

        if auto_body:
            st["body_raw"] = auto_body
            st["step"] = "waiting_action"
            user_state[uid] = st

            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(chat_id=c.message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb(st.get("source_url", "")))
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

    if st.get("step") == "waiting_enhance_photo":
        try:
            file_id = message.photo[-1].file_id
            photo_bytes = tg_file_bytes(file_id)

            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return

            processing_msg = bot.reply_to(message, "⏳ Профессиональная обработка фото... (это может занять несколько секунд)")
            
            try:
                enhanced = enhance_image_quality_pro(photo_bytes)
                quality_text = "профессионально обработано"
            except:
                enhanced = enhance_image_quality(photo_bytes)
                quality_text = "улучшено"
            
            bot.send_photo(message.chat.id, photo=enhanced, caption=f"✨ Фото {quality_text}!\n\n✓ +30-40% резкости\n✓ +20-25% насыщенности\n✓ +20-25% контрастности\n✓ Удалены шумы\n✓ HDR-эффект", reply_markup=main_menu_kb())
            bot.delete_message(message.chat.id, processing_msg.message_id)
            st["step"] = "idle"
            user_state[uid] = st
            return
        except Exception as e:
            logger.error(f"Error enhancing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка при улучшении фото: {e}")
            return

    if st.get("step") == "waiting_template":
        bot.send_message(message.chat.id, "Сначала выбери шаблон:", reply_markup=template_kb())
        return

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

            bot.reply_to(message, "📸 Фото сохранено!\n\nТеперь отправь <b>ПОЛНЫЙ ЗАГОЛОВОК</b> поста:", parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error processing photo for FDR_POST: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return

    if st.get("step") == "waiting_photo_mn_tg":
        try:
            file_id = message.photo[-1].file_id
            photo_bytes = tg_file_bytes(file_id)

            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return

            warn_if_too_small(message.chat.id, photo_bytes)

            card = make_card_mn_tg(photo_bytes, "")
            st["photo_bytes"] = photo_bytes
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_text_mn_tg"
            user_state[uid] = st

            bot.reply_to(message, "📸 Фото сохранено!\n\nТеперь отправь <b>ВЕСЬ ТЕКСТ</b> поста одним сообщением.\nПервый абзац станет жирным заголовком, остальное - основным текстом.", parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error processing photo for MN_TG: {e}")
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
                        bot.send_photo(chat_id=message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb(st.get("source_url", "")))
                        bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")
                        return
                    else:
                        st["step"] = "waiting_body_fdr"
                        st.pop("prefill_title", None)
                        st.pop("prefill_source", None)
                        user_state[uid] = st
                        bot.reply_to(message, "Фото получено ✅ Заголовок уже есть. Теперь пришли ОСНОВНОЙ ТЕКСТ для сторис.")
                        return

                if st["template"] in ["MN", "MN2"]:
                    card = make_card(st["photo_bytes"], st["title"], st["template"], text_position=st.get("text_position", TEXT_POSITION_TOP))
                else:
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
                    bot.send_photo(chat_id=message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb(st.get("source_url", "")))
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


@bot.message_handler(content_types=["video"])
def on_video(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    
    if message.video.file_size > MAX_VIDEO_SIZE:
        bot.reply_to(message, f"❌ Видео слишком большое. Максимальный размер {MAX_VIDEO_SIZE//1024//1024}MB.")
        return
    
    step = st.get("step")
    
    if step == "waiting_video_for_gif":
        processing_msg = bot.reply_to(message, "⏳ Конвертирую видео в GIF... Это может занять некоторое время.")
        try:
            video_bytes = tg_file_bytes(message.video.file_id)
            gif_bytes = convert_video_to_gif(video_bytes, max_duration=10, fps=10)
            bot.send_animation(message.chat.id, animation=gif_bytes, caption="🎬 Видео конвертировано в GIF!")
            bot.delete_message(message.chat.id, processing_msg.message_id)
        except Exception as e:
            logger.error(f"Error converting video to GIF: {e}")
            bot.reply_to(message, f"❌ Ошибка при конвертации: {e}")
        st["step"] = "idle"
        user_state[uid] = st
        return
    
    elif step == "waiting_video_for_edit":
        video_bytes = tg_file_bytes(message.video.file_id)
        st["video_bytes"] = video_bytes
        st["step"] = "waiting_video_template"
        user_state[uid] = st
        bot.reply_to(message, "📹 Видео получено!\n\nТеперь выбери шаблон для оформления:", reply_markup=video_template_kb())
        return
    
    else:
        bot.reply_to(message, "🎥 Получено видео!\n\nВыбери действие в меню:", reply_markup=video_menu_kb())


@bot.message_handler(content_types=["document"])
def on_document(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")

    doc = message.document
    video_mime_types = ['video/mp4', 'video/avi', 'video/mov', 'video/mkv', 'video/webm']
    
    if doc.mime_type and doc.mime_type in video_mime_types:
        try:
            if doc.file_size > MAX_VIDEO_SIZE:
                bot.reply_to(message, f"❌ Видео слишком большое. Максимальный размер {MAX_VIDEO_SIZE//1024//1024}MB.")
                return
            
            step = st.get("step")
            
            if step in ["waiting_video_for_gif", "waiting_video_for_edit", "waiting_video_template"]:
                class VideoMock:
                    def __init__(self, file_id, file_size):
                        self.file_id = file_id
                        self.file_size = file_size
                message.video = VideoMock(doc.file_id, doc.file_size)
                on_video(message)
                return
            else:
                bot.reply_to(message, "🎥 Получено видео!\n\nВыбери действие в меню:", reply_markup=video_menu_kb())
                return
        except Exception as e:
            logger.error(f"Error processing video document: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке видео: {e}")
            return
    
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        bot.reply_to(message, "Пришли картинку (JPG/PNG) или видео.")
        return

    if st.get("step") == "waiting_enhance_photo":
        try:
            photo_bytes = tg_file_bytes(doc.file_id)

            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return

            processing_msg = bot.reply_to(message, "⏳ Улучшаю качество фото...")
            enhanced = enhance_image_quality(photo_bytes)
            bot.send_photo(message.chat.id, photo=enhanced, caption="✨ Фото улучшено!\n\n✓ +30-40% резкости\n✓ +20-25% насыщенности\n✓ +20-25% контрастности\n✓ Удалены шумы\n✓ HDR-эффект", reply_markup=main_menu_kb())
            bot.delete_message(message.chat.id, processing_msg.message_id)
            st["step"] = "idle"
            user_state[uid] = st
        except Exception as e:
            logger.error(f"Error enhancing document: {e}")
            bot.reply_to(message, f"❌ Ошибка при улучшении фото: {e}")
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

    if text == BTN_ENHANCE or text.lower() in {"улучшить качество", "улучшить фото", "улучшить"}:
        cmd_enhance(message)
        return

    step = st.get("step")

    if step == "waiting_text_mn_tg":
        if not text:
            bot.reply_to(message, "❌ Текст не может быть пустым. Отправь текст:")
            return
        
        st["full_text"] = text
        st["step"] = "waiting_action"
        user_state[uid] = st
        
        caption = build_caption_tg(text)
        bot.send_photo(chat_id=message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb(st.get("source_url", "")))
        bot.reply_to(message, "✅ Пост готов! Нажми кнопку под превью для публикации.", reply_markup=main_menu_kb())
        return

    if step == "waiting_title_fdr_post":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым. Отправь текст:")
            return
        
        st["full_title"] = text
        st["step"] = "waiting_highlight_fdr_post"
        user_state[uid] = st
        
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n<b>{html.escape(text)}</b>\n\n🎯 Теперь отправь <b>ФРАЗУ</b>, которую нужно выделить фиолетовой плашкой:\n\n<i>(можно скопировать часть заголовка или написать свою)</i>", parse_mode="HTML")
        return

    if step == "waiting_highlight_fdr_post":
        if not text:
            bot.reply_to(message, "❌ Фраза не может быть пустой. Отправь текст:")
            return
        
        st["highlight_phrase"] = text
        st["step"] = "waiting_body_fdr_post"
        user_state[uid] = st
        
        try:
            card = make_card(st["photo_bytes"], st["full_title"], st["template"], highlight_phrase=st["highlight_phrase"])
            st["card_bytes"] = card.getvalue()
            bot.send_photo(message.chat.id, photo=BytesIO(st["card_bytes"]), caption=f"💜 <b>Предпросмотр</b>\n\nВыделенная фраза: <b>{html.escape(text)}</b>\n\nТеперь отправь <b>ОСНОВНОЙ ТЕКСТ</b> поста:", parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error creating FDR_POST preview: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании превью: {e}\n\nПопробуй отправить фразу ещё раз или начни заново с /post")
            st["step"] = "waiting_highlight_fdr_post"
            user_state[uid] = st
        return

    if step == "waiting_body_fdr_post":
        st["body_raw"] = text
        body_src = extract_source_url(text)
        if body_src:
            st["source_url"] = body_src
        
        st["step"] = "waiting_action"
        user_state[uid] = st
        
        try:
            card = make_card(st["photo_bytes"], st["full_title"], st["template"], body_text=st["body_raw"], highlight_phrase=st["highlight_phrase"])
            caption = build_caption_html(st["full_title"], st["body_raw"])
            bot.send_photo(chat_id=message.chat.id, photo=BytesIO(card.getvalue()), caption=caption, parse_mode="HTML", reply_markup=preview_kb(st.get("source_url", "")))
            bot.reply_to(message, "✅ Пост готов! Нажми кнопку под превью для публикации.", reply_markup=main_menu_kb())
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
            card = make_card(st["photo_bytes"], st["title"], st.get("template", "FDR_STORY"), st["body_raw"])
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st

            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(chat_id=message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb(st.get("source_url", "")))
            bot.reply_to(message, "Сторис готова ✅ Нажми кнопку.")
        except Exception as e:
            logger.error(f"Error creating story: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании сторис: {e}")
            st["step"] = "waiting_photo"
            user_state[uid] = st
        return

    if step == "waiting_video_title":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым. Отправь текст:")
            return
        
        template = st.get("video_template", "MN")
        processing_msg = bot.reply_to(message, "⏳ Обрабатываю видео... Это может занять некоторое время.")
        
        try:
            result = process_video_with_template(
                st["video_bytes"],
                template,
                title=text,
                text_position=st.get("video_text_position", TEXT_POSITION_TOP)
            )
            
            caption = f"🎥 Видео в стиле {template}\n\n{html.escape(text)}"
            bot.send_video(message.chat.id, video=result, caption=caption, parse_mode="HTML")
            bot.delete_message(message.chat.id, processing_msg.message_id)
        except Exception as e:
            logger.error(f"Error processing video: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке видео: {e}")
        
        st.pop("step", None)
        st.pop("video_bytes", None)
        st.pop("video_template", None)
        st.pop("video_text_position", None)
        user_state[uid] = st
        return
    
    if step == "waiting_video_highlight":
        if not text:
            bot.reply_to(message, "❌ Фраза не может быть пустой. Отправь текст:")
            return
        
        st["video_highlight"] = text
        st["step"] = "waiting_video_title"
        user_state[uid] = st
        
        bot.reply_to(message, f"✅ Фраза сохранена: {html.escape(text)}\n\nТеперь отправь заголовок для видео:", parse_mode="HTML")
        return

    if step == "waiting_title":
        st["title"] = text
        try:
            if st.get("template") in ["MN", "MN2"]:
                card = make_card(st["photo_bytes"], st["title"], st.get("template", "MN"), text_position=st.get("text_position", TEXT_POSITION_TOP))
            elif st.get("template") == "MN_TG":
                card = make_card(st["photo_bytes"], st["title"], st.get("template", "MN_TG"))
            else:
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
        
        if st.get("template") == "MN_TG":
            caption = build_caption_tg(st["body_raw"])
        else:
            caption = build_caption_html(st["title"], st["body_raw"])
            
        bot.send_photo(chat_id=message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb(st.get("source_url", "")))
        bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")

    elif step == "waiting_action":
        bot.reply_to(message, "Нажми кнопку под превью ✅✏️❌ (или выбери действие в меню снизу).", reply_markup=main_menu_kb())

    elif step == "waiting_template":
        bot.send_message(message.chat.id, "Выбери шаблон кнопками:", reply_markup=template_kb())

    elif step == "waiting_text_position":
        bot.send_message(message.chat.id, "Сначала выбери расположение текста:", reply_markup=text_position_kb())

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
            if st.get("template") == "MN_TG" and "full_text" in st:
                caption = build_caption_tg(st["full_text"])
            else:
                title_to_use = st["full_title"] if st.get("template") == "FDR_POST" and "full_title" in st else st.get("title", "")
                caption = build_caption_html(title_to_use, st["body_raw"])
                
            bot.send_photo(CHANNEL, BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=channel_kb())
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
        elif st.get("template") == "MN_TG":
            st["step"] = "waiting_text_mn_tg"
            user_state[uid] = st
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(call.message.chat.id, "Пришли новый ТЕКСТ целиком. Первый абзац станет заголовком.", reply_markup=main_menu_kb())
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
        elif st.get("template") == "MN_TG":
            st["step"] = "waiting_text_mn_tg"
            user_state[uid] = st
            bot.answer_callback_query(call.id, "Ок")
            bot.send_message(call.message.chat.id, "Пришли новый ТЕКСТ целиком. Первый абзац станет заголовком.", reply_markup=main_menu_kb())
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
    try:
        ensure_fonts()
        logger.info("Fonts loaded successfully")
        
        if AUTO_NEWS_CHAT_ID:
            news_publisher.start()
        
        logger.info("Bot started polling...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60, logger_level=logging.ERROR)
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        if AUTO_NEWS_CHAT_ID and 'news_publisher' in globals():
            news_publisher.stop()
        try:
            if os.path.exists(lock_file):
                os.unlink(lock_file)
        except:
            pass
        raise
