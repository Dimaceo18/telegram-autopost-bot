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
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
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

if not SUGGEST_URL and BOT_USERNAME:
    SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"

# Constants
MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_VIDEO_SIZE = 50 * 1024 * 1024
CACHE_TTL = 3600
REQUEST_TIMEOUT = 15
MAX_RETRIES = 1

FDR_POST_PURPLE_COLOR = (122, 58, 240)
FDR_POST_PLATE_HEIGHT_PCT = 0.15
TEXT_POSITION_TOP = "top"
TEXT_POSITION_BOTTOM = "bottom"

# Константы для видео
VIDEO_TARGET_SIZE = (750, 938)
VIDEO_FPS = 24
VIDEO_BITRATE = "2000k"

# Размеры для квадратных фото
SQUARE_SIZE = 1080  # 1:1 квадрат


# =========================
# UI BUTTONS
# =========================
BTN_POST = "📝 Оформить пост"
BTN_SQUARE = "⬛ Квадраты"
BTN_NEWS = "📰 Получить новости"
BTN_NEWS_BY_LINK = "🔗 Новость по ссылке"
BTN_ENHANCE = "✨ Улучшить качество"
BTN_WATERMARK = "💧 Водяные знаки"
BTN_PRICES = "💰 Цены"

def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(BTN_POST), KeyboardButton(BTN_SQUARE))
    kb.row(KeyboardButton(BTN_NEWS), KeyboardButton(BTN_NEWS_BY_LINK))
    kb.row(KeyboardButton(BTN_ENHANCE), KeyboardButton(BTN_WATERMARK))
    kb.row(KeyboardButton(BTN_PRICES), KeyboardButton("🎥 Видео"))
    kb.row(KeyboardButton("🎬 Видео в GIF"))
    return kb


def prices_menu_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💰 Наши цены", callback_data="prices:list"),
        InlineKeyboardButton("📋 Условия размещения", callback_data="prices:terms")
    )
    kb.add(InlineKeyboardButton("❌ Закрыть", callback_data="prices:close"))
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
# NEWS SOURCES
# =========================
NEWS_FIRST_BATCH = 20
NEWS_MORE_BATCH = 10
NEWS_CACHE_TTL_SEC = 10 * 60
NEWS_PER_SOURCE_CAP = 20

NEWS_SOURCES = [
    {
        "id": "onliner",
        "name": "Onliner",
        "kind": "rss",
        "url": "https://www.onliner.by/feed",
        "limit": 20,
        "timeout": 10
    },
    {
        "id": "sputnik",
        "name": "Sputnik",
        "kind": "rss",
        "url": "https://sputnik.by/export/rss2/index.xml",
        "limit": 20,
        "timeout": 10
    },
    {
        "id": "telegraf",
        "name": "Telegraf",
        "kind": "rss",
        "url": "https://telegraf.news/feed/",
        "limit": 20,
        "timeout": 10
    },
    {
        "id": "tochka",
        "name": "Tochka",
        "kind": "rss",
        "url": "https://tochka.by/rss/",
        "limit": 20,
        "timeout": 10
    },
    {
        "id": "smartpress",
        "name": "Smartpress",
        "kind": "rss",
        "url": "https://smartpress.by/rss/",
        "limit": 20,
        "timeout": 10
    },
    {
        "id": "minsknews",
        "name": "Minsknews",
        "kind": "rss",
        "url": "https://minsknews.by/feed/",
        "limit": 20,
        "timeout": 10
    },
    {
        "id": "mlyn",
        "name": "Mlyn",
        "kind": "rss",
        "url": "https://mlyn.by/feed/",
        "limit": 20,
        "timeout": 10
    },
    {
        "id": "ont",
        "name": "ONT",
        "kind": "rss",
        "url": "https://ont.by/rss/",
        "limit": 20,
        "timeout": 10
    },
]

# =========================
# BOT + SESSION
# =========================
bot = telebot.TeleBot(TOKEN)

SESSION = requests.Session()
retry_strategy = Retry(
    total=0,
    backoff_factor=0,
    status_forcelist=[],
)
adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=10,
    pool_maxsize=10
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
# Helper functions
# =========================
def validate_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except Exception:
        return False


def check_file_size(file_bytes: bytes) -> bool:
    return len(file_bytes) <= MAX_FILE_SIZE


@functools.lru_cache(maxsize=100)
def get_cached_image(url: str) -> bytes:
    if not validate_url(url):
        raise ValueError(f"Invalid URL: {url}")
    return http_get_bytes(url)


def http_get(url: str, timeout: int = REQUEST_TIMEOUT, headers: dict = None) -> Optional[str]:
    if not validate_url(url):
        return None
    try:
        request_headers = SESSION.headers.copy()
        if headers:
            request_headers.update(headers)
            
        r = SESSION.get(url, timeout=timeout, headers=request_headers)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.debug(f"HTTP error for {url}: {e}")
        return None


def http_get_bytes(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[bytes]:
    if not validate_url(url):
        return None
    try:
        r = SESSION.get(url, timeout=timeout)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.debug(f"Failed to get bytes from {url}: {e}")
        return None


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
            raise RuntimeError(f"Font not found: {font}")


def clear_state(user_id: int):
    if user_id in user_state:
        template = user_state[user_id].get("template", "MN")
        user_state[user_id] = {"template": template, "step": "idle"}
        logger.info(f"Cleared state for user {user_id}")


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
# Date parsing
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
def parse_rss_fast(url: str, source_name: str, limit: int = 20) -> List[Dict]:
    try:
        xml_text = http_get(url, timeout=REQUEST_TIMEOUT)
        if not xml_text:
            return []
        root = ET.fromstring(xml_text)
    except Exception as e:
        logger.error(f"Failed to parse RSS {url}: {e}")
        return []

    out = []
    for item in root.findall(".//item"):
        try:
            title = (item.findtext("title") or "").strip()[:150]
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()

            image = ""
            enc = item.find("enclosure")
            if enc is not None and enc.get("url"):
                image = enc.get("url") or ""
            
            if not image:
                media = item.find("{http://search.yahoo.com/mrss/}content")
                if media is not None and media.get("url"):
                    image = media.get("url")

            dt = parse_dt(pub)

            if title and link:
                out.append({
                    "source": source_name,
                    "title": title,
                    "url": link,
                    "summary": html.unescape(re.sub(r"<[^>]+>", " ", desc))[:300],
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


def fetch_article_text_fast(url: str) -> str:
    try:
        page_html = http_get(url, timeout=REQUEST_TIMEOUT)
        if not page_html:
            return ""
        
        soup = BeautifulSoup(page_html, "html.parser")
        
        for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            tag.decompose()
        
        article = soup.find('article') or soup.find(class_=re.compile(r'(content|article|post|news)', re.I))
        
        if not article:
            article = soup.body
        
        if not article:
            return ""
        
        paragraphs = []
        for p in article.find_all(['p']):
            text = p.get_text(strip=True)
            if text and len(text) > 40:
                paragraphs.append(text)
        
        return '\n\n'.join(paragraphs)[:4000]
        
    except Exception as e:
        logger.error(f"Failed to fetch article text from {url}: {e}")
        return ""


def fetch_news_from_source(source_id: str) -> List[Dict]:
    source = next((s for s in NEWS_SOURCES if s["id"] == source_id), None)
    if not source:
        return []
    
    try:
        items = parse_rss_fast(source["url"], source["name"], limit=NEWS_FIRST_BATCH)
        logger.info(f"[NEWS] {source['name']} loaded {len(items)} items")
        
        filtered = []
        for item in items:
            dt = parse_dt(item.get("dt_utc") or "")
            if dt and is_last_24h(dt):
                filtered.append(item)
        
        return filtered[:NEWS_FIRST_BATCH]
        
    except Exception as e:
        logger.error(f"[NEWS-ERROR] {source['name']}: {e}")
        return []


def fetch_all_news_fast() -> List[Dict]:
    all_items = []
    seen_urls = set()
    
    for source in NEWS_SOURCES:
        try:
            items = parse_rss_fast(source["url"], source["name"], limit=5)
            
            for item in items:
                url = item.get("url", "")
                if not url or url in seen_urls:
                    continue
                
                dt = parse_dt(item.get("dt_utc") or "")
                if dt and is_last_24h(dt):
                    seen_urls.add(url)
                    all_items.append(item)
                    
        except Exception as e:
            logger.error(f"Error loading {source['name']}: {e}")
            continue
    
    all_items.sort(
        key=lambda x: parse_dt(x.get("dt_utc") or "") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )
    
    return all_items[:NEWS_FIRST_BATCH]


# =========================
# Image enhancement
# =========================
def enhance_image_simple(image_bytes: bytes) -> BytesIO:
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        
        enhancer_sharpness = ImageEnhance.Sharpness(img)
        img = enhancer_sharpness.enhance(1.20)
        
        enhancer_color = ImageEnhance.Color(img)
        img = enhancer_color.enhance(1.15)
        
        output = BytesIO()
        img.save(output, format="JPEG", quality=98, optimize=True)
        output.seek(0)
        return output
        
    except Exception as e:
        logger.error(f"Error enhancing image: {e}")
        output = BytesIO(image_bytes)
        output.seek(0)
        return output


# =========================
# Watermark functions
# =========================
def apply_watermark_mn(photo_bytes: bytes) -> BytesIO:
    """
    Наносит водяной знак "MINSK NEWS" по центру фото с прозрачностью 25%
    """
    try:
        # Открываем изображение
        img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
        
        # Создаем слой для водяного знака
        watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        
        # Определяем размер шрифта (10% от ширины изображения)
        font_size = int(img.width * 0.1)
        
        # Загружаем шрифт
        try:
            font = ImageFont.truetype(FONT_MN, font_size)
        except:
            font = ImageFont.load_default()
        
        # Текст водяного знака
        watermark_text = "MINSK NEWS"
        
        # Получаем размеры текста
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Вычисляем позицию для центрирования
        x = (img.width - text_width) // 2
        y = (img.height - text_height) // 2
        
        # Рисуем текст с прозрачностью 25% (64 из 255)
        draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 64))
        
        # Накладываем водяной знак на исходное изображение
        result = Image.alpha_composite(img, watermark)
        
        # Конвертируем обратно в RGB для сохранения в JPEG
        result = result.convert("RGB")
        
        # Сохраняем в буфер
        output = BytesIO()
        result.save(output, format="JPEG", quality=95, optimize=True)
        output.seek(0)
        
        return output
        
    except Exception as e:
        logger.error(f"Error applying MN watermark: {e}")
        raise


def apply_watermark_chp(photo_bytes: bytes) -> BytesIO:
    """
    Наносит водяной знак "ЧП Минск" по центру фото с прозрачностью 25%
    """
    try:
        # Открываем изображение
        img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
        
        # Создаем слой для водяного знака
        watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        
        # Определяем размер шрифта (10% от ширины изображения)
        font_size = int(img.width * 0.1)
        
        # Загружаем шрифт
        try:
            font = ImageFont.truetype(FONT_CHP, font_size)
        except:
            font = ImageFont.load_default()
        
        # Текст водяного знака
        watermark_text = "ЧП Минск"
        
        # Получаем размеры текста
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        # Вычисляем позицию для центрирования
        x = (img.width - text_width) // 2
        y = (img.height - text_height) // 2
        
        # Рисуем текст с прозрачностью 25% (64 из 255)
        draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 64))
        
        # Накладываем водяной знак на исходное изображение
        result = Image.alpha_composite(img, watermark)
        
        # Конвертируем обратно в RGB для сохранения в JPEG
        result = result.convert("RGB")
        
        # Сохраняем в буфер
        output = BytesIO()
        result.save(output, format="JPEG", quality=95, optimize=True)
        output.seek(0)
        
        return output
        
    except Exception as e:
        logger.error(f"Error applying CHP watermark: {e}")
        raise


