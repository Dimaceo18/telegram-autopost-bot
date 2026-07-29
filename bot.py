# -*- coding: utf-8 -*-

import os
import re
import html
import time
import logging
import signal
import sys
import threading
import asyncio
from io import BytesIO
from typing import Dict, List, Optional, Tuple
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
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =========================
# ENV
# =========================
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

CHANNEL_MN = (os.getenv("CHANNEL_MN") or "").strip()
CHANNEL_CHP = (os.getenv("CHANNEL_CHP") or "").strip()
CHANNEL_AFISHA = (os.getenv("CHANNEL_AFISHA") or "").strip()
CHANNEL_TEST = (os.getenv("CHANNEL_TEST") or "").strip()

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

MAX_FILE_SIZE = 50 * 1024 * 1024

TARGET_W, TARGET_H = 720, 900
STORY_W, STORY_H = 720, 1280

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
# BOT
# =========================
bot = telebot.TeleBot(TOKEN)

try:
    bot.remove_webhook()
    logger.info("Webhook removed")
except:
    pass

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

def preview_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("📢 Опубликовать в канале", callback_data="publish_to_channel"),
        InlineKeyboardButton("💧 Водяной знак", callback_data="add_watermark"),
        InlineKeyboardButton("✏️ Редактировать текст", callback_data="edit_text"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel")
    )
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

def watermark_type_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📰 МН (MINSK NEWS)", callback_data="watermark:mn"),
        InlineKeyboardButton("🚨 ЧП (Минск ЧП)", callback_data="watermark:chp"),
        InlineKeyboardButton("◀️ Назад", callback_data="watermark:back")
    )
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="watermark:cancel"))
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


# =========================
# HELPER FUNCTIONS
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
        r = requests.get(file_url, timeout=30)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.error(f"Failed to download file: {e}")
        raise

def get_video_info(file_id: str, video_obj) -> Dict:
    return {
        'file_id': file_id,
        'file_size': getattr(video_obj, 'file_size', 0),
        'media_type': 'video',
        'duration': getattr(video_obj, 'duration', 0),
        'width': getattr(video_obj, 'width', 0),
        'height': getattr(video_obj, 'height', 0),
    }

