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
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urljoin

import requests
import httpx
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    InputMediaPhoto, InputMediaVideo
)
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# =========================
# Проверка на единственный экземпляр
# =========================
lock_file = '/tmp/bot_instance.lock'
lock_fd = None

def check_single_instance():
    global lock_fd
    try:
        if os.path.exists(lock_file):
            try:
                os.unlink(lock_file)
            except:
                pass
        
        lock_fd = open(lock_file, 'w')
        fcntl.lockf(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(str(os.getpid()))
        lock_fd.flush()
        
        def unlock():
            try:
                if lock_fd:
                    fcntl.lockf(lock_fd, fcntl.LOCK_UN)
                    lock_fd.close()
                if os.path.exists(lock_file):
                    os.unlink(lock_file)
            except:
                pass
        
        atexit.register(unlock)
        return True
        
    except IOError:
        if lock_fd:
            lock_fd.close()
        if os.path.exists(lock_file):
            try:
                os.unlink(lock_file)
                return check_single_instance()
            except:
                pass
        return False
    except Exception as e:
        print(f"Error checking single instance: {e}")
        return True

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
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

CHANNEL_MN = (os.getenv("CHANNEL_MN") or "").strip()
CHANNEL_CHP = (os.getenv("CHANNEL_CHP") or "").strip()
CHANNEL_AFISHA = (os.getenv("CHANNEL_AFISHA") or "").strip()
CHANNEL_TEST = (os.getenv("CHANNEL_TEST") or "").strip()

if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL
if CHANNEL_MN and not CHANNEL_MN.startswith("@"):
    CHANNEL_MN = "@" + CHANNEL_MN
if CHANNEL_CHP and not CHANNEL_CHP.startswith("@"):
    CHANNEL_CHP = "@" + CHANNEL_CHP
if CHANNEL_AFISHA and not CHANNEL_AFISHA.startswith("@"):
    CHANNEL_AFISHA = "@" + CHANNEL_AFISHA
if CHANNEL_TEST and not CHANNEL_TEST.startswith("@"):
    CHANNEL_TEST = "@" + CHANNEL_TEST

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN must not contain spaces")

if not SUGGEST_URL and BOT_USERNAME:
    SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"

MAX_FILE_SIZE = 50 * 1024 * 1024
REQUEST_TIMEOUT = 30

TARGET_W, TARGET_H = 720, 900
STORY_W = 720
STORY_H = 1280

FDR_POST_PURPLE_COLOR = (122, 58, 240)
TEXT_POSITION_TOP = "top"
TEXT_POSITION_BOTTOM = "bottom"

FONT_MN = "CaviarDreams.ttf"
FONT_MN_BOLD = "CaviarDreams_Bold.ttf"
FONT_CHP = "Montserrat-Black.ttf"
FONT_AM = "IntroInline.ttf"
FONT_MONTSERRAT_BLACK = "Montserrat-Black.ttf"
FONT_PATH = "Inter-ExtraBold.ttf"
FONT_FALLBACK = "Montserrat-Black.ttf"
FONT_REGULAR = "Inter-Regular.ttf"

FOOTER_TEXT = "MINSK NEWS"

MN_TITLE_ZONE_PCT = 0.23
CHP_GRADIENT_PCT = 0.48
AM_TOP_BLUR_PCT = 0.20
AM_BLUR_RADIUS = 18
AM_BLUR_BLEND = 0.50

BRIGHTNESS_FACTOR = 0.85
GRADIENT_HEIGHT_PCT = 0.48
GRADIENT_MAX_ALPHA = 220
MARGIN_TOP_PCT = 0.15
TEXT_MAX_WIDTH_PCT = 0.80
LINE_SPACING_RATIO = 0.22
DATE_PLACE_BOTTOM_MARGIN = 180
DATE_PLACE_TOP_MARGIN = 130
DATE_PLACE_LINE_SPACING = 15
DATE_PLACE_LEFT_MARGIN = 45
RUBRIC_TOP_MARGIN = 40
RUBRIC_PADDING = 20
RUBRIC_RADIUS = 25
DATE_PLACE_PADDING = 15
DATE_PLACE_RADIUS = 25

TEXT_COLOR = (255, 255, 255)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

HIGHLIGHT_COLORS = {
    "red": (255, 80, 80),
    "yellow": (255, 220, 80),
    "blue": (80, 150, 255)
}


# =========================
# BOT + SESSION
# =========================
bot = telebot.TeleBot(TOKEN)

try:
    bot.remove_webhook()
    logger.info("Webhook removed successfully")
except Exception as e:
    logger.warning(f"Webhook removal failed: {e}")

SESSION = requests.Session()
retry_strategy = Retry(
    total=5,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"]
)
adapter = HTTPAdapter(
    max_retries=retry_strategy,
    pool_connections=20,
    pool_maxsize=20,
    pool_block=False
)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)

SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Connection": "close"
})

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

user_state: Dict[int, Dict] = {}
user_album_cache: Dict[str, Dict] = {}


# =========================
# UI BUTTONS
# =========================
BTN_POST = "📝 Оформить пост"
BTN_ENHANCE = "✨ Улучшить качество"
BTN_WATERMARK = "💧 Водяные знаки"
BTN_PRICES = "💰 Цены"
BTN_AI_TEXT = "🤖 Текст в ИИ"

def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(BTN_POST), KeyboardButton(BTN_AI_TEXT))
    kb.row(KeyboardButton(BTN_ENHANCE), KeyboardButton(BTN_WATERMARK))
    kb.row(KeyboardButton(BTN_PRICES))
    return kb

def repost_action_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Оформить пост", callback_data="repost:design"),
        InlineKeyboardButton("🤖 Обработать через ИИ", callback_data="repost:ai"),
        InlineKeyboardButton("📱 Пост для ТГ (500 симв.)", callback_data="repost:tg"),
        InlineKeyboardButton("📱 Пост для Тредс (400 симв.)", callback_data="repost:threads")
    )
    kb.add(InlineKeyboardButton("💧 Нанести водяной знак", callback_data="repost:watermark"))
    return kb

def after_ai_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📝 Оформить пост", callback_data="ai:design"),
        InlineKeyboardButton("💧 Водяной знак", callback_data="ai:watermark"),
        InlineKeyboardButton("📢 Выбрать канал", callback_data="ai:select_channel"),
        InlineKeyboardButton("🔄 Переделать через ИИ", callback_data="ai:redo"),
        InlineKeyboardButton("◀️ Вернуться назад", callback_data="ai:back")
    )
    return kb

def post_action_kb(post_type: str = "tg"):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🔄 Переделать еще раз", callback_data=f"{post_type}:redo"),
        InlineKeyboardButton("📢 Выбрать канал", callback_data=f"{post_type}:select_channel")
    )
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data=f"{post_type}:back"))
    return kb

def prices_menu_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💰 Наши цены", callback_data="prices:list"),
        InlineKeyboardButton("📋 Условия размещения", callback_data="prices:terms"),
        InlineKeyboardButton("📊 График аккаунтов", callback_data="prices:schedule")
    )
    kb.add(InlineKeyboardButton("❌ Закрыть", callback_data="prices:close"))
    return kb

def watermark_type_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📰 МН (MINSK NEWS)", callback_data="watermark:mn"),
        InlineKeyboardButton("🚨 ЧП (Минск ЧП)", callback_data="watermark:chp"),
        InlineKeyboardButton("◀️ Назад", callback_data="watermark:back")
    )
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="watermark:cancel"))
    return kb

def preview_kb(source_url: str = ""):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("📢 Опубликовать в канале", callback_data="publish_to_channel"),
        InlineKeyboardButton("💧 Водяной знак", callback_data="add_watermark"),
        InlineKeyboardButton("✏️ Редактировать текст", callback_data="edit_text"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel")
    )
    if source_url:
        kb.add(InlineKeyboardButton("🔗 Источник", url=source_url))
    return kb

def channel_selection_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    if CHANNEL_MN:
        kb.add(InlineKeyboardButton("📰 MINSK NEWS", callback_data="select_channel:mn"))
    if CHANNEL_CHP:
        kb.add(InlineKeyboardButton("🚨 МИНСК ЧП", callback_data="select_channel:chp"))
    if CHANNEL_AFISHA:
        kb.add(InlineKeyboardButton("🎫 Афиша Минска", callback_data="select_channel:afisha"))
    if CHANNEL_TEST:
        kb.add(InlineKeyboardButton("🧪 ТЕСТОВЫЙ КАНАЛ", callback_data="select_channel:test"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="select_channel:cancel"))
    return kb