# =========================
# Gradient functions
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


# =========================
# Crop functions
# =========================
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


def crop_to_square(img: Image.Image) -> Image.Image:
    """
    Обрезает изображение до квадрата 1:1
    """
    w, h = img.size
    size = min(w, h)
    left = (w - size) // 2
    top = (h - size) // 2
    return img.crop((left, top, left + size, top + size))


# =========================
# Text wrapping functions
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


def fit_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    safe_w: int,
    max_block_h: int,
    max_lines: int = 6,
    start_size: int = 90,
    min_size: int = 16,
    line_spacing: int = 10,
) -> Tuple[ImageFont.FreeTypeFont, List[str], List[int], int, int]:
    """
    Подбирает размер шрифта так, чтобы текст поместился в заданную область.
    Использует фиксированный межстрочный интервал line_spacing.
    Возвращает: (font, lines, line_heights, line_spacing, total_height)
    """
    text = (text or "").strip()
    if not text:
        text = " "

    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines, ok = wrap_no_truncate(draw, text, font, safe_w, max_lines=max_lines)

        # Вычисляем высоты строк и общую высоту с фиксированным интервалом
        line_heights = []
        total_h = 0
        max_w = 0
        
        for i, ln in enumerate(lines):
            bb = draw.textbbox((0, 0), ln, font=font)
            lw = bb[2] - bb[0]
            lh = bb[3] - bb[1]
            line_heights.append(lh)
            total_h += lh
            max_w = max(max_w, lw)
            
            # Добавляем межстрочный интервал после каждой строки, кроме последней
            if i < len(lines) - 1:
                total_h += line_spacing

        if ok and max_w <= safe_w and total_h <= max_block_h:
            return font, lines, line_heights, line_spacing, total_h

        size -= 2

    # Если не удалось подобрать размер, используем минимальный
    font = ImageFont.truetype(font_path, min_size)
    lines, _ = wrap_no_truncate(draw, text, font, safe_w, max_lines=max_lines)
    
    line_heights = []
    total_h = 0
    for i, ln in enumerate(lines):
        bb = draw.textbbox((0, 0), ln, font=font)
        lh = bb[3] - bb[1]
        line_heights.append(lh)
        total_h += lh
        if i < len(lines) - 1:
            total_h += line_spacing
            
    return font, lines, line_heights, line_spacing, total_h


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


