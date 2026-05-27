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
from urllib.parse import urlparse

import requests
import httpx
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
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

# Каналы для публикации
CHANNEL_MN = (os.getenv("CHANNEL_MN") or "").strip()
CHANNEL_CHP = (os.getenv("CHANNEL_CHP") or "").strip()

if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL
if CHANNEL_MN and not CHANNEL_MN.startswith("@"):
    CHANNEL_MN = "@" + CHANNEL_MN
if CHANNEL_CHP and not CHANNEL_CHP.startswith("@"):
    CHANNEL_CHP = "@" + CHANNEL_CHP

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN must not contain spaces")

if not SUGGEST_URL and BOT_USERNAME:
    SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"

# Constants
MAX_FILE_SIZE = 20 * 1024 * 1024
REQUEST_TIMEOUT = 15

# Размеры для всех шаблонов - 720x900
TARGET_W, TARGET_H = 720, 900
STORY_W = 720
STORY_H = 1280

# Размеры для квадратных фото
SQUARE_SIZE = 1080

# Параметры для шаблонов
FDR_POST_PURPLE_COLOR = (122, 58, 240)
TEXT_POSITION_TOP = "top"
TEXT_POSITION_BOTTOM = "bottom"

# Шрифты
FONT_MN = "CaviarDreams.ttf"
FONT_MN_BOLD = "CaviarDreams_Bold.ttf"
FONT_CHP = "Montserrat-Black.ttf"
FONT_AM = "IntroInline.ttf"
FONT_MONTSERRAT_BLACK = "Montserrat-Black.ttf"
FONT_PATH = "Inter-ExtraBold.ttf"
FONT_FALLBACK = "Montserrat-Black.ttf"
FONT_REGULAR = "Inter-Regular.ttf"

FOOTER_TEXT = "MINSK NEWS"

# Параметры шаблонов
MN_TITLE_ZONE_PCT = 0.23
CHP_GRADIENT_PCT = 0.48
AM_TOP_BLUR_PCT = 0.20
AM_BLUR_RADIUS = 18
AM_BLUR_BLEND = 0.50

# Параметры для АМ 2 (афиша)
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

# Цвета
TEXT_COLOR = (255, 255, 255)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

# Цвета для выделения
HIGHLIGHT_COLORS = {
    "red": (255, 80, 80),
    "yellow": (255, 220, 80),
    "blue": (80, 150, 255)
}


# =========================
# BOT + SESSION
# =========================
bot = telebot.TeleBot(TOKEN)

SESSION = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=0.5,
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9",
})

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

user_state: Dict[int, Dict] = {}


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
        InlineKeyboardButton("💧 Нанести водяной знак", callback_data="repost:watermark")
    )
    return kb

def after_ai_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("📝 Оформить пост", callback_data="ai:design"),
        InlineKeyboardButton("❌ Отмена", callback_data="ai:cancel")
    )
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
        InlineKeyboardButton("🚨 ЧП (Минск ЧП)", callback_data="watermark:chp")
    )
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="watermark:cancel"))
    return kb

def preview_kb(source_url: str = ""):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("📢 Опубликовать в канале", callback_data="publish_to_channel"),
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
        kb.add(InlineKeyboardButton("🚨 Минск ЧП", callback_data="select_channel:chp"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="select_channel:cancel"))
    return kb

def channel_kb():
    kb = InlineKeyboardMarkup()
    if SUGGEST_URL:
        kb.add(InlineKeyboardButton("📝 Предложить новость", url=SUGGEST_URL))
    return kb

def build_caption_with_buttons(title: str, body: str, channel_type: str) -> Tuple[str, InlineKeyboardMarkup]:
    title_safe = html.escape((title or "").strip())
    body_safe = html.escape((body or "").strip())
    caption = f"<b>{title_safe}</b>\n\n{body_safe}"
    
    if channel_type == "mn":
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("📝 Прислать новость", url="https://t.me/prishlinews_bot"),
            InlineKeyboardButton("🔗 Подписаться на канал", url="https://t.me/vestiminska")
        )
    else:
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("📝 Прислать новость", url="https://t.me/prishlinews_bot"),
            InlineKeyboardButton("🔗 Подписаться на канал", url="https://t.me/minskchpidtp")
        )
    return caption, kb

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
def template_kb(is_square: bool = False):
    kb = InlineKeyboardMarkup()
    prefix = "square:" if is_square else "tpl:"
    
    if is_square:
        kb.row(
            InlineKeyboardButton("📰 МН", callback_data=f"{prefix}MN"),
            InlineKeyboardButton("🚨 ЧП ВМ", callback_data=f"{prefix}CHP"),
        )
        kb.row(
            InlineKeyboardButton("✨ АМ", callback_data=f"{prefix}AM"),
            InlineKeyboardButton("🆕 АМ 2", callback_data=f"{prefix}AM2"),
        )
        kb.row(
            InlineKeyboardButton("💜 Пост ФДР", callback_data=f"{prefix}FDR_POST"),
            InlineKeyboardButton("📱 МН ТГ", callback_data=f"{prefix}MN_TG"),
        )
        kb.row(
            InlineKeyboardButton("🆕 МН 2", callback_data=f"{prefix}MN2"),
            InlineKeyboardButton("◀️ Назад к оформлению", callback_data="square:back"),
        )
    else:
        kb.row(
            InlineKeyboardButton("📰 МН", callback_data=f"{prefix}MN"),
            InlineKeyboardButton("🚨 ЧП ВМ", callback_data=f"{prefix}CHP"),
        )
        kb.row(
            InlineKeyboardButton("✨ АМ", callback_data=f"{prefix}AM"),
            InlineKeyboardButton("🆕 АМ 2", callback_data=f"{prefix}AM2"),
        )
        kb.row(
            InlineKeyboardButton("📱 Сторис ФДР", callback_data=f"{prefix}FDR_STORY"),
            InlineKeyboardButton("💜 Пост ФДР", callback_data=f"{prefix}FDR_POST"),
        )
        kb.row(
            InlineKeyboardButton("📱 МН ТГ", callback_data=f"{prefix}MN_TG"),
            InlineKeyboardButton("🆕 МН 2", callback_data=f"{prefix}MN2"),
        )
        kb.row(
            InlineKeyboardButton("⬛ Квадраты", callback_data="show_squares"),
        )
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
# Text wrapping functions
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
# Функции для шаблона АМ 2
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
    text = (title_text or "").strip().upper()
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
def make_card_mn(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP, is_square: bool = False) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), Image.Resampling.LANCZOS)
    else:
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
    text = (title_text or "").strip().upper()
    font, lines, heights, spacing, total_text_height = fit_text_block(
        draw=draw, text=text, font_path=FONT_MN, safe_w=safe_w,
        max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
        min_size=16, line_spacing_ratio=0.22
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

def make_card_mn2(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP, font_size_multiplier: float = 1.0, is_square: bool = False, bold_phrase: str = "") -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), Image.Resampling.LANCZOS)
    else:
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
    text = (title_text or "").strip().upper()
    bold_phrase_upper = bold_phrase.strip().upper() if bold_phrase else ""
    bold_words = set(bold_phrase_upper.split())
    base_start_size = int(img.height * 0.11)
    adjusted_start_size = int(base_start_size * font_size_multiplier)
    font, lines, heights, spacing, total_text_height = fit_text_block(
        draw=draw, text=text, font_path=FONT_MN, safe_w=safe_w,
        max_block_h=title_max_h, max_lines=6, start_size=adjusted_start_size,
        min_size=16, line_spacing_ratio=0.25
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
    def draw_line_with_bold(line_text, x_start, y_pos):
        words = line_text.split()
        current_x = x_start
        for word in words:
            if word in bold_words:
                bold_font = load_font(FONT_MN_BOLD, font.size)
                draw.text((current_x, y_pos), word, font=bold_font, fill="white")
            else:
                draw.text((current_x, y_pos), word, font=font, fill="white")
            if word != words[-1]:
                space_width = text_width(draw, " ", font)
                current_x += text_width(draw, word, font) + space_width
            else:
                current_x += text_width(draw, word, font)
    y = title_y
    for i, ln in enumerate(lines):
        draw_line_with_bold(ln, block_x, y)
        if i < len(lines) - 1:
            line_height = max(heights[i], int(font.size * 0.9))
            y += line_height + spacing
        else:
            y += heights[i]
    footer_x = (img.width - footer_w) // 2
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out

def make_card_mn_tg(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP, is_square: bool = False) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), Image.Resampling.LANCZOS)
    else:
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

