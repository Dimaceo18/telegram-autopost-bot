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

# Импорты для DeepSeek AI
import httpx

# =========================
# Проверка на единственный экземпляр - УЛУЧШЕННАЯ ВЕРСИЯ
# =========================
lock_file = '/tmp/bot_instance.lock'
lock_fd = None

# DeepSeek API
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

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
        logger.error(f"Error checking single instance: {e}")
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

if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN must not contain spaces")
if not CHANNEL or CHANNEL == "@":
    raise RuntimeError("CHANNEL_USERNAME is not set")

if not SUGGEST_URL and BOT_USERNAME:
    SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"

# Constants
MAX_FILE_SIZE = 20 * 1024 * 1024
REQUEST_TIMEOUT = 15

# Размеры афиши (изменены на 720x900)
TARGET_W = 720
TARGET_H = 900

# Шрифты
FONT_PATH = "Inter-ExtraBold.ttf"
FONT_FALLBACK = "Montserrat-Black.ttf"
FONT_REGULAR = "Inter-Regular.ttf"

# Размеры шрифта
FONT_SIZE_TITLE = 60
FONT_SIZE_MIN = 24
FONT_SIZE_DATE_PLACE = 24
FONT_SIZE_RUBRIC = 30

# Затемнение фото
BRIGHTNESS_FACTOR = 0.85

# Градиент
GRADIENT_HEIGHT_PCT = 0.48
GRADIENT_MAX_ALPHA = 220

# Отступы
MARGIN_TOP_PCT = 0.15
TEXT_MAX_WIDTH_PCT = 0.80
LINE_SPACING_RATIO = 0.22

# Отступ для даты и места
DATE_PLACE_BOTTOM_MARGIN = 180
DATE_PLACE_TOP_MARGIN = 130
DATE_PLACE_LINE_SPACING = 15
DATE_PLACE_LEFT_MARGIN = 45

# Скругленный прямоугольник для рубрики
RUBRIC_TOP_MARGIN = 40
RUBRIC_PADDING = 20
RUBRIC_RADIUS = 25

# Скругленный прямоугольник для даты и места
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

user_state: Dict[int, Dict] = {}

# =========================
# UI BUTTONS - НОВОЕ МЕНЮ (убраны новости, видео, гиф)
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

def prices_menu_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💰 Наши цены", callback_data="prices:list"),
        InlineKeyboardButton("📋 Условия размещения", callback_data="prices:terms"),
        InlineKeyboardButton("📊 График аккаунтов", callback_data="prices:schedule")
    )
    kb.add(InlineKeyboardButton("❌ Закрыть", callback_data="prices:close"))
    return kb

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
        kb.row(InlineKeyboardButton("◀️ Назад к оформлению", callback_data="square:back"))
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
            InlineKeyboardButton("🆕 МН 2", callback_data=f"{prefix}MN2"),
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

def watermark_type_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📰 МН", callback_data="watermark:mn"),
        InlineKeyboardButton("🚨 ЧП", callback_data="watermark:chp")
    )
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="watermark:cancel"))
    return kb

def preview_kb(source_url: str = ""):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("✏️ Редактировать текст", callback_data="edit_body"),
        InlineKeyboardButton("✏️ Редактировать заголовок", callback_data="edit_title"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel")
    )
    if source_url:
        kb.add(InlineKeyboardButton("🔗 Источник", url=source_url))
    return kb

def channel_kb():
    kb = InlineKeyboardMarkup()
    if SUGGEST_URL:
        kb.add(InlineKeyboardButton("📝 Предложить новость", url=SUGGEST_URL))
    return kb

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
        logger.info(f"Cleared state for user {user_id}")

def ensure_fonts():
    fonts = [FONT_PATH, FONT_FALLBACK, FONT_REGULAR]
    for font in fonts:
        if not os.path.exists(font):
            logger.warning(f"Font not found: {font}")