# =========================
# Card making functions (стандартные 4:5)
# =========================
def make_card_mn(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP, is_square: bool = False) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), resample=Image.Resampling.LANCZOS)
        target_w, target_h = SQUARE_SIZE, SQUARE_SIZE
    else:
        img = crop_to_4x5(img)
        img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
        target_w, target_h = TARGET_W, TARGET_H
    
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

    # Фиксированный межстрочный интервал - 15% от высоты шрифта
    base_font_size = int(img.height * 0.11)
    line_spacing = int(base_font_size * 0.15)
    
    font, lines, heights, spacing, total_text_height = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_MN,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=base_font_size,
        min_size=16,
        line_spacing=line_spacing
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
        y += heights[i] + (spacing if i < len(lines) - 1 else 0)

    footer_x = (img.width - footer_w) // 2
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_mn2(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP, font_size_multiplier: float = 1.0, is_square: bool = False) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), resample=Image.Resampling.LANCZOS)
        target_w, target_h = SQUARE_SIZE, SQUARE_SIZE
    else:
        img = crop_to_4x5(img)
        img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
        target_w, target_h = TARGET_W, TARGET_H
    
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

    # Применяем множитель к начальному размеру шрифта
    base_start_size = int(img.height * 0.11)
    adjusted_start_size = int(base_start_size * font_size_multiplier)
    
    # Фиксированный межстрочный интервал - 15% от скорректированного размера шрифта
    line_spacing = int(adjusted_start_size * 0.15)
    
    font, lines, heights, spacing, total_text_height = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_MN,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=adjusted_start_size,
        min_size=16,
        line_spacing=line_spacing
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
        y += heights[i] + (spacing if i < len(lines) - 1 else 0)

    footer_x = (img.width - footer_w) // 2
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_chp(photo_bytes: bytes, title_text: str, is_square: bool = False) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), resample=Image.Resampling.LANCZOS)
        target_w, target_h = SQUARE_SIZE, SQUARE_SIZE
    else:
        img = crop_to_4x5(img)
        img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
        target_w, target_h = TARGET_W, TARGET_H
    
    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    draw = ImageDraw.Draw(img)

    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    safe_w = img.width - 2 * margin_x

    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    text = (title_text or "").strip().upper()

    base_font_size = int(img.height * 0.11)
    line_spacing = int(base_font_size * 0.15)

    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_CHP,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=base_font_size,
        min_size=16,
        line_spacing=line_spacing
    )

    y = img.height - margin_bottom - total_h
    for i, ln in enumerate(lines):
        draw.text((margin_x, y), ln, font=font, fill="white")
        y += heights[i] + (spacing if i < len(lines) - 1 else 0)

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_am(photo_bytes: bytes, title_text: str, is_square: bool = False) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), resample=Image.Resampling.LANCZOS)
        target_w, target_h = SQUARE_SIZE, SQUARE_SIZE
    else:
        img = crop_to_4x5(img)
        img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
        target_w, target_h = TARGET_W, TARGET_H
    
    img = apply_top_blur_band(img)

    draw = ImageDraw.Draw(img)

    margin_x = int(img.width * 0.055)
    band_h = int(img.height * AM_TOP_BLUR_PCT)
    safe_w = img.width - 2 * margin_x
    text = (title_text or "").strip().upper()

    text_zone_top = int(band_h * 0.12)
    text_zone_bottom = int(band_h * 0.12)
    text_zone_h = max(1, band_h - text_zone_top - text_zone_bottom)

    base_font_size = int(img.height * 0.060)
    line_spacing = int(base_font_size * 0.12)

    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_AM,
        safe_w=safe_w,
        max_block_h=text_zone_h,
        max_lines=3,
        start_size=base_font_size,
        min_size=20,
        line_spacing=line_spacing
    )

    y = text_zone_top + max(0, (text_zone_h - total_h) // 2)
    for i, ln in enumerate(lines):
        lw = text_width(draw, ln, font)
        x = (img.width - lw) // 2
        draw.text((x, y), ln, font=font, fill="white")
        y += heights[i] + (spacing if i < len(lines) - 1 else 0)

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_fdr_story(photo_bytes: bytes, title: str, body_text: str, is_square: bool = False) -> BytesIO:
    # Для сторис всегда используем пропорции stories, даже если is_square=True
    ensure_fonts()

    canvas = Image.new("RGB", (STORY_W, STORY_H), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    photo_h = 410
    header_h = 220

    photo = Image.open(BytesIO(photo_bytes)).convert("RGB")
    
    def fit_cover(im: Image.Image, target_w: int, target_h: int) -> Image.Image:
        src_w, src_h = im.size
        scale = max(target_w / src_w, target_h / src_h)
        nw, nh = int(src_w * scale), int(src_h * scale)
        resized = im.resize((nw, nh), Image.LANCZOS)
        left = max(0, (nw - target_w) // 2)
        top = max(0, (nh - target_h) // 2)
        return resized.crop((left, top, left + target_w, top + target_h))
    
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

    out = BytesIO()
    canvas.save(out, format="JPEG", quality=92, optimize=True)
    out.seek(0)
    return out


def make_card_fdr_post(photo_bytes: bytes, title_text: str, highlight_phrase: str, is_square: bool = False) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), resample=Image.Resampling.LANCZOS)
        target_w, target_h = SQUARE_SIZE, SQUARE_SIZE
    else:
        img = crop_to_4x5(img)
        img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
        target_w, target_h = TARGET_W, TARGET_H
    
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
    
    base_font_size = int(img.height * 0.11)
    line_spacing = int(base_font_size * 0.15)
    
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=title_text_upper,
        font_path=FONT_CHP,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=base_font_size,
        min_size=16,
        line_spacing=line_spacing
    )
    
    base_y = img.height - margin_bottom - total_h
    
    # Сначала рисуем фиолетовые плашки
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
        
        y += heights[line_idx] + (spacing if line_idx < len(lines) - 1 else 0)
    
    # Затем рисуем текст поверх
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
        
        y += heights[line_idx] + (spacing if line_idx < len(lines) - 1 else 0)
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_mn_tg(photo_bytes: bytes, title_text: str, is_square: bool = False) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
    
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), resample=Image.Resampling.LANCZOS)
    
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    
    font_size = int(img.width * 0.08)
    font = ImageFont.truetype(FONT_MN, font_size)
    
    text_bbox = draw.textbbox((0, 0), FOOTER_TEXT, font=font)
    text_width_val = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    x = (img.width - text_width_val) // 2
    y = int(img.height * 0.2) - (text_height // 2)
    
    draw.text((x, y), FOOTER_TEXT, font=font, fill=(255, 255, 255, 38))
    
    result = Image.alpha_composite(img, overlay)
    result = result.convert("RGB")
    
    out = BytesIO()
    result.save(out, format="JPEG", quality=95, optimize=True)
    out.seek(0)
    return out


def make_card(photo_bytes: bytes, title_text: str, template: str, body_text: str = "", highlight_phrase: str = "", text_position: str = TEXT_POSITION_TOP, font_size_multiplier: float = 1.0, is_square: bool = False) -> BytesIO:
    if template == "CHP":
        return make_card_chp(photo_bytes, title_text, is_square)
    if template == "AM":
        return make_card_am(photo_bytes, title_text, is_square)
    if template == "FDR_STORY":
        return make_card_fdr_story(photo_bytes, title_text, body_text, is_square)
    if template == "FDR_POST":
        return make_card_fdr_post(photo_bytes, title_text, highlight_phrase, is_square)
    if template == "MN_TG":
        return make_card_mn_tg(photo_bytes, title_text, is_square)
    if template == "MN2":
        return make_card_mn2(photo_bytes, title_text, text_position, font_size_multiplier, is_square)
    return make_card_mn(photo_bytes, title_text, text_position, is_square)


# =========================
# News by link parser
# =========================
def parse_news_from_url(url: str) -> Optional[Dict]:
    """
    Парсит новость по ссылке, извлекает заголовок и изображение
    """
    try:
        # Получаем HTML страницы
        html_content = http_get(url, timeout=REQUEST_TIMEOUT)
        if not html_content:
            return None
        
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Удаляем ненужные элементы
        for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe']):
            tag.decompose()
        
        # Ищем заголовок
        title = None
        
        # Пробуем найти по разным селекторам
        title_selectors = [
            'h1',
            'h1.article__title',
            'h1.news__title',
            'h1.post__title',
            'h1.entry-title',
            '.article-title',
            '.news-title',
            '.post-title',
            '.entry-title',
            'meta[property="og:title"]',
            'meta[name="twitter:title"]'
        ]
        
        for selector in title_selectors:
            if selector.startswith('meta'):
                # Для meta тегов
                meta_tag = soup.find('meta', attrs={'property': selector.split('[')[1].split('=')[1].strip('"\'')})
                if meta_tag and meta_tag.get('content'):
                    title = meta_tag['content']
                    break
            else:
                # Для обычных селекторов
                element = soup.select_one(selector)
                if element:
                    title = element.get_text(strip=True)
                    break
        
        # Если не нашли, пробуем получить из title страницы
        if not title and soup.title:
            title = soup.title.get_text(strip=True)
            # Обрезаем название сайта, если есть
            common_site_names = ['Onliner', 'Sputnik', 'Telegraf', 'Tochka', 'Smartpress', 'Minsknews', 'Mlyn', 'ONT']
            for site in common_site_names:
                if f' - {site}' in title:
                    title = title.split(f' - {site}')[0]
                    break
                elif f' | {site}' in title:
                    title = title.split(f' | {site}')[0]
                    break
        
        # Ищем изображение
        image_url = None
        
        # Пробуем Open Graph изображение
        og_image = soup.find('meta', property='og:image')
        if og_image and og_image.get('content'):
            image_url = og_image['content']
        
        # Если нет og:image, ищем другие изображения
        if not image_url:
            # Ищем Twitter изображение
            twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                image_url = twitter_image['content']
        
        if not image_url:
            # Ищем первое подходящее изображение в статье
            # Сначала ищем в article
            article = soup.find('article') or soup.find(class_=re.compile(r'(content|article|post|news)', re.I))
            if article:
                img = article.find('img', src=True)
                if img and img.get('src'):
                    image_url = normalize_url(url, img['src'])
            
            # Если не нашли, ищем любое большое изображение
            if not image_url:
                for img in soup.find_all('img', src=True):
                    src = img.get('src', '')
                    # Проверяем, что изображение не иконка и не маленькое
                    if any(x in src.lower() for x in ['photo', 'image', 'picture', 'news', 'article', 'post']):
                        if not any(x in src.lower() for x in ['icon', 'logo', 'avatar', 'profile', 'comment']):
                            image_url = normalize_url(url, src)
                            # Проверяем размер, если сможем
                            try:
                                img_data = http_get_bytes(image_url, timeout=3)
                                if img_data:
                                    img_pil = Image.open(BytesIO(img_data))
                                    if img_pil.width > 300 and img_pil.height > 200:
                                        break
                            except:
                                continue
        
        if not title:
            title = "Новость"
        
        return {
            "title": title,
            "image_url": image_url,
            "url": url
        }
        
    except Exception as e:
        logger.error(f"Error parsing news from URL {url}: {e}")
        return None


# =========================
# Prices and terms
# =========================
def get_prices_text() -> str:
    return """
💰 <b>НАШИ ЦЕНЫ</b>

Можем предложить вам несколько вариантов размещений, от одиночных постов до полного комплекса:

🔻 <b>Размещение только в</b> https://www.instagram.com/minsk_news/ 478.000 чел. 
Пост + stories — 550 руб.

🔻 <b>Пакет «МИНИ»</b> (более 860.000 подписчиков) — 685 рублей.

1. https://www.instagram.com/minsk_news/
2. https://www.instagram.com/afishaminsk/
3. https://www.instagram.com/tvoyminsk/
4. https://www.instagram.com/minskgood/
5. https://www.instagram.com/novostiminska/
6. https://www.instagram.com/minskhot/
7. https://www.instagram.com/minsksmile/

Публикации во всех 7 городских медиа со сторис в minsk_news, afishaminsk и tvoyminsk.

🔻 <b>Пакет «СТАНДАРТ»</b> (более 1 300.000 подписчиков): 745 рублей.

1. https://www.instagram.com/minsk_news/
2. https://www.instagram.com/minskchp/
3. https://www.instagram.com/afishaminsk/
4. https://www.instagram.com/tvoyminsk/
5. https://www.instagram.com/vestiminska/
6. https://www.instagram.com/minskpress/
7. https://www.instagram.com/xxminsk/
8. https://www.instagram.com/minskgood/
9. https://www.instagram.com/novostiminska/
10. https://www.instagram.com/minskhot/
11. https://www.instagram.com/minsksmile/

Публикации во всех 11 городских медиа со сторис в minsk_news, afishaminsk, minskchp, tvoyminsk, vestiminska, xxminsk.

🔻 <b>Пакет «ПРЕМИУМ»</b> (более 1 700.000 подписчиков):

<b>Instagram:</b>

1. https://www.instagram.com/minsk_news/
2. https://www.instagram.com/minskchp/
3. https://www.instagram.com/afishaminsk/
4. https://www.instagram.com/tvoyminsk/
5. https://www.instagram.com/vestiminska/
6. https://www.instagram.com/minskpress/
7. https://www.instagram.com/xxminsk/
8. https://www.instagram.com/minskgood/
9. https://www.instagram.com/novostiminska/
10. https://www.instagram.com/minskhot/
11. https://www.instagram.com/minsksmile/

<b>Вконтакте:</b>

1. vk.com/etominsk
2. vk.com/belaruschp
3. vk.com/ominske
4. vk.com/7rabota
5. vk.com/minsktime
6. vk.com/belaris
7. vk.com/belarusfood
8. vk.com/minsksmile
9. vk.com/minskrepost

<b>Телеграм:</b>

1. t.me/vestiminska 47 000 чел. — стоимость одиночного размещения 400 белорусских рублей.
2. t.me/minskchpdtp 16 000 чел.

Публикации во всех 11 городских медиа в Instagram со сторис в minsk_news, afishaminsk, minskchp, tvoyminsk, vestiminska, xxminsk + 9 сообществ в Вконтакте + в 2 канала в Телеграм.
"""


def get_terms_text() -> str:
    return """
🔔 <b>УСЛОВИЯ РАЗМЕЩЕНИЯ:</b>

1. Инстаграм и Вконтакте — пост 1 час на первом месте в ленте, далее пост перекрывается другими новостями.

2. Телеграм — пост на 30 минут на первом месте, далее пост перекрывается другими новостями.

Рекламные посты размещаются на 7 дней в ленте, затем они удаляются.

При заказе комплекса ПРЕМИУМ — посты размещаются на 30 дней в ленте, затем удаление.

Оставить посты можно навсегда, без их удаления. Данная услуга платная: + 50 рублей к стоимости размещений.

🔔 <b>ВАЖНЫЙ МОМЕНТ:</b> Все рекламные посты мы размещаем в новостной стилистике от третьего лица, как обычная новость. Фотографии для публикаций мы используем живые и тематические, рекламные баннеры - мы не размещаем.
"""


# =========================
# Caption formatting (оставлено для совместимости, но не используется)
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
# Keyboard layouts
# =========================
def template_kb(is_square: bool = False):
    kb = InlineKeyboardMarkup()
    prefix = "square:" if is_square else "tpl:"
    kb.row(
        InlineKeyboardButton("📰 МН", callback_data=f"{prefix}MN"),
        InlineKeyboardButton("🚨 ЧП ВМ", callback_data=f"{prefix}CHP"),
    )
    kb.row(
        InlineKeyboardButton("✨ АМ", callback_data=f"{prefix}AM"),
        InlineKeyboardButton("📱 Сторис ФДР", callback_data=f"{prefix}FDR_STORY"),
    )
    kb.row(
        InlineKeyboardButton("💜 Пост ФДР", callback_data=f"{prefix}FDR_POST"),
        InlineKeyboardButton("📱 МН ТГ", callback_data=f"{prefix}MN_TG"),
    )
    kb.row(
        InlineKeyboardButton("🆕 МН 2", callback_data=f"{prefix}MN2"),
    )
    if is_square:
        kb.row(InlineKeyboardButton("◀️ Назад к квадратам", callback_data="square:back"))
    return kb


def text_position_kb(is_square: bool = False):
    kb = InlineKeyboardMarkup(row_width=2)
    prefix = "square_pos:" if is_square else "text_pos:"
    kb.add(
        InlineKeyboardButton("⬆️ Сверху", callback_data=f"{prefix}top"),
        InlineKeyboardButton("⬇️ Снизу", callback_data=f"{prefix}bottom")
    )
    return kb


def font_size_kb(current_multiplier: float = 1.0, is_square: bool = False):
    kb = InlineKeyboardMarkup(row_width=3)
    prefix = "square_font:" if is_square else "font_size:"
    kb.add(
        InlineKeyboardButton("➖", callback_data=f"{prefix}minus:{current_multiplier}"),
        InlineKeyboardButton(f"{int(current_multiplier*100)}%", callback_data=f"{prefix}current"),
        InlineKeyboardButton("➕", callback_data=f"{prefix}plus:{current_multiplier}")
    )
    kb.add(InlineKeyboardButton("✅ Готово", callback_data=f"{prefix}done"))
    return kb


def watermark_type_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📰 МН", callback_data="watermark:mn"),
        InlineKeyboardButton("🚨 ЧП", callback_data="watermark:chp")
    )
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="watermark:cancel"))
    return kb


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
        buttons.append(InlineKeyboardButton(source_name, callback_data=f"news_source:{source_id}"))
    kb.add(*buttons)
    kb.row(
        InlineKeyboardButton("🌐 Все сайты", callback_data="news_source:all"),
        InlineKeyboardButton("❌ Отмена", callback_data="news_source:cancel")
    )
    return kb


def news_item_kb(key: str, link: str):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📖 Полная статья", callback_data=f"read_full:{key}"),
        InlineKeyboardButton("🔗 Источник", url=link)
    )
    return kb


def news_more_kb(source_id: str = None):
    kb = InlineKeyboardMarkup()
    if source_id:
        kb.row(InlineKeyboardButton(f"➕ Еще {NEWS_MORE_SIZE} новостей", callback_data=f"news_more:{source_id}"))
    else:
        kb.row(InlineKeyboardButton(f"➕ Еще {NEWS_MORE_SIZE} новостей", callback_data="news_more:all"))
    return kb


def video_menu_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🎬 Конвертировать в GIF", callback_data="video:gif"),
        InlineKeyboardButton("📝 Оформить видео", callback_data="video:edit")
    )
    kb.row(InlineKeyboardButton("❌ Отмена", callback_data="video:cancel"))
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
    kb.row(InlineKeyboardButton("❌ Отмена", callback_data="video_tpl:cancel"))
    return kb