def make_card_chp(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP, is_square: bool = False) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), Image.Resampling.LANCZOS)
    else:
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
    text = (title_text or "").strip().upper()
    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw, text=text, font_path=FONT_CHP, safe_w=safe_w,
        max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
        min_size=16, line_spacing_ratio=0.22
    )
    if text_position == TEXT_POSITION_TOP:
        y = margin_top
    else:
        y = img.height - margin_bottom - total_h
    for i, ln in enumerate(lines):
        draw.text((margin_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out

def make_card_am(photo_bytes: bytes, title_text: str, is_square: bool = False) -> BytesIO:
    ensure_fonts()
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    if is_square:
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), Image.Resampling.LANCZOS)
    else:
        img = crop_to_4x5(img)
        img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
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
        draw=draw, text=text, font_path=FONT_AM, safe_w=safe_w,
        max_block_h=text_zone_h, max_lines=3, start_size=int(img.height * 0.060),
        min_size=20, line_spacing_ratio=0.16
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

def make_card_am2(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP,
                  date: str = "", place: str = "", rubric: str = "",
                  highlight_word: str = "", highlight_color: tuple = None, is_yellow: bool = False,
                  is_square: bool = False) -> BytesIO:
    if is_square:
        img = Image.open(BytesIO(photo_bytes)).convert("RGB")
        img = crop_to_square(img)
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), Image.Resampling.LANCZOS)
        img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS_FACTOR)
        if text_position == "top":
            img = apply_gradient_direction(img, "top", GRADIENT_HEIGHT_PCT, GRADIENT_MAX_ALPHA)
        else:
            img = apply_gradient_direction(img, "bottom", GRADIENT_HEIGHT_PCT, GRADIENT_MAX_ALPHA)
        draw = ImageDraw.Draw(img)
        margin_x = int(img.width * 0.06)
        margin_top = int(img.height * 0.15)
        safe_w = img.width - 2 * margin_x
        text = (title_text or "").strip().upper()
        title_max_h = int(img.height * 0.23)
        font, lines, heights, spacing, total_h = fit_text_block_center(
            draw=draw, text=text, font_path=FONT_PATH, safe_w=safe_w,
            max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
            min_size=24, line_spacing_ratio=LINE_SPACING_RATIO
        )
        y = margin_top
        for i, ln in enumerate(lines):
            line_w = text_width(draw, ln, font)
            x = (img.width - line_w) // 2
            draw.text((x, y), ln, font=font, fill="white")
            y += heights[i] + spacing
        out = BytesIO()
        img.save(out, format="JPEG", quality=95, subsampling=0)
        out.seek(0)
        return out
    else:
        return create_poster_am2(photo_bytes, title_text, text_position, date, place, rubric,
                                 highlight_word, highlight_color, is_yellow)

def make_card_fdr_story(photo_bytes: bytes, title: str, body_text: str) -> BytesIO:
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
        img = img.resize((SQUARE_SIZE, SQUARE_SIZE), Image.Resampling.LANCZOS)
    else:
        img = crop_to_4x5(img)
        img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
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
        draw=draw, text=title_text_upper, font_path=FONT_CHP, safe_w=safe_w,
        max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
        min_size=16, line_spacing_ratio=0.22
    )
    base_y = img.height - margin_bottom - total_h
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
        y += heights[line_idx] + spacing
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

def make_card(photo_bytes: bytes, title_text: str, template: str, body_text: str = "", highlight_phrase: str = "", 
              text_position: str = TEXT_POSITION_TOP, font_size_multiplier: float = 1.0, is_square: bool = False, 
              bold_phrase: str = "", date: str = "", place: str = "", rubric: str = "",
              highlight_word: str = "", highlight_color: tuple = None, is_yellow: bool = False) -> BytesIO:
    if template == "CHP":
        return make_card_chp(photo_bytes, title_text, text_position, is_square)
    if template == "AM":
        return make_card_am(photo_bytes, title_text, is_square)
    if template == "AM2":
        return make_card_am2(photo_bytes, title_text, text_position, date, place, rubric,
                            highlight_word, highlight_color, is_yellow, is_square)
    if template == "FDR_STORY":
        return make_card_fdr_story(photo_bytes, title_text, body_text)
    if template == "FDR_POST":
        return make_card_fdr_post(photo_bytes, title_text, highlight_phrase, is_square)
    if template == "MN_TG":
        return make_card_mn_tg(photo_bytes, title_text, text_position, is_square)
    if template == "MN2":
        return make_card_mn2(photo_bytes, title_text, text_position, font_size_multiplier, is_square, bold_phrase)
    return make_card_mn(photo_bytes, title_text, text_position, is_square)


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
    try:
        img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
        watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        font_size = int(img.width * 0.1)
        try:
            font = load_font(FONT_MN, font_size)
        except:
            font = ImageFont.load_default()
        watermark_text = "MINSK NEWS"
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width_val = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (img.width - text_width_val) // 2
        y = (img.height - text_height) // 2
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
        watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        font_size = int(img.width * 0.1)
        try:
            font = load_font(FONT_CHP, font_size)
        except:
            font = ImageFont.load_default()
        watermark_text = "ЧП Минск"
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width_val = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (img.width - text_width_val) // 2
        y = (img.height - text_height) // 2
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
# Caption formatting
# =========================
RU_STOP = {"и", "в", "во", "на", "но", "а", "что", "это", "как", "к", "по", "из", "за", "для", "с", "со", "у", "от", "до", "при", "без", "над", "под", "же", "ли", "то", "не", "ни", "да", "нет", "уже", "еще", "ещё", "там", "тут"}

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
    links = "\n\n🔗 <a href='https://t.me/vestiminska'>Все новости Минска</a>\n📝 <a href='https://t.me/prishlinews_bot'>Прислать новость</a>"
    return f"<b>{title_safe}</b>\n\n{body_text}{links}"


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

🔻 <b>Пакет «ПРЕМИУМ»</b> (более 1 700.000 подписчиков): <b>905 рублей</b>.

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