def download_fonts():
    fonts = {
        "Inter-ExtraBold.ttf": "https://github.com/rsms/inter/raw/master/docs/fonts/Inter-ExtraBold.otf",
        "Inter-Regular.ttf": "https://github.com/rsms/inter/raw/master/docs/fonts/Inter-Regular.otf",
        "Montserrat-Black.ttf": "https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat-Black.ttf"
    }
    
    for font_name, url in fonts.items():
        if not os.path.exists(font_name):
            try:
                logger.info(f"Downloading {font_name}...")
                response = requests.get(url, timeout=30)
                with open(font_name, "wb") as f:
                    f.write(response.content)
                logger.info(f"Downloaded {font_name}")
            except Exception as e:
                logger.error(f"Failed to download {font_name}: {e}")

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
                          max_lines: int = 6, start_size: int = 60, min_size: int = 16,
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

def apply_top_gradient(img: Image.Image, height_pct: float, max_alpha: int = 220) -> Image.Image:
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

def apply_top_blur_band(img: Image.Image, band_pct: float = 0.20, radius: int = 18, blend: float = 0.50) -> Image.Image:
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

def draw_highlighted_text(draw, text: str, highlight_word: str, color, font, x, y):
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

def draw_rounded_rect_with_text(draw, text: str, bg_color, text_color, x: int, y: int, padding: int, radius: int):
    if not text:
        return y
    
    font = load_font(FONT_REGULAR, FONT_SIZE_DATE_PLACE)
    text_upper = text.upper()
    
    text_w = draw.textlength(text_upper, font=font)
    bbox = draw.textbbox((0, 0), text_upper, font=font)
    text_h = bbox[3] - bbox[1]
    
    rect_w = int(text_w + padding * 2)
    rect_h = int(text_h + padding * 2)
    
    draw.rounded_rectangle(
        [x, y, x + rect_w, y + rect_h],
        radius=radius,
        fill=bg_color
    )
    
    text_x = x + (rect_w - text_w) / 2
    text_y = y + (rect_h - text_h) / 2 - bbox[1]
    draw.text((text_x, text_y), text_upper, font=font, fill=text_color)
    
    return y + rect_h + DATE_PLACE_LINE_SPACING

def draw_rubric_top_center(draw, rubric: str, highlight_color, is_yellow: bool):
    if not rubric:
        return 0
    
    font_rubric = load_font(FONT_PATH, FONT_SIZE_RUBRIC)
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
    
    draw.rounded_rectangle(
        [rect_x, rect_y, rect_x + rect_w, rect_y + rect_h],
        radius=RUBRIC_RADIUS,
        fill=bg_color
    )
    
    text_x = rect_x + (rect_w - text_w) / 2
    text_y = rect_y + (rect_h - text_h) / 2 - bbox[1]
    draw.text((text_x, text_y), rubric_text, font=font_rubric, fill=text_color)
    
    return rect_y + rect_h