def video_text_position_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⬆️ Сверху", callback_data="video_pos:top"),
        InlineKeyboardButton("⬇️ Снизу", callback_data="video_pos:bottom"),
        InlineKeyboardButton("❌ Отмена", callback_data="video_pos:cancel")
    )
    return kb


# =========================
# News cache functions
# =========================
def get_news_cache(uid: int) -> Optional[Dict]:
    st = user_state.get(uid) or {}
    cache = st.get("news_cache")
    if not cache:
        return None
    if time.time() - cache.get("ts", 0) > NEWS_CACHE_TTL_SEC:
        return None
    return cache


def set_news_cache(uid: int, items: List[Dict], source_id: str = None):
    st = user_state.get(uid) or {}
    st["news_cache"] = {
        "ts": time.time(),
        "items": items,
        "pos": 0,
        "by_key": {},
        "source_id": source_id
    }
    user_state[uid] = st


def item_key(title: str, url: str) -> str:
    return hashlib.sha256(f"{title}|{url}".encode("utf-8")).hexdigest()[:16]


# =========================
# Health check server
# =========================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write("Бот запущен! 🤖".encode('utf-8'))
    
    def log_message(self, format, *args):
        return


def run_http_server():
    try:
        port = int(os.environ.get('PORT', 10000))
        server_address = ('0.0.0.0', port)
        httpd = HTTPServer(server_address, HealthCheckHandler)
        logger.info(f"🌐 Health check server started on port {port}")
        httpd.serve_forever()
    except Exception as e:
        logger.error(f"Failed to start health check server: {e}")


# =========================
# Callback handlers
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("prices:"))
def on_prices_callback(c):
    action = c.data.split(":", 1)[1]
    
    if action == "list":
        bot.edit_message_text(
            get_prices_text(),
            c.message.chat.id,
            c.message.message_id,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=prices_menu_kb()
        )
        bot.answer_callback_query(c.id)
    
    elif action == "terms":
        bot.edit_message_text(
            get_terms_text(),
            c.message.chat.id,
            c.message.message_id,
            parse_mode="HTML",
            reply_markup=prices_menu_kb()
        )
        bot.answer_callback_query(c.id)
    
    elif action == "close":
        bot.delete_message(c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Меню закрыто")


@bot.callback_query_handler(func=lambda c: c.data.startswith("watermark:"))
def on_watermark_type(c):
    uid = c.from_user.id
    wm_type = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    
    if wm_type == "cancel":
        st.pop("step", None)
        user_state[uid] = st
        bot.edit_message_text(
            "❌ Отменено",
            c.message.chat.id,
            c.message.message_id
        )
        bot.answer_callback_query(c.id, "Отменено")
        return
    
    # Сохраняем тип водяного знака
    st["watermark_type"] = wm_type
    st["step"] = "waiting_watermark_photo"
    user_state[uid] = st
    
    wm_names = {"mn": "MINSK NEWS", "chp": "ЧП Минск"}
    wm_name = wm_names.get(wm_type, wm_type)
    
    bot.edit_message_text(
        f"✅ Выбран водяной знак: <b>{wm_name}</b>\n\n"
        f"📸 Теперь отправь фото, на которое нужно нанести водяной знак.\n\n"
        f"<i>Знак будет расположен по центру с прозрачностью 25%</i>",
        c.message.chat.id,
        c.message.message_id,
        parse_mode="HTML"
    )
    bot.answer_callback_query(c.id, f"Выбран {wm_name}")


@bot.callback_query_handler(func=lambda c: c.data.startswith("font_size:") or c.data.startswith("square_font:"))
def on_font_size_adjust(c):
    uid = c.from_user.id
    parts = c.data.split(":")
    prefix = parts[0]
    action = parts[1]
    
    is_square = (prefix == "square_font")
    
    st = user_state.get(uid) or {}
    
    if action == "done":
        # Проверяем режим новости
        if st.get("step") == "waiting_font_size_for_news":
            st["step"] = "waiting_text_position_for_news"
            user_state[uid] = st
            bot.edit_message_text(
                "✅ Размер шрифта настроен. Теперь выбери расположение текста:",
                c.message.chat.id,
                c.message.message_id,
                reply_markup=text_position_kb(is_square)
            )
        elif is_square:
            st["step"] = "waiting_text_position_square"
            user_state[uid] = st
            bot.edit_message_text(
                "✅ Размер шрифта настроен. Теперь выбери расположение текста:",
                c.message.chat.id,
                c.message.message_id,
                reply_markup=text_position_kb(True)
            )
        else:
            st["step"] = "waiting_text_position"
            user_state[uid] = st
            bot.edit_message_text(
                "✅ Размер шрифта настроен. Теперь выбери расположение текста:",
                c.message.chat.id,
                c.message.message_id,
                reply_markup=text_position_kb()
            )
        bot.answer_callback_query(c.id, "Настройки сохранены")
        return
    
    current = float(parts[2]) if len(parts) > 2 else st.get("font_size_multiplier", 1.0)
    
    if action == "plus":
        new_mult = min(2.0, current + 0.1)
    elif action == "minus":
        new_mult = max(0.5, current - 0.1)
    else:
        bot.answer_callback_query(c.id)
        return
    
    st["font_size_multiplier"] = new_mult
    user_state[uid] = st
    
    # Обновляем сообщение с новой клавиатурой
    template_name = "квадратного МН 2" if is_square else "МН 2"
    bot.edit_message_text(
        f"🔤 Настройка размера шрифта для {template_name}\n\n"
        f"Текущий размер: {int(new_mult*100)}%\n"
        f"Используй кнопки + и - для регулировки.\n"
        f"Нажми «Готово» когда закончишь.",
        c.message.chat.id,
        c.message.message_id,
        reply_markup=font_size_kb(new_mult, is_square)
    )
    
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("square:"))
def on_square_template(c):
    uid = c.from_user.id
    action = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    
    if action == "back":
        st["step"] = "idle"
        user_state[uid] = st
        bot.edit_message_text(
            "⬛ Выбери шаблон для квадратного фото:",
            c.message.chat.id,
            c.message.message_id,
            reply_markup=template_kb(True)
        )
        bot.answer_callback_query(c.id)
        return
    
    st["is_square"] = True
    st["template"] = action
    
    if action == "MN2":
        st["step"] = "waiting_font_size_square"
        user_state[uid] = st
        bot.answer_callback_query(c.id, f"Квадратный шаблон МН 2 выбран ✅")
        bot.edit_message_text(
            "🔤 Настрой размер шрифта для квадратного заголовка:",
            c.message.chat.id,
            c.message.message_id,
            reply_markup=font_size_kb(1.0, True)
        )
    elif action in ["MN", "MN2"]:
        st["step"] = "waiting_text_position_square"
        user_state[uid] = st
        bot.answer_callback_query(c.id, f"Квадратный шаблон {action} выбран ✅")
        template_name = "МН 2" if action == "MN2" else "МН"
        bot.edit_message_text(
            f"⬛ Выбран квадратный шаблон <b>{template_name}</b>\n\nГде разместить текст?",
            c.message.chat.id,
            c.message.message_id,
            parse_mode="HTML",
            reply_markup=text_position_kb(True)
        )
    elif action == "FDR_POST":
        st["step"] = "waiting_photo_fdr_post_square"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Квадратный шаблон 'Пост ФДР' выбран ✅")
        bot.edit_message_text(
            "💜 Выбран квадратный шаблон <b>Пост ФДР</b>\n\n📸 Пришли квадратное фото для поста.\n\n<i>Дальше нужно будет:</i>\n1️⃣ Отправить полный заголовок\n2️⃣ Отправить фразу для фиолетовой плашки",
            c.message.chat.id,
            c.message.message_id,
            parse_mode="HTML"
        )
    elif action == "FDR_STORY":
        st["step"] = "waiting_photo_fdr_story_square"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Квадратный шаблон 'Сторис ФДР' выбран ✅")
        bot.edit_message_text(
            "📱 Выбран квадратный шаблон <b>Сторис ФДР</b>\n\n📸 Пришли квадратное фото для сторис.\n\n<i>Дальше нужно будет:</i>\n1️⃣ Отправить заголовок\n2️⃣ Отправить основной текст",
            c.message.chat.id,
            c.message.message_id,
            parse_mode="HTML"
        )
    elif action == "MN_TG":
        st["step"] = "waiting_photo_mn_tg_square"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Квадратный шаблон 'МН ТГ' выбран ✅")
        bot.edit_message_text(
            "📱 Выбран квадратный шаблон <b>МН ТГ</b>\n\n📸 Пришли квадратное фото для поста.\n\n<i>После фото нужно будет отправить заголовок.</i>",
            c.message.chat.id,
            c.message.message_id,
            parse_mode="HTML"
        )
    else:
        if st.get("step") in {"waiting_template", None}:
            st["step"] = "waiting_photo_square"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок ✅")
        tpl_names = {'CHP': 'ЧП ВМ', 'AM': 'АМ'}
        tpl_name = tpl_names.get(action, action)
        bot.edit_message_text(
            f"Квадратный шаблон выбран: {tpl_name}. Пришли квадратное фото 📷",
            c.message.chat.id,
            c.message.message_id
        )


@bot.callback_query_handler(func=lambda c: c.data.startswith("news_source:"))
def on_news_source_select(c):
    uid = c.from_user.id
    source_id = c.data.split(":", 1)[1]
    
    if source_id == "cancel":
        bot.edit_message_text("❌ Отменено", c.message.chat.id, c.message.message_id)
        bot.answer_callback_query(c.id, "Отменено")
        return
    
    bot.edit_message_text(
        f"⏳ Загружаю новости...",
        c.message.chat.id,
        c.message.message_id
    )
    
    if source_id == "all":
        source_name = "всех источников"
        items = fetch_all_news_fast()
    else:
        source_name = SOURCE_NAMES.get(source_id, source_id)
        items = fetch_news_from_source(source_id)
    
    if not items:
        bot.edit_message_text(
            f"😕 Не удалось загрузить новости с {source_name}.\nПопробуйте позже.",
            c.message.chat.id,
            c.message.message_id
        )
        bot.answer_callback_query(c.id, "Ошибка загрузки")
        return
    
    set_news_cache(uid, items, source_id)
    
    send_news_batch(c.message.chat.id, uid, c.message.message_id, NEWS_FIRST_BATCH)