def clear_state(user_id: int):
    if user_id in user_state:
        user_state[user_id] = {"step": "idle"}

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
# GRADIENT FUNCTIONS
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
# TEXT WRAPPING FUNCTIONS
# =========================
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
# AM2 FUNCTIONS
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
# CARD MAKING FUNCTIONS
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
# IMAGE ENHANCEMENT
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
# WATERMARK FUNCTIONS
# =========================
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
# DETECT TOPIC EMOJI
# =========================
def detect_topic_emoji(text: str) -> str:
    text_lower = text.lower()
    topics = {
        "🚨": ["дтп", "авар", "пожар", "взрыв", "происшеств", "чп", "полици", "милици", "скорая", "мчс", "катастроф"],
        "✈️": ["белавиа", "рейс", "аэропорт", "самолет", "полет", "авиа", "борт"],
        "🚇": ["метро", "станци", "маршрут", "автобус", "троллейбус", "трамвай", "транспорт"],
        "💳": ["банк", "технобанк", "карта", "налог", "выплат", "деньги", "финанс", "кредит"],
        "🏷️": ["скидк", "распрод", "акци", "дешев", "бесплат", "цена", "стоимость"],
        "🎫": ["концерт", "афиша", "выставк", "фестиваль", "мероприят", "кино", "театр"],
        "🌦️": ["погод", "шторм", "ветер", "снег", "дожд", "гроз", "температур", "мороз", "жара"],
        "🏥": ["больниц", "врач", "здоров", "вакцин", "лекарств", "медицин"],
        "📱": ["смартфон", "айфон", "телефон", "гаджет", "технологи"],
        "🚀": ["космос", "спутник", "наук", "исследован", "открыт"],
        "🎓": ["образован", "школ", "университет", "студент", "учител", "экзамен"],
        "⚽": ["футбол", "спорт", "хоккей", "чемпионат", "матч"],
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
# REMOVE EMOJIS
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
# DEEPSEEK FUNCTIONS
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
                        {"role": "system", "content": "Ты редактор новостного сайта. Отвечай только готовым новостным текстом, без пояснений."},
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

async def process_text_with_deepseek_tg(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор новостного канала. Сократи текст новости до 500 символов.

Правила:
1. Текст не более 500 символов
2. Сохрани ВСЮ ключевую информацию
3. Заголовок сделай жирным с помощью <b> и отдельной строкой
4. Разбей текст на абзацы
5. НЕ используй эмодзи в тексте
6. НЕ используй многоточие

Формат:
<b>Заголовок</b>

Текст новости...

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
                        {"role": "system", "content": "Ты редактор новостного канала. Отвечай только готовым постом. Используй <b> для заголовка."},
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
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                
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

async def process_text_with_deepseek_threads(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор для Threads. Сократи текст новости до 400 символов.

Правила:
1. Текст не более 400 символов
2. Сохрани ВСЮ ключевую информацию
3. Заголовок сделай жирным с помощью <b> и отдельной строкой
4. Разбей текст на абзацы
5. НЕ используй эмодзи в тексте
6. НЕ используй многоточие

Формат:
<b>Заголовок</b>

Текст новости...

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
                        {"role": "system", "content": "Ты редактор для Threads. Отвечай только готовым постом. Используй <b> для заголовка."},
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
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                
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

async def process_text_with_deepseek_tg_redo(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор новостного канала. Переделай эту новость в НОВЫЙ пост для Telegram.

Правила:
1. Текст не более 500 символов
2. Сохрани ВСЮ ключевую информацию
3. Заголовок: новый, сделай жирным с помощью <b>
4. НЕ используй эмодзи в тексте
5. НЕ используй многоточие

Формат:
<b>Новый заголовок</b>

Текст новости...

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
                        {"role": "system", "content": "Ты редактор новостного канала. Переделывай новости в новые посты. Используй <b> для заголовка."},
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
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                
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

async def process_text_with_deepseek_threads_redo(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор для Threads. Переделай эту новость в НОВЫЙ пост для Threads.

Правила:
1. Текст не более 400 символов
2. Сохрани ВСЮ ключевую информацию
3. Заголовок: новый, сделай жирным с помощью <b>
4. НЕ используй эмодзи в тексте
5. НЕ используй многоточие

Формат:
<b>Новый заголовок</b>

Текст новости...

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
                        {"role": "system", "content": "Ты редактор для Threads. Переделывай новости в новые посты. Используй <b> для заголовка."},
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
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                
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
# Функция для извлечения контента из статей через ИИ (РАБОЧАЯ)
# =========================
async def extract_article_content(url: str) -> Dict[str, any]:
    """
    Извлекает содержимое статьи по ссылке через ИИ (DeepSeek)
    1. Сначала загружает HTML страницы
    2. Отправляет HTML в DeepSeek для извлечения текста
    """
    if not DEEPSEEK_API_KEY:
        return {
            "text": "❌ API ключ DeepSeek не настроен.",
            "images": [],
            "title": "",
            "url": url
        }
    
    try:
        # ШАГ 1: Загружаем HTML страницы
        logger.info(f"Loading article from URL: {url}")
        
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            html_content = response.text
            logger.info(f"Loaded {len(html_content)} bytes of HTML")
        
        # Извлекаем заголовок страницы
        title_match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE)
        page_title = title_match.group(1).strip() if title_match else "Статья"
        
        # Очищаем HTML от скриптов и стилей
        clean_html = re.sub(r'<script.*?>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        clean_html = re.sub(r'<style.*?>.*?</style>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)
        clean_html = re.sub(r'<nav.*?>.*?</nav>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)
        clean_html = re.sub(r'<header.*?>.*?</header>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)
        clean_html = re.sub(r'<footer.*?>.*?</footer>', '', clean_html, flags=re.DOTALL | re.IGNORECASE)
        
        # ШАГ 2: Отправляем HTML в DeepSeek для извлечения текста
        prompt = f"""Ты КОПИРОВАЛЬЩИК текста. Извлеки основной текст статьи из HTML кода.

URL статьи: {url}
Заголовок страницы: {page_title}

КРИТИЧЕСКИ ВАЖНЫЕ ПРАВИЛА:
1. Ты НЕ редактор, ты КОПИРОВАЛЬЩИК
2. Скопируй ТОЧНО такой же текст, как на сайте - слово в слово
3. НЕ МЕНЯЙ слова, НЕ ПЕРЕФРАЗИРУЙ, НЕ РЕДАКТИРУЙ
4. НЕ добавляй свои слова, НЕ убирай слова
5. НЕ меняй имена, названия, цифры, даты
6. НЕ додумывай информацию, которой нет в тексте
7. Сохрани все абзацы и структуру
8. Убери только рекламу, баннеры, меню, навигацию
9. Верни ПОЛНЫЙ текст статьи без изменений

HTML код страницы:
{clean_html[:20000]}

Верни только точную копию текста статьи, без пояснений.
"""

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты КОПИРОВАЛЬЩИК текста. Твоя задача - скопировать текст ТОЧНО как на сайте, без изменений, без перефразирования, без редактирования. Ты НЕ редактор, ты КОПИРОВАЛЬЩИК. Скопируй текст слово в слово."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 8000
                }
            )
            
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"]
                
                # Очищаем только лишние фразы
                result = re.sub(r'^Вот извлеченный текст статьи.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Текст статьи.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Извлеченный текст.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Вот текст статьи.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^Вот.*?:', '', result, flags=re.IGNORECASE)
                result = result.strip()
                
                # Извлекаем заголовок
                lines = result.split('\n')
                page_title = lines[0].strip() if lines else ""
                body_text = '\n'.join(lines[1:]).strip() if len(lines) > 1 else ""
                
                if len(page_title) < 10 or 'http' in page_title:
                    title_match = re.search(r'^(.{10,200}?)(?:\n|$)', result)
                    if title_match:
                        page_title = title_match.group(1).strip()
                        body_text = result[len(page_title):].strip()
                
                logger.info(f"Extracted {len(body_text)} characters of text")
                
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
                    "title": page_title,
                    "url": url
                }
                
    except httpx.TimeoutException:
        logger.error(f"Timeout extracting article: {url}")
        return {
            "text": "❌ Превышено время ожидания при загрузке статьи. Попробуйте позже.",
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
# PRICES
# =========================
def get_prices_text() -> str:
    return """
💰 <b>НАШИ ЦЕНЫ</b>

🔻 <b>Размещение только в</b> minsk_news — 550 руб.

🔻 <b>Пакет «МИНИ»</b> (7 каналов) — 685 руб.

🔻 <b>Пакет «СТАНДАРТ»</b> (11 каналов) — 745 руб.

🔻 <b>Пакет «ПРЕМИУМ»</b> (Instagram + VK + Telegram) — 905 руб.
"""

def get_terms_text() -> str:
    return """
🔔 <b>УСЛОВИЯ РАЗМЕЩЕНИЯ:</b>

1. Инстаграм и Вконтакте — пост 1 час на первом месте
2. Телеграм — пост 30 минут на первом месте
3. Рекламные посты размещаются на 7 дней
4. При заказе ПРЕМИУМ — на 30 дней
"""

def get_schedule_text() -> str:
    return "📊 График аккаунтов:\n\n<a href='https://instagram.com/minsk_news'>instagram.com/minsk_news</a>"


# =========================
# HEALTH CHECK
# =========================
from http.server import HTTPServer, BaseHTTPRequestHandler

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
# CALLBACK HANDLERS (ОСНОВНЫЕ)
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
    
    if wm_type == "back":
        st.pop("step", None)
        user_state[uid] = st
        send_message_with_retry(c.message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())
        bot.answer_callback_query(c.id, "◀️ Возврат")
        return
    
    if not st.get("photo_bytes") and not st.get("saved_photo_bytes"):
        st["watermark_type"] = wm_type
        st["step"] = "waiting_watermark_photo"
        user_state[uid] = st
        send_message_with_retry(c.message.chat.id, f"✅ Выбран водяной знак. Отправь фото:", parse_mode="HTML")
        bot.answer_callback_query(c.id)
        return
    
    if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
        st["photo_bytes"] = st["saved_photo_bytes"]
    
    bot.answer_callback_query(c.id, f"✅ Наношу водяной знак {wm_type.upper()}...")
    
    try:
        if wm_type == "mn":
            result = apply_watermark_mn(st["photo_bytes"])
            watermark_name = "MINSK NEWS"
        else:
            result = apply_watermark_chp(st["photo_bytes"])
            watermark_name = "ЧП Минск"
        
        watermarked_photo = result.getvalue()
        st["photo_bytes"] = watermarked_photo
        st["saved_photo_bytes"] = watermarked_photo
        st["watermark_applied"] = True
        
        if st.get("card_bytes") and st.get("template") and st.get("title"):
            card = make_card(st["photo_bytes"], st["title"], st.get("template", "MN"),
                            text_position=st.get("text_position", TEXT_POSITION_TOP),
                            bold_phrase=st.get("bold_phrase", ""), date=st.get("date", ""),
                            place=st.get("place", ""), rubric=st.get("rubric", ""),
                            highlight_word=st.get("highlight_word", ""),
                            highlight_color=st.get("highlight_color"),
                            is_yellow=st.get("is_yellow", False))
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption_html = build_caption_html(st["title"], st["body_raw"])
            bot.delete_message(c.message.chat.id, c.message.message_id)
            send_photo_with_retry(c.message.chat.id, BytesIO(st["card_bytes"]),
                caption=f"💧 <b>Водяной знак «{watermark_name}» нанесён!</b>\n\n{caption_html}",
                parse_mode="HTML", reply_markup=preview_kb())
            return
        
        else:
            st["photo_bytes"] = watermarked_photo
            st["saved_photo_bytes"] = watermarked_photo
            st["step"] = "waiting_watermark_photo"
            user_state[uid] = st
            bot.delete_message(c.message.chat.id, c.message.message_id)
            send_photo_with_retry(c.message.chat.id, BytesIO(watermarked_photo),
                caption=f"💧 <b>Водяной знак «{watermark_name}» нанесён!</b>", parse_mode="HTML")
            send_message_with_retry(c.message.chat.id, "✅ Водяной знак нанесён!", reply_markup=main_menu_kb())
            return
            
    except Exception as e:
        logger.error(f"Error applying watermark: {e}")
        send_message_with_retry(c.message.chat.id, f"❌ Ошибка: {e}")

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

@bot.callback_query_handler(func=lambda c: c.data.startswith("repost:"))
def on_repost_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "design":
        st["step"] = "waiting_template"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Выбери шаблон для оформления поста ✅")
        send_message_with_retry(c.message.chat.id, "📝 Выбери шаблон оформления", reply_markup=template_kb())
    
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
            send_message_with_retry(c.message.chat.id, formatted_text, parse_mode="HTML", reply_markup=after_ai_kb())
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
                logger.info(f"Saved photo for TG post for user {uid}")
            
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            media_info = ""
            if st.get("photo_bytes"):
                media_info = "\n📸 <b>Медиа:</b> фото сохранено"
            elif st.get("video_info"):
                media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
            elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
                photo_count = len(st["media_group"].get("photos", []))
                video_count = len(st["media_group"].get("videos", []))
                media_info = f"\n📸 <b>Медиа:</b> {photo_count} фото, {video_count} видео"
            
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
                logger.info(f"Saved photo for Threads post for user {uid}")
            
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            media_info = ""
            if st.get("photo_bytes"):
                media_info = "\n📸 <b>Медиа:</b> фото сохранено"
            elif st.get("video_info"):
                media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
            elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
                photo_count = len(st["media_group"].get("photos", []))
                video_count = len(st["media_group"].get("videos", []))
                media_info = f"\n📸 <b>Медиа:</b> {photo_count} фото, {video_count} видео"
            
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
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>", parse_mode="HTML", reply_markup=watermark_type_kb())
        else:
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>", parse_mode="HTML", reply_markup=watermark_type_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("ai:"))
def on_ai_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "design":
        if st.get("saved_photo_bytes"):
            st["photo_bytes"] = st["saved_photo_bytes"]
        st["step"] = "waiting_template"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Выбери шаблон для оформления ✅")
        send_message_with_retry(c.message.chat.id, "📝 Выбери шаблон оформления", reply_markup=template_kb())
    
    elif action == "watermark":
        if st.get("photo_bytes") or st.get("saved_photo_bytes"):
            if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
                st["photo_bytes"] = st["saved_photo_bytes"]
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>", parse_mode="HTML", reply_markup=watermark_type_kb())
        else:
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>", parse_mode="HTML", reply_markup=watermark_type_kb())
    
    elif action == "select_channel":
        if not CHANNEL_MN and not CHANNEL_CHP and not CHANNEL_AFISHA and not CHANNEL_TEST:
            bot.answer_callback_query(c.id, "❌ Каналы не настроены")
            send_message_with_retry(c.message.chat.id, "❌ Ни один канал для публикации не настроен.", reply_markup=after_ai_kb())
            return
        
        bot.answer_callback_query(c.id, "📢 Выбери канал для публикации")
        send_message_with_retry(c.message.chat.id, "📢 <b>Выбери канал для публикации текста:</b>", parse_mode="HTML", reply_markup=channel_selection_kb())
    
    elif action == "redo":
        bot.answer_callback_query(c.id, "🔄 Переделываю текст...")
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Переобрабатываю текст в DeepSeek AI...")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("original_text_for_ai", st.get("original_text", ""))
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
            bot.edit_message_text(formatted_text, c.message.chat.id, c.message.message_id, parse_mode="HTML", reply_markup=after_ai_kb())
        except Exception as e:
            logger.error(f"AI redo error: {e}")
            bot.edit_message_text(f"❌ Ошибка при переделке: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "back":
        bot.answer_callback_query(c.id, "◀️ Возврат назад")
        clear_state(uid)
        send_message_with_retry(c.message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())
    
    else:
        clear_state(uid)
        bot.answer_callback_query(c.id, "Отменено")
        send_message_with_retry(c.message.chat.id, "❌ Отменено", reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("tg:"))
def on_tg_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "redo":
        bot.answer_callback_query(c.id, "🔄 Переделываю пост для Telegram...")
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Переделываю пост... (до 30 секунд)")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("original_text_for_ai") or st.get("original_text") or st.get("extracted_text")
            
            if not original_text:
                bot.edit_message_text(
                    "❌ Нет исходного текста для переделки. Отправьте новую ссылку или текст.",
                    c.message.chat.id,
                    processing_msg.message_id
                )
                return
            
            result = loop.run_until_complete(process_text_with_deepseek_tg_redo(original_text))
            
            st["tg_post_text"] = result
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            if st.get("photo_bytes"):
                st["saved_photo_bytes"] = st["photo_bytes"]
            
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            
            media_info = ""
            if st.get("photo_bytes"):
                media_info = "\n📸 <b>Медиа:</b> фото сохранено"
            elif st.get("video_info"):
                media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
            elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
                photo_count = len(st["media_group"].get("photos", []))
                video_count = len(st["media_group"].get("videos", []))
                media_info = f"\n📸 <b>Медиа:</b> {photo_count} фото, {video_count} видео"
            
            send_message_with_retry(
                c.message.chat.id,
                f"📱 <b>Пост для Telegram (500 символов) - версия 2</b>\n\n{result}{media_info}",
                parse_mode="HTML",
                reply_markup=post_action_kb("tg")
            )
                
        except Exception as e:
            logger.error(f"TG redo error: {e}")
            bot.edit_message_text(f"❌ Ошибка при переделке: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "select_channel":
        bot.answer_callback_query(c.id, "📢 Выбери канал")
        send_message_with_retry(
            c.message.chat.id,
            "📢 <b>Выбери канал для публикации поста:</b>",
            parse_mode="HTML",
            reply_markup=post_channel_selection_kb("tg")
        )
    
    elif action == "back":
        bot.answer_callback_query(c.id, "◀️ Назад")
        clear_state(uid)
        send_message_with_retry(c.message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("threads:"))
def on_threads_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "redo":
        bot.answer_callback_query(c.id, "🔄 Переделываю пост для Threads...")
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Переделываю пост... (до 30 секунд)")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            original_text = st.get("original_text_for_ai") or st.get("original_text") or st.get("extracted_text")
            
            if not original_text:
                bot.edit_message_text(
                    "❌ Нет исходного текста для переделки. Отправьте новую ссылку или текст.",
                    c.message.chat.id,
                    processing_msg.message_id
                )
                return
            
            result = loop.run_until_complete(process_text_with_deepseek_threads_redo(original_text))
            
            st["threads_post_text"] = result
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            if st.get("photo_bytes"):
                st["saved_photo_bytes"] = st["photo_bytes"]
            
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            
            media_info = ""
            if st.get("photo_bytes"):
                media_info = "\n📸 <b>Медиа:</b> фото сохранено"
            elif st.get("video_info"):
                media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
            elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
                photo_count = len(st["media_group"].get("photos", []))
                video_count = len(st["media_group"].get("videos", []))
                media_info = f"\n📸 <b>Медиа:</b> {photo_count} фото, {video_count} видео"
            
            send_message_with_retry(
                c.message.chat.id,
                f"📱 <b>Пост для Threads (400 символов) - версия 2</b>\n\n{result}{media_info}",
                parse_mode="HTML",
                reply_markup=post_action_kb("threads")
            )
                
        except Exception as e:
            logger.error(f"Threads redo error: {e}")
            bot.edit_message_text(f"❌ Ошибка при переделке: {e}", c.message.chat.id, processing_msg.message_id)
        finally:
            loop.close()
    
    elif action == "select_channel":
        bot.answer_callback_query(c.id, "📢 Выбери канал")
        send_message_with_retry(
            c.message.chat.id,
            "📢 <b>Выбери канал для публикации поста:</b>",
            parse_mode="HTML",
            reply_markup=post_channel_selection_kb("threads")
        )
    
    elif action == "back":
        bot.answer_callback_query(c.id, "◀️ Назад")
        clear_state(uid)
        send_message_with_retry(c.message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("post_channel:"))
def on_post_channel_select(c):
    uid = c.from_user.id
    _, post_type, channel_type = c.data.split(":", 2)
    st = user_state.get(uid) or {}
    
    if channel_type == "cancel":
        bot.answer_callback_query(c.id, "Отменено")
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        if post_type == "tg" and st.get("tg_post_text"):
            media_info = ""
            if st.get("photo_bytes"):
                media_info = "\n📸 <b>Медиа:</b> фото сохранено"
            send_message_with_retry(
                c.message.chat.id,
                f"📱 <b>Пост для Telegram (500 символов)</b>\n\n{st['tg_post_text']}{media_info}",
                parse_mode="HTML",
                reply_markup=post_action_kb("tg")
            )
        elif post_type == "threads" and st.get("threads_post_text"):
            media_info = ""
            if st.get("photo_bytes"):
                media_info = "\n📸 <b>Медиа:</b> фото сохранено"
            send_message_with_retry(
                c.message.chat.id,
                f"📱 <b>Пост для Тредс (400 символов)</b>\n\n{st['threads_post_text']}{media_info}",
                parse_mode="HTML",
                reply_markup=post_action_kb("threads")
            )
        return
    
    if channel_type == "mn":
        target_channel = CHANNEL_MN
        channel_name = "MINSK NEWS"
    elif channel_type == "chp":
        target_channel = CHANNEL_CHP
        channel_name = "МИНСК ЧП"
    elif channel_type == "afisha":
        target_channel = CHANNEL_AFISHA
        channel_name = "Афиша Минска"
    elif channel_type == "test":
        target_channel = CHANNEL_TEST
        channel_name = "ТЕСТОВЫЙ КАНАЛ"
    else:
        bot.answer_callback_query(c.id, "❌ Неизвестный канал")
        return
    
    if not target_channel:
        bot.answer_callback_query(c.id, f"❌ Канал {channel_name} не настроен")
        return
    
    try:
        if post_type == "tg":
            post_text = st.get("tg_post_text", "")
        else:
            post_text = st.get("threads_post_text", "")
        
        if not post_text:
            bot.answer_callback_query(c.id, "❌ Нет текста для публикации")
            return
        
        media_group = st.get("media_group", {"photos": [], "videos": []})
        photo_bytes = st.get("photo_bytes") or st.get("saved_photo_bytes")
        video_info = st.get("video_info")
        
        has_media = False
        
        if photo_bytes:
            send_photo_with_retry(
                target_channel,
                BytesIO(photo_bytes),
                caption=post_text,
                parse_mode="HTML"
            )
            has_media = True
            logger.info(f"Published photo to {channel_name} with post text")
            
        elif media_group.get("photos") or media_group.get("videos"):
            media_list = []
            first = True
            
            for photo in media_group.get("photos", []):
                if first:
                    media_list.append(InputMediaPhoto(BytesIO(photo), caption=post_text, parse_mode="HTML"))
                    first = False
                else:
                    media_list.append(InputMediaPhoto(BytesIO(photo)))
            
            for video in media_group.get("videos", []):
                file_id = video.get('file_id')
                if file_id:
                    if first:
                        media_list.append(InputMediaVideo(file_id, caption=post_text, parse_mode="HTML"))
                        first = False
                    else:
                        media_list.append(InputMediaVideo(file_id))
            
            if len(media_list) > 1:
                send_media_group_with_retry(target_channel, media_list)
                has_media = True
                logger.info(f"Published {len(media_list)} media items to {channel_name}")
            elif len(media_list) == 1:
                if isinstance(media_list[0], InputMediaPhoto):
                    send_photo_with_retry(target_channel, media_list[0].media, caption=media_list[0].caption, parse_mode="HTML")
                elif isinstance(media_list[0], InputMediaVideo):
                    bot.send_video(target_channel, media_list[0].media, caption=media_list[0].caption, parse_mode="HTML")
                has_media = True
        
        elif video_info:
            try:
                file_id = video_info.get('file_id')
                if file_id:
                    bot.send_video(
                        target_channel,
                        file_id,
                        caption=post_text,
                        parse_mode="HTML"
                    )
                    has_media = True
                    logger.info(f"Published video to {channel_name} with post text")
            except Exception as e:
                logger.error(f"Error sending video: {e}")
                bot.send_message(target_channel, post_text, parse_mode="HTML")
                has_media = True
        
        if not has_media:
            bot.send_message(target_channel, post_text, parse_mode="HTML")
            logger.info(f"Published text only to {channel_name}")
        
        bot.answer_callback_query(c.id, f"✅ Опубликовано в {channel_name}")
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        
        clear_state(uid)
        send_message_with_retry(
            c.message.chat.id,
            f"✅ Пост опубликован в канале {channel_name}!",
            reply_markup=main_menu_kb()
        )
        
    except Exception as e:
        logger.error(f"Error publishing post to channel: {e}")
        bot.answer_callback_query(c.id, "❌ Ошибка публикации")
        
        try:
            if post_type == "tg":
                post_text = st.get("tg_post_text", "")
            else:
                post_text = st.get("threads_post_text", "")
            
            if post_text:
                bot.send_message(target_channel, post_text, parse_mode="HTML")
                send_message_with_retry(
                    c.message.chat.id,
                    f"⚠️ Текст опубликован, но медиа не загрузились.",
                    reply_markup=main_menu_kb()
                )
        except:
            send_message_with_retry(
                c.message.chat.id,
                f"❌ Не удалось опубликовать: {e}",
                reply_markup=main_menu_kb()
            )

@bot.callback_query_handler(func=lambda c: c.data.startswith("select_channel:"))
def on_select_channel(c):
    uid = c.from_user.id
    channel_type = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if channel_type == "cancel":
        bot.answer_callback_query(c.id, "Отменено")
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        if st.get("card_bytes"):
            caption = build_caption_html(st.get("title", ""), st.get("body_raw", ""))
            send_photo_with_retry(c.message.chat.id, BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
        elif st.get("original_text"):
            title, body, formatted_text = format_ai_response(st.get("original_text", ""))
            bot.send_message(c.message.chat.id, formatted_text, parse_mode="HTML", reply_markup=after_ai_kb())
        else:
            send_message_with_retry(c.message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())
        return
    
    if channel_type == "mn":
        target_channel = CHANNEL_MN
        channel_name = "MINSK NEWS"
    elif channel_type == "chp":
        target_channel = CHANNEL_CHP
        channel_name = "МИНСК ЧП"
    elif channel_type == "afisha":
        target_channel = CHANNEL_AFISHA
        channel_name = "Афиша Минска"
    elif channel_type == "test":
        target_channel = CHANNEL_TEST
        channel_name = "ТЕСТОВЫЙ КАНАЛ"
    else:
        bot.answer_callback_query(c.id, "❌ Неизвестный канал")
        return
    
    if not target_channel:
        bot.answer_callback_query(c.id, f"❌ Канал {channel_name} не настроен")
        return
    
    try:
        if st.get("photo_bytes"):
            send_photo_with_retry(target_channel, BytesIO(st["photo_bytes"]), caption=st.get("title", ""), parse_mode="HTML")
        elif st.get("card_bytes"):
            send_photo_with_retry(target_channel, BytesIO(st["card_bytes"]), caption=st.get("title", ""), parse_mode="HTML")
        elif st.get("original_text"):
            bot.send_message(target_channel, st.get("original_text", ""), parse_mode="HTML")
        else:
            bot.answer_callback_query(c.id, "❌ Нет контента для публикации")
            return
        
        bot.answer_callback_query(c.id, f"✅ Опубликовано в {channel_name}")
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        clear_state(uid)
        send_message_with_retry(c.message.chat.id, f"✅ Пост опубликован в канале {channel_name}!", reply_markup=main_menu_kb())
        
    except Exception as e:
        logger.error(f"Error publishing to channel: {e}")
        bot.answer_callback_query(c.id, "❌ Ошибка публикации")
        send_message_with_retry(c.message.chat.id, f"❌ Не удалось опубликовать: {e}", reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data in ["publish", "edit_text", "cancel"])
def on_action(call):
    uid = call.from_user.id
    st = user_state.get(uid)
    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(call.id, "Нет активного превью.")
        return
    if call.data == "publish":
        try:
            caption = build_caption_html(st.get("title", ""), st.get("body_raw", ""))
            photo_to_send = st.get("photo_bytes")
            if photo_to_send is None:
                photo_to_send = st.get("card_bytes")
            if photo_to_send:
                # Используем CHANNEL из ENV
                channel = os.getenv("CHANNEL_USERNAME", "").strip()
                if channel and not channel.startswith("@"):
                    channel = "@" + channel
                if channel:
                    send_photo_with_retry(channel, BytesIO(photo_to_send), caption=caption, parse_mode="HTML")
                    bot.answer_callback_query(call.id, "Опубликовано ✅")
                else:
                    bot.answer_callback_query(call.id, "❌ Канал не настроен")
                send_message_with_retry(call.message.chat.id, "Готово ✅", reply_markup=main_menu_kb())
            else:
                bot.answer_callback_query(call.id, "❌ Нет фото для публикации")
            clear_state(uid)
        except Exception as e:
            logger.error(f"Error publishing: {e}")
            bot.answer_callback_query(call.id, "Ошибка публикации")
    elif call.data == "edit_text":
        st["step"] = "waiting_title"
        user_state[uid] = st
        bot.answer_callback_query(call.id, "Ок")
        send_message_with_retry(call.message.chat.id, "Пришли новый ЗАГОЛОВОК.", reply_markup=main_menu_kb())
    elif call.data == "cancel":
        bot.answer_callback_query(call.id, "Отменено")
        clear_state(uid)
        send_message_with_retry(call.message.chat.id, "Отменил ❌", reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("tpl:"))
def on_tpl(c):
    uid = c.from_user.id
    parts = c.data.split(":", 1)
    tpl = parts[1]
    st = user_state.get(uid) or {}
    
    if tpl == "watermark":
        st["step"] = "waiting_watermark_type"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
        send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>", parse_mode="HTML", reply_markup=watermark_type_kb())
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        return
    
    st["template"] = tpl
    
    if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
        st["photo_bytes"] = st["saved_photo_bytes"]
    
    has_photo = st.get("photo_bytes") is not None
    
    if tpl in ["MN", "CHP", "AM", "MN_TG", "MN2"]:
        if has_photo:
            st["step"] = "waiting_text_position"
            user_state[uid] = st
            template_names = {"MN": "МН", "AM": "АМ", "MN_TG": "МН ТГ", "CHP": "ЧП ВМ", "MN2": "МН 2"}
            template_name = template_names.get(tpl, tpl)
            bot.answer_callback_query(c.id, f"Шаблон {template_name} выбран ✅")
            send_message_with_retry(c.message.chat.id, f"📰 Выбран шаблон <b>{template_name}</b>\n\n📸 Фото уже есть!\n\nГде разместить текст?", parse_mode="HTML", reply_markup=text_position_kb())
        else:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            template_names = {"MN": "МН", "AM": "АМ", "MN_TG": "МН ТГ", "CHP": "ЧП ВМ", "MN2": "МН 2"}
            template_name = template_names.get(tpl, tpl)
            bot.answer_callback_query(c.id, f"Шаблон {template_name} выбран ✅")
            send_message_with_retry(c.message.chat.id, f"📰 Выбран шаблон <b>{template_name}</b>\n\nТеперь пришли фото 📷", parse_mode="HTML")
    
    elif tpl == "AM2":
        if has_photo:
            st["step"] = "waiting_text_position_am2"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон АМ 2 выбран ✅")
            send_message_with_retry(c.message.chat.id, f"🎨 Выбран шаблон <b>АМ 2</b>\n\n📐 <b>Выбери расположение текста:</b>", parse_mode="HTML", reply_markup=text_position_kb_am2())
        else:
            st["step"] = "waiting_photo_am2"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон АМ 2 выбран ✅")
            send_message_with_retry(c.message.chat.id, f"🎨 Выбран шаблон <b>АМ 2</b>\n\n📸 Пришли фото:", parse_mode="HTML")
    
    elif tpl == "FDR_POST":
        if has_photo:
            st["step"] = "waiting_title_fdr_post"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
            send_message_with_retry(c.message.chat.id, f"💜 Выбран шаблон <b>Пост ФДР</b>\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b>:", parse_mode="HTML")
        else:
            st["step"] = "waiting_photo_fdr_post"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
            send_message_with_retry(c.message.chat.id, f"💜 Выбран шаблон <b>Пост ФДР</b>\n\n📸 Пришли фото:", parse_mode="HTML")
    
    elif tpl == "FDR_STORY":
        if has_photo:
            st["step"] = "waiting_title_fdr"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Сторис ФДР' выбран ✅")
            send_message_with_retry(c.message.chat.id, f"📱 Выбран шаблон <b>Сторис ФДР</b>\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b> для сторис:", parse_mode="HTML")
        else:
            st["step"] = "waiting_photo_fdr_story"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон 'Сторис ФДР' выбран ✅")
            send_message_with_retry(c.message.chat.id, "📱 Выбран шаблон <b>Сторис ФДР</b>\n\n📸 Пришли фото:", parse_mode="HTML")
    
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except:
        pass

@bot.callback_query_handler(func=lambda c: c.data.startswith("text_pos:"))
def on_text_position(c):
    uid = c.from_user.id
    parts = c.data.split(":", 1)
    position = parts[1]
    st = user_state.get(uid) or {}
    st["text_position"] = position
    
    if st.get("photo_bytes"):
        st["step"] = "waiting_title"
        user_state[uid] = st
        position_text = "сверху" if position == "top" else "снизу"
        bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")
        send_message_with_retry(c.message.chat.id, f"✅ Текст будет расположен <b>{position_text}</b> фотографии.\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b>:", parse_mode="HTML")
    else:
        st["step"] = "waiting_photo"
        user_state[uid] = st
        position_text = "сверху" if position == "top" else "снизу"
        send_message_with_retry(c.message.chat.id, f"✅ Текст будет расположен <b>{position_text}</b> фотографии.\n\nТеперь пришли фото 📷", parse_mode="HTML")
        bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")
    
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
    send_message_with_retry(c.message.chat.id, f"✅ Текст будет расположен <b>{pos_text}</b>\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b>:", parse_mode="HTML")
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

@bot.callback_query_handler(func=lambda c: c.data == "add_watermark")
def on_add_watermark(c):
    uid = c.from_user.id
    st = user_state.get(uid) or {}
    
    if not st.get("photo_bytes") and not st.get("saved_photo_bytes"):
        bot.answer_callback_query(c.id, "⚠️ Нет фото для водяного знака")
        send_message_with_retry(c.message.chat.id, "⚠️ Не найдено фото.", reply_markup=main_menu_kb())
        return
    
    if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
        st["photo_bytes"] = st["saved_photo_bytes"]
    
    st["step"] = "waiting_watermark_type"
    user_state[uid] = st
    bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
    send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>", parse_mode="HTML", reply_markup=watermark_type_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("article:"))
def on_article_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "design":
        if not st.get("extracted_text"):
            bot.answer_callback_query(c.id, "❌ Нет текста для оформления")
            return
        
        st["original_text"] = st.get("extracted_text", "")
        st["original_text_for_ai"] = st.get("extracted_text", "")
        title, body = split_title_and_body(st["extracted_text"])
        st["title"] = title if title else "Статья"
        st["body_raw"] = body
        st["step"] = "waiting_template"
        user_state[uid] = st
        
        bot.answer_callback_query(c.id, "📝 Выбери шаблон для оформления")
        send_message_with_retry(c.message.chat.id, "📝 Выбери шаблон оформления.", parse_mode="HTML", reply_markup=template_kb())
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
    
    elif action == "ai":
        if not st.get("extracted_text"):
            bot.answer_callback_query(c.id, "❌ Нет текста для обработки")
            return
        
        bot.answer_callback_query(c.id, "🤖 Обрабатываю текст через ИИ...")
        processing_msg = bot.send_message(c.message.chat.id, "⏳ Обрабатываю текст в DeepSeek AI...")
        
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
            send_message_with_retry(c.message.chat.id, formatted_text, parse_mode="HTML", reply_markup=after_ai_kb())
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
            
            if st.get("extracted_images"):
                st["photo_bytes"] = st["extracted_images"][0]
                st["saved_photo_bytes"] = st["extracted_images"][0]
            
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            media_info = ""
            if st.get("extracted_images"):
                media_info = f"\n📸 <b>Медиа:</b> {len(st['extracted_images'])} фото сохранено"
            
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
            
            if st.get("extracted_images"):
                st["photo_bytes"] = st["extracted_images"][0]
                st["saved_photo_bytes"] = st["extracted_images"][0]
            
            user_state[uid] = st
            
            bot.delete_message(c.message.chat.id, processing_msg.message_id)
            
            media_info = ""
            if st.get("extracted_images"):
                media_info = f"\n📸 <b>Медиа:</b> {len(st['extracted_images'])} фото сохранено"
            
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
        if st.get("extracted_images") and len(st["extracted_images"]) > 0:
            st["photo_bytes"] = st["extracted_images"][0]
            st["saved_photo_bytes"] = st["extracted_images"][0]
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>", parse_mode="HTML", reply_markup=watermark_type_kb())
        else:
            st["step"] = "waiting_watermark_type"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "💧 Выбери тип водяного знака")
            send_message_with_retry(c.message.chat.id, "💧 <b>Выбери тип водяного знака:</b>", parse_mode="HTML", reply_markup=watermark_type_kb())
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
        send_message_with_retry(c.message.chat.id, "📢 <b>Выбери канал для публикации текста:</b>", parse_mode="HTML", reply_markup=channel_selection_kb())
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass


# =========================
# HANDLE FORWARDED MESSAGES
# =========================
def process_album_with_media(uid: int, media_group_id: str, chat_id: int, is_repost: bool = False):
    time.sleep(2)
    if media_group_id not in user_album_cache:
        return
    
    album_data = user_album_cache.pop(media_group_id)
    st = user_state.get(uid) or {}
    
    caption = album_data.get("caption", "")
    photos = album_data.get("photos", [])
    videos = album_data.get("videos", [])
    
    if caption:
        title, body = split_title_and_body(caption)
        st["title"] = title
        st["body_raw"] = body
        st["original_text"] = caption
        st["original_text_for_ai"] = caption
    
    st["media_group"] = {"photos": photos, "videos": videos}
    
    if photos:
        st["photo_bytes"] = photos[0]
        st["saved_photo_bytes"] = photos[0]
    
    if videos:
        st["video_info"] = videos[0]
    
    st["step"] = "waiting_repost_action"
    user_state[uid] = st
    
    text_preview = caption[:200] if caption else "(без текста)"
    photo_count = len(photos)
    video_count = len(videos)
    media_status = []
    if photo_count > 0:
        media_status.append(f"✅ <b>Фото:</b> {photo_count} шт")
    if video_count > 0:
        total_size = sum(v.get('file_size', 0) for v in videos) / (1024 * 1024)
        media_status.append(f"✅ <b>Видео:</b> {video_count} шт ({total_size:.1f}MB)")
    if not media_status:
        media_status.append("⚠️ <b>Медиа:</b> не найдено")
    
    send_message_with_retry(chat_id,
        f"📸 <b>Альбом обнаружен!</b>\n\n{', '.join(media_status)}\n📝 <b>Текст:</b> {text_preview}...\n\n<b>Что сделать с этим постом?</b>",
        parse_mode="HTML", reply_markup=repost_action_kb())

@bot.message_handler(content_types=["text", "photo", "video", "document", "audio", "animation", "voice", "video_note"], 
                     func=lambda message: message.forward_from_chat is not None or (message.forward_from is not None))
def handle_forwarded_message(message):
    uid = message.from_user.id
    
    if hasattr(message, 'media_group_id') and message.media_group_id:
        media_group_id = message.media_group_id
        
        if media_group_id not in user_album_cache:
            user_album_cache[media_group_id] = {
                "photos": [], "videos": [], "caption": "",
                "start_time": time.time(), "message_id": message.message_id, "chat_id": message.chat.id
            }
        
        if message.photo:
            try:
                file_id = message.photo[-1].file_id
                photo_bytes = tg_file_bytes(file_id)
                if check_file_size(photo_bytes):
                    user_album_cache[media_group_id]["photos"].append(photo_bytes)
            except Exception as e:
                logger.error(f"Error extracting photo from album: {e}")
        
        if message.video:
            try:
                video_info = get_video_info(message.video.file_id, message.video)
                user_album_cache[media_group_id]["videos"].append(video_info)
            except Exception as e:
                logger.error(f"Error extracting video from album: {e}")
        
        if message.caption:
            user_album_cache[media_group_id]["caption"] = message.caption
        
        threading.Thread(target=process_album_with_media, args=(uid, media_group_id, message.chat.id, True), daemon=True).start()
        return
    
    original_text = ""
    if message.text:
        original_text = message.text
    elif message.caption:
        original_text = message.caption
    
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
    
    st = user_state.get(uid) or {}
    st["original_text"] = original_text
    st["original_text_for_ai"] = original_text
    st["original_url"] = source_url
    st["step"] = "waiting_repost_action"
    st["photo_bytes"] = None
    st["video_info"] = None
    st["media_group"] = {"photos": [], "videos": []}
    
    if message.photo:
        try:
            file_id = message.photo[-1].file_id
            photo_bytes = tg_file_bytes(file_id)
            if check_file_size(photo_bytes):
                st["photo_bytes"] = photo_bytes
                st["saved_photo_bytes"] = photo_bytes
                st["media_group"]["photos"].append(photo_bytes)
        except Exception as e:
            logger.error(f"Error extracting photo from forward: {e}")
    
    if message.video:
        try:
            video_info = get_video_info(message.video.file_id, message.video)
            st["video_info"] = video_info
            st["media_group"]["videos"].append(video_info)
        except Exception as e:
            logger.error(f"Error extracting video from forward: {e}")
    
    if not st["photo_bytes"] and (message.video or message.document or message.animation):
        st["has_media"] = True
        st["media_type"] = "video" if message.video else "document"
    
    if original_text:
        title, body = split_title_and_body(original_text)
        st["title"] = title
        st["body_raw"] = body
    
    user_state[uid] = st
    
    text_preview = original_text[:200] if original_text else "(без текста)"
    source_text = f"📢 <b>Источник:</b> {source_info}\n" if source_info else ""
    
    media_status = []
    if st["photo_bytes"]:
        media_status.append("✅ <b>Фото:</b> сохранено")
    if st["video_info"]:
        file_size_mb = st["video_info"].get('file_size', 0) / (1024 * 1024)
        media_status.append(f"✅ <b>Видео:</b> сохранено ({file_size_mb:.1f}MB)")
    if not media_status:
        media_status.append("⚠️ <b>Медиа:</b> не найдено")
    
    send_message_with_retry(message.chat.id,
        f"📎 <b>Пересланный пост обнаружен!</b>\n\n{source_text}{'<br>'.join(media_status)}\n📝 <b>Текст:</b> {text_preview}...\n\n<b>Что сделать с этим постом?</b>",
        parse_mode="HTML", reply_markup=repost_action_kb())


# =========================
# HANDLE ARTICLE LINK
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
            bot.edit_message_text("❌ Не удалось извлечь текст статьи.", message.chat.id, processing_msg.message_id)
            return
        
        try:
            bot.delete_message(message.chat.id, processing_msg.message_id)
        except:
            pass
        
        st = user_state.get(uid) or {}
        st["extracted_text"] = result.get("text", "")
        st["extracted_title"] = result.get("title", "")
        st["extracted_url"] = result.get("url", url)
        st["extracted_images"] = []
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
                        bot.send_message(message.chat.id, f"📝 <b>Продолжение ({i+1}/{len(parts)}):</b>\n\n{part}", parse_mode="HTML")
            else:
                bot.send_message(message.chat.id, full_message, parse_mode="HTML")
            
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("📝 Оформить пост", callback_data="article:design"),
                InlineKeyboardButton("🤖 Обработать через ИИ", callback_data="article:ai"),
                InlineKeyboardButton("📱 Пост для ТГ (500 симв.)", callback_data="article:tg"),
                InlineKeyboardButton("📱 Пост для Тредс (400 симв.)", callback_data="article:threads"),
                InlineKeyboardButton("💧 Водяной знак", callback_data="article:watermark")
            )
            kb.add(InlineKeyboardButton("📢 Опубликовать в канале", callback_data="article:publish"))
            bot.send_message(message.chat.id, "🎯 <b>Что сделать с этой статьей?</b>", parse_mode="HTML", reply_markup=kb)
            
        except Exception as e:
            logger.error(f"Error sending article content: {e}")
            if result.get("text"):
                bot.send_message(message.chat.id, f"⚠️ Текст сохранен.\n\n{result['text'][:1000]}...", parse_mode="HTML")
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("📝 Оформить пост", callback_data="article:design"),
                InlineKeyboardButton("🤖 Обработать через ИИ", callback_data="article:ai")
            )
            bot.send_message(message.chat.id, "🎯 <b>Что сделать с этой статьей?</b>", parse_mode="HTML", reply_markup=kb)
            
    except Exception as e:
        logger.error(f"Error processing article: {e}")
        try:
            bot.edit_message_text(f"❌ Ошибка: {str(e)}", message.chat.id, processing_msg.message_id)
        except:
            bot.send_message(message.chat.id, f"❌ Ошибка: {str(e)}", parse_mode="HTML")
    finally:
        loop.close()


# =========================
# HANDLE TEXT
# =========================
@bot.message_handler(content_types=["text"])
def on_text(message):
    uid = message.from_user.id
    text = message.text.strip() if message.text else ""
    st = user_state.get(uid) or {"template": "MN", "step": "idle"}
    
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
    
    tme_match = re.search(r'(?:https?://)?t\.me/([^/]+)/(\d+)', text)
    if tme_match and not message.forward_from_chat:
        username = tme_match.group(1)
        post_id = tme_match.group(2)
        st["original_url"] = text
        st["original_text"] = text
        st["original_text_for_ai"] = text
        st["step"] = "waiting_repost_action"
        user_state[uid] = st
        send_message_with_retry(message.chat.id,
            f"📎 <b>Ссылка на пост обнаружена!</b>\n\n🔗 t.me/{username}/{post_id}",
            parse_mode="HTML", reply_markup=repost_action_kb())
        return
    
    step = st.get("step")
    
    if step == "waiting_ai_text":
        processing_msg = bot.reply_to(message, "🤖 Обрабатываю текст в ИИ...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_text_with_deepseek(text))
            bot.delete_message(message.chat.id, processing_msg.message_id)
            send_message_with_retry(message.chat.id, f"✍️ <b>Результат:</b>\n\n{result}", parse_mode="HTML", reply_markup=main_menu_kb())
        except Exception as e:
            bot.delete_message(message.chat.id, processing_msg.message_id)
            send_message_with_retry(message.chat.id, f"❌ Ошибка: {e}", reply_markup=main_menu_kb())
        finally:
            loop.close()
        clear_state(uid)
        return
    
    if step == "waiting_title":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = clean_markdown(text)
        if "body_raw" not in st:
            st["body_raw"] = ""
        user_state[uid] = st
        try:
            card = make_card(st["photo_bytes"], st["title"], st.get("template", "MN"), 
                            text_position=st.get("text_position", TEXT_POSITION_TOP),
                            bold_phrase=st.get("bold_phrase", ""))
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_html(st["title"], st["body_raw"])
            send_photo_with_retry(message.chat.id, BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
            bot.reply_to(message, "Превью готово ✅")
        except Exception as e:
            logger.error(f"Error creating card: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    if step == "waiting_title_am2":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = text
        st["body_raw"] = text
        st["step"] = "waiting_date_place_choice_am2"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n📅 <b>Добавить дату и место?</b>", parse_mode="HTML", reply_markup=add_date_place_kb())
        return
    
    if step == "waiting_date_am2":
        st["date"] = text
        st["step"] = "waiting_place_am2"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Дата: {text}\n\n✏️ <b>Введи МЕСТО</b>:", parse_mode="HTML")
        return
    
    if step == "waiting_place_am2":
        st["place"] = text
        st["step"] = "waiting_highlight_word_am2"
        user_state[uid] = st
        try:
            card = create_poster_am2(st["photo_bytes"], st.get("title", ""), st.get("text_position", "top"), st.get("date", ""), st.get("place", ""), "", "", None, False)
            st["preview_bytes"] = card.getvalue()
            user_state[uid] = st
            bot.send_photo(message.chat.id, photo=BytesIO(st["preview_bytes"]),
                caption=f"✅ <b>Предпросмотр</b>\n\n✏️ <b>Напиши СЛОВО для выделения цветом</b>\n(или «-» чтобы пропустить):",
                parse_mode="HTML")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
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
            bot.send_photo(message.chat.id, photo=BytesIO(st["card_bytes"]), caption="🎉 <b>Афиша готова!</b>", parse_mode="HTML", reply_markup=preview_kb())
        except Exception as e:
            logger.error(f"Error: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    if step == "waiting_title_fdr_post":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = text
        st["body_raw"] = text
        st["step"] = "waiting_highlight_phrase_fdr_post"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n✏️ Теперь отправь слова для выделения цветом (через пробел):", parse_mode="HTML")
        return
    
    if step == "waiting_highlight_phrase_fdr_post":
        st["highlight_phrase"] = text
        try:
            card = make_card(st["photo_bytes"], st["title"], "FDR_POST", highlight_phrase=st["highlight_phrase"])
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_html(st["title"], st["body_raw"])
            send_photo_with_retry(message.chat.id, BytesIO(card.getvalue()), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
        except Exception as e:
            logger.error(f"Error creating FDR_POST card: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    if step == "waiting_title_fdr":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = text
        st["step"] = "waiting_body_fdr"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n✏️ Теперь отправь основной текст для сторис:", parse_mode="HTML")
        return
    
    if step == "waiting_body_fdr":
        try:
            card = make_card_fdr_story(st["photo_bytes"], st["title"], text)
            st["card_bytes"] = card.getvalue()
            st["body_raw"] = text
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_html(st["title"], st["body_raw"])
            send_photo_with_retry(message.chat.id, BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML", reply_markup=preview_kb())
            bot.reply_to(message, "Превью готово ✅")
        except Exception as e:
            logger.error(f"Error creating FDR_STORY card: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    else:
        user_state[uid] = st
        send_message_with_retry(message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())


# =========================
# HANDLE PHOTO
# =========================
@bot.message_handler(content_types=["photo", "document"])
def on_photo_or_document(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    
    if hasattr(message, 'media_group_id') and message.media_group_id:
        media_group_id = message.media_group_id
        if media_group_id not in user_album_cache:
            user_album_cache[media_group_id] = {
                "photos": [], "videos": [], "caption": "",
                "start_time": time.time(), "message_id": message.message_id, "chat_id": message.chat.id
            }
        if message.photo:
            try:
                file_id = message.photo[-1].file_id
                photo_bytes = tg_file_bytes(file_id)
                if check_file_size(photo_bytes):
                    user_album_cache[media_group_id]["photos"].append(photo_bytes)
            except Exception as e:
                logger.error(f"Error extracting photo from album: {e}")
        if message.caption:
            user_album_cache[media_group_id]["caption"] = message.caption
        threading.Thread(target=process_album_with_media, args=(uid, media_group_id, message.chat.id, False), daemon=True).start()
        return
    
    if st.get("step") == "waiting_enhance_photo":
        try:
            file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимум 20MB.")
                return
            processing_msg = bot.reply_to(message, "⏳ Улучшаю качество...")
            enhanced = enhance_image_simple(photo_bytes)
            bot.send_document(message.chat.id, document=enhanced, visible_file_name="enhanced_photo.jpg", caption="✨ Фото улучшено!")
            bot.delete_message(message.chat.id, processing_msg.message_id)
            clear_state(uid)
            return
        except Exception as e:
            logger.error(f"Error enhancing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
            return
    
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
            bot.reply_to(message, f"❌ Ошибка: {e}")
            return
    
    if st.get("step") in ["waiting_photo_am2", "waiting_photo_fdr_post", "waiting_photo_fdr_story", "waiting_photo"]:
        try:
            file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return
            st["photo_bytes"] = photo_bytes
            st["saved_photo_bytes"] = photo_bytes
            
            if st.get("step") == "waiting_photo_am2":
                st["step"] = "waiting_text_position_am2"
                bot.reply_to(message, "📸 Фото сохранено!\n\n📐 <b>Выбери расположение текста:</b>", parse_mode="HTML", reply_markup=text_position_kb_am2())
            elif st.get("step") == "waiting_photo_fdr_post":
                st["step"] = "waiting_title_fdr_post"
                bot.reply_to(message, f"📸 Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b>:", parse_mode="HTML")
            elif st.get("step") == "waiting_photo_fdr_story":
                st["step"] = "waiting_title_fdr"
                bot.reply_to(message, f"📸 Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b> для сторис:", parse_mode="HTML")
            else:
                st["step"] = "waiting_title"
                bot.reply_to(message, f"📸 Фото сохранено!\n\nТеперь отправь <b>ЗАГОЛОВОК</b>:", parse_mode="HTML")
            user_state[uid] = st
            return
        except Exception as e:
            logger.error(f"Error processing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
            return
    
    # Если просто отправили фото
    try:
        file_id = message.photo[-1].file_id if message.content_type == "photo" else message.document.file_id
        photo_bytes = tg_file_bytes(file_id)
        if not check_file_size(photo_bytes):
            bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
            return
        
        st["photo_bytes"] = photo_bytes
        st["saved_photo_bytes"] = photo_bytes
        st["step"] = "waiting_template"
        user_state[uid] = st
        
        bot.reply_to(message, "📸 Фото сохранено!\n\nТеперь выбери шаблон оформления:", reply_markup=template_kb())
        return
    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        bot.reply_to(message, f"❌ Ошибка: {e}")
        return


# =========================
# COMMANDS
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
    
    send_message_with_retry(message.chat.id,
        f"👋 <b>Привет! Я бот для оформления постов</b>\n\n"
        f"<b>📝 Основные функции:</b>\n"
        f"• 📝 Оформление постов с фото (7 шаблонов)\n"
        f"• ✨ Улучшение качества фото\n"
        f"• 💧 Водяные знаки\n"
        f"• 🤖 Текст в ИИ (сокращение до 650 символов)\n"
        f"• 📱 Пост для ТГ (500 символов)\n"
        f"• 📱 Пост для Тредс (400 символов)\n"
        f"• 📰 Извлечение статьи по ссылке (точное копирование)\n"
        f"• 📎 Репосты из каналов\n\n"
        f"<b>📌 Доступные каналы:</b> {channels_text}\n\n"
        f"Выбери действие 👇",
        parse_mode="HTML", reply_markup=main_menu_kb())

@bot.message_handler(commands=["post"])
def cmd_post(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_photo_first"
    user_state[uid] = st
    send_message_with_retry(message.chat.id, "📸 Отправь фото для оформления поста:", reply_markup=main_menu_kb())

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
# GRACEFUL SHUTDOWN
# =========================
def signal_handler(sig, frame):
    logger.info("Shutting down gracefully...")
    try:
        bot.stop_polling()
    except:
        pass
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# =========================
# MAIN
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
                    try:
                        bot.remove_webhook()
                    except:
                        pass
                    time.sleep(30)
                else:
                    time.sleep(10)
                continue
                
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        raise