def post_channel_selection_kb(post_type: str):
    kb = InlineKeyboardMarkup(row_width=1)
    if CHANNEL_MN:
        kb.add(InlineKeyboardButton("📰 MINSK NEWS", callback_data=f"post_channel:{post_type}:mn"))
    if CHANNEL_CHP:
        kb.add(InlineKeyboardButton("🚨 МИНСК ЧП", callback_data=f"post_channel:{post_type}:chp"))
    if CHANNEL_AFISHA:
        kb.add(InlineKeyboardButton("🎫 Афиша Минска", callback_data=f"post_channel:{post_type}:afisha"))
    if CHANNEL_TEST:
        kb.add(InlineKeyboardButton("🧪 ТЕСТОВЫЙ КАНАЛ", callback_data=f"post_channel:{post_type}:test"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data=f"post_channel:{post_type}:cancel"))
    return kb

def channel_kb():
    kb = InlineKeyboardMarkup()
    if SUGGEST_URL:
        kb.add(InlineKeyboardButton("📝 Предложить новость", url=SUGGEST_URL))
    return kb

def text_position_kb_am2():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⬆️ Текст сверху", callback_data="am2_pos:top"),
        InlineKeyboardButton("⬇️ Текст снизу", callback_data="am2_pos:bottom")
    )
    return kb

def add_date_place_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Да, добавить", callback_data="am2_date_place:yes"),
        InlineKeyboardButton("➖ Нет, пропустить", callback_data="am2_date_place:no")
    )
    return kb

def color_kb_am2():
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("🔴 Красный", callback_data="am2_color:red"),
        InlineKeyboardButton("🟡 Желтый", callback_data="am2_color:yellow"),
        InlineKeyboardButton("🔵 Голубой", callback_data="am2_color:blue")
    )
    kb.add(InlineKeyboardButton("➖ Без выделения", callback_data="am2_color:none"))
    return kb


# =========================
# Keyboard layouts для шаблонов
# =========================
def template_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📰 МН", callback_data="tpl:MN"),
        InlineKeyboardButton("🚨 ЧП ВМ", callback_data="tpl:CHP"),
        InlineKeyboardButton("✨ АМ", callback_data="tpl:AM"),
        InlineKeyboardButton("🆕 АМ 2", callback_data="tpl:AM2"),
        InlineKeyboardButton("📱 Сторис ФДР", callback_data="tpl:FDR_STORY"),
        InlineKeyboardButton("💜 Пост ФДР", callback_data="tpl:FDR_POST"),
        InlineKeyboardButton("📱 МН ТГ", callback_data="tpl:MN_TG"),
        InlineKeyboardButton("🆕 МН 2", callback_data="tpl:MN2"),
        InlineKeyboardButton("💧 Водяной знак", callback_data="tpl:watermark")
    )
    return kb

def text_position_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⬆️ Сверху", callback_data="text_pos:top"),
        InlineKeyboardButton("⬇️ Снизу", callback_data="text_pos:bottom")
    )
    return kb


# =========================
# Helper functions
# =========================
def send_message_with_retry(chat_id, text, parse_mode=None, reply_markup=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            return bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(1 + attempt)
            else:
                try:
                    clean_text = re.sub(r'<[^>]+>', '', text)
                    return bot.send_message(
                        chat_id=chat_id,
                        text=clean_text,
                        reply_markup=reply_markup
                    )
                except:
                    raise
    return None

def send_photo_with_retry(chat_id, photo, caption=None, parse_mode=None, reply_markup=None, max_retries=3):
    if caption and len(caption) > 950:
        caption = caption[:947] + "..."
    
    for attempt in range(max_retries):
        try:
            return bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Send photo attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 + attempt * 2)
            else:
                try:
                    return bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        reply_markup=reply_markup
                    )
                except:
                    return None
    return None