def send_news_batch(chat_id: int, uid: int, original_msg_id: int, count: int):
    cache = get_news_cache(uid)
    if not cache:
        bot.send_message(chat_id, "❌ Кэш новостей устарел. Начните заново.")
        return
    
    items = cache["items"]
    pos = cache.get("pos", 0)
    
    if pos >= len(items):
        bot.send_message(chat_id, "✅ Все новости показаны!")
        return
    
    end = min(pos + count, len(items))
    
    try:
        bot.delete_message(chat_id, original_msg_id)
    except:
        pass
    
    for i in range(pos, end):
        item = items[i]
        title = item.get("title", "Без названия")
        url = item.get("url", "#")
        source = item.get("source", "")
        image_url = item.get("image", "")
        
        key = item_key(title, url)
        cache["by_key"][key] = item
        
        msg = f"<b>{html.escape(title)}</b>\n\n📰 {html.escape(source)}"
        
        if image_url:
            try:
                photo_bytes = http_get_bytes(image_url, timeout=5)
                if photo_bytes:
                    bot.send_photo(
                        chat_id,
                        photo=photo_bytes,
                        caption=msg,
                        parse_mode="HTML",
                        reply_markup=news_item_kb(key, url)
                    )
                else:
                    bot.send_message(
                        chat_id,
                        msg,
                        parse_mode="HTML",
                        reply_markup=news_item_kb(key, url),
                        disable_web_page_preview=True
                    )
            except:
                bot.send_message(
                    chat_id,
                    msg,
                    parse_mode="HTML",
                    reply_markup=news_item_kb(key, url),
                    disable_web_page_preview=True
                )
        else:
            bot.send_message(
                chat_id,
                msg,
                parse_mode="HTML",
                reply_markup=news_item_kb(key, url),
                disable_web_page_preview=True
            )
        
        time.sleep(0.3)
    
    cache["pos"] = end
    user_state[uid]["news_cache"] = cache
    
    if end < len(items):
        bot.send_message(
            chat_id,
            f"📊 Показано {end} из {len(items)} новостей",
            reply_markup=news_more_kb(cache.get("source_id"))
        )
    else:
        bot.send_message(chat_id, "✅ Все новости загружены!")


@bot.callback_query_handler(func=lambda c: c.data.startswith("news_more:"))
def on_news_more(c):
    uid = c.from_user.id
    source_id = c.data.split(":", 1)[1]
    
    cache = get_news_cache(uid)
    if not cache:
        bot.answer_callback_query(c.id, "❌ Кэш устарел. Начните заново.", show_alert=True)
        return
    
    current_pos = cache.get("pos", 0)
    end = min(current_pos + NEWS_MORE_SIZE, len(cache["items"]))
    
    for i in range(current_pos, end):
        item = cache["items"][i]
        title = item.get("title", "Без названия")
        url = item.get("url", "#")
        source = item.get("source", "")
        image_url = item.get("image", "")
        
        key = item_key(title, url)
        cache["by_key"][key] = item
        
        msg = f"<b>{html.escape(title)}</b>\n\n📰 {html.escape(source)}"
        
        if image_url:
            try:
                photo_bytes = http_get_bytes(image_url, timeout=5)
                if photo_bytes:
                    bot.send_photo(
                        c.message.chat.id,
                        photo=photo_bytes,
                        caption=msg,
                        parse_mode="HTML",
                        reply_markup=news_item_kb(key, url)
                    )
                else:
                    bot.send_message(
                        c.message.chat.id,
                        msg,
                        parse_mode="HTML",
                        reply_markup=news_item_kb(key, url),
                        disable_web_page_preview=True
                    )
            except:
                bot.send_message(
                    c.message.chat.id,
                    msg,
                    parse_mode="HTML",
                    reply_markup=news_item_kb(key, url),
                    disable_web_page_preview=True
                )
        else:
            bot.send_message(
                c.message.chat.id,
                msg,
                parse_mode="HTML",
                reply_markup=news_item_kb(key, url),
                disable_web_page_preview=True
            )
        
        time.sleep(0.2)
    
    cache["pos"] = end
    user_state[uid]["news_cache"] = cache
    
    if end < len(cache["items"]):
        bot.send_message(
            c.message.chat.id,
            f"📊 Показано {end} из {len(cache['items'])} новостей",
            reply_markup=news_more_kb(source_id if source_id != "all" else None)
        )
    else:
        bot.send_message(c.message.chat.id, "✅ Все новости загружены!")
    
    bot.answer_callback_query(c.id, f"Загружено еще {NEWS_MORE_SIZE} новостей")


@bot.callback_query_handler(func=lambda c: c.data.startswith("read_full:"))
def on_read_full_news(c):
    uid = c.from_user.id
    key = c.data.split(":", 1)[1]
    
    cache = get_news_cache(uid)
    if not cache:
        bot.answer_callback_query(c.id, "❌ Новость не найдена. Начните заново.", show_alert=True)
        return
    
    item = cache["by_key"].get(key)
    if not item:
        bot.answer_callback_query(c.id, "❌ Новость устарела.", show_alert=True)
        return
    
    bot.answer_callback_query(c.id, "⏳ Загружаю полный текст...")
    
    url = item.get("url", "")
    title = item.get("title", "")
    image_url = item.get("image", "")
    
    if image_url:
        try:
            photo_bytes = http_get_bytes(image_url, timeout=5)
            if photo_bytes:
                bot.send_photo(
                    c.message.chat.id,
                    photo=photo_bytes,
                    caption=f"<b>{html.escape(title)}</b>",
                    parse_mode="HTML"
                )
        except:
            pass
    
    full_text = fetch_article_text_fast(url)
    if full_text:
        if len(full_text) <= 4000:
            bot.send_message(c.message.chat.id, full_text, parse_mode="HTML")
        else:
            parts = [full_text[i:i+4000] for i in range(0, len(full_text), 4000)]
            for i, part in enumerate(parts):
                if i == 0:
                    bot.send_message(c.message.chat.id, part, parse_mode="HTML")
                else:
                    bot.send_message(
                        c.message.chat.id,
                        f"<i>Продолжение ({i+1}/{len(parts)}):</i>\n\n{part}",
                        parse_mode="HTML"
                    )
    else:
        bot.send_message(c.message.chat.id, "❌ Не удалось загрузить текст статьи")


@bot.callback_query_handler(func=lambda c: c.data.startswith("tpl:") or c.data.startswith("square_tpl:"))
def on_tpl(c):
    uid = c.from_user.id
    parts = c.data.split(":", 1)
    prefix = parts[0]
    tpl = parts[1]
    
    is_square = (prefix == "square_tpl")
    st = user_state.get(uid) or {}
    
    # Проверяем, находимся ли мы в режиме новости по ссылке
    if st.get("step") == "waiting_template_for_news":
        # Обрабатываем новость по ссылке
        st["template"] = tpl
        st["is_square"] = is_square
        
        # Получаем данные новости
        news_title = st.get("news_title", "")
        news_image_url = st.get("news_image_url")
        news_url = st.get("news_url", "")
        
        # Если есть фото по ссылке, скачиваем его
        if news_image_url:
            try:
                photo_bytes = http_get_bytes(news_image_url, timeout=10)
                if not photo_bytes:
                    bot.answer_callback_query(c.id, "❌ Не удалось загрузить фото")
                    return
                
                st["photo_bytes"] = photo_bytes
            except Exception as e:
                logger.error(f"Error downloading news image: {e}")
                bot.answer_callback_query(c.id, "❌ Ошибка загрузки фото")
                return
        else:
            # Если фото нет, просим пользователя прислать своё
            st["step"] = "waiting_photo_for_news"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Выбери шаблон ✅")
            size_text = "квадратное " if is_square else ""
            bot.send_message(
                c.message.chat.id,
                f"📸 Фото не найдено. Пришли своё {size_text}фото для оформления новости.\n\n"
                f"Заголовок новости:\n<b>{html.escape(news_title)}</b>",
                parse_mode="HTML"
            )
            return
        
        # Если есть фото, проверяем нужна ли настройка шрифта/позиции
        if tpl == "MN2":
            st["step"] = "waiting_font_size_for_news"
            user_state[uid] = st
            bot.answer_callback_query(c.id, f"Шаблон МН 2 выбран ✅")
            size_text = "квадратного " if is_square else ""
            bot.send_message(
                c.message.chat.id,
                f"🔤 Настрой размер шрифта для {size_text}заголовка:",
                reply_markup=font_size_kb(1.0, is_square)
            )
        elif tpl in ["MN", "MN2"]:
            st["step"] = "waiting_text_position_for_news"
            user_state[uid] = st
            bot.answer_callback_query(c.id, f"Шаблон {tpl} выбран ✅")
            template_name = "МН 2" if tpl == "MN2" else "МН"
            size_text = "квадратный " if is_square else ""
            bot.send_message(
                c.message.chat.id,
                f"📰 Выбран {size_text}шаблон <b>{template_name}</b>\n\nГде разместить текст?",
                parse_mode="HTML",
                reply_markup=text_position_kb(is_square)
            )
        elif tpl == "FDR_POST":
            st["step"] = "waiting_highlight_for_news"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
            size_text = "квадратный " if is_square else ""
            bot.send_message(
                c.message.chat.id,
                f"💜 Выбран {size_text}шаблон <b>Пост ФДР</b>\n\n"
                f"🎯 Отправь <b>ФРАЗУ</b>, которую нужно выделить фиолетовой плашкой:\n\n"
                f"<i>(можно скопировать часть заголовка: {html.escape(news_title[:50])}...)</i>",
                parse_mode="HTML"
            )
        elif tpl == "FDR_STORY":
            st["step"] = "waiting_body_for_news_story"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Сторис ФДР' выбран ✅")
            size_text = "квадратный " if is_square else ""
            bot.send_message(
                c.message.chat.id,
                f"📱 Выбран {size_text}шаблон <b>Сторис ФДР</b>\n\n"
                f"📝 Заголовок уже есть: <b>{html.escape(news_title)}</b>\n\n"
                f"Теперь отправь <b>ОСНОВНОЙ ТЕКСТ</b> для сторис:",
                parse_mode="HTML"
            )
        else:
            # Для остальных шаблонов сразу создаём карточку
            try:
                font_mult = st.get("font_size_multiplier", 1.0) if tpl == "MN2" else 1.0
                
                card = make_card(
                    st["photo_bytes"],
                    news_title,
                    tpl,
                    text_position=st.get("text_position", TEXT_POSITION_TOP),
                    font_size_multiplier=font_mult,
                    is_square=is_square
                )
                
                size_text = "_square" if is_square else ""
                # Отправляем файлом
                bot.send_document(
                    chat_id=c.message.chat.id,
                    document=BytesIO(card.getvalue()),
                    visible_file_name=f"news_{tpl}{size_text}.jpg",
                    caption=f"✅ Новость оформлена в шаблоне {tpl}\n\n🔗 <a href='{news_url}'>Источник</a>",
                    parse_mode="HTML"
                )
                
                # Сбрасываем состояние
                clear_state(uid)
                bot.answer_callback_query(c.id, "Готово ✅")
                
            except Exception as e:
                logger.error(f"Error creating news card: {e}")
                bot.answer_callback_query(c.id, "❌ Ошибка создания")
                bot.send_message(c.message.chat.id, f"❌ Ошибка: {e}")
        
        return
    
    # Если не в режиме новости, обрабатываем как обычно
    st["template"] = tpl
    st["is_square"] = is_square
    
    if tpl == "MN2":
        st["step"] = "waiting_font_size_square" if is_square else "waiting_font_size"
        user_state[uid] = st
        bot.answer_callback_query(c.id, f"Шаблон МН 2 выбран ✅")
        size_text = "квадратного " if is_square else ""
        bot.send_message(
            c.message.chat.id, 
            f"🔤 Настрой размер шрифта для {size_text}заголовка:",
            reply_markup=font_size_kb(1.0, is_square)
        )
    elif tpl in ["MN", "MN2"]:
        st["step"] = "waiting_text_position_square" if is_square else "waiting_text_position"
        user_state[uid] = st
        bot.answer_callback_query(c.id, f"Шаблон {tpl} выбран ✅")
        template_name = "МН 2" if tpl == "MN2" else "МН"
        size_text = "квадратный " if is_square else ""
        bot.send_message(c.message.chat.id, f"📰 Выбран {size_text}шаблон <b>{template_name}</b>\n\nГде разместить текст?", parse_mode="HTML", reply_markup=text_position_kb(is_square))
    elif tpl == "FDR_POST":
        st["step"] = "waiting_photo_fdr_post_square" if is_square else "waiting_photo_fdr_post"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
        size_text = "квадратное " if is_square else ""
        bot.send_message(c.message.chat.id, f"💜 Выбран шаблон <b>Пост ФДР</b>\n\n📸 Пришли {size_text}фото для поста.\n\n<i>Дальше нужно будет:</i>\n1️⃣ Отправить полный заголовок\n2️⃣ Отправить фразу для фиолетовой плашки", parse_mode="HTML")
    elif tpl == "FDR_STORY":
        st["step"] = "waiting_photo_fdr_story_square" if is_square else "waiting_photo_fdr_story"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Шаблон 'Сторис ФДР' выбран ✅")
        size_text = "квадратное " if is_square else ""
        bot.send_message(c.message.chat.id, f"📱 Выбран шаблон <b>Сторис ФДР</b>\n\n📸 Пришли {size_text}фото для сторис.\n\n<i>Дальше нужно будет:</i>\n1️⃣ Отправить заголовок\n2️⃣ Отправить основной текст", parse_mode="HTML")
    elif tpl == "MN_TG":
        st["step"] = "waiting_photo_mn_tg_square" if is_square else "waiting_photo_mn_tg"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Шаблон 'МН ТГ' выбран ✅")
        size_text = "квадратное " if is_square else ""
        bot.send_message(c.message.chat.id, f"📱 Выбран шаблон <b>МН ТГ</b>\n\n📸 Пришли {size_text}фото для поста.\n\n<i>После фото нужно будет отправить заголовок.</i>", parse_mode="HTML")
    else:
        if st.get("step") in {"waiting_template", None}:
            st["step"] = "waiting_photo_square" if is_square else "waiting_photo"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок ✅")
        tpl_names = {'CHP': 'ЧП ВМ', 'AM': 'АМ'}
        tpl_name = tpl_names.get(tpl, tpl)
        size_text = "квадратный " if is_square else ""
        bot.send_message(c.message.chat.id, f"{size_text}Шаблон выбран: {tpl_name}. Пришли {size_text}фото 📷")