def get_schedule_text() -> str:
    text = "📊 График аккаунтов:\n\n"
    text += "<a href='https://instagram.com/minsk_news'>instagram.com/minsk_news</a> -\n"
    text += "<a href='https://instagram.com/minskchp'>instagram.com/minskchp</a> -\n"
    text += "<a href='https://instagram.com/afishaminsk'>instagram.com/afishaminsk</a> -\n"
    text += "<a href='https://instagram.com/tvoyminsk'>instagram.com/tvoyminsk</a> -\n"
    text += "<a href='https://instagram.com/vestiminska'>instagram.com/vestiminska</a> -\n"
    text += "<a href='https://instagram.com/minskpress'>instagram.com/minskpress</a> -\n"
    text += "<a href='https://instagram.com/xxminsk'>instagram.com/xxminsk</a> -\n"
    text += "<a href='https://instagram.com/minskgood'>instagram.com/minskgood</a> -\n"
    text += "<a href='https://instagram.com/novostiminska'>instagram.com/novostiminska</a> -\n"
    text += "<a href='https://instagram.com/minskhot'>instagram.com/minskhot</a> -\n"
    text += "<a href='https://instagram.com/minsksmile'>instagram.com/minsksmile</a> -"
    return text


# =========================
# DeepSeek AI
# =========================
async def process_text_with_deepseek(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен. Добавьте DEEPSEEK_API_KEY в переменные окружения."
    prompt = """Ты редактор новостного сайта, у тебя строгий новостной городской формат. Без обращений на вы, ты и т.д. Только новостной формат.

Но тебе нужно переделывать новость с большого объема в новость на 650 символов.
Убирая всю лишнюю воду, текст, делать интересным заголовок, никаких смайликов. Сохраняй главный факты, проверяй всю информацию несколько раз, чтобы не было никаких ошибок. Расставляй абзацы в нужно месте, чтобы текст не был единым пластом.

Вот текст для обработки:"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [{"role": "system", "content": "Ты редактор новостного сайта."}, {"role": "user", "content": f"{prompt}\n\n{text}"}], "temperature": 0.7, "max_tokens": 1000}
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка при обращении к API: {str(e)}"


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
        send_message_with_retry(c.message.chat.id, get_prices_text(), parse_mode="HTML", reply_markup=prices_menu_kb())
    elif action == "terms":
        send_message_with_retry(c.message.chat.id, get_terms_text(), parse_mode="HTML", reply_markup=prices_menu_kb())
    elif action == "schedule":
        send_message_with_retry(c.message.chat.id, get_schedule_text(), parse_mode="HTML", reply_markup=prices_menu_kb())
    elif action == "close":
        bot.delete_message(c.message.chat.id, c.message.message_id)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("watermark:"))
def on_watermark_type(c):
    uid = c.from_user.id
    wm_type = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    if wm_type == "cancel":
        st.pop("step", None)
        user_state[uid] = st
        send_message_with_retry(c.message.chat.id, "❌ Отменено")
        bot.answer_callback_query(c.id)
        return
    
    # Если есть фото из репоста - используем его сразу
    if st.get("photo_bytes") and not st.get("watermark_photo_sent"):
        st["watermark_type"] = wm_type
        st["step"] = "waiting_watermark_photo"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "✅ Наношу водяной знак на фото из репоста...")
        
        # Сразу применяем водяной знак
        try:
            if wm_type == "mn":
                result = apply_watermark_mn(st["photo_bytes"])
                caption = "💧 Водяной знак <b>MINSK NEWS</b> нанесён на фото из репоста!"
            else:
                result = apply_watermark_chp(st["photo_bytes"])
                caption = "💧 Водяной знак <b>ЧП Минск</b> нанесён на фото из репоста!"
            
            bot.send_document(c.message.chat.id, document=result, visible_file_name=f"watermark_{wm_type}.jpg", caption=caption, parse_mode="HTML")
            clear_state(uid)
        except Exception as e:
            logger.error(f"Error applying watermark: {e}")
            send_message_with_retry(c.message.chat.id, f"❌ Ошибка при нанесении водяного знака: {e}")
        return
    
    st["watermark_type"] = wm_type
    st["step"] = "waiting_watermark_photo"
    user_state[uid] = st
    send_message_with_retry(c.message.chat.id, f"✅ Выбран водяной знак. Отправь фото:", parse_mode="HTML")
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("show_squares"))
def on_show_squares(c):
    uid = c.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_template_square"
    user_state[uid] = st
    send_message_with_retry(c.message.chat.id, "⬛ Выбери шаблон для квадратного фото:", reply_markup=template_kb(True))
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("tpl:") or c.data.startswith("square:"))
def on_tpl(c):
    uid = c.from_user.id
    parts = c.data.split(":", 1)
    prefix = parts[0]
    tpl = parts[1]
    is_square = (prefix == "square")
    st = user_state.get(uid) or {}
    
    if tpl == "back" and is_square:
        st["step"] = "waiting_template"
        user_state[uid] = st
        send_message_with_retry(c.message.chat.id, "📝 Выбери шаблон оформления:", reply_markup=template_kb(False))
        bot.answer_callback_query(c.id)
        return
    
    st["is_square"] = is_square
    st["template"] = tpl
    
    # Проверяем, есть ли уже сохранённые фото и текст из репоста
    has_photo = st.get("photo_bytes") is not None
    has_text = st.get("original_text") is not None
    
    if tpl == "AM2":
        if has_photo:
            st["photo_bytes"] = st["photo_bytes"]  # используем фото из репоста
            st["step"] = "waiting_text_position_am2"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон АМ 2 выбран ✅")
            send_message_with_retry(c.message.chat.id, f"🎨 Выбран шаблон <b>АМ 2</b>\n\n📸 Фото из репоста сохранено!\n\n📐 <b>Выбери расположение текста:</b>", parse_mode="HTML", reply_markup=text_position_kb_am2())
        else:
            st["step"] = "waiting_photo_am2"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон АМ 2 выбран ✅")
            size_text = "квадратное " if is_square else ""
            send_message_with_retry(c.message.chat.id, f"🎨 Выбран {size_text}шаблон <b>АМ 2</b>\n\n📸 Пришли {size_text}фото:", parse_mode="HTML")
            
    elif tpl == "MN2":
        if has_photo:
            st["photo_bytes"] = st["photo_bytes"]
            st["step"] = "waiting_font_size"
            user_state[uid] = st
            bot.answer_callback_query(c.id, f"Шаблон МН 2 выбран ✅")
            size_text = "квадратного " if is_square else ""
            send_message_with_retry(c.message.chat.id, f"🔤 Настрой размер шрифта для {size_text}заголовка (используй фото из репоста):", reply_markup=font_size_kb(1.0, is_square))
        else:
            st["step"] = "waiting_font_size"
            user_state[uid] = st
            bot.answer_callback_query(c.id, f"Шаблон МН 2 выбран ✅")
            size_text = "квадратного " if is_square else ""
            send_message_with_retry(c.message.chat.id, f"🔤 Настрой размер шрифта для {size_text}заголовка:", reply_markup=font_size_kb(1.0, is_square))
            
    elif tpl == "FDR_POST":
        if has_photo:
            st["photo_bytes"] = st["photo_bytes"]
            st["step"] = "waiting_title_fdr_post"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
            size_text = "квадратное " if is_square else ""
            default_text = f"\n\n💡 <i>Используй текст из репоста (напиши «+» чтобы использовать его):</i>\n\n{st.get('original_text', '')[:200]}..." if has_text else ""
            send_message_with_retry(c.message.chat.id, f"💜 Выбран {size_text}шаблон <b>Пост ФДР</b>\n\n📸 Фото из репоста сохранено!{default_text}\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b> (или «+» чтобы использовать текст из репоста):", parse_mode="HTML")
        else:
            st["step"] = "waiting_photo_fdr_post"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
            size_text = "квадратное " if is_square else ""
            send_message_with_retry(c.message.chat.id, f"💜 Выбран {size_text}шаблон <b>Пост ФДР</b>\n\n📸 Пришли {size_text}фото:", parse_mode="HTML")
            
    elif tpl == "FDR_STORY" and not is_square:
        if has_photo:
            st["photo_bytes"] = st["photo_bytes"]
            st["step"] = "waiting_title_fdr"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Сторис ФДР' выбран ✅")
            default_text = f"\n\n💡 <i>Используй текст из репоста (напиши «+» чтобы использовать его):</i>\n\n{st.get('original_text', '')[:200]}..." if has_text else ""
            send_message_with_retry(c.message.chat.id, f"📱 Выбран шаблон <b>Сторис ФДР</b>\n\n📸 Фото из репоста сохранено!{default_text}\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b> для сторис:", parse_mode="HTML")
        else:
            st["step"] = "waiting_photo_fdr_story"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Сторис ФДР' выбран ✅")
            send_message_with_retry(c.message.chat.id, "📱 Выбран шаблон <b>Сторис ФДР</b>\n\n📸 Пришли фото:", parse_mode="HTML")
            
    else:
        # Обычные шаблоны (MN, CHP, AM, MN_TG)
        st["step"] = "waiting_text_position"
        user_state[uid] = st
        template_names = {"MN": "МН", "AM": "АМ", "MN_TG": "МН ТГ", "CHP": "ЧП ВМ"}
        template_name = template_names.get(tpl, tpl)
        size_text = "квадратный " if is_square else ""
        
        if has_photo:
            bot.answer_callback_query(c.id, f"Шаблон {template_name} выбран ✅")
            send_message_with_retry(c.message.chat.id, f"📰 Выбран {size_text}шаблон <b>{template_name}</b>\n\n📸 Фото из репоста уже есть!\n\nГде разместить текст?", parse_mode="HTML", reply_markup=text_position_kb(is_square))
        else:
            bot.answer_callback_query(c.id, f"Шаблон {template_name} выбран ✅")
            send_message_with_retry(c.message.chat.id, f"📰 Выбран {size_text}шаблон <b>{template_name}</b>\n\nГде разместить текст?\n\nЗатем пришли фото 📷", parse_mode="HTML", reply_markup=text_position_kb(is_square))
    
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("am2_pos:"))
def on_am2_text_position(c):
    uid = c.from_user.id
    position = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    st["text_position"] = position
    st["step"] = "waiting_title_am2"
    user_state[uid] = st
    pos_text = "сверху" if position == "top" else "снизу"
    bot.answer_callback_query(c.id, f"Текст будет {pos_text} ✅")
    
    default_text = f"\n\n💡 <i>Используй текст из репоста (напиши «+» чтобы использовать его):</i>\n\n{st.get('original_text', '')[:300]}..." if st.get("original_text") else ""
    send_message_with_retry(c.message.chat.id, f"✅ Текст будет расположен <b>{pos_text}</b>\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b>:{default_text}", parse_mode="HTML")
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("am2_date_place:"))
def on_am2_date_place_choice(c):
    uid = c.from_user.id
    choice = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    if choice == "yes":
        st["step"] = "waiting_date_am2"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Добавляем дату и место ✅")
        send_message_with_retry(c.message.chat.id, f"✏️ <b>Введи ДАТУ</b>:", parse_mode="HTML")
    else:
        st["date"] = ""
        st["place"] = ""
        st["step"] = "waiting_highlight_word_am2"
        user_state[uid] = st
        try:
            card = create_poster_am2(st["photo_bytes"], st.get("title", ""), st.get("text_position", "top"), "", "", "", "", None, False)
            st["preview_bytes"] = card.getvalue()
            user_state[uid] = st
            bot.send_photo(c.message.chat.id, photo=BytesIO(st["preview_bytes"]),
                caption=f"✅ <b>Предпросмотр</b>\n\n✏️ <b>Напиши СЛОВО для выделения цветом</b>\n(или «-» чтобы пропустить):",
                parse_mode="HTML")
        except Exception as e:
            send_message_with_retry(c.message.chat.id, f"❌ Ошибка: {e}")
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("am2_color:"))
def on_am2_color_select(c):
    uid = c.from_user.id
    color_key = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    if color_key == "none":
        st["highlight_word"] = ""
        st["highlight_color"] = None
        st["is_yellow"] = False
        bot.answer_callback_query(c.id, "Без выделения ✅")
    else:
        st["highlight_word"] = st.get("temp_highlight_word", "")
        st["highlight_color"] = HIGHLIGHT_COLORS.get(color_key)
        st["is_yellow"] = (color_key == "yellow")
        color_names = {"red": "красный", "yellow": "желтый", "blue": "голубой"}
        bot.answer_callback_query(c.id, f"Выбран {color_names.get(color_key)} цвет ✅")
    st["step"] = "waiting_rubric_am2"
    user_state[uid] = st
    send_message_with_retry(c.message.chat.id, f"✏️ <b>Введи РУБРИКУ</b>:", parse_mode="HTML")
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("text_pos:") or c.data.startswith("square_pos:"))
def on_text_position(c):
    uid = c.from_user.id
    parts = c.data.split(":", 1)
    prefix = parts[0]
    position = parts[1]
    is_square = (prefix == "square_pos")
    st = user_state.get(uid) or {}
    st["text_position"] = position
    st["step"] = "waiting_photo" if not st.get("photo_bytes") else "waiting_title"
    user_state[uid] = st
    position_text = "сверху" if position == "top" else "снизу"
    
    if st.get("photo_bytes"):
        # Фото уже есть из репоста
        bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")
        default_text = f"\n\n💡 <i>Используй текст из репоста (напиши «+» чтобы использовать его):</i>\n\n{st.get('original_text', '')[:300]}..." if st.get("original_text") else ""
        send_message_with_retry(c.message.chat.id, f"Текст будет расположен <b>{position_text}</b> фотографии.\n\n📸 Фото из репоста уже есть!{default_text}\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b> (или «+» чтобы использовать текст из репоста):", parse_mode="HTML")
    else:
        size_text = "квадратное " if is_square else ""
        send_message_with_retry(c.message.chat.id, f"Текст будет расположен <b>{position_text}</b> фотографии.\n\nТеперь пришли {size_text}фото 📷", parse_mode="HTML")
        bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")

@bot.callback_query_handler(func=lambda c: c.data.startswith("font_size:") or c.data.startswith("square_font:"))
def on_font_size_adjust(c):
    uid = c.from_user.id
    parts = c.data.split(":")
    prefix = parts[0]
    action = parts[1]
    is_square = (prefix == "square_font")
    st = user_state.get(uid) or {}
    if action == "done":
        st["step"] = "waiting_text_position"
        user_state[uid] = st
        send_message_with_retry(c.message.chat.id, "✅ Размер шрифта настроен. Теперь выбери расположение текста:", reply_markup=text_position_kb(is_square))
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
    template_name = "квадратного МН 2" if is_square else "МН 2"
    send_message_with_retry(c.message.chat.id, f"🔤 Настройка размера шрифта для {template_name}\n\nТекущий размер: {int(new_mult*100)}%\nИспользуй кнопки + и - для регулировки.\nНажми «Готово» когда закончишь.", reply_markup=font_size_kb(new_mult, is_square))
    bot.answer_callback_query(c.id)

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
        send_message_with_retry(c.message.chat.id, "⏳ Отправляю текст на обработку в DeepSeek AI... Это может занять до 30 секунд.")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("original_text", "")
            if not original_text:
                send_message_with_retry(c.message.chat.id, "❌ Нет текста для обработки. Попробуй ещё раз.")
                return
            
            result = loop.run_until_complete(process_text_with_deepseek(original_text))
            st["ai_processed_text"] = result
            st["original_text"] = result  # Обновляем текст на обработанный
            st["step"] = "waiting_after_ai"
            user_state[uid] = st
            
            send_message_with_retry(c.message.chat.id, f"✍️ <b>Текст обработан ИИ:</b>\n\n{result}\n\nЧто дальше? (Фото из репоста сохранено!)", parse_mode="HTML", reply_markup=after_ai_kb())
        except Exception as e:
            logger.error(f"AI processing error: {e}")
            send_message_with_retry(c.message.chat.id, f"❌ Ошибка при обработке ИИ: {e}")
        finally:
            loop.close()
            
    elif action == "watermark":
        if st.get("photo_bytes"):
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, f"💧 <b>Выбери тип водяного знака:</b>\n\n📸 Фото из репоста будет использовано автоматически!", parse_mode="HTML", reply_markup=watermark_type_kb())
        else:
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>\n\n⚠️ В репосте не найдено фото. Отправь фото отдельно.", parse_mode="HTML", reply_markup=watermark_type_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("ai:"))
def on_ai_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "design":
        st["step"] = "waiting_template"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Выбери шаблон для оформления ✅")
        send_message_with_retry(c.message.chat.id, "📝 Выбери шаблон оформления. Фото и обработанный ИИ текст будут использованы автоматически! 🎉", reply_markup=template_kb())
    else:
        clear_state(uid)
        bot.answer_callback_query(c.id, "Отменено")
        send_message_with_retry(c.message.chat.id, "❌ Отменено", reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("select_channel:"))
def on_select_channel(c):
    uid = c.from_user.id
    channel_type = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    if channel_type == "cancel":
        bot.answer_callback_query(c.id, "Отменено")
        send_message_with_retry(c.message.chat.id, "❌ Публикация отменена", reply_markup=main_menu_kb())
        return
    target_channel = CHANNEL_MN if channel_type == "mn" else CHANNEL_CHP
    channel_name = "MINSK NEWS" if channel_type == "mn" else "Минск ЧП"
    if not target_channel:
        bot.answer_callback_query(c.id, f"❌ Канал {channel_name} не настроен")
        send_message_with_retry(c.message.chat.id, f"❌ Канал {channel_name} не настроен. Добавьте переменную окружения.", reply_markup=main_menu_kb())
        return
    try:
        if st.get("card_bytes"):
            caption, kb = build_caption_with_buttons(st.get("title", ""), st.get("body_raw", ""), channel_type)
            bot.send_photo(target_channel, BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=kb)
            bot.answer_callback_query(c.id, f"Опубликовано в {channel_name} ✅")
            send_message_with_retry(c.message.chat.id, f"✅ Пост опубликован в канале {channel_name}!", reply_markup=main_menu_kb())
        else:
            bot.answer_callback_query(c.id, "Ошибка: нет сохранённого поста")
    except Exception as e:
        logger.error(f"Error publishing to channel: {e}")
        bot.answer_callback_query(c.id, "Ошибка публикации")
        send_message_with_retry(c.message.chat.id, f"❌ Не удалось опубликовать: {e}", reply_markup=main_menu_kb())
    clear_state(uid)

@bot.callback_query_handler(func=lambda c: c.data == "publish_to_channel")
def on_publish_to_channel(c):
    uid = c.from_user.id
    st = user_state.get(uid) or {}
    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(c.id, "Нет активного поста. Начни с «Оформить пост».")
        return
    if not CHANNEL_MN and not CHANNEL_CHP:
        bot.answer_callback_query(c.id, "❌ Каналы не настроены")
        send_message_with_retry(c.message.chat.id, "❌ Ни один канал для публикации не настроен.", reply_markup=main_menu_kb())
        return
    bot.answer_callback_query(c.id, "Выбери канал для публикации")
    send_message_with_retry(c.message.chat.id, "📢 <b>Выбери канал для публикации:</b>", parse_mode="HTML", reply_markup=channel_selection_kb())

@bot.callback_query_handler(func=lambda c: c.data in ["publish", "edit_text", "cancel"])
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
            elif st.get("template") == "AM2":
                caption = build_caption_html(st["title"], st.get("body_raw", ""))
            else:
                caption = build_caption_html(st.get("title", ""), st.get("body_raw", ""))
            bot.send_photo(CHANNEL, BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=channel_kb())
            bot.answer_callback_query(call.id, "Опубликовано ✅")
            send_message_with_retry(call.message.chat.id, "Готово ✅", reply_markup=main_menu_kb())
            clear_state(uid)
        except Exception as e:
            logger.error(f"Error publishing: {e}")
            bot.answer_callback_query(call.id, "Ошибка публикации")
            send_message_with_retry(call.message.chat.id, f"Не смог опубликовать: {e}", reply_markup=main_menu_kb())
    elif call.data == "edit_text":
        st["step"] = "waiting_title"
        user_state[uid] = st
        bot.answer_callback_query(call.id, "Ок")
        send_message_with_retry(call.message.chat.id, "Пришли новый ЗАГОЛОВОК.", reply_markup=main_menu_kb())
    elif call.data == "cancel":
        bot.answer_callback_query(call.id, "Отменено")
        clear_state(uid)
        send_message_with_retry(call.message.chat.id, "Отменил ❌", reply_markup=main_menu_kb())


# =========================
# Обработчик текста
# =========================
@bot.message_handler(content_types=["text"])
def on_text(message):
    uid = message.from_user.id
    text = message.text.strip() if message.text else ""
    st = user_state.get(uid) or {"template": "MN", "step": "idle"}
    
    # Обработка команд меню
    if text == BTN_POST:
        cmd_post(message)
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
    if text == BTN_AI_TEXT:
        cmd_ai_text(message)
        return
    
    # Обработка ссылок на Telegram посты
    tme_match = re.search(r'(?:https?://)?t\.me/([^/]+)/(\d+)', text)
    if tme_match and not message.forward_from_chat:
        username = tme_match.group(1)
        post_id = tme_match.group(2)
        st["original_url"] = text
        st["original_text"] = text  # Сохраняем текст ссылки
        st["step"] = "waiting_repost_action"
        user_state[uid] = st
        
        send_message_with_retry(
            message.chat.id,
            f"📎 <b>Ссылка на пост обнаружена!</b>\n\n🔗 t.me/{username}/{post_id}\n\n<b>Что сделать с этим постом?</b>\n\n⚠️ Для наилучшего результата, перешлите сам пост в чат с ботом (вместе с фото).",
            parse_mode="HTML",
            reply_markup=repost_action_kb()
        )
        return
    
    step = st.get("step")
    
    # Обработка AI текста
    if step == "waiting_ai_text":
        processing_msg = bot.reply_to(message, "🤖 Обрабатываю текст в ИИ... Это может занять до 30 секунд.")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_text_with_deepseek(text))
            bot.delete_message(message.chat.id, processing_msg.message_id)
            send_message_with_retry(message.chat.id, f"✍️ <b>Результат обработки:</b>\n\n{result}", parse_mode="HTML", reply_markup=main_menu_kb())
        except Exception as e:
            bot.delete_message(message.chat.id, processing_msg.message_id)
            send_message_with_retry(message.chat.id, f"❌ Ошибка при обработке: {e}", reply_markup=main_menu_kb())
        finally:
            loop.close()
        clear_state(uid)
        return
    
    # Обработка заголовка для АМ 2 с поддержкой «+» (использовать текст из репоста)
    if step == "waiting_title_am2":
        if text == "+" and st.get("original_text"):
            use_text = st["original_text"]
        elif text == "+":
            bot.reply_to(message, "❌ Нет сохранённого текста из репоста. Введи заголовок вручную.")
            return
        else:
            use_text = text
        
        if not use_text or use_text.strip() == "":
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
            
        st["title"] = use_text
        st["body_raw"] = use_text
        st["step"] = "waiting_date_place_choice_am2"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Заголовок: <b>{html.escape(use_text[:100])}</b>\n\n📅 <b>Добавить дату и место?</b>", parse_mode="HTML", reply_markup=add_date_place_kb())
        return
    
    # Обработка даты для АМ 2
    if step == "waiting_date_am2":
        st["date"] = text
        st["step"] = "waiting_place_am2"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Дата: {text}\n\n✏️ <b>Введи МЕСТО</b>:", parse_mode="HTML")
        return
    
    # Обработка места для АМ 2
    if step == "waiting_place_am2":
        st["place"] = text
        st["step"] = "waiting_highlight_word_am2"
        user_state[uid] = st
        try:
            card = create_poster_am2(st["photo_bytes"], st.get("title", ""), st.get("text_position", "top"), st.get("date", ""), st.get("place", ""), "", "", None, False)
            st["preview_bytes"] = card.getvalue()
            user_state[uid] = st
            bot.send_photo(message.chat.id, photo=BytesIO(st["preview_bytes"]), caption=f"✅ <b>Предпросмотр</b>\n\n✏️ <b>Напиши СЛОВО для выделения цветом</b>\n(или «-» чтобы пропустить):", parse_mode="HTML")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    # Обработка слова для выделения в АМ 2
    if step == "waiting_highlight_word_am2":
        if text == "-":
            st["highlight_word"] = ""
            st["highlight_color"] = None
            st["is_yellow"] = False
            st["step"] = "waiting_rubric_am2"
            user_state[uid] = st
            bot.reply_to(message, f"✏️ <b>Введи РУБРИКУ</b>:", parse_mode="HTML")
        else:
            title = st.get("title", "").lower()
            if text.lower() in title:
                st["temp_highlight_word"] = text
                st["step"] = "waiting_color_am2"
                user_state[uid] = st
                bot.reply_to(message, f"✅ Слово «{text}» <b>НАЙДЕНО</b>!\n\n🎨 <b>Выбери цвет:</b>", parse_mode="HTML", reply_markup=color_kb_am2())
            else:
                bot.reply_to(message, f"⚠️ Слово «{text}» <b>НЕ НАЙДЕНО</b>!\n\nПопробуй другое слово или «-»", parse_mode="HTML")
        return
    
    # Обработка рубрики для АМ 2
    if step == "waiting_rubric_am2":
        st["rubric"] = text
        st["step"] = "creating_am2"
        user_state[uid] = st
        try:
            card = create_poster_am2(st["photo_bytes"], st.get("title", ""), st.get("text_position", "top"), st.get("date", ""), st.get("place", ""), st.get("rubric", ""), st.get("highlight_word", ""), st.get("highlight_color"), st.get("is_yellow", False))
            st["card_bytes"] = card.getvalue()
            st["body_raw"] = f"{st.get('date', '')} {st.get('place', '')} {st.get('rubric', '')}".strip()
            st["step"] = "waiting_action"
            user_state[uid] = st
            bot.send_photo(message.chat.id, photo=BytesIO(st["card_bytes"]), caption="🎉 <b>Афиша готова!</b>\n\nНажми кнопку для публикации:", parse_mode="HTML", reply_markup=preview_kb())
        except Exception as e:
            logger.error(f"Error: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    # Обработка заголовка для МН 2
    if step == "waiting_title_mn2":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = text
        st["body_raw"] = text
        st["step"] = "waiting_bold_phrase_mn2"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n<b>{html.escape(text)}</b>\n\n✏️ Теперь отправь слова для выделения жирным (через пробел):", parse_mode="HTML")
        return
    
    # Обработка фразы для выделения жирным в МН 2
    if step == "waiting_bold_phrase_mn2":
        st["bold_phrase"] = text if text != " " else ""
        try:
            font_mult = st.get("font_size_multiplier", 1.0)
            card = make_card(st["photo_bytes"], st["title"], "MN2", text_position=st.get("text_position", TEXT_POSITION_TOP), font_size_multiplier=font_mult, is_square=st.get("is_square", False), bold_phrase=st["bold_phrase"])
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(message.chat.id, photo=BytesIO(card.getvalue()), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
        except Exception as e:
            logger.error(f"Error creating MN2 card: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    # Обработка текста для МН ТГ
    if step == "waiting_title_mn_tg":
        if text == "+" and st.get("original_text"):
            use_text = st["original_text"]
        elif text == "+":
            bot.reply_to(message, "❌ Нет сохранённого текста из репоста. Введи текст вручную.")
            return
        else:
            use_text = text
            
        if not use_text:
            bot.reply_to(message, "❌ Текст не может быть пустым")
            return
        try:
            card = make_card(st["photo_bytes"], use_text, "MN_TG", text_position=st.get("text_position", TEXT_POSITION_TOP), is_square=st.get("is_square", False))
            st["card_bytes"] = card.getvalue()
            st["full_text"] = use_text
            st["title"] = use_text.split('\n\n')[0] if '\n\n' in use_text else use_text[:100]
            st["body_raw"] = use_text
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_tg(use_text)
            bot.send_photo(message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
            bot.reply_to(message, "Превью готово ✅")
        except Exception as e:
            logger.error(f"Error creating MN_TG card: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    # Обработка заголовка для FDR_POST
    if step == "waiting_title_fdr_post":
        if text == "+" and st.get("original_text"):
            use_text = st["original_text"]
        elif text == "+":
            bot.reply_to(message, "❌ Нет сохранённого текста из репоста. Введи заголовок вручную.")
            return
        else:
            use_text = text
            
        if not use_text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = use_text
        st["body_raw"] = use_text
        st["step"] = "waiting_highlight_phrase_fdr_post"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n<b>{html.escape(use_text[:100])}</b>\n\n✏️ Теперь отправь слова для выделения цветом (через пробел):", parse_mode="HTML")
        return
    
    # Обработка фразы для выделения в FDR_POST
    if step == "waiting_highlight_phrase_fdr_post":
        st["highlight_phrase"] = text if text != " " else ""
        try:
            card = make_card(st["photo_bytes"], st["title"], "FDR_POST", highlight_phrase=st["highlight_phrase"], is_square=st.get("is_square", False))
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(message.chat.id, photo=BytesIO(card.getvalue()), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
        except Exception as e:
            logger.error(f"Error creating FDR_POST card: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    # Обработка заголовка для FDR_STORY
    if step == "waiting_title_fdr":
        if text == "+" and st.get("original_text"):
            use_text = st["original_text"]
        elif text == "+":
            bot.reply_to(message, "❌ Нет сохранённого текста из репоста. Введи заголовок вручную.")
            return
        else:
            use_text = text
            
        if not use_text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = use_text
        st["step"] = "waiting_body_fdr"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n<b>{html.escape(use_text[:100])}</b>\n\n✏️ Теперь отправь основной текст для сторис:", parse_mode="HTML")
        return
    
    # Обработка основного текста для FDR_STORY
    if step == "waiting_body_fdr":
        if text == "+" and st.get("original_text"):
            use_text = st["original_text"]
        elif text == "+":
            bot.reply_to(message, "❌ Нет сохранённого текста из репоста. Введи текст вручную.")
            return
        else:
            use_text = text
        try:
            card = make_card_fdr_story(st["photo_bytes"], st["title"], use_text)
            st["card_bytes"] = card.getvalue()
            st["body_raw"] = use_text
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
            bot.reply_to(message, "Превью готово ✅")
        except Exception as e:
            logger.error(f"Error creating FDR_STORY card: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    # Обработка обычного заголовка
    if step == "waiting_title":
        if text == "+" and st.get("original_text"):
            use_text = st["original_text"]
        elif text == "+":
            bot.reply_to(message, "❌ Нет сохранённого текста из репоста. Введи заголовок вручную.")
            return
        else:
            use_text = text
            
        if not use_text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = use_text
        st["body_raw"] = use_text
        try:
            font_mult = st.get("font_size_multiplier", 1.0) if st.get("template") == "MN2" else 1.0
            card = make_card(st["photo_bytes"], st["title"], st.get("template", "MN"), text_position=st.get("text_position", TEXT_POSITION_TOP), font_size_multiplier=font_mult, is_square=st.get("is_square", False), bold_phrase=st.get("bold_phrase", ""), date=st.get("date", ""), place=st.get("place", ""), rubric=st.get("rubric", ""), highlight_word=st.get("highlight_word", ""), highlight_color=st.get("highlight_color"), is_yellow=st.get("is_yellow", False))
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(message.chat.id, photo=BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
            bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")
        except Exception as e:
            logger.error(f"Error creating card: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    if step == "waiting_action":
        bot.reply_to(message, "Нажми кнопку под превью ✅✏️❌", reply_markup=main_menu_kb())
    elif step == "waiting_template":
        bot.send_message(message.chat.id, "Выбери шаблон кнопками:", reply_markup=template_kb())
    elif step == "waiting_text_position":
        bot.send_message(message.chat.id, "Сначала выбери расположение текста:", reply_markup=text_position_kb())
    else:
        user_state[uid] = st
        send_message_with_retry(message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())


# =========================
# Обработчик пересылаемых сообщений (репостов)
# =========================
@bot.message_handler(content_types=["text", "photo"], func=lambda message: message.forward_from_chat is not None or (message.forward_from is not None))
def handle_forwarded_message(message):
    uid = message.from_user.id
    
    # Получаем текст из пересланного сообщения
    original_text = ""
    if message.text:
        original_text = message.text
    elif message.caption:
        original_text = message.caption
    
    # Получаем информацию об источнике
    source_info = ""
    source_url = ""
    if message.forward_from_chat:
        channel = message.forward_from_chat
        source_info = f"@{channel.username}" if channel.username else channel.title
        if channel.username:
            source_url = f"https://t.me/{channel.username}"
    elif message.forward_from:
        user = message.forward_from
        source_info = f"@{user.username}" if user.username else f"{user.first_name}"
    
    # Сохраняем в состояние
    st = user_state.get(uid) or {}
    st["original_text"] = original_text
    st["original_url"] = source_url
    st["repost_type"] = "forward"
    st["step"] = "waiting_repost_action"
    st["photo_bytes"] = None  # Сбросим перед сохранением нового фото
    
    # Если есть фото в пересланном сообщении
    if message.photo:
        try:
            file_id = message.photo[-1].file_id
            photo_bytes = tg_file_bytes(file_id)
            if check_file_size(photo_bytes):
                st["photo_bytes"] = photo_bytes
                logger.info(f"Saved photo from forward for user {uid}, size: {len(photo_bytes)} bytes")
        except Exception as e:
            logger.error(f"Error extracting photo from forward: {e}")
    
    user_state[uid] = st
    
    text_preview = original_text[:200] if original_text else "(без текста)"
    source_text = f"📢 <b>Источник:</b> {source_info}\n" if source_info else ""
    photo_status = "✅ <b>Фото:</b> сохранено\n" if st["photo_bytes"] else "⚠️ <b>Фото:</b> не найдено в репосте\n"
    
    send_message_with_retry(
        message.chat.id,
        f"📎 <b>Пересланный пост обнаружен!</b>\n\n{source_text}{photo_status}📝 <b>Текст:</b> {text_preview}...\n\n<b>Что сделать с этим постом?</b>",
        parse_mode="HTML",
        reply_markup=repost_action_kb()
    )


# =========================
# Обработчик фото и документов (для ручной загрузки, если нет фото в репосте)
# =========================
@bot.message_handler(content_types=["photo", "document"])
def on_photo_or_document(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    
    # Если это ответ на улучшение качества
    if st.get("step") == "waiting_enhance_photo":
        try:
            file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимум 20MB.")
                return
            processing_msg = bot.reply_to(message, "⏳ Улучшаю качество...")
            enhanced = enhance_image_simple(photo_bytes)
            bot.send_document(message.chat.id, document=enhanced, visible_file_name="enhanced_photo.jpg", caption="✨ Фото улучшено!\n\n• Резкость +20%\n• Насыщенность +15%")
            bot.delete_message(message.chat.id, processing_msg.message_id)
            clear_state(uid)
            return
        except Exception as e:
            logger.error(f"Error enhancing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка при улучшении: {e}")
            return
    
    # Если это ответ на водяной знак
    if st.get("step") == "waiting_watermark_photo":
        try:
            file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимум 20MB.")
                return
            processing_msg = bot.reply_to(message, "⏳ Наношу водяной знак...")
            wm_type = st.get("watermark_type", "mn")
            if wm_type == "mn":
                result = apply_watermark_mn(photo_bytes)
                caption = "💧 Водяной знак <b>MINSK NEWS</b> нанесён!"
            else:
                result = apply_watermark_chp(photo_bytes)
                caption = "💧 Водяной знак <b>ЧП Минск</b> нанесён!"
            bot.send_document(message.chat.id, document=result, visible_file_name=f"watermark_{wm_type}.jpg", caption=caption, parse_mode="HTML")
            bot.delete_message(message.chat.id, processing_msg.message_id)
            clear_state(uid)
            return
        except Exception as e:
            logger.error(f"Error applying watermark: {e}")
            bot.reply_to(message, f"❌ Ошибка при нанесении водяного знака: {e}")
            return
    
    # Обработка фото для АМ 2 (если нет фото в репосте)
    if st.get("step") == "waiting_photo_am2":
        try:
            file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return
            st["photo_bytes"] = photo_bytes
            st["step"] = "waiting_text_position_am2"
            user_state[uid] = st
            bot.reply_to(message, "📸 Фото сохранено!\n\n📐 <b>Выбери расположение текста:</b>", parse_mode="HTML", reply_markup=text_position_kb_am2())
            return
        except Exception as e:
            logger.error(f"Error processing photo for AM2: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return
    
    # Обработка фото для Пост ФДР (если нет фото в репосте)
    if st.get("step") == "waiting_photo_fdr_post":
        try:
            file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return
            st["photo_bytes"] = photo_bytes
            st["step"] = "waiting_title_fdr_post"
            user_state[uid] = st
            default_text = f"\n\n💡 <i>Используй текст из репоста (напиши «+» чтобы использовать его):</i>\n\n{st.get('original_text', '')[:200]}..." if st.get("original_text") else ""
            bot.reply_to(message, f"📸 Фото сохранено!{default_text}\n\nТеперь отправь <b>ЗАГОЛОВОК</b> поста (или «+» чтобы использовать текст из репоста):", parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error processing photo for FDR_POST: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return
    
    # Обработка фото для Сторис ФДР (если нет фото в репосте)
    if st.get("step") == "waiting_photo_fdr_story":
        try:
            file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return
            st["photo_bytes"] = photo_bytes
            st["step"] = "waiting_title_fdr"
            user_state[uid] = st
            default_text = f"\n\n💡 <i>Используй текст из репоста (напиши «+» чтобы использовать его):</i>\n\n{st.get('original_text', '')[:200]}..." if st.get("original_text") else ""
            bot.reply_to(message, f"📸 Фото сохранено!{default_text}\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для сторис:", parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error processing photo for FDR_STORY: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return
    
    # Основная обработка фото (если нет фото в репосте)
    if st.get("step") == "waiting_photo":
        try:
            file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return
            st["photo_bytes"] = photo_bytes
            is_square = st.get("is_square", False)
            
            if st.get("template") == "MN2":
                st["step"] = "waiting_title_mn2"
                user_state[uid] = st
                size_text = "квадратное " if is_square else ""
                bot.reply_to(message, f"📸 {size_text}Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
            elif st.get("template") == "MN_TG":
                st["step"] = "waiting_title_mn_tg"
                user_state[uid] = st
                size_text = "квадратное " if is_square else ""
                default_text = f"\n\n💡 <i>Используй текст из репоста (напиши «+» чтобы использовать его):</i>\n\n{st.get('original_text', '')[:200]}..." if st.get("original_text") else ""
                bot.reply_to(message, f"📸 {size_text}Фото сохранено!{default_text}\n\nТеперь отправь <b>ТЕКСТ</b> для поста (первый абзац станет заголовком):", parse_mode="HTML")
            else:
                st["step"] = "waiting_title"
                user_state[uid] = st
                size_text = "квадратное " if is_square else ""
                default_text = f"\n\n💡 <i>Используй текст из репоста (напиши «+» чтобы использовать его):</i>\n\n{st.get('original_text', '')[:200]}..." if st.get("original_text") else ""
                bot.reply_to(message, f"📸 {size_text}Фото сохранено!{default_text}\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
            return
        except Exception as e:
            logger.error(f"Error processing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return
    
    bot.reply_to(message, "Не знаю, что делать с этим фото. Нажми «Оформить пост» или выбери другое действие в меню.")


# =========================
# Message handlers для команд
# =========================
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    clear_state(message.from_user.id)
    send_message_with_retry(
        message.chat.id,
        "👋 <b>Привет! Я бот для оформления постов</b>\n\n"
        "<b>📝 Основные функции:</b>\n"
        "• 📝 Оформление постов с фото (7 шаблонов, включая Квадраты)\n"
        "• ✨ Улучшение качества фото (+20% резкость, +15% насыщенность)\n"
        "• 💧 Водяные знаки - нанеси \"MINSK NEWS\" или \"ЧП Минск\" на фото\n"
        "• 🤖 Текст в ИИ - отправь текст, ИИ сократит его до 650 символов\n"
        "• 💰 Цены и условия размещения\n"
        "• 📎 Репосты из каналов - отправь ссылку на пост или перешли его\n\n"
        "<b>📌 Как использовать репосты:</b>\n"
        "1️⃣ Перешли любой пост из Telegram канала в этот чат\n"
        "2️⃣ Или отправь ссылку на пост (например, https://t.me/channel/123)\n"
        "3️⃣ Бот автоматически сохранит текст и фото из репоста\n"
        "4️⃣ Выбери действие: оформить по шаблону, обработать ИИ или нанести водяной знак\n"
        "5️⃣ При оформлении бот предложит использовать сохранённые данные (напиши «+»)\n\n"
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
    send_message_with_retry(message.chat.id, "📝 Выбери шаблон оформления:", reply_markup=template_kb())

@bot.message_handler(commands=["enhance"])
def cmd_enhance(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_enhance_photo"
    user_state[uid] = st
    send_message_with_retry(message.chat.id, "✨ <b>Улучшение качества фото</b>\n\nОтправь фото, и я увеличу резкость на +20% и насыщенность на +15%", parse_mode="HTML", reply_markup=main_menu_kb())

@bot.message_handler(commands=["watermark"])
def cmd_watermark(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_watermark_type"
    user_state[uid] = st
    send_message_with_retry(message.chat.id, "💧 <b>Водяные знаки</b>\n\nВыбери тип водяного знака:", parse_mode="HTML", reply_markup=watermark_type_kb())

@bot.message_handler(commands=["prices"])
def cmd_prices(message):
    send_message_with_retry(message.chat.id, "💰 <b>Цены и условия размещения</b>\n\nВыбери интересующий раздел:", parse_mode="HTML", reply_markup=prices_menu_kb())

@bot.message_handler(commands=["ai_text"])
def cmd_ai_text(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_ai_text"
    user_state[uid] = st
    send_message_with_retry(message.chat.id, "🤖 <b>Текст в ИИ</b>\n\nОтправь текст новости, и я сокращу его до 650 символов.\n\n<i>Обработка может занять до 30 секунд...</i>", parse_mode="HTML", reply_markup=main_menu_kb())

@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    clear_state(message.from_user.id)
    send_message_with_retry(message.chat.id, "🛑 Бот сброшен в исходное состояние.", reply_markup=main_menu_kb())

@bot.message_handler(func=lambda message: message.text == BTN_POST)
def handle_post_button(message):
    cmd_post(message)

@bot.message_handler(func=lambda message: message.text == BTN_ENHANCE)
def handle_enhance_button(message):
    cmd_enhance(message)

@bot.message_handler(func=lambda message: message.text == BTN_WATERMARK)
def handle_watermark_button(message):
    cmd_watermark(message)

@bot.message_handler(func=lambda message: message.text == BTN_PRICES)
def handle_prices_button(message):
    cmd_prices(message)

@bot.message_handler(func=lambda message: message.text == BTN_AI_TEXT)
def handle_ai_text_button(message):
    cmd_ai_text(message)


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
        
        http_thread = threading.Thread(target=run_http_server, daemon=True)
        http_thread.start()
        logger.info("🌐 Health check server thread started")
        
        logger.info("🤖 Bot started polling...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        try:
            if os.path.exists(lock_file):
                os.unlink(lock_file)
        except:
            pass
        raise