def send_media_group_with_retry(chat_id, media_list, max_retries=3):
    for attempt in range(max_retries):
        try:
            return bot.send_media_group(chat_id, media_list)
        except Exception as e:
            logger.error(f"Media group attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 + attempt * 2)
            else:
                for media in media_list:
                    try:
                        if isinstance(media, InputMediaPhoto):
                            bot.send_photo(chat_id, media.media, caption=media.caption, parse_mode="HTML")
                        elif isinstance(media, InputMediaVideo):
                            bot.send_video(chat_id, media.media, caption=media.caption, parse_mode="HTML")
                    except:
                        pass
                return None
    return None

def check_file_size(file_bytes: bytes) -> bool:
    return len(file_bytes) <= MAX_FILE_SIZE

def tg_file_bytes(file_id: str) -> bytes:
    try:
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        r = SESSION.get(file_url, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        raise

def tg_file_bytes_with_info(file_id: str) -> Tuple[bytes, Dict]:
    try:
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        r = SESSION.get(file_url, timeout=60)
        r.raise_for_status()
        
        file_path = file_info.file_path
        if file_path.startswith('video/'):
            media_type = 'video'
        elif file_path.startswith('photo/'):
            media_type = 'photo'
        else:
            media_type = 'document'
        
        info = {
            'file_id': file_id,
            'file_path': file_path,
            'file_size': file_info.file_size,
            'media_type': media_type
        }
        return r.content, info
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        raise

def get_video_info(file_id: str, video_obj) -> Dict:
    try:
        info = {
            'file_id': file_id,
            'file_size': getattr(video_obj, 'file_size', 0),
            'media_type': 'video',
            'duration': getattr(video_obj, 'duration', 0),
            'width': getattr(video_obj, 'width', 0),
            'height': getattr(video_obj, 'height', 0),
            'mime_type': getattr(video_obj, 'mime_type', 'video/mp4'),
            'thumb': getattr(video_obj, 'thumb', None),
        }
        return info
    except Exception as e:
        logger.error(f"Failed to get video info: {e}")
        raise

def download_video(file_id: str) -> Tuple[bytes, Dict]:
    return tg_file_bytes_with_info(file_id)

def clear_state(user_id: int):
    if user_id in user_state:
        template = user_state[user_id].get("template", "MN")
        user_state[user_id] = {"template": template, "step": "idle"}

def ensure_fonts():
    fonts = [FONT_MN, FONT_MN_BOLD, FONT_CHP, FONT_AM, FONT_MONTSERRAT_BLACK, FONT_PATH, FONT_REGULAR]
    for font in fonts:
        if not os.path.exists(font):
            logger.warning(f"Font not found: {font}")

def download_fonts():
    fonts_urls = {
        "CaviarDreams.ttf": "https://github.com/paullang/evil-icons/raw/master/assets/fonts/CaviarDreams.ttf",
        "CaviarDreams_Bold.ttf": "https://github.com/paullang/evil-icons/raw/master/assets/fonts/CaviarDreams_Bold.ttf",
        "Montserrat-Black.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Black.ttf",
        "IntroInline.ttf": "https://github.com/paullang/evil-icons/raw/master/assets/fonts/IntroInline.ttf",
        "Inter-ExtraBold.ttf": "https://github.com/rsms/inter/raw/master/docs/fonts/Inter-ExtraBold.otf",
        "Inter-Regular.ttf": "https://github.com/rsms/inter/raw/master/docs/fonts/Inter-Regular.otf",
    }
    for font_name, url in fonts_urls.items():
        if not os.path.exists(font_name):
            try:
                logger.info(f"Downloading {font_name}...")
                response = requests.get(url, timeout=30)
                with open(font_name, "wb") as f:
                    f.write(response.content)
                logger.info(f"Downloaded {font_name}")
            except Exception as e:
                logger.error(f"Failed to download {font_name}: {e}")

def extract_source_url(text: str) -> str:
    m = URL_RE.search(text or "")
    return m.group(1) if m else ""

def extract_title_from_text(text: str) -> str:
    if not text:
        return ""
    
    lines = text.strip().split('\n')
    if lines and lines[0].strip():
        first_line = lines[0].strip()
        if len(first_line) <= 100:
            return first_line
    
    sentences = re.split(r'[.!?]', text)
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) > 10:
            return sentence[:100]
    
    return text[:80]

def clean_markdown(text: str) -> str:
    if not text:
        return text
    
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    
    return text.strip()

def split_title_and_body(text: str) -> Tuple[str, str]:
    if not text:
        return "", ""
    
    text = text.strip()
    
    if '\n' in text:
        lines = text.split('\n')
        title = lines[0].strip()
        body = '\n'.join(lines[1:]).strip()
        return title, body
    
    if len(text) > 100 and '. ' in text:
        parts = text.split('. ', 1)
        title = (parts[0] + '.').strip()
        body = parts[1].strip() if len(parts) > 1 else ""
        return title, body
    
    return text, ""

def format_ai_response(text: str) -> Tuple[str, str, str]:
    text = re.sub(r'^#+\s*', '', text)
    text = clean_markdown(text)
    
    title, body = split_title_and_body(text)
    
    formatted_title = f"<b>{html.escape(title)}</b>" if title else ""
    formatted_body = html.escape(body) if body else ""
    
    if formatted_title and formatted_body:
        formatted_text = f"{formatted_title}\n\n{formatted_body}"
    elif formatted_title:
        formatted_text = formatted_title
    else:
        formatted_text = formatted_body
    
    return title, body, formatted_text

def load_font(font_name: str, size: int):
    try:
        return ImageFont.truetype(font_name, size=size)
    except Exception:
        try:
            return ImageFont.truetype(FONT_FALLBACK, size=size)
        except:
            return ImageFont.load_default()

def text_width(draw, s: str, font) -> int:
    bbox = draw.textbbox((0, 0), s, font=font)
    return bbox[2] - bbox[0]

def wrap_text_center(draw, text: str, font, max_width: int, max_lines: int = 6) -> Tuple[List[str], bool]:
    words = text.split()
    if not words:
        return [""], True
    lines = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        if text_width(draw, test, font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines, True

def fit_text_block_center(draw, text: str, font_path: str, safe_w: int, max_block_h: int,
                          max_lines: int = 6, start_size: int = 90, min_size: int = 16,
                          line_spacing_ratio: float = 0.22):
    text = (text or "").strip()
    if not text:
        text = " "
    size = start_size
    while size >= min_size:
        font = load_font(font_path, size)
        lines, ok = wrap_text_center(draw, text, font, safe_w, max_lines=max_lines)
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
    font = load_font(font_path, min_size)
    lines, _ = wrap_text_center(draw, text, font, safe_w, max_lines=max_lines)
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
# Gradient functions (сокращенно)
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

def apply_gradient_direction(img: Image.Image, direction: str, height_pct: float, max_alpha: int = 220) -> Image.Image:
    w, h = img.size
    gh = int(h * height_pct)
    if gh <= 0:
        return img
    overlay_alpha = Image.new("L", (w, h), 0)
    grad = Image.new("L", (1, gh), 0)
    for y in range(gh):
        if direction == "top":
            a = int(max_alpha * (1 - y / max(1, gh - 1)))
        else:
            a = int(max_alpha * (y / max(1, gh - 1)))
        grad.putpixel((0, y), a)
    grad = grad.resize((w, gh))
    if direction == "top":
        overlay_alpha.paste(grad, (0, 0))
    else:
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
    w, h = img.size
    size = min(w, h)
    left = (w - size) // 2
    top = (h - size) // 2
    return img.crop((left, top, left + size, top + size))


# =========================
# Text wrapping functions (сокращенно)
# =========================
def wrap_no_truncate(draw, text: str, font, max_width: int, max_lines: int = 6):
    words = [w for w in (text or "").split() if w.strip()]
    if not words:
        return [""], True
    lines = []
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

def fit_text_block(draw, text: str, font_path: str, safe_w: int, max_block_h: int,
                   max_lines: int = 6, start_size: int = 90, min_size: int = 16,
                   line_spacing_ratio: float = 0.22):
    text = (text or "").strip()
    if not text:
        text = " "
    size = start_size
    while size >= min_size:
        font = load_font(font_path, size)
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
    font = load_font(font_path, min_size)
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
    selected_font = load_font(FONT_MONTSERRAT_BLACK, min_size)
    selected_gap = 8
    selected_paragraph_gap = 12
    for size in range(max_size, min_size - 1, -1):
        font = load_font(FONT_MONTSERRAT_BLACK, size)
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
# Функции для шаблона АМ 2 (сокращенно)
# =========================
def draw_highlighted_text_am2(draw, text: str, highlight_word: str, color, font, x, y):
    if not highlight_word:
        draw.text((x, y), text, font=font, fill=TEXT_COLOR)
        return
    text_lower = text.lower()
    word_lower = highlight_word.lower()
    if word_lower not in text_lower:
        draw.text((x, y), text, font=font, fill=TEXT_COLOR)
        return
    pos = text_lower.find(word_lower)
    before = text[:pos]
    word_part = text[pos:pos + len(highlight_word)]
    after = text[pos + len(highlight_word):]
    current_x = x
    if before:
        draw.text((current_x, y), before, font=font, fill=TEXT_COLOR)
        current_x += text_width(draw, before, font)
    if word_part:
        draw.text((current_x, y), word_part, font=font, fill=color)
        current_x += text_width(draw, word_part, font)
    if after:
        draw.text((current_x, y), after, font=font, fill=TEXT_COLOR)

def draw_rounded_rect_with_text_am2(draw, text: str, bg_color, text_color, x: int, y: int, padding: int, radius: int):
    if not text:
        return y
    font = load_font(FONT_REGULAR, 24)
    text_upper = text.upper()
    text_w = draw.textlength(text_upper, font=font)
    bbox = draw.textbbox((0, 0), text_upper, font=font)
    text_h = bbox[3] - bbox[1]
    rect_w = int(text_w + padding * 2)
    rect_h = int(text_h + padding * 2)
    draw.rounded_rectangle([x, y, x + rect_w, y + rect_h], radius=radius, fill=bg_color)
    text_x = x + (rect_w - text_w) / 2
    text_y = y + (rect_h - text_h) / 2 - bbox[1]
    draw.text((text_x, text_y), text_upper, font=font, fill=text_color)
    return y + rect_h + 15

def draw_rubric_top_center_am2(draw, rubric: str, highlight_color, is_yellow: bool):
    if not rubric:
        return 0
    font_rubric = load_font(FONT_PATH, 30)
    rubric_text = rubric.upper()
    text_w = draw.textlength(rubric_text, font=font_rubric)
    bbox = draw.textbbox((0, 0), rubric_text, font=font_rubric)
    text_h = bbox[3] - bbox[1]
    rect_w = int(text_w + RUBRIC_PADDING * 2)
    rect_h = int(text_h + RUBRIC_PADDING * 2)
    rect_x = (TARGET_W - rect_w) // 2
    rect_y = RUBRIC_TOP_MARGIN
    if is_yellow:
        bg_color = highlight_color
        text_color = BLACK
    else:
        bg_color = WHITE
        text_color = highlight_color
    draw.rounded_rectangle([rect_x, rect_y, rect_x + rect_w, rect_y + rect_h], radius=RUBRIC_RADIUS, fill=bg_color)
    text_x = rect_x + (rect_w - text_w) / 2
    text_y = rect_y + (rect_h - text_h) / 2 - bbox[1]
    draw.text((text_x, text_y), rubric_text, font=font_rubric, fill=text_color)
    return rect_y + rect_h

def create_poster_am2(image_bytes: bytes, title_text: str, text_position: str,
                      date: str = "", place: str = "", rubric: str = "",
                      highlight_word: str = "", highlight_color: tuple = None, is_yellow: bool = False) -> BytesIO:
    if highlight_color is None:
        highlight_color = HIGHLIGHT_COLORS["yellow"]
        is_yellow = True
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS_FACTOR)
    if text_position == "top":
        img = apply_gradient_direction(img, "top", GRADIENT_HEIGHT_PCT, GRADIENT_MAX_ALPHA)
    else:
        img = apply_gradient_direction(img, "bottom", GRADIENT_HEIGHT_PCT, GRADIENT_MAX_ALPHA)
    draw = ImageDraw.Draw(img)
    rubric_bottom = 0
    if rubric:
        rubric_bottom = draw_rubric_top_center_am2(draw, rubric, highlight_color, is_yellow)
    margin_top = int(TARGET_H * MARGIN_TOP_PCT)
    if rubric_bottom > 0:
        margin_top = rubric_bottom + 40
    else:
        margin_top = 130
    max_text_width = int(TARGET_W * TEXT_MAX_WIDTH_PCT)
    
    clean_title = clean_markdown(title_text)
    text = (clean_title or "").strip().upper()
    
    title_max_h = int(TARGET_H * 0.23)
    font, lines, heights, spacing, total_h = fit_text_block_center(
        draw=draw, text=text, font_path=FONT_PATH, safe_w=max_text_width,
        max_block_h=title_max_h, max_lines=6, start_size=int(TARGET_H * 0.11),
        min_size=24, line_spacing_ratio=LINE_SPACING_RATIO
    )
    if is_yellow:
        date_place_text_color = BLACK
    else:
        date_place_text_color = WHITE
    if text_position == "top":
        y = margin_top
        for i, ln in enumerate(lines):
            line_w = text_width(draw, ln, font)
            x = (TARGET_W - line_w) // 2
            draw_highlighted_text_am2(draw, ln, highlight_word, highlight_color, font, x, y)
            y += heights[i] + spacing
        if date or place:
            date_place_y = TARGET_H - DATE_PLACE_BOTTOM_MARGIN
            if date:
                date_place_y = draw_rounded_rect_with_text_am2(
                    draw, f"ДАТА: {date}", highlight_color, date_place_text_color,
                    DATE_PLACE_LEFT_MARGIN, date_place_y, DATE_PLACE_PADDING, DATE_PLACE_RADIUS
                )
            if place:
                draw_rounded_rect_with_text_am2(
                    draw, f"МЕСТО: {place}", highlight_color, date_place_text_color,
                    DATE_PLACE_LEFT_MARGIN, date_place_y, DATE_PLACE_PADDING, DATE_PLACE_RADIUS
                )
    else:
        date_place_y = DATE_PLACE_TOP_MARGIN
        if date or place:
            if date:
                date_place_y = draw_rounded_rect_with_text_am2(
                    draw, f"ДАТА: {date}", highlight_color, date_place_text_color,
                    DATE_PLACE_LEFT_MARGIN, date_place_y, DATE_PLACE_PADDING, DATE_PLACE_RADIUS
                )
            if place:
                draw_rounded_rect_with_text_am2(
                    draw, f"МЕСТО: {place}", highlight_color, date_place_text_color,
                    DATE_PLACE_LEFT_MARGIN, date_place_y, DATE_PLACE_PADDING, DATE_PLACE_RADIUS
                )
            y = date_place_y + 65
        else:
            y = margin_top
        for i, ln in enumerate(lines):
            line_w = text_width(draw, ln, font)
            x = (TARGET_W - line_w) // 2
            draw_highlighted_text_am2(draw, ln, highlight_word, highlight_color, font, x, y)
            y += heights[i] + spacing
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0)
    out.seek(0)
    return out