@bot.callback_query_handler(func=lambda c: c.data.startswith("text_pos:") or c.data.startswith("square_pos:"))
def on_text_position(c):
    uid = c.from_user.id
    parts = c.data.split(":", 1)
    prefix = parts[0]
    position = parts[1]
    
    is_square = (prefix == "square_pos")
    st = user_state.get(uid) or {}
    
    # Проверяем режим новости
    if st.get("step") == "waiting_text_position_for_news":
        st["text_position"] = position
        st["step"] = "create_news_card"
        user_state[uid] = st
        
        position_text = "сверху" if position == "top" else "снизу"
        bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")
        
        # Создаём карточку
        try:
            font_mult = st.get("font_size_multiplier", 1.0)
            
            card = make_card(
                st["photo_bytes"],
                st.get("news_title", ""),
                st.get("template", "MN"),
                text_position=position,
                font_size_multiplier=font_mult,
                is_square=st.get("is_square", False)
            )
            
            bot.send_document(
                chat_id=c.message.chat.id,
                document=BytesIO(card.getvalue()),
                visible_file_name="news.jpg",
                caption=f"✅ Новость готова!\n\n🔗 <a href='{st.get('news_url', '')}'>Источник</a>",
                parse_mode="HTML"
            )
            
            clear_state(uid)
            
        except Exception as e:
            logger.error(f"Error creating news card: {e}")
            bot.send_message(c.message.chat.id, f"❌ Ошибка: {e}")
        
        return
    
    # Если не в режиме новости, обрабатываем как обычно
    st["text_position"] = position
    
    if is_square:
        st["step"] = "waiting_photo_square"
    else:
        st["step"] = "waiting_photo"
    
    user_state[uid] = st
    
    position_text = "сверху" if position == "top" else "снизу"
    size_text = "квадратного " if is_square else ""
    bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")
    bot.send_message(c.message.chat.id, f"Текст будет расположен <b>{position_text}</b> {size_text}фотографии.\n\nТеперь пришли {size_text}фото 📷", parse_mode="HTML")