def create_poster(image_bytes: bytes, title_text: str, text_position: str,
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
        img = apply_top_gradient(img, GRADIENT_HEIGHT_PCT, GRADIENT_MAX_ALPHA)
    else:
        img = apply_bottom_gradient(img, GRADIENT_HEIGHT_PCT, GRADIENT_MAX_ALPHA)
    
    draw = ImageDraw.Draw(img)
    
    rubric_bottom = 0
    if rubric:
        rubric_bottom = draw_rubric_top_center(draw, rubric, highlight_color, is_yellow)
    
    margin_top = int(TARGET_H * MARGIN_TOP_PCT)
    if rubric_bottom > 0:
        margin_top = rubric_bottom + 40
    else:
        margin_top = 130
    
    max_text_width = int(TARGET_W * TEXT_MAX_WIDTH_PCT)
    
    text = (title_text or "").strip().upper()
    title_max_h = int(TARGET_H * 0.23)
    
    font, lines, heights, spacing, total_h = fit_text_block_center(
        draw=draw,
        text=text,
        font_path=FONT_PATH,
        safe_w=max_text_width,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(TARGET_H * 0.11),
        min_size=FONT_SIZE_MIN,
        line_spacing_ratio=LINE_SPACING_RATIO
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
            draw_highlighted_text(draw, ln, highlight_word, highlight_color, font, x, y)
            y += heights[i] + spacing
        
        if date or place:
            date_place_y = TARGET_H - DATE_PLACE_BOTTOM_MARGIN
            if date:
                date_place_y = draw_rounded_rect_with_text(
                    draw, f"ДАТА: {date}", highlight_color, date_place_text_color,
                    DATE_PLACE_LEFT_MARGIN, date_place_y,
                    DATE_PLACE_PADDING, DATE_PLACE_RADIUS
                )
            if place:
                draw_rounded_rect_with_text(
                    draw, f"МЕСТО: {place}", highlight_color, date_place_text_color,
                    DATE_PLACE_LEFT_MARGIN, date_place_y,
                    DATE_PLACE_PADDING, DATE_PLACE_RADIUS
                )
    
    else:
        date_place_y = DATE_PLACE_TOP_MARGIN
        if date or place:
            if date:
                date_place_y = draw_rounded_rect_with_text(
                    draw, f"ДАТА: {date}", highlight_color, date_place_text_color,
                    DATE_PLACE_LEFT_MARGIN, date_place_y,
                    DATE_PLACE_PADDING, DATE_PLACE_RADIUS
                )
            if place:
                draw_rounded_rect_with_text(
                    draw, f"МЕСТО: {place}", highlight_color, date_place_text_color,
                    DATE_PLACE_LEFT_MARGIN, date_place_y,
                    DATE_PLACE_PADDING, DATE_PLACE_RADIUS
                )
            y = date_place_y + 65
        else:
            y = margin_top
        
        for i, ln in enumerate(lines):
            line_w = text_width(draw, ln, font)
            x = (TARGET_W - line_w) // 2
            draw_highlighted_text(draw, ln, highlight_word, highlight_color, font, x, y)
            y += heights[i] + spacing
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0)
    out.seek(0)
    return out

# Шаблон АМ 2 (как в "создать афишу")
def create_poster_am2(image_bytes: bytes, title_text: str, date: str = "", place: str = "", 
                      rubric: str = "", highlight_word: str = "", highlight_color: tuple = None, 
                      is_yellow: bool = False) -> BytesIO:
    
    if highlight_color is None:
        highlight_color = HIGHLIGHT_COLORS["yellow"]
        is_yellow = True
    
    img = Image.open(BytesIO(image_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    
    img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS_FACTOR)
    img = apply_top_gradient(img, GRADIENT_HEIGHT_PCT, GRADIENT_MAX_ALPHA)
    
    draw = ImageDraw.Draw(img)
    
    rubric_bottom = 0
    if rubric:
        rubric_bottom = draw_rubric_top_center(draw, rubric, highlight_color, is_yellow)
    
    margin_top = int(TARGET_H * 0.18)
    if rubric_bottom > 0:
        margin_top = rubric_bottom + 50
    
    max_text_width = int(TARGET_W * TEXT_MAX_WIDTH_PCT)
    
    text = (title_text or "").strip().upper()
    title_max_h = int(TARGET_H * 0.25)
    
    font, lines, heights, spacing, total_h = fit_text_block_center(
        draw=draw,
        text=text,
        font_path=FONT_PATH,
        safe_w=max_text_width,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(TARGET_H * 0.09),
        min_size=FONT_SIZE_MIN,
        line_spacing_ratio=LINE_SPACING_RATIO
    )
    
    if is_yellow:
        date_place_text_color = BLACK
    else:
        date_place_text_color = WHITE
    
    y = margin_top
    for i, ln in enumerate(lines):
        line_w = text_width(draw, ln, font)
        x = (TARGET_W - line_w) // 2
        draw_highlighted_text(draw, ln, highlight_word, highlight_color, font, x, y)
        y += heights[i] + spacing
    
    if date or place:
        date_place_y = TARGET_H - DATE_PLACE_BOTTOM_MARGIN
        if date:
            date_place_y = draw_rounded_rect_with_text(
                draw, f"ДАТА: {date}", highlight_color, date_place_text_color,
                DATE_PLACE_LEFT_MARGIN, date_place_y,
                DATE_PLACE_PADDING, DATE_PLACE_RADIUS
            )
        if place:
            draw_rounded_rect_with_text(
                draw, f"МЕСТО: {place}", highlight_color, date_place_text_color,
                DATE_PLACE_LEFT_MARGIN, date_place_y,
                DATE_PLACE_PADDING, DATE_PLACE_RADIUS
            )
    
    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0)
    out.seek(0)
    return out

# =========================
# Функции для шаблонов
# =========================
def make_card_mn(photo_bytes: bytes, title_text: str, text_position: str = "top", is_square: bool = False) -> BytesIO:
    if is_square:
        img = Image.open(BytesIO(photo_bytes)).convert("RGB")
        img = crop_to_square(img)
        img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
        img = ImageEnhance.Brightness(img).enhance(0.55)
        
        draw = ImageDraw.Draw(img)
        margin_x = int(img.width * 0.06)
        margin_top = int(img.height * 0.06)
        margin_bottom = int(img.height * 0.07)
        safe_w = img.width - 2 * margin_x
        
        title_max_h = int(img.height * 0.23)
        text = (title_text or "").strip().upper()
        
        font, lines, heights, spacing, total_h = fit_text_block_center(
            draw=draw, text=text, font_path=FONT_PATH,
            safe_w=safe_w, max_block_h=title_max_h,
            max_lines=6, start_size=int(img.height * 0.11),
            min_size=16, line_spacing_ratio=0.22
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
        return create_poster(photo_bytes, title_text, text_position)

def make_card_mn2(photo_bytes: bytes, title_text: str, text_position: str = "top", 
                  font_size_multiplier: float = 1.0, is_square: bool = False) -> BytesIO:
    if is_square:
        img = Image.open(BytesIO(photo_bytes)).convert("RGB")
        img = crop_to_square(img)
        img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
        img = ImageEnhance.Brightness(img).enhance(0.55)
        
        draw = ImageDraw.Draw(img)
        margin_x = int(img.width * 0.06)
        margin_top = int(img.height * 0.06)
        safe_w = img.width - 2 * margin_x
        
        title_max_h = int(img.height * 0.23)
        text = (title_text or "").strip().upper()
        
        start_size = int(int(img.height * 0.11) * font_size_multiplier)
        
        font, lines, heights, spacing, total_h = fit_text_block_center(
            draw=draw, text=text, font_path=FONT_PATH,
            safe_w=safe_w, max_block_h=title_max_h,
            max_lines=6, start_size=start_size,
            min_size=16, line_spacing_ratio=0.25
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
        return create_poster(photo_bytes, title_text, text_position)

def make_card_chp(photo_bytes: bytes, title_text: str, text_position: str = "top", is_square: bool = False) -> BytesIO:
    return create_poster(photo_bytes, title_text, text_position)

def make_card_am(photo_bytes: bytes, title_text: str, is_square: bool = False) -> BytesIO:
    if is_square:
        img = Image.open(BytesIO(photo_bytes)).convert("RGB")
        img = crop_to_square(img)
        img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
        img = apply_top_blur_band(img)
        
        draw = ImageDraw.Draw(img)
        margin_x = int(img.width * 0.06)
        band_h = int(img.height * 0.20)
        safe_w = img.width - 2 * margin_x
        text = (title_text or "").strip().upper()
        
        text_zone_top = int(band_h * 0.12)
        text_zone_bottom = int(band_h * 0.12)
        text_zone_h = max(1, band_h - text_zone_top - text_zone_bottom)
        
        font, lines, heights, spacing, total_h = fit_text_block_center(
            draw=draw, text=text, font_path=FONT_PATH,
            safe_w=safe_w, max_block_h=text_zone_h,
            max_lines=3, start_size=int(img.height * 0.05),
            min_size=20, line_spacing_ratio=0.16
        )
        
        y = text_zone_top + max(0, (text_zone_h - total_h) // 2)
        for i, ln in enumerate(lines):
            lw = text_width(draw, ln, font)
            x = (img.width - lw) // 2
            draw.text((x, y), ln, font=font, fill="white")
            y += heights[i] + spacing
        
        out = BytesIO()
        img.save(out, format="JPEG", quality=95, subsampling=0)
        out.seek(0)
        return out
    else:
        return create_poster(photo_bytes, title_text, "top")

def make_card_am2(photo_bytes: bytes, title_text: str, is_square: bool = False) -> BytesIO:
    return create_poster_am2(photo_bytes, title_text)

def make_card(photo_bytes: bytes, title_text: str, template: str, text_position: str = "top", 
              font_size_multiplier: float = 1.0, is_square: bool = False) -> BytesIO:
    if template == "CHP":
        return make_card_chp(photo_bytes, title_text, text_position, is_square)
    if template == "AM":
        return make_card_am(photo_bytes, title_text, is_square)
    if template == "AM2":
        return make_card_am2(photo_bytes, title_text, is_square)
    if template == "MN2":
        return make_card_mn2(photo_bytes, title_text, text_position, font_size_multiplier, is_square)
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
            font = ImageFont.truetype(FONT_PATH, font_size)
        except:
            font = ImageFont.load_default()
        
        watermark_text = "MINSK NEWS"
        
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (img.width - text_width) // 2
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
            font = ImageFont.truetype(FONT_PATH, font_size)
        except:
            font = ImageFont.load_default()
        
        watermark_text = "ЧП Минск"
        
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (img.width - text_width) // 2
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
# DeepSeek AI
# =========================
async def process_text_with_deepseek(text: str) -> str:
    """Отправляет текст в DeepSeek API для обработки"""
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
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты редактор новостного сайта. Твоя задача - сокращать новости до 650 символов, сохраняя главные факты."},
                        {"role": "user", "content": f"{prompt}\n\n{text}"}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"]
            else:
                logger.error(f"DeepSeek API error: {response.status_code} - {response.text}")
                return f"❌ Ошибка API: {response.status_code}"
                
        except Exception as e:
            logger.error(f"DeepSeek request error: {e}")
            return f"❌ Ошибка при обращении к API: {str(e)}"

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
        try:
            bot.edit_message_text(
                get_prices_text(),
                c.message.chat.id,
                c.message.message_id,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=prices_menu_kb()
            )
        except:
            bot.send_message(
                c.message.chat.id,
                get_prices_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=prices_menu_kb()
            )
        bot.answer_callback_query(c.id)
    
    elif action == "terms":
        try:
            bot.edit_message_text(
                get_terms_text(),
                c.message.chat.id,
                c.message.message_id,
                parse_mode="HTML",
                reply_markup=prices_menu_kb()
            )
        except:
            bot.send_message(
                c.message.chat.id,
                get_terms_text(),
                parse_mode="HTML",
                reply_markup=prices_menu_kb()
            )
        bot.answer_callback_query(c.id)
    
    elif action == "schedule":
        try:
            bot.edit_message_text(
                get_schedule_text(),
                c.message.chat.id,
                c.message.message_id,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=prices_menu_kb()
            )
        except:
            bot.send_message(
                c.message.chat.id,
                get_schedule_text(),
                parse_mode="HTML",
                disable_web_page_preview=True,
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
        try:
            bot.edit_message_text(
                "❌ Отменено",
                c.message.chat.id,
                c.message.message_id
            )
        except:
            bot.send_message(c.message.chat.id, "❌ Отменено")
        bot.answer_callback_query(c.id, "Отменено")
        return
    
    st["watermark_type"] = wm_type
    st["step"] = "waiting_watermark_photo"
    user_state[uid] = st
    
    wm_names = {"mn": "MINSK NEWS", "chp": "ЧП Минск"}
    wm_name = wm_names.get(wm_type, wm_type)
    
    try:
        bot.edit_message_text(
            f"✅ Выбран водяной знак: <b>{wm_name}</b>\n\n"
            f"📸 Теперь отправь фото, на которое нужно нанести водяной знак.\n\n"
            f"<i>Знак будет расположен по центру с прозрачностью 25%</i>",
            c.message.chat.id,
            c.message.message_id,
            parse_mode="HTML"
        )
    except:
        bot.send_message(
            c.message.chat.id,
            f"✅ Выбран водяной знак: <b>{wm_name}</b>\n\n"
            f"📸 Теперь отправь фото, на которое нужно нанести водяной знак.\n\n"
            f"<i>Знак будет расположен по центру с прозрачностью 25%</i>",
            parse_mode="HTML"
        )
    bot.answer_callback_query(c.id, f"Выбран {wm_name}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("show_squares"))
def on_show_squares(c):
    uid = c.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_template_square"
    user_state[uid] = st
    
    try:
        bot.edit_message_text(
            "⬛ Выбери шаблон для квадратного фото:",
            c.message.chat.id,
            c.message.message_id,
            reply_markup=template_kb(True)
        )
    except:
        bot.send_message(
            c.message.chat.id,
            "⬛ Выбери шаблон для квадратного фото:",
            reply_markup=template_kb(True)
        )
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
        try:
            bot.edit_message_text(
                "📝 Выбери шаблон оформления:",
                c.message.chat.id,
                c.message.message_id,
                reply_markup=template_kb(False)
            )
        except:
            bot.send_message(
                c.message.chat.id,
                "📝 Выбери шаблон оформления:",
                reply_markup=template_kb(False)
            )
        bot.answer_callback_query(c.id)
        return
    
    st["is_square"] = is_square
    st["template"] = tpl
    
    if tpl in ["MN2"]:
        st["step"] = "waiting_font_size"
        user_state[uid] = st
        bot.answer_callback_query(c.id, f"Шаблон МН 2 выбран ✅")
        size_text = "квадратного " if is_square else ""
        try:
            bot.edit_message_text(
                f"🔤 Настрой размер шрифта для {size_text}заголовка:",
                c.message.chat.id,
                c.message.message_id,
                reply_markup=font_size_kb(1.0, is_square)
            )
        except:
            bot.send_message(
                c.message.chat.id,
                f"🔤 Настрой размер шрифта для {size_text}заголовка:",
                reply_markup=font_size_kb(1.0, is_square)
            )
    elif tpl in ["MN", "CHP", "AM", "AM2"]:
        st["step"] = "waiting_text_position"
        user_state[uid] = st
        template_names = {"MN": "МН", "CHP": "ЧП ВМ", "AM": "АМ", "AM2": "АМ 2"}
        template_name = template_names.get(tpl, tpl)
        size_text = "квадратный " if is_square else ""
        bot.answer_callback_query(c.id, f"Шаблон {template_name} выбран ✅")
        try:
            bot.edit_message_text(
                f"📰 Выбран {size_text}шаблон <b>{template_name}</b>\n\nГде разместить текст?",
                c.message.chat.id,
                c.message.message_id,
                parse_mode="HTML",
                reply_markup=text_position_kb(is_square)
            )
        except:
            bot.send_message(
                c.message.chat.id,
                f"📰 Выбран {size_text}шаблон <b>{template_name}</b>\n\nГде разместить текст?",
                parse_mode="HTML",
                reply_markup=text_position_kb(is_square)
            )
    else:
        bot.answer_callback_query(c.id, "Этот шаблон недоступен для квадратного фото")
        return

@bot.callback_query_handler(func=lambda c: c.data.startswith("text_pos:") or c.data.startswith("square_pos:"))
def on_text_position(c):
    uid = c.from_user.id
    parts = c.data.split(":", 1)
    prefix = parts[0]
    position = parts[1]
    
    is_square = (prefix == "square_pos")
    st = user_state.get(uid) or {}
    
    st["text_position"] = position
    st["step"] = "waiting_photo"
    user_state[uid] = st
    
    position_text = "сверху" if position == "top" else "снизу"
    size_text = "квадратное " if is_square else ""
    try:
        bot.edit_message_text(
            f"Текст будет расположен <b>{position_text}</b> фотографии.\n\nТеперь пришли {size_text}фото 📷",
            c.message.chat.id,
            c.message.message_id,
            parse_mode="HTML"
        )
    except:
        bot.send_message(
            c.message.chat.id,
            f"Текст будет расположен <b>{position_text}</b> фотографии.\n\nТеперь пришли {size_text}фото 📷",
            parse_mode="HTML"
        )
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
        try:
            bot.edit_message_text(
                "✅ Размер шрифта настроен. Теперь выбери расположение текста:",
                c.message.chat.id,
                c.message.message_id,
                reply_markup=text_position_kb(is_square)
            )
        except:
            bot.send_message(
                c.message.chat.id,
                "✅ Размер шрифта настроен. Теперь выбери расположение текста:",
                reply_markup=text_position_kb(is_square)
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
    
    template_name = "квадратного МН 2" if is_square else "МН 2"
    try:
        bot.edit_message_text(
            f"🔤 Настройка размера шрифта для {template_name}\n\n"
            f"Текущий размер: {int(new_mult*100)}%\n"
            f"Используй кнопки + и - для регулировки.\n"
            f"Нажми «Готово» когда закончишь.",
            c.message.chat.id,
            c.message.message_id,
            reply_markup=font_size_kb(new_mult, is_square)
        )
    except:
        bot.send_message(
            c.message.chat.id,
            f"🔤 Настройка размера шрифта для {template_name}\n\n"
            f"Текущий размер: {int(new_mult*100)}%\n"
            f"Используй кнопки + и - для регулировки.\n"
            f"Нажми «Готово» когда закончишь.",
            reply_markup=font_size_kb(new_mult, is_square)
        )
    
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data in ["publish", "edit_body", "edit_title", "cancel"])
def on_action(call):
    uid = call.from_user.id
    st = user_state.get(uid)

    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(call.id, "Нет активного превью. Начни с «Оформить пост».")
        return

    if call.data == "publish":
        try:
            caption = build_caption_html(st.get("title", ""), st.get("body_raw", ""))
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
        st["step"] = "waiting_body"
        user_state[uid] = st
        bot.answer_callback_query(call.id, "Ок")
        bot.send_message(call.message.chat.id, "Пришли новый ОСНОВНОЙ ТЕКСТ.", reply_markup=main_menu_kb())

    elif call.data == "edit_title":
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
        "• 📝 Оформление постов с фото (7 шаблонов, включая Квадраты)\n"
        "• ✨ Улучшение качества фото (+20% резкость, +15% насыщенность)\n"
        "• 💧 Водяные знаки - нанеси \"MINSK NEWS\" или \"ЧП Минск\" на фото\n"
        "• 🤖 Текст в ИИ - отправь текст, ИИ сократит его до 650 символов\n"
        "• 💰 Цены и условия размещения\n\n"
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

@bot.message_handler(commands=["enhance"])
def cmd_enhance(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_enhance_photo"
    user_state[uid] = st
    
    bot.send_message(
        message.chat.id,
        "✨ <b>Улучшение качества фото</b>\n\n"
        "Отправь фото, и я увеличу резкость на +20% и насыщенность на +15%",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

@bot.message_handler(commands=["watermark"])
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

@bot.message_handler(commands=["prices"])
def cmd_prices(message):
    bot.send_message(
        message.chat.id,
        "💰 <b>Цены и условия размещения</b>\n\n"
        "Выбери интересующий раздел:",
        parse_mode="HTML",
        reply_markup=prices_menu_kb()
    )

@bot.message_handler(commands=["ai_text"])
def cmd_ai_text(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_ai_text"
    user_state[uid] = st
    
    bot.send_message(
        message.chat.id,
        "🤖 <b>Текст в ИИ</b>\n\n"
        "Отправь текст новости, и я сокращу его до 650 символов,\n"
        "сохраняя все главные факты в новостном формате.\n\n"
        "<i>Обработка может занять до 30 секунд...</i>",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    uid = message.from_user.id
    clear_state(uid)
    bot.send_message(message.chat.id, "🛑 Бот сброшен в исходное состояние.", reply_markup=main_menu_kb())

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

@bot.message_handler(content_types=["photo", "document"])
def on_photo_or_document(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    
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
            
            if wm_type == "mn":
                result = apply_watermark_mn(photo_bytes)
                caption = "💧 Водяной знак <b>MINSK NEWS</b> нанесён!"
            else:
                result = apply_watermark_chp(photo_bytes)
                caption = "💧 Водяной знак <b>ЧП Минск</b> нанесён!"
            
            bot.send_document(
                message.chat.id,
                document=result,
                visible_file_name=f"watermark_{wm_type}.jpg",
                caption=caption,
                parse_mode="HTML"
            )
            
            bot.delete_message(message.chat.id, processing_msg.message_id)
            clear_state(uid)
            return
            
        except Exception as e:
            logger.error(f"Error applying watermark: {e}")
            bot.reply_to(message, f"❌ Ошибка при нанесении водяного знака: {e}")
            return
    
    if st.get("step") == "waiting_template":
        bot.send_message(message.chat.id, "Сначала выбери шаблон:", reply_markup=template_kb())
        return

    if st.get("step") == "waiting_photo":
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
            is_square = st.get("is_square", False)
            
            if st.get("template") == "MN2":
                st["step"] = "waiting_title_mn2"
                user_state[uid] = st
                size_text = "квадратное " if is_square else ""
                bot.reply_to(message, f"📸 {size_text}Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
            else:
                st["step"] = "waiting_title"
                user_state[uid] = st
                size_text = "квадратное " if is_square else ""
                bot.reply_to(message, f"📸 {size_text}Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
            
            return

        except Exception as e:
            logger.error(f"Error processing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка при обработке фото: {e}")
            return

    bot.reply_to(message, "Не знаю, что делать с этим фото. Начни с /post")

@bot.message_handler(content_types=["text"])
def on_text(message):
    uid = message.from_user.id
    text = (message.text or "").strip()
    st = user_state.get(uid) or {"template": "MN", "step": "idle"}

    # Обработка кнопок главного меню
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

    step = st.get("step")

    # Обработка AI текста
    if step == "waiting_ai_text":
        processing_msg = bot.reply_to(message, "🤖 Обрабатываю текст в ИИ... Это может занять до 30 секунд.")
        
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_text_with_deepseek(text))
            bot.delete_message(message.chat.id, processing_msg.message_id)
            bot.send_message(message.chat.id, f"✍️ <b>Результат обработки:</b>\n\n{result}", parse_mode="HTML", reply_markup=main_menu_kb())
        except Exception as e:
            bot.delete_message(message.chat.id, processing_msg.message_id)
            bot.send_message(message.chat.id, f"❌ Ошибка при обработке: {e}", reply_markup=main_menu_kb())
        finally:
            loop.close()
        
        clear_state(uid)
        return

    # Обработка заголовка для МН2
    if step == "waiting_title_mn2":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым. Отправь текст:")
            return
        
        st["title"] = text
        st["step"] = "waiting_body_mn2"
        user_state[uid] = st
        
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n<b>{html.escape(text)}</b>\n\n✏️ Теперь отправь ОСНОВНОЙ ТЕКСТ:", parse_mode="HTML")
        return

    # Обработка текста для МН2
    if step == "waiting_body_mn2":
        st["body_raw"] = text
        body_src = re.search(r"(https?://[^\s]+)", text)
        if body_src:
            st["source_url"] = body_src.group(1)
        
        try:
            font_mult = st.get("font_size_multiplier", 1.0)
            
            card = make_card(
                st["photo_bytes"], 
                st["title"], 
                st.get("template", "MN"), 
                text_position=st.get("text_position", "top"),
                font_size_multiplier=font_mult,
                is_square=st.get("is_square", False)
            )
            
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st
            
            caption = build_caption_html(st["title"], text)
            
            bot.send_photo(
                chat_id=message.chat.id, 
                photo=BytesIO(st["card_bytes"]), 
                caption=caption, 
                parse_mode="HTML", 
                reply_markup=preview_kb(st.get("source_url", ""))
            )
            bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")
            
        except Exception as e:
            logger.error(f"Error creating card: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании карточки: {e}")
        return

    # Обработка заголовка для остальных шаблонов
    if step == "waiting_title":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым. Отправь текст:")
            return
        
        st["title"] = text
        st["step"] = "waiting_body"
        user_state[uid] = st
        
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n<b>{html.escape(text)}</b>\n\n✏️ Теперь отправь ОСНОВНОЙ ТЕКСТ:", parse_mode="HTML")
        return

    if step == "waiting_body":
        st["body_raw"] = text
        body_src = re.search(r"(https?://[^\s]+)", text)
        if body_src:
            st["source_url"] = body_src.group(1)

        try:
            font_mult = st.get("font_size_multiplier", 1.0) if st.get("template") == "MN2" else 1.0
            
            card = make_card(
                st["photo_bytes"], 
                st["title"], 
                st.get("template", "MN"), 
                text_position=st.get("text_position", "top"),
                font_size_multiplier=font_mult,
                is_square=st.get("is_square", False)
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
                reply_markup=preview_kb(st.get("source_url", ""))
            )
            bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")
            
        except Exception as e:
            logger.error(f"Error creating card: {e}")
            bot.reply_to(message, f"❌ Ошибка при создании карточки: {e}")
        return

    if step == "waiting_action":
        bot.reply_to(message, "Нажми кнопку под превью ✅✏️❌", reply_markup=main_menu_kb())

    if step == "waiting_template":
        bot.send_message(message.chat.id, "Выбери шаблон кнопками:", reply_markup=template_kb())

    if step == "waiting_text_position":
        bot.send_message(message.chat.id, "Сначала выбери расположение текста:", reply_markup=text_position_kb())

    else:
        user_state[uid] = st
        bot.send_message(message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())

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
        bot.infinity_polling(timeout=60, long_polling_timeout=60, logger_level=logging.ERROR)
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        try:
            if os.path.exists(lock_file):
                os.unlink(lock_file)
        except:
            pass
        raise