# =========================
# Card making functions - ВСЕ ШАБЛОНЫ
# =========================
def make_card_mn(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
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
    footer_font = load_font(FONT_MN, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    clean_title = clean_markdown(title_text)
    text = (clean_title or "").strip().upper()
    
    font, lines, heights, spacing, total_text_height = fit_text_block(
        draw=draw, text=text, font_path=FONT_MN, safe_w=safe_w,
        max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
        min_size=16, line_spacing_ratio=0.22
    )
    
    line_height = font.size
    total_text_height = len(lines) * line_height + (len(lines) - 1) * 2
    
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
    for ln in lines:
        draw.text((block_x, y), ln, font=font, fill="white")
        y += line_height + 2
    
    footer_x = (img.width - footer_w) // 2
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out

def make_card_mn2(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP, bold_phrase: str = "") -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
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
    footer_font = load_font(FONT_MN, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    clean_title = clean_markdown(title_text)
    text = (clean_title or "").strip().upper()
    
    clean_bold_phrase = clean_markdown(bold_phrase)
    bold_phrase_upper = clean_bold_phrase.strip().upper() if clean_bold_phrase else ""
    bold_words = set(bold_phrase_upper.split())
    
    font, lines, heights, spacing, total_text_height = fit_text_block(
        draw=draw, text=text, font_path=FONT_MN, safe_w=safe_w,
        max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
        min_size=16, line_spacing_ratio=0.25
    )
    
    line_height = font.size
    total_text_height = len(lines) * line_height + (len(lines) - 1) * 2
    
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
    for ln in lines:
        current_x = block_x
        words = ln.split()
        for word in words:
            if word in bold_words:
                bold_font = load_font(FONT_MN_BOLD, font.size)
                draw.text((current_x, y), word, font=bold_font, fill="white")
            else:
                draw.text((current_x, y), word, font=font, fill="white")
            if word != words[-1]:
                space_width = text_width(draw, " ", font)
                current_x += text_width(draw, word, font) + space_width
            else:
                current_x += text_width(draw, word, font)
        y += line_height + 2
    
    footer_x = (img.width - footer_w) // 2
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out

def make_card_mn_tg(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font_size = int(img.width * 0.08)
    font = load_font(FONT_MN, font_size)
    text_bbox = draw.textbbox((0, 0), FOOTER_TEXT, font=font)
    text_width_val = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (img.width - text_width_val) // 2
    if text_position == TEXT_POSITION_TOP:
        y = int(img.height * 0.2) - (text_height // 2)
    else:
        y = int(img.height * 0.8) - (text_height // 2)
    draw.text((x, y), FOOTER_TEXT, font=font, fill=(255, 255, 255, 38))
    result = Image.alpha_composite(img.convert("RGBA"), overlay)
    result = result.convert("RGB")
    out = BytesIO()
    result.save(out, format="JPEG", quality=95, optimize=True)
    out.seek(0)
    return out

def make_card_chp(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    if text_position == TEXT_POSITION_TOP:
        img = apply_top_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    else:
        img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    draw = ImageDraw.Draw(img)
    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    margin_top = int(img.height * 0.08)
    safe_w = img.width - 2 * margin_x
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    clean_title = clean_markdown(title_text)
    text = (clean_title or "").strip().upper()
    
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw, text=text, font_path=FONT_CHP, safe_w=safe_w,
        max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
        min_size=16, line_spacing_ratio=0.22
    )
    
    line_height = font.size
    total_text_height = len(lines) * line_height + (len(lines) - 1) * 2
    
    if text_position == TEXT_POSITION_TOP:
        y = margin_top
    else:
        y = img.height - margin_bottom - total_text_height
    
    for ln in lines:
        draw.text((margin_x, y), ln, font=font, fill="white")
        y += line_height + 2
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out

def make_card_am(photo_bytes: bytes, title_text: str) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    img = apply_top_blur_band(img)
    draw = ImageDraw.Draw(img)
    margin_x = int(img.width * 0.055)
    band_h = int(img.height * AM_TOP_BLUR_PCT)
    safe_w = img.width - 2 * margin_x
    
    clean_title = clean_markdown(title_text)
    text = (clean_title or "").strip().upper()
    
    text_zone_top = int(band_h * 0.12)
    text_zone_bottom = int(band_h * 0.12)
    text_zone_h = max(1, band_h - text_zone_top - text_zone_bottom)
    
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw, text=text, font_path=FONT_AM, safe_w=safe_w,
        max_block_h=text_zone_h, max_lines=3, start_size=int(img.height * 0.060),
        min_size=20, line_spacing_ratio=0.16
    )
    
    line_height = font.size
    total_text_height = len(lines) * line_height + (len(lines) - 1) * 2
    
    y = text_zone_top + max(0, (text_zone_h - total_text_height) // 2)
    for ln in lines:
        lw = text_width(draw, ln, font)
        x = (img.width - lw) // 2
        draw.text((x, y), ln, font=font, fill="white")
        y += line_height + 2
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out

def make_card_am2(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP,
                  date: str = "", place: str = "", rubric: str = "",
                  highlight_word: str = "", highlight_color: tuple = None, is_yellow: bool = False) -> BytesIO:
    return create_poster_am2(photo_bytes, title_text, text_position, date, place, rubric,
                             highlight_word, highlight_color, is_yellow)

def make_card_fdr_story(photo_bytes: bytes, title: str, body_text: str) -> BytesIO:
    ensure_fonts()
    clean_title = clean_markdown(title)
    clean_body = clean_markdown(body_text)
    
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
        draw, clean_title, header_box, min_size=28, max_size=54,
        line_gap_ratio=0.08, paragraph_gap_ratio=0.18
    )
    _draw_story_text(draw, clean_title, header_box, title_font, fill=(255, 255, 255),
                     align="center", valign="center", line_gap=title_gap,
                     paragraph_gap_extra=title_paragraph_gap)
    body_font, body_gap, body_paragraph_gap = _fit_story_text(
        draw, clean_body, body_box, min_size=14, max_size=30,
        line_gap_ratio=0.10, paragraph_gap_ratio=0.32
    )
    _draw_story_text(draw, clean_body, body_box, body_font, fill=(255, 255, 255),
                     align="left", valign="top", line_gap=body_gap,
                     paragraph_gap_extra=body_paragraph_gap)
    out = BytesIO()
    canvas.save(out, format="JPEG", quality=92, optimize=True)
    out.seek(0)
    return out

def make_card_fdr_post(photo_bytes: bytes, title_text: str, highlight_phrase: str) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    draw = ImageDraw.Draw(img)
    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    safe_w = img.width - 2 * margin_x
    
    clean_title = clean_markdown(title_text)
    title_text_upper = clean_title.strip().upper()
    
    clean_highlight = clean_markdown(highlight_phrase)
    highlight_phrase_upper = clean_highlight.strip().upper()
    highlight_words = set(highlight_phrase_upper.split())
    
    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw, text=title_text_upper, font_path=FONT_CHP, safe_w=safe_w,
        max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
        min_size=16, line_spacing_ratio=0.22
    )
    
    line_height = font.size
    total_text_height = len(lines) * line_height + (len(lines) - 1) * 2
    
    base_y = img.height - margin_bottom - total_text_height
    y = base_y
    
    for line_idx, line in enumerate(lines):
        line_words = line.split()
        current_x = margin_x
        for word in line_words:
            word_bbox = draw.textbbox((current_x, y), word, font=font)
            word_x1, word_y1, word_x2, word_y2 = word_bbox
            if word in highlight_words:
                padding = 10
                draw.rectangle([word_x1 - padding, word_y1 - padding, word_x2 + padding, word_y2 + padding], fill=FDR_POST_PURPLE_COLOR)
            if word != line_words[-1]:
                space_width = text_width(draw, " ", font)
                current_x += text_width(draw, word, font) + space_width
            else:
                current_x += text_width(draw, word, font)
        y += line_height + 2
    
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
        y += line_height + 2
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out

def make_card(photo_bytes: bytes, title_text: str, template: str, body_text: str = "", highlight_phrase: str = "", 
              text_position: str = TEXT_POSITION_TOP, 
              bold_phrase: str = "", date: str = "", place: str = "", rubric: str = "",
              highlight_word: str = "", highlight_color: tuple = None, is_yellow: bool = False) -> BytesIO:
    if template == "CHP":
        return make_card_chp(photo_bytes, title_text, text_position)
    if template == "AM":
        return make_card_am(photo_bytes, title_text)
    if template == "AM2":
        return make_card_am2(photo_bytes, title_text, text_position, date, place, rubric,
                            highlight_word, highlight_color, is_yellow)
    if template == "FDR_STORY":
        return make_card_fdr_story(photo_bytes, title_text, body_text)
    if template == "FDR_POST":
        return make_card_fdr_post(photo_bytes, title_text, highlight_phrase)
    if template == "MN_TG":
        return make_card_mn_tg(photo_bytes, title_text, text_position)
    if template == "MN2":
        return make_card_mn2(photo_bytes, title_text, text_position, bold_phrase)
    return make_card_mn(photo_bytes, title_text, text_position)


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
def ensure_4x5_ratio(img: Image.Image) -> Image.Image:
    w, h = img.size
    target_ratio = 4 / 5
    current_ratio = w / h
    
    if abs(current_ratio - target_ratio) > 0.01:
        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            return img.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            return img.crop((0, top, w, top + new_h))
    return img

def apply_watermark_mn(photo_bytes: bytes) -> BytesIO:
    try:
        img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
        
        img_width, img_height = img.size
        
        watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        
        font_size = int(img_width * 0.10)
        font_size = max(30, min(120, font_size))
        
        try:
            font = load_font(FONT_MN, font_size)
        except:
            font = ImageFont.load_default()
        
        watermark_text = "MINSK NEWS"
        
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width_val = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        max_attempts = 10
        attempt = 0
        while text_width_val > img_width * 0.9 and attempt < max_attempts:
            font_size = int(font_size * 0.9)
            if font_size < 20:
                break
            try:
                font = load_font(FONT_MN, font_size)
            except:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width_val = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            attempt += 1
        
        x = (img_width - text_width_val) // 2
        y = (img_height - text_height) // 2
        
        draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 64))
        
        result = Image.alpha_composite(img, watermark)
        result = result.convert("RGB")
        
        output = BytesIO()
        result.save(output, format="JPEG", quality=95, optimize=True)
        output.seek(0)
        return output
        
    except Exception as e:
        logger.error(f"Error applying MN watermark: {e}")
        raise

def apply_watermark_chp(photo_bytes: bytes) -> BytesIO:
    try:
        img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
        
        img_width, img_height = img.size
        
        watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        
        font_size = int(img_width * 0.10)
        font_size = max(30, min(120, font_size))
        
        try:
            font = load_font(FONT_CHP, font_size)
        except:
            font = ImageFont.load_default()
        
        watermark_text = "ЧП Минск"
        
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width_val = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        max_attempts = 10
        attempt = 0
        while text_width_val > img_width * 0.9 and attempt < max_attempts:
            font_size = int(font_size * 0.9)
            if font_size < 20:
                break
            try:
                font = load_font(FONT_CHP, font_size)
            except:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            text_width_val = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            attempt += 1
        
        x = (img_width - text_width_val) // 2
        y = (img_height - text_height) // 2
        
        draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 64))
        
        result = Image.alpha_composite(img, watermark)
        result = result.convert("RGB")
        
        output = BytesIO()
        result.save(output, format="JPEG", quality=95, optimize=True)
        output.seek(0)
        return output
        
    except Exception as e:
        logger.error(f"Error applying CHP watermark: {e}")
        raise