# =========================
# Video callbacks
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
            # Здесь должна быть функция обработки видео
            # result = process_video_with_template(st["video_bytes"], action, title="")
            # bot.send_video(c.message.chat.id, video=result, caption="📱 Видео в стиле МН ТГ")
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            bot.send_message(c.message.chat.id, "⚠️ Обработка видео временно недоступна")
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
# Message handlers
# =========================
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")
    st["step"] = "idle"
    user_state[uid] = st

    bot.send_message(
        message.chat.id,
        "👋 <b>Привет! Я бот для оформления постов</b>\n\n"
        "<b>📝 Основные функции:</b>\n"
        "• 📝 Оформление постов с фото (7 шаблонов)\n"
        "• ⬛ <b>Квадраты</b> - те же шаблоны для квадратных фото\n"
        "• 🔗 Новость по ссылке - отправь ссылку, я найду заголовок и фото\n"
        "• 📰 Получение свежих новостей из 8 источников\n"
        "• ✨ Улучшение качества фото (+20% резкость, +15% насыщенность)\n"
        "• 💧 <b>Водяные знаки</b> - нанеси \"MINSK NEWS\" или \"ЧП Минск\" на фото\n"
        "• 💰 <b>Цены и условия размещения</b>\n"
        "• Работа с видео (конвертация в GIF, оформление)\n\n"
        "Выбери действие 👇",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(commands=["post"])
def cmd_post(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")
    st["step"] = "waiting_template"
    user_state[uid] = st
    bot.send_message(message.chat.id, "📝 Выбери шаблон оформления:", reply_markup=template_kb())


@bot.message_handler(commands=["square"])
def cmd_square(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_template_square"
    user_state[uid] = st
    bot.send_message(message.chat.id, "⬛ Выбери шаблон для квадратного фото:", reply_markup=template_kb(True))


@bot.message_handler(commands=["news"])
def cmd_news(message):
    bot.send_message(
        message.chat.id,
        "📰 <b>Выбери источник новостей:</b>\n\n"
        "• Выбери конкретный сайт для быстрой загрузки\n"
        "• Или нажми «Все сайты» для общей ленты\n\n"
        "<i>Загрузка займет не более 1-2 минут</i>",
        parse_mode="HTML",
        reply_markup=news_sources_kb()
    )


@bot.message_handler(commands=["template"])
def cmd_template(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_template"
    user_state[uid] = st
    bot.send_message(message.chat.id, "Выбери шаблон оформления:", reply_markup=template_kb())


@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    uid = message.from_user.id
    clear_state(uid)
    bot.send_message(message.chat.id, "🛑 Бот сброшен в исходное состояние.\nМожно начинать новую команду.", reply_markup=main_menu_kb())


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


@bot.message_handler(func=lambda message: message.text == BTN_POST)
def handle_post_button(message):
    cmd_post(message)


@bot.message_handler(func=lambda message: message.text == BTN_SQUARE)
def handle_square_button(message):
    cmd_square(message)


@bot.message_handler(func=lambda message: message.text == BTN_NEWS)
def handle_news_button(message):
    cmd_news(message)


@bot.message_handler(func=lambda message: message.text == BTN_NEWS_BY_LINK)
def cmd_news_by_link(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_news_link"
    st.setdefault("template", "MN")
    user_state[uid] = st
    
    bot.send_message(
        message.chat.id,
        "🔗 <b>Новость по ссылке</b>\n\n"
        "Отправь ссылку на новость, и я:\n"
        "1️⃣ Извлеку заголовок\n"
        "2️⃣ Найду главное фото\n"
        "3️⃣ Предложу выбрать шаблон оформления (обычный или квадратный)\n\n"
        "<i>Поддерживаются сайты: Onliner, Sputnik, Telegraf, Tochka, Smartpress, Minsknews, Mlyn, ONT и другие</i>",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(func=lambda message: message.text == BTN_ENHANCE)
def cmd_enhance(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_enhance_photo"
    user_state[uid] = st
    
    bot.send_message(
        message.chat.id,
        "✨ <b>Улучшение качества фото</b>\n\n"
        "Отправь фото (как файл или картинку), и я:\n"
        "• 🔍 Увеличу резкость на +20%\n"
        "• 🎨 Увеличу насыщенность на +15%\n\n"
        "<i>Лучше отправлять фото как файл (документ) для сохранения оригинального качества</i>",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(func=lambda message: message.text == BTN_WATERMARK)
def cmd_watermark(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_watermark_type"
    user_state[uid] = st
    
    bot.send_message(
        message.chat.id,
        "💧 <b>Водяные знаки</b>\n\n"
        "Выбери тип водяного знака:",
        parse_mode="HTML",
        reply_markup=watermark_type_kb()
    )


@bot.message_handler(func=lambda message: message.text == BTN_PRICES)
def cmd_prices(message):
    bot.send_message(
        message.chat.id,
        "💰 <b>Цены и условия размещения</b>\n\n"
        "Выбери интересующий раздел:",
        parse_mode="HTML",
        reply_markup=prices_menu_kb()
    )


@bot.message_handler(func=lambda message: message.text == "🎥 Видео")
def cmd_video_menu(message):
    bot.send_message(
        message.chat.id,
        "🎥 <b>Работа с видео</b>\n\n"
        "Выбери действие:",
        parse_mode="HTML",
        reply_markup=video_menu_kb()
    )


@bot.message_handler(func=lambda message: message.text == "🎬 Видео в GIF")
def cmd_video_to_gif(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_video_for_gif"
    user_state[uid] = st
    
    bot.send_message(
        message.chat.id,
        "🎬 Отправь видео, и я конвертирую его в GIF.\n\n"
        "• Видео будет обрезано до 10 секунд\n"
        "• Размер будет оптимизирован",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(content_types=["photo", "document"])
def on_photo_or_document(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    
    # Обработка фото для водяного знака
    if st.get("step") == "waiting_watermark_photo":
        try:
            if message.content_type == "photo":
                file_id = message.photo[-1].file_id
            else:
                doc = message.document
                if not doc.mime_type or not doc.mime_type.startswith("image/"):
                    bot.reply_to(message, "❌ Это не изображение. Отправь JPG или PNG файл.")
                    return
                file_id = doc.file_id
            
            photo_bytes = tg_file_bytes(file_id)
            
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимум 20MB.")
                return
            
            processing_msg = bot.reply_to(message, "⏳ Наношу водяной знак...")
            
            wm_type = st.get("watermark_type", "mn")
            
            # Применяем соответствующий водяной знак
            if wm_type == "mn":
                result = apply_watermark_mn(photo_bytes)
                caption = "💧 Водяной знак <b>MINSK NEWS</b> нанесён!"
            else:  # chp
                result = apply_watermark_chp(photo_bytes)
                caption = "💧 Водяной знак <b>ЧП Минск</b> нанесён!"
            
            # Отправляем результат
            bot.send_document(
                message.chat.id,
                document=result,
                visible_file_name=f"watermark_{wm_type}.jpg",
                caption=caption,
                parse_mode="HTML"
            )
            
            bot.delete_message(message.chat.id, processing_msg.message_id)
            
            # Сбрасываем состояние
            clear_state(uid)
            return
            
        except Exception as e:
            logger.error(f"Error applying watermark: {e}")
            bot.reply_to(message, f"❌ Ошибка при нанесении водяного знака: {e}")
            return
    
    # Обработка улучшения фото
    if st.get("step") == "waiting_enhance_photo":
        try:
            if message.content_type == "photo":
                file_id = message.photo[-1].file_id
            else:
                doc = message.document
                if not doc.mime_type or not doc.mime_type.startswith("image/"):
                    bot.reply_to(message, "❌ Это не изображение. Отправь JPG или PNG файл.")
                    return
                file_id = doc.file_id
            
            photo_bytes = tg_file_bytes(file_id)
            
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимум 20MB.")
                return
            
            processing_msg = bot.reply_to(message, "⏳ Улучшаю качество...")
            
            enhanced = enhance_image_simple(photo_bytes)
            
            bot.send_document(
                message.chat.id,
                document=enhanced,
                visible_file_name="enhanced_photo.jpg",
                caption="✨ Фото улучшено!\n\n• Резкость +20%\n• Насыщенность +15%"
            )
            
            bot.delete_message(message.chat.id, processing_msg.message_id)
            st["step"] = "idle"
            user_state[uid] = st
            return
            
        except Exception as e:
            logger.error(f"Error enhancing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка при улучшении: {e}")
            return
    
    # Обработка фото для новости, если не нашлось автоматически
    if st.get("step") == "waiting_photo_for_news":
        try:
            if message.content_type == "photo":
                file_id = message.photo[-1].file_id
            else:
                file_id = message.document.file_id
            
            photo_bytes = tg_file_bytes(file_id)

            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return

            st["photo_bytes"] = photo_bytes
            
            # Проверяем нужна ли настройка шрифта/позиции
            tpl = st.get("template")
            news_title = st.get("news_title", "")
            is_square = st.get("is_square", False)
            
            if tpl == "MN2":
                st["step"] = "waiting_font_size_for_news"
                user_state[uid] = st
                size_text = "квадратного " if is_square else ""
                bot.reply_to(
                    message,
                    f"📸 Фото сохранено!\n\n🔤 Настрой размер шрифта для {size_text}заголовка:",
                    reply_markup=font_size_kb(1.0, is_square)
                )
            elif tpl in ["MN", "MN2"]:
                st["step"] = "waiting_text_position_for_news"
                user_state[uid] = st
                bot.reply_to(
                    message,
                    f"📸 Фото сохранено!\n\n📰 Где разместить текст?",
                    reply_markup=text_position_kb(is_square)
                )
            elif tpl == "FDR_POST":
                st["step"] = "waiting_highlight_for_news"
                user_state[uid] = st
                bot.reply_to(
                    message,
                    f"📸 Фото сохранено!\n\n"
                    f"🎯 Отправь <b>ФРАЗУ</b>, которую нужно выделить фиолетовой плашкой:\n\n"
                    f"<i>(можно скопировать часть заголовка: {html.escape(news_title[:50])}...)</i>",
                    parse_mode="HTML"
                )
            elif tpl == "FDR_STORY":
                st["step"] = "waiting_body_for_news_story"
                user_state[uid] = st
                bot.reply_to(
                    message,
                    f"📸 Фото сохранено!\n\n"
                    f"📝 Заголовок: <b>{html.escape(news_title)}</b>\n\n"
                    f"Теперь отправь <b>ОСНОВНОЙ ТЕКСТ</b> для сторис:",
                    parse_mode="HTML"
                )
            else:
                # Для остальных шаблонов сразу создаём карточку
                try:
                    font_mult = st.get("font_size_multiplier", 1.0) if tpl == "MN2" else 1.0
                    
                    card = make_card(
                        photo_bytes,
                        news_title,
                        tpl,
                        text_position=st.get("text_position", TEXT_POSITION_TOP),
                        font_size_multiplier=font_mult,
                        is_square=is_square
                    )
                    
                    size_text = "_square" if is_square else ""
                    bot.send_document(
                        chat_id=message.chat.id,
                        document=BytesIO(card.getvalue()),
                        visible_file_name=f"news_{tpl}{size_text}.jpg",
                        caption=f"✅ Новость готова!\n\n🔗 <a href='{st.get('news_url', '')}'>Источник</a>",
                        parse_mode="HTML"
                    )
                    
                    clear_state(uid)
                    
                except Exception as e:
                    logger.error(f"Error creating news card: {e}")
                    bot.reply_to(message, f"❌ Ошибка: {e}")
            
        except Exception as e:
            logger.error(f"Error processing photo for news: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
        return

    if st.get("step") == "waiting_template":
        bot.send_message(message.chat.id, "Сначала выбери шаблон:", reply_markup=template_kb())
        return

    if st.get("step") == "waiting_template_square":
        bot.send_message(message.chat.id, "Сначала выбери шаблон для квадратного фото:", reply_markup=template_kb(True))
        return

    # Обработка фото для квадратных шаблонов
    square_steps = [
        "waiting_photo_square",
        "waiting_photo_fdr_post_square",
        "waiting_photo_fdr_story_square",
        "waiting_photo_mn_tg_square"
    ]
    
    if st.get("step") in square_steps:
        try:
            if message.content_type == "photo":
                file_id = message.photo[-1].file_id
            else:
                file_id = message.document.file_id
            
            photo_bytes = tg_file_bytes(file_id)

            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return

            st["photo_bytes"] = photo_bytes
            st["is_square"] = True
            
            step = st.get("step")
            
            if step == "waiting_photo_square":
                st["step"] = "waiting_title"
                user_state[uid] = st
                bot.reply_to(message, "📸 Квадратное фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
            
            elif step == "waiting_photo_fdr_post_square":
                st["step"] = "waiting_title_fdr_post"
                user_state[uid] = st
                bot.reply_to(message, "📸 Квадратное фото сохранено!\n\nТеперь отправь <b>ПОЛНЫЙ ЗАГОЛОВОК</b> поста:", parse_mode="HTML")
            
            elif step == "waiting_photo_fdr_story_square":
                st["step"] = "waiting_title_fdr_story"
                user_state[uid] = st
                bot.reply_to(message, "📸 Квадратное фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для сторис:", parse_mode="HTML")
            
            elif step == "waiting_photo_mn_tg_square":
                st["step"] = "waiting_title"
                user_state[uid] = st
                bot.reply_to(message, "📸 Квадратное фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
            
            return

        except Exception as e:
            logger.error(f"Error processing square photo: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return

    # Обработка фото для стандартных шаблонов
    if st.get("step") in ["waiting_photo", "waiting_photo_fdr_post", "waiting_photo_fdr_story", "waiting_photo_mn_tg"]:
        try:
            if message.content_type == "photo":
                file_id = message.photo[-1].file_id
            else:
                file_id = message.document.file_id
            
            photo_bytes = tg_file_bytes(file_id)

            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return

            st["photo_bytes"] = photo_bytes
            
            step = st.get("step")
            
            if step == "waiting_photo":
                st["step"] = "waiting_title"
                user_state[uid] = st
                bot.reply_to(message, "📸 Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
            
            elif step == "waiting_photo_fdr_post":
                st["step"] = "waiting_title_fdr_post"
                user_state[uid] = st
                bot.reply_to(message, "📸 Фото сохранено!\n\nТеперь отправь <b>ПОЛНЫЙ ЗАГОЛОВОК</b> поста:", parse_mode="HTML")
            
            elif step == "waiting_photo_fdr_story":
                st["step"] = "waiting_title_fdr_story"
                user_state[uid] = st
                bot.reply_to(message, "📸 Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для сторис:", parse_mode="HTML")
            
            elif step == "waiting_photo_mn_tg":
                st["step"] = "waiting_title"
                user_state[uid] = st
                bot.reply_to(message, "📸 Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
            
            return

        except Exception as e:
            logger.error(f"Error processing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return

    bot.reply_to(message, "Не знаю, что делать с этим фото. Начни с /post")


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
            # Здесь должна быть функция конвертации
            # gif_bytes = convert_video_to_gif(video_bytes, max_duration=10, fps=10)
            # bot.send_animation(message.chat.id, animation=gif_bytes, caption="🎬 Видео конвертировано в GIF!")
            bot.delete_message(message.chat.id, processing_msg.message_id)
            bot.send_message(message.chat.id, "⚠️ Конвертация видео временно недоступна")
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


@bot.message_handler(content_types=["text"])
def on_text(message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    st = user_state.get(uid) or {"template": "MN", "step": "idle"}

    # Обработка кнопок главного меню
    if text == BTN_POST:
        cmd_post(message)
        return
    if text == BTN_SQUARE:
        cmd_square(message)
        return
    if text == BTN_NEWS:
        cmd_news(message)
        return
    if text == BTN_NEWS_BY_LINK:
        cmd_news_by_link(message)
        return
    if text == BTN_ENHANCE:
        cmd_enhance(message)
        return
    if text == BTN_WATERMARK:
        cmd_watermark(message)
        return
    if text == BTN_PRICES:
        cmd_prices(message)
        return
    if text == "🎥 Видео":
        cmd_video_menu(message)
        return
    if text == "🎬 Видео в GIF":
        cmd_video_to_gif(message)
        return

    step = st.get("step")

    # Обработка ссылки на новость
    if step == "waiting_news_link":
        # Проверяем, что это валидная ссылка
        if not validate_url(text):
            bot.reply_to(message, "❌ Это не похоже на валидную ссылку. Попробуй ещё раз или нажми /stop для отмены.")
            return
        
        processing_msg = bot.reply_to(message, "⏳ Анализирую ссылку и ищу фото...")
        
        # Парсим новость
        news_data = parse_news_from_url(text)
        
        if not news_data:
            bot.edit_message_text(
                "❌ Не удалось получить данные по ссылке.\n"
                "Попробуй другую ссылку или нажми /stop для отмены.",
                message.chat.id,
                processing_msg.message_id
            )
            return
        
        # Сохраняем данные в состояние
        st["news_title"] = news_data["title"]
        st["news_image_url"] = news_data["image_url"]
        st["news_url"] = news_data["url"]
        st["step"] = "waiting_template_for_news"
        user_state[uid] = st
        
        # Отправляем информацию о найденной новости
        info_text = (
            f"🔍 <b>Найдена новость:</b>\n\n"
            f"📰 <b>Заголовок:</b>\n{html.escape(news_data['title'])}\n\n"
        )
        
        if news_data["image_url"]:
            info_text += f"🖼️ <b>Фото найдено</b>\n\n"
        else:
            info_text += f"⚠️ <b>Фото не найдено</b> - будешь использовать своё?\n\n"
        
        info_text += f"📋 <b>Теперь выбери шаблон оформления (обычный или квадратный):</b>"
        
        # Создаем клавиатуру с выбором обычных и квадратных шаблонов
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("📰 МН", callback_data="tpl:MN"),
            InlineKeyboardButton("⬛ МН (квадрат)", callback_data="square_tpl:MN"),
        )
        kb.row(
            InlineKeyboardButton("🚨 ЧП ВМ", callback_data="tpl:CHP"),
            InlineKeyboardButton("⬛ ЧП ВМ (квадрат)", callback_data="square_tpl:CHP"),
        )
        kb.row(
            InlineKeyboardButton("✨ АМ", callback_data="tpl:AM"),
            InlineKeyboardButton("⬛ АМ (квадрат)", callback_data="square_tpl:AM"),
        )
        kb.row(
            InlineKeyboardButton("📱 Сторис ФДР", callback_data="tpl:FDR_STORY"),
            InlineKeyboardButton("⬛ Сторис ФДР (квадрат)", callback_data="square_tpl:FDR_STORY"),
        )
        kb.row(
            InlineKeyboardButton("💜 Пост ФДР", callback_data="tpl:FDR_POST"),
            InlineKeyboardButton("⬛ Пост ФДР (квадрат)", callback_data="square_tpl:FDR_POST"),
        )
        kb.row(
            InlineKeyboardButton("📱 МН ТГ", callback_data="tpl:MN_TG"),
            InlineKeyboardButton("⬛ МН ТГ (квадрат)", callback_data="square_tpl:MN_TG"),
        )
        kb.row(
            InlineKeyboardButton("🆕 МН 2", callback_data="tpl:MN2"),
            InlineKeyboardButton("⬛ МН 2 (квадрат)", callback_data="square_tpl:MN2"),
        )
        
        bot.edit_message_text(
            info_text,
            message.chat.id,
            processing_msg.message_id,
            parse_mode="HTML",
            reply_markup=kb
        )
        return

    # Обработка выделенной фразы для FDR_POST в режиме новости
    if step == "waiting_highlight_for_news":
        if not text:
            bot.reply_to(message, "❌ Фраза не может быть пустой. Отправь текст:")
            return
        
        st["highlight_phrase"] = text
        
        try:
            card = make_card(
                st["photo_bytes"],
                st.get("news_title", ""),
                "FDR_POST",
                highlight_phrase=text,
                is_square=st.get("is_square", False)
            )
            
            size_text = "_square" if st.get("is_square") else ""
            bot.send_document(
                chat_id=message.chat.id,
                document=BytesIO(card.getvalue()),
                visible_file_name=f"news_fdr_post{size_text}.jpg",
                caption=f"✅ Новость готова!\n\n🔗 <a href='{st.get('news_url', '')}'>Источник</a>",
                parse_mode="HTML"
            )
            
            clear_state(uid)
            
        except Exception as e:
            logger.error(f"Error creating FDR_POST for news: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return

    # Обработка основного текста для FDR_STORY в режиме новости
    if step == "waiting_body_for_news_story":
        if not text:
            bot.reply_to(message, "❌ Текст не может быть пустым. Отправь текст:")
            return
        
        try:
            card = make_card(
                st["photo_bytes"],
                st.get("news_title", ""),
                "FDR_STORY",
                body_text=text,
                is_square=st.get("is_square", False)
            )
            
            size_text = "_square" if st.get("is_square") else ""
            bot.send_document(
                chat_id=message.chat.id,
                document=BytesIO(card.getvalue()),
                visible_file_name=f"news_story{size_text}.jpg",
                caption=f"✅ Сторис готова!\n\n🔗 <a href='{st.get('news_url', '')}'>Источник</a>",
                parse_mode="HTML"
            )
            
            clear_state(uid)
            
        except Exception as e:
            logger.error(f"Error creating story for news: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return

    # Обработка заголовка для FDR_STORY
    if step == "waiting_title_fdr_story":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым. Отправь текст:")
            return
        
        st["title"] = text
        st["step"] = "waiting_body_fdr_story"
        user_state[uid] = st
        
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\nТеперь отправь <b>ОСНОВНОЙ ТЕКСТ</b> для сторис:", parse_mode="HTML")
        return

    # Обработка основного текста для FDR_STORY
    if step == "waiting_body_fdr_story":
        if not st.get("photo_bytes"):
            bot.reply_to(message, "❌ Фото потерялось. Начни заново с /post")
            clear_state(uid)
            return

        try:
            card = make_card(
                st["photo_bytes"], 
                st["title"], 
                "FDR_STORY", 
                body_text=text,
                is_square=st.get("is_square", False)
            )
            
            size_text = "_square" if st.get("is_square") else ""
            # Отправляем файлом
            bot.send_document(
                chat_id=message.chat.id,
                document=BytesIO(card.getvalue()),
                visible_file_name=f"story{size_text}.jpg",
                caption="✅ Сторис готова!"
            )
            
            # Сбрасываем состояние
            clear_state(uid)
            
        except Exception as e:
            logger.error(f"Error creating story: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании сторис: {e}")
        return

    # Обработка полного заголовка для FDR_POST
    if step == "waiting_title_fdr_post":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым. Отправь текст:")
            return
        
        st["full_title"] = text
        st["step"] = "waiting_highlight_fdr_post"
        user_state[uid] = st
        
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n<b>{html.escape(text)}</b>\n\n🎯 Теперь отправь <b>ФРАЗУ</b>, которую нужно выделить фиолетовой плашкой:\n\n<i>(можно скопировать часть заголовка или написать свою)</i>", parse_mode="HTML")
        return

    # Обработка выделенной фразы для FDR_POST
    if step == "waiting_highlight_fdr_post":
        if not text:
            bot.reply_to(message, "❌ Фраза не может быть пустой. Отправь текст:")
            return
        
        st["highlight_phrase"] = text
        
        try:
            card = make_card(
                st["photo_bytes"], 
                st["full_title"], 
                "FDR_POST", 
                highlight_phrase=st["highlight_phrase"],
                is_square=st.get("is_square", False)
            )
            
            size_text = "_square" if st.get("is_square") else ""
            # Отправляем файлом
            bot.send_document(
                chat_id=message.chat.id,
                document=BytesIO(card.getvalue()),
                visible_file_name=f"post{size_text}.jpg",
                caption="✅ Пост готов!"
            )
            
            # Сбрасываем состояние
            clear_state(uid)
            
        except Exception as e:
            logger.error(f"Error creating FDR_POST: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании поста: {e}")
        return

    # Обработка заголовка для остальных шаблонов
    if step == "waiting_title":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым. Отправь текст:")
            return
        
        try:
            font_mult = st.get("font_size_multiplier", 1.0) if st.get("template") == "MN2" else 1.0
            
            card = make_card(
                st["photo_bytes"], 
                text, 
                st.get("template", "MN"), 
                text_position=st.get("text_position", TEXT_POSITION_TOP),
                font_size_multiplier=font_mult,
                is_square=st.get("is_square", False)
            )
            
            size_text = "_square" if st.get("is_square") else ""
            # Отправляем файлом
            bot.send_document(
                chat_id=message.chat.id,
                document=BytesIO(card.getvalue()),
                visible_file_name=f"post{size_text}.jpg",
                caption="✅ Пост готов!"
            )
            
            # Сбрасываем состояние
            clear_state(uid)
            
        except Exception as e:
            logger.error(f"Error creating card: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании карточки: {e}")
        return

    # Если мы в состоянии ожидания шаблона
    if step == "waiting_template":
        bot.send_message(message.chat.id, "Выбери шаблон кнопками:", reply_markup=template_kb())
        return
    
    if step == "waiting_template_square":
        bot.send_message(message.chat.id, "Выбери шаблон для квадратного фото:", reply_markup=template_kb(True))
        return

    # Если в состоянии ожидания расположения текста
    if step == "waiting_text_position":
        bot.send_message(message.chat.id, "Сначала выбери расположение текста:", reply_markup=text_position_kb())
        return
    
    if step == "waiting_text_position_square":
        bot.send_message(message.chat.id, "Сначала выбери расположение текста для квадратного фото:", reply_markup=text_position_kb(True))
        return

    # Если в состоянии ожидания настройки шрифта
    if step == "waiting_font_size":
        bot.send_message(message.chat.id, "Сначала настрой размер шрифта:", reply_markup=font_size_kb(st.get("font_size_multiplier", 1.0)))
        return
    
    if step == "waiting_font_size_square":
        bot.send_message(message.chat.id, "Сначала настрой размер шрифта для квадратного фото:", reply_markup=font_size_kb(st.get("font_size_multiplier", 1.0), True))
        return

    # Если ничего не подошло, показываем главное меню
    bot.send_message(message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())


# =========================
# NewsAutoPublisher
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
            items = fetch_all_news_fast()
            
            if not items:
                msg = "😕 За последние 24 часа новостей не найдено"
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
            
            self.bot.send_message(self.chat_id, header, parse_mode="HTML")
            
            for item in items[:5]:  # Отправляем только 5 первых для примера
                title = item.get("title", "")
                url = item.get("url", "#")
                source = item.get("source", "")
                
                msg = f"<b>{html.escape(title)}</b>\n\n📰 {html.escape(source)}"
                self.bot.send_message(self.chat_id, msg, parse_mode="HTML", disable_web_page_preview=True)
                time.sleep(0.5)
            
            logger.info(f"News digest published successfully")
            
        except Exception as e:
            logger.error(f"Failed to publish news digest: {e}")


# =========================
# Main execution
# =========================
if __name__ == "__main__":
    logger.info("Starting bot...")
    try:
        ensure_fonts()
        logger.info("Fonts loaded successfully")
        
        news_publisher = None
        if AUTO_NEWS_CHAT_ID:
            news_publisher = NewsAutoPublisher(bot, AUTO_NEWS_CHAT_ID)
            news_publisher.start()
        
        http_thread = threading.Thread(target=run_http_server, daemon=True)
        http_thread.start()
        logger.info("🌐 Health check server thread started")
        
        logger.info("🤖 Bot started polling...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60, logger_level=logging.ERROR)
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        if news_publisher:
            news_publisher.stop()
        try:
            if os.path.exists(lock_file):
                os.unlink(lock_file)
        except:
            pass
        raise