# =========================
# Определение тематики для эмодзи
# =========================
def detect_topic_emoji(text: str) -> str:
    text_lower = text.lower()
    
    topics = {
        "🚨": ["дтп", "авар", "пожар", "взрыв", "происшеств", "чп", "полици", "милици", "скорая", "мчс", "катастроф"],
        "✈️": ["белавиа", "рейс", "аэропорт", "самолет", "полет", "авиа", "борт"],
        "🚇": ["метро", "станци", "маршрут", "автобус", "троллейбус", "трамвай", "транспорт", "общественный"],
        "💳": ["банк", "технобанк", "карта", "налог", "выплат", "деньги", "финанс", "кредит", "валюта"],
        "🏷️": ["скидк", "распрод", "акци", "дешев", "бесплат", "цена", "стоимость", "рубль"],
        "🎫": ["концерт", "афиша", "выставк", "фестиваль", "мероприят", "кино", "театр"],
        "🌦️": ["погод", "шторм", "ветер", "снег", "дожд", "гроз", "температур", "мороз", "жара"],
        "🏥": ["больниц", "врач", "здоров", "вакцин", "лекарств", "медицин", "здравоохран"],
        "📱": ["смартфон", "айфон", "телефон", "гаджет", "технологи"],
        "🚀": ["космос", "спутник", "наук", "исследован", "открыт"],
        "🎓": ["образован", "школ", "университет", "студент", "учител", "экзамен"],
        "⚽": ["футбол", "спорт", "хоккей", "чемпионат", "матч", "команд"],
        "🎮": ["игр", "кибер", "компьютер", "консоль"],
        "🍔": ["еда", "ресторан", "кафе", "блюд", "кулинар", "продукт"],
        "🏠": ["строительств", "ремонт", "квартир", "жкх", "коммунал", "дом"],
        "🌿": ["эколог", "природ", "зелен", "парк", "дерев"],
        "💼": ["бизнес", "компани", "предприят", "рынок", "торговл", "экономик"],
    }
    
    for emoji, keywords in topics.items():
        for keyword in keywords:
            if keyword in text_lower:
                return emoji
    
    return "📰"


# =========================
# Функция для удаления эмодзи из текста
# =========================
def remove_emojis(text: str) -> str:
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\u2600-\u27BF"
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)


# =========================
# Функция для обработки текста через DeepSeek (основная)
# =========================
async def process_text_with_deepseek(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = """Ты редактор новостного сайта. Перепиши новость в строгом городском формате, объемом около 650 символов. Убери лишнюю воду, сделай интересный заголовок. Не используй символы # и ** в ответе. Сохрани главные факты. Расставь абзацы.

Вот текст:"""
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты редактор новостного сайта. Отвечай только готовым новостным текстом, без пояснений и вступлений. Не используй символы # и ** в ответе."},
                        {"role": "user", "content": f"{prompt}\n\n{text}"}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000
                }
            )
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"]
                result = re.sub(r'^Вот обработанный новостной текст.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Вот.*?текст.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Вот.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^#+\s+', '', result, flags=re.MULTILINE)
                result = result.strip()
                return result
            return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка при обращении к API: {str(e)}"


# =========================
# Функция для создания поста в Telegram
# =========================
async def process_text_with_deepseek_tg(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор новостного канала. Сократи текст новости до 500 символов.

Правила:
1. Текст должен быть не более 500 символов (включая пробелы и знаки препинания)
2. Сохрани ВСЮ ключевую информацию: цифры, даты, имена, названия, события
3. НЕ изменяй суть новости
4. Заголовок: короткий, четкий, отражающий суть - сделай его отдельной строкой и жирным с помощью <b>
5. Текст: 2-3 абзаца с главными фактами
6. НЕ используй многоточие в конце
7. НЕ используй эмодзи в тексте (эмодзи добавится автоматически)

Формат ответа:
<b>Заголовок новости</b>

Первый абзац с самой важной информацией.

Второй абзац с дополнительными деталями.

Исходный текст:
{text}

Верни ТОЛЬКО готовый пост, без пояснений."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты редактор новостного канала. Сокращай новости, сохраняя всю важную информацию. НЕ используй эмодзи. Отвечай только готовым постом. Используй <b> для заголовка."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 800
                }
            )
            
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"]
                result = re.sub(r'^Вот.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^#+\s+', '', result, flags=re.MULTILINE)
                result = result.strip()
                
                result = remove_emojis(result)
                
                if not re.search(r'<b>.*?</b>', result):
                    lines = result.split('\n')
                    if lines:
                        first_line = lines[0].strip()
                        if first_line and len(first_line) < 100:
                            result = f"<b>{first_line}</b>\n\n" + '\n\n'.join([line for line in lines[1:] if line.strip()])
                
                if len(result) > 500:
                    cut_point = 500
                    while cut_point > 0 and result[cut_point] not in ['.', '!', '?', '\n']:
                        cut_point -= 1
                    if cut_point > 10:
                        result = result[:cut_point + 1]
                    else:
                        cut_point = 500
                        while cut_point > 0 and result[cut_point] != ' ':
                            cut_point -= 1
                        if cut_point > 10:
                            result = result[:cut_point]
                
                emoji = detect_topic_emoji(result)
                result = f"{emoji} {result}"
                
                if len(result) > 500:
                    result = result[:500]
                
                return result
                
            return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"


# =========================
# Функция для создания поста в Тредс
# =========================
async def process_text_with_deepseek_threads(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор для соцсети Threads. Сократи текст новости до 400 символов.

Правила:
1. Текст должен быть не более 400 символов (включая пробелы и знаки препинания)
2. Сохрани ВСЮ ключевую информацию: цифры, даты, имена, названия, события
3. НЕ изменяй суть новости
4. Заголовок: короткий, яркий, отражающий суть - сделай его отдельной строкой и жирным с помощью <b>
5. Текст: 2 абзаца с главными фактами
6. НЕ используй многоточие в конце
7. НЕ используй эмодзи в тексте (эмодзи добавится автоматически)

Формат ответа:
<b>Заголовок новости</b>

Первый абзац с самой важной информацией.

Второй абзац с дополнительными деталями.

Исходный текст:
{text}

Верни ТОЛЬКО готовый пост, без пояснений."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты редактор для Threads. Сокращай новости, сохраняя всю важную информацию. НЕ используй эмодзи. Отвечай только готовым постом. Используй <b> для заголовка."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 600
                }
            )
            
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"]
                result = re.sub(r'^Вот.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^#+\s+', '', result, flags=re.MULTILINE)
                result = result.strip()
                
                result = remove_emojis(result)
                
                if not re.search(r'<b>.*?</b>', result):
                    lines = result.split('\n')
                    if lines:
                        first_line = lines[0].strip()
                        if first_line and len(first_line) < 80:
                            result = f"<b>{first_line}</b>\n\n" + '\n\n'.join([line for line in lines[1:] if line.strip()])
                
                if len(result) > 400:
                    cut_point = 400
                    while cut_point > 0 and result[cut_point] not in ['.', '!', '?', '\n']:
                        cut_point -= 1
                    if cut_point > 10:
                        result = result[:cut_point + 1]
                    else:
                        cut_point = 400
                        while cut_point > 0 and result[cut_point] != ' ':
                            cut_point -= 1
                        if cut_point > 10:
                            result = result[:cut_point]
                
                emoji = detect_topic_emoji(result)
                result = f"{emoji} {result}"
                
                if len(result) > 400:
                    result = result[:400]
                
                return result
                
            return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"


# =========================
# Функция для ПЕРЕДЕЛКИ поста в Telegram
# =========================
async def process_text_with_deepseek_tg_redo(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор новостного канала. Переделай эту новость в НОВЫЙ пост для Telegram.

Правила:
1. Текст должен быть не более 500 символов
2. Сохрани ВСЮ ключевую информацию: цифры, даты, имена, названия, события
3. НЕ изменяй суть новости
4. Заголовок: новый, но такой же информативный - сделай его жирным с помощью <b>
5. НЕ используй многоточие в конце
6. НЕ используй эмодзи в тексте (эмодзи добавится автоматически)

Формат ответа:
<b>Новый заголовок</b>

Первый абзац с главной информацией.

Второй абзац с деталями.

Важно: Переделай текст в новый формат, но вся информация должна остаться

Исходный текст новости:
{text}

Верни ТОЛЬКО готовый пост, без пояснений."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты редактор новостного канала. Переделывай новости в новые посты, сохраняя всю информацию. НЕ используй эмодзи. Отвечай только готовым постом. Используй <b> для заголовка."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 800
                }
            )
            
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"]
                result = re.sub(r'^Вот.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^#+\s+', '', result, flags=re.MULTILINE)
                result = result.strip()
                
                result = remove_emojis(result)
                
                if not re.search(r'<b>.*?</b>', result):
                    lines = result.split('\n')
                    if lines:
                        first_line = lines[0].strip()
                        if first_line and len(first_line) < 100:
                            result = f"<b>{first_line}</b>\n\n" + '\n\n'.join([line for line in lines[1:] if line.strip()])
                
                if len(result) > 500:
                    cut_point = 500
                    while cut_point > 0 and result[cut_point] not in ['.', '!', '?', '\n']:
                        cut_point -= 1
                    if cut_point > 10:
                        result = result[:cut_point + 1]
                    else:
                        cut_point = 500
                        while cut_point > 0 and result[cut_point] != ' ':
                            cut_point -= 1
                        if cut_point > 10:
                            result = result[:cut_point]
                
                emoji = detect_topic_emoji(result)
                result = f"{emoji} {result}"
                
                if len(result) > 500:
                    result = result[:500]
                
                return result
                
            return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"


# =========================
# Функция для ПЕРЕДЕЛКИ поста в Тредс
# =========================
async def process_text_with_deepseek_threads_redo(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор для Threads. Переделай эту новость в НОВЫЙ пост для Threads.

Правила:
1. Текст должен быть не более 400 символов
2. Сохрани ВСЮ ключевую информацию: цифры, даты, имена, названия, события
3. НЕ изменяй суть новости
4. Заголовок: новый, интригующий - сделай его жирным с помощью <b>
5. НЕ используй многоточие в конце
6. НЕ используй эмодзи в тексте (эмодзи добавится автоматически)

Формат ответа:
<b>Новый заголовок</b>

Первый абзац с главной информацией.

Второй абзац с дополнительными деталями.

Важно: Переделай текст в новый формат, но вся информация должна остаться

Исходный текст новости:
{text}

Верни ТОЛЬКО готовый пост, без пояснений."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты редактор для Threads. Переделывай новости в новые посты, сохраняя всю информацию. НЕ используй эмодзи. Отвечай только готовым постом. Используй <b> для заголовка."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 600
                }
            )
            
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"]
                result = re.sub(r'^Вот.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^#+\s+', '', result, flags=re.MULTILINE)
                result = result.strip()
                
                result = remove_emojis(result)
                
                if not re.search(r'<b>.*?</b>', result):
                    lines = result.split('\n')
                    if lines:
                        first_line = lines[0].strip()
                        if first_line and len(first_line) < 80:
                            result = f"<b>{first_line}</b>\n\n" + '\n\n'.join([line for line in lines[1:] if line.strip()])
                
                if len(result) > 400:
                    cut_point = 400
                    while cut_point > 0 and result[cut_point] not in ['.', '!', '?', '\n']:
                        cut_point -= 1
                    if cut_point > 10:
                        result = result[:cut_point + 1]
                    else:
                        cut_point = 400
                        while cut_point > 0 and result[cut_point] != ' ':
                            cut_point -= 1
                        if cut_point > 10:
                            result = result[:cut_point]
                
                emoji = detect_topic_emoji(result)
                result = f"{emoji} {result}"
                
                if len(result) > 400:
                    result = result[:400]
                
                return result
                
            return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"


# =========================
# Функция для извлечения контента из статей через ИИ
# =========================
async def extract_article_content(url: str) -> Dict[str, any]:
    if not DEEPSEEK_API_KEY:
        return {
            "text": "❌ API ключ DeepSeek не настроен.",
            "images": [],
            "title": "",
            "url": url
        }
    
    try:
        prompt = f"""Прочитай статью по ссылке ниже и извлеки из неё текст.

URL статьи: {url}

Правила:
1. Прочитай страницу по ссылке
2. Извлеки ТОЛЬКО текст статьи
3. Убери всю рекламу, баннеры, меню, навигацию
4. Сохрани структуру абзацев
5. НЕ ИЗМЕНЯЙ ТЕКСТ - верни его точно таким же, как на сайте
6. НЕ сокращай, НЕ переписывай, НЕ редактируй текст
7. Верни полный текст статьи без изменений

Верни только текст статьи, без пояснений.
"""

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты помощник по извлечению контента. Извлекай точный текст без изменений. НЕ переписывай текст."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 8000
                }
            )
            
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"]
                
                result = re.sub(r'^Вот извлеченный текст статьи.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Текст статьи.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Извлеченный текст.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Вот текст статьи.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Ссылка.*?:', '', result, flags=re.IGNORECASE)
                result = result.strip()
                
                lines = result.split('\n')
                page_title = lines[0].strip() if lines else ""
                body_text = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
                
                if len(page_title) < 10 or 'http' in page_title:
                    title_match = re.search(r'^(.{10,200}?)(?:\n|$)', result)
                    if title_match:
                        page_title = title_match.group(1).strip()
                        body_text = result[len(page_title):].strip()
                
                return {
                    "text": body_text,
                    "title": page_title,
                    "images": [],
                    "url": url
                }
            else:
                error_text = f"❌ Ошибка API DeepSeek: {response.status_code}"
                try:
                    error_data = response.json()
                    if "error" in error_data:
                        error_text += f"\n{error_data['error'].get('message', '')}"
                except:
                    pass
                return {
                    "text": error_text,
                    "images": [],
                    "title": "",
                    "url": url
                }
                
    except httpx.TimeoutException:
        logger.error(f"Timeout extracting article: {url}")
        return {
            "text": "❌ Превышено время ожидания при извлечении статьи. Попробуйте позже.",
            "images": [],
            "title": "",
            "url": url
        }
    except Exception as e:
        logger.error(f"Error extracting article: {e}")
        return {
            "text": f"❌ Ошибка при извлечении статьи: {str(e)}",
            "images": [],
            "title": "",
            "url": url
        }


# =========================
# Caption formatting
# =========================
def build_caption_html(title: str, body: str, max_length: int = 950) -> str:
    title_safe = html.escape((title or "").strip())
    body_safe = html.escape((body or "").strip())
    
    if title_safe and body_safe:
        caption = f"<b>{title_safe}</b>\n\n{body_safe}"
    elif title_safe:
        caption = f"<b>{title_safe}</b>"
    else:
        caption = body_safe
    
    if len(caption) > max_length:
        caption = caption[:max_length - 3] + "..."
    
    return caption


# =========================
# Callback handlers (основные)
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("repost:"))
def on_repost_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "design":
        st["step"] = "waiting_template"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Выбери шаблон для оформления поста ✅")
        send_message_with_retry(c.message.chat.id, "📝 Выбери шаблон оформления. Фото и текст из репоста будут использованы автоматически! 🎉", reply_markup=template_kb())
    
    elif action == "ai":
        bot.answer_callback_query(c.id, "🤖 Обрабатываю текст через ИИ...")
        
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Обрабатываю текст в DeepSeek AI... (до 30 секунд)")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("original_text", "")
            if not original_text:
                bot.edit_message_text("❌ Нет текста для обработки.", c.message.chat.id, processing_msg.message_id)
                return
            
            result = loop.run_until_complete(process_text_with_deepseek(original_text))
            
            st["ai_processed_text"] = result
            st["original_text"] = result
            
            title, body, formatted_text = format_ai_response(result)
            st["title"] = title
            st["body_raw"] = body
            
            st["step"] = "waiting_after_ai"
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            send_message_with_retry(
                c.message.chat.id, 
                formatted_text,
                parse_mode="HTML", 
                reply_markup=after_ai_kb()
            )
        except Exception as e:
            logger.error(f"AI processing error: {e}")
            bot.edit_message_text(f"❌ Ошибка при обработке ИИ: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "tg":
        if not st.get("original_text"):
            bot.answer_callback_query(c.id, "❌ Нет текста для обработки")
            return
        
        bot.answer_callback_query(c.id, "📱 Сокращаю текст для Telegram...")
        
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Сокращаю текст до 500 символов...")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("original_text", "")
            result = loop.run_until_complete(process_text_with_deepseek_tg(original_text))
            
            st["tg_post_text"] = result
            st["post_type"] = "tg"
            st["step"] = "waiting_post_action"
            
            if st.get("photo_bytes"):
                st["saved_photo_bytes"] = st["photo_bytes"]
            
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            media_info = ""
            if st.get("photo_bytes"):
                media_info = "\n📸 <b>Медиа:</b> фото сохранено"
            elif st.get("video_info"):
                media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
            
            send_message_with_retry(
                c.message.chat.id,
                f"📱 <b>Пост для Telegram (500 символов)</b>\n\n{result}{media_info}",
                parse_mode="HTML",
                reply_markup=post_action_kb("tg")
            )
            
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            
        except Exception as e:
            logger.error(f"TG post error: {e}")
            bot.edit_message_text(f"❌ Ошибка: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "threads":
        if not st.get("original_text"):
            bot.answer_callback_query(c.id, "❌ Нет текста для обработки")
            return
        
        bot.answer_callback_query(c.id, "📱 Сокращаю текст для Тредс...")
        
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Сокращаю текст до 400 символов...")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("original_text", "")
            result = loop.run_until_complete(process_text_with_deepseek_threads(original_text))
            
            st["threads_post_text"] = result
            st["post_type"] = "threads"
            st["step"] = "waiting_post_action"
            
            if st.get("photo_bytes"):
                st["saved_photo_bytes"] = st["photo_bytes"]
            
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            media_info = ""
            if st.get("photo_bytes"):
                media_info = "\n📸 <b>Медиа:</b> фото сохранено"
            elif st.get("video_info"):
                media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
            
            send_message_with_retry(
                c.message.chat.id,
                f"📱 <b>Пост для Тредс (400 символов)</b>\n\n{result}{media_info}",
                parse_mode="HTML",
                reply_markup=post_action_kb("threads")
            )
            
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            
        except Exception as e:
            logger.error(f"Threads post error: {e}")
            bot.edit_message_text(f"❌ Ошибка: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "watermark":
        if st.get("photo_bytes") or st.get("saved_photo_bytes"):
            if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
                st["photo_bytes"] = st["saved_photo_bytes"]
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>\n\n📸 Фото из репоста будет использовано автоматически!", parse_mode="HTML", reply_markup=watermark_type_kb())
        else:
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>\n\n⚠️ В репосте не найдено фото. Отправь фото отдельно.", parse_mode="HTML", reply_markup=watermark_type_kb())


# =========================
# Обработчик ссылок на статьи
# =========================
@bot.message_handler(func=lambda message: re.search(r'https?://[^\s]+', message.text) and not re.search(r't\.me/', message.text))
def handle_article_link(message):
    uid = message.from_user.id
    text = message.text.strip()
    
    url_match = re.search(r'(https?://[^\s]+)', text)
    if not url_match:
        bot.reply_to(message, "❌ Не найдена ссылка в сообщении")
        return
    
    url = url_match.group(1)
    
    if 't.me' in url:
        return
    
    processing_msg = bot.reply_to(message, "🔍 Извлекаю содержимое статьи через ИИ...\n\n⏳ Это может занять до 30-60 секунд...")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        result = loop.run_until_complete(extract_article_content(url))
        
        if not result or not result.get("text"):
            bot.edit_message_text(
                "❌ Не удалось извлечь текст статьи. Попробуйте другую ссылку или отправьте текст вручную.",
                message.chat.id,
                processing_msg.message_id
            )
            return
        
        try:
            bot.delete_message(message.chat.id, processing_msg.message_id)
        except:
            pass
        
        st = user_state.get(uid) or {}
        st["extracted_text"] = result.get("text", "")
        st["extracted_title"] = result.get("title", "")
        st["extracted_url"] = result.get("url", url)
        st["step"] = "waiting_extracted_article"
        user_state[uid] = st
        
        try:
            title_text = result.get("title", "")
            article_text = result.get("text", "")
            
            full_message = ""
            if title_text:
                full_message = f"<b>{html.escape(title_text)}</b>\n\n"
            if article_text:
                full_message += article_text
            
            if len(full_message) > 4000:
                parts = []
                current_part = ""
                
                if title_text:
                    current_part = f"<b>{html.escape(title_text)}</b>\n\n"
                
                paragraphs = article_text.split('\n\n')
                for p in paragraphs:
                    if len(current_part) + len(p) + 2 < 4000:
                        current_part += p + '\n\n'
                    else:
                        if current_part:
                            parts.append(current_part.strip())
                        current_part = p + '\n\n'
                
                if current_part:
                    parts.append(current_part.strip())
                
                for i, part in enumerate(parts):
                    if i == 0:
                        bot.send_message(message.chat.id, part, parse_mode="HTML")
                    else:
                        bot.send_message(
                            message.chat.id, 
                            f"📝 <b>Продолжение ({i+1}/{len(parts)}):</b>\n\n{part}", 
                            parse_mode="HTML"
                        )
            else:
                bot.send_message(message.chat.id, full_message, parse_mode="HTML")
            
            # Кнопки для действий
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("📝 Оформить пост", callback_data="article:design"),
                InlineKeyboardButton("🤖 Обработать через ИИ", callback_data="article:ai"),
                InlineKeyboardButton("📱 Пост для ТГ (500 симв.)", callback_data="article:tg"),
                InlineKeyboardButton("📱 Пост для Тредс (400 симв.)", callback_data="article:threads"),
                InlineKeyboardButton("💧 Водяной знак", callback_data="article:watermark")
            )
            kb.add(InlineKeyboardButton("📢 Опубликовать в канале", callback_data="article:publish"))
            
            bot.send_message(
                message.chat.id,
                "🎯 <b>Что сделать с этой статьей?</b>",
                parse_mode="HTML",
                reply_markup=kb
            )
            
        except Exception as e:
            logger.error(f"Error sending article content: {e}")
            if result.get("text"):
                bot.send_message(
                    message.chat.id,
                    f"⚠️ Часть контента не отобразилась, но текст сохранен.\n\n{result['text'][:1000]}...",
                    parse_mode="HTML"
                )
            
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("📝 Оформить пост", callback_data="article:design"),
                InlineKeyboardButton("🤖 Обработать через ИИ", callback_data="article:ai")
            )
            bot.send_message(
                message.chat.id,
                "🎯 <b>Что сделать с этой статьей?</b>",
                parse_mode="HTML",
                reply_markup=kb
            )
            
    except Exception as e:
        logger.error(f"Error processing article: {e}")
        try:
            bot.edit_message_text(
                f"❌ Ошибка при обработке статьи: {str(e)}",
                message.chat.id,
                processing_msg.message_id
            )
        except:
            bot.send_message(
                message.chat.id,
                f"❌ Ошибка при обработке статьи: {str(e)}",
                parse_mode="HTML"
            )
    finally:
        loop.close()


# =========================
# Обработчики для кнопок article
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("article:"))
def on_article_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "design":
        if not st.get("extracted_text"):
            bot.answer_callback_query(c.id, "❌ Нет текста для оформления. Сначала отправьте ссылку на статью.")
            return
        
        st["original_text"] = st.get("extracted_text", "")
        st["original_text_for_ai"] = st.get("extracted_text", "")
        title, body = split_title_and_body(st["extracted_text"])
        st["title"] = title if title else "Статья"
        st["body_raw"] = body
        st["step"] = "waiting_template"
        user_state[uid] = st
        
        bot.answer_callback_query(c.id, "📝 Выбери шаблон для оформления")
        send_message_with_retry(
            c.message.chat.id,
            "📝 Выбери шаблон оформления. Текст из статьи будет использован автоматически! 🎉",
            parse_mode="HTML",
            reply_markup=template_kb()
        )
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
    
    elif action == "ai":
        if not st.get("extracted_text"):
            bot.answer_callback_query(c.id, "❌ Нет текста для обработки")
            return
        
        bot.answer_callback_query(c.id, "🤖 Обрабатываю текст через ИИ...")
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Обрабатываю текст в DeepSeek AI... (до 30 секунд)")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("extracted_text", "")
            result = loop.run_until_complete(process_text_with_deepseek(original_text))
            
            st["ai_processed_text"] = result
            st["original_text"] = result
            title, body, formatted_text = format_ai_response(result)
            st["title"] = title
            st["body_raw"] = body
            st["step"] = "waiting_after_ai"
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            send_message_with_retry(
                c.message.chat.id,
                f"✍️ <b>Обработанный текст:</b>\n\n{formatted_text}",
                parse_mode="HTML",
                reply_markup=after_ai_kb()
            )
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
        except Exception as e:
            logger.error(f"AI processing error: {e}")
            bot.edit_message_text(f"❌ Ошибка при обработке ИИ: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "tg":
        if not st.get("extracted_text"):
            bot.answer_callback_query(c.id, "❌ Нет текста для обработки")
            return
        
        bot.answer_callback_query(c.id, "📱 Сокращаю текст для Telegram...")
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Сокращаю текст до 500 символов...")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("extracted_text", "")
            result = loop.run_until_complete(process_text_with_deepseek_tg(original_text))
            
            st["tg_post_text"] = result
            st["post_type"] = "tg"
            st["step"] = "waiting_post_action"
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            send_message_with_retry(
                c.message.chat.id,
                f"📱 <b>Пост для Telegram (500 символов)</b>\n\n{result}",
                parse_mode="HTML",
                reply_markup=post_action_kb("tg")
            )
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
        except Exception as e:
            logger.error(f"TG post error: {e}")
            bot.edit_message_text(f"❌ Ошибка: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "threads":
        if not st.get("extracted_text"):
            bot.answer_callback_query(c.id, "❌ Нет текста для обработки")
            return
        
        bot.answer_callback_query(c.id, "📱 Сокращаю текст для Тредс...")
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Сокращаю текст до 400 символов...")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("extracted_text", "")
            result = loop.run_until_complete(process_text_with_deepseek_threads(original_text))
            
            st["threads_post_text"] = result
            st["post_type"] = "threads"
            st["step"] = "waiting_post_action"
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            send_message_with_retry(
                c.message.chat.id,
                f"📱 <b>Пост для Тредс (400 символов)</b>\n\n{result}",
                parse_mode="HTML",
                reply_markup=post_action_kb("threads")
            )
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
        except Exception as e:
            logger.error(f"Threads post error: {e}")
            bot.edit_message_text(f"❌ Ошибка: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "watermark":
        bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
        st["step"] = "waiting_watermark_type"
        user_state[uid] = st
        send_message_with_retry(
            c.message.chat.id,
            "💧 <b>Выбери тип водяного знака:</b>",
            parse_mode="HTML",
            reply_markup=watermark_type_kb()
        )
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
    
    elif action == "publish":
        if not CHANNEL_MN and not CHANNEL_CHP and not CHANNEL_AFISHA and not CHANNEL_TEST:
            bot.answer_callback_query(c.id, "❌ Каналы не настроены")
            send_message_with_retry(c.message.chat.id, "❌ Ни один канал для публикации не настроен.", reply_markup=main_menu_kb())
            return
        
        bot.answer_callback_query(c.id, "📢 Выбери канал для публикации")
        st["original_text"] = st.get("extracted_text", "")
        st["title"], st["body_raw"] = split_title_and_body(st["original_text"])
        user_state[uid] = st
        send_message_with_retry(
            c.message.chat.id,
            "📢 <b>Выбери канал для публикации текста:</b>",
            parse_mode="HTML",
            reply_markup=channel_selection_kb()
        )
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass


# =========================
# Message handlers для команд
# =========================
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    clear_state(message.from_user.id)
    
    channels_list = []
    if CHANNEL_MN:
        channels_list.append("📰 MINSK NEWS")
    if CHANNEL_CHP:
        channels_list.append("🚨 МИНСК ЧП")
    if CHANNEL_AFISHA:
        channels_list.append("🎫 Афиша Минска")
    if CHANNEL_TEST:
        channels_list.append("🧪 ТЕСТОВЫЙ")
    channels_text = ", ".join(channels_list) if channels_list else "не настроены"
    
    send_message_with_retry(
        message.chat.id,
        f"👋 <b>Привет! Я бот для оформления постов</b>\n\n"
        f"<b>📝 Основные функции:</b>\n"
        f"• 📝 Оформление постов с фото (7 шаблонов)\n"
        f"• ✨ Улучшение качества фото\n"
        f"• 💧 Водяные знаки\n"
        f"• 🤖 Текст в ИИ - сокращение до 650 символов\n"
        f"• 📱 Пост для ТГ - сокращение до 500 символов\n"
        f"• 📱 Пост для Тредс - сокращение до 400 символов\n"
        f"• 📰 Извлечение статьи - отправь ссылку\n"
        f"• 💰 Цены и условия размещения\n"
        f"• 📎 Репосты из каналов\n\n"
        f"<b>📌 Доступные каналы для публикации:</b> {channels_text}\n\n"
        f"Выбери действие 👇",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

@bot.message_handler(commands=["post"])
def cmd_post(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_photo_first"
    user_state[uid] = st
    send_message_with_retry(message.chat.id, "📸 Отправь фото для оформления поста:", reply_markup=main_menu_kb())


# =========================
# Graceful shutdown
# =========================
def signal_handler(sig, frame):
    logger.info("Shutting down gracefully...")
    try:
        bot.stop_polling()
    except:
        pass
    try:
        if os.path.exists(lock_file):
            os.unlink(lock_file)
    except:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# =========================
# Main execution
# =========================
if __name__ == "__main__":
    logger.info("Starting bot...")
    try:
        download_fonts()
        ensure_fonts()
        logger.info("Fonts loaded successfully")
        
        for attempt in range(3):
            try:
                bot.remove_webhook()
                time.sleep(1)
                logger.info(f"Webhook removed (attempt {attempt + 1})")
                break
            except Exception as e:
                logger.warning(f"Failed to remove webhook (attempt {attempt + 1}): {e}")
                time.sleep(2)
        
        http_thread = threading.Thread(target=run_http_server, daemon=True)
        http_thread.start()
        logger.info("🌐 Health check server thread started")
        
        logger.info("🤖 Bot started polling...")
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                logger.error(f"Polling error: {e}")
                if "409" in str(e):
                    logger.error("Conflict detected! Waiting 30 seconds...")
                    time.sleep(30)
                else:
                    time.sleep(10)
                continue
                
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        try:
            if os.path.exists(lock_file):
                os.unlink(lock_file)
        except:
            pass
        raise
