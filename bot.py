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
import tempfile
import shutil
import traceback
import subprocess
import random
from io import BytesIO
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin
from collections import defaultdict

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

# Проверка moviepy для видео
try:
    from moviepy import VideoFileClip, ImageSequenceClip
    from moviepy.video.fx import resize
    from moviepy.video.compositing.concatenate import concatenate_videoclips
    from moviepy.audio.io.AudioFileClip import AudioFileClip
    from moviepy.audio.fx.all import audio_loop
except ImportError:
    try:
        from moviepy.video.io.VideoFileClip import VideoFileClip
        from moviepy.video.io.ImageSequenceClip import ImageSequenceClip
        from moviepy.video.compositing.concatenate import concatenate_videoclips
        from moviepy.audio.io.AudioFileClip import AudioFileClip
        from moviepy.audio.fx.all import audio_loop
        try:
            from moviepy.video.fx import resize
        except:
            resize = None
    except:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "moviepy==1.0.3"])
        from moviepy.video.io.VideoFileClip import VideoFileClip
        from moviepy.video.io.ImageSequenceClip import ImageSequenceClip
        from moviepy.video.compositing.concatenate import concatenate_videoclips
        from moviepy.audio.io.AudioFileClip import AudioFileClip
        from moviepy.audio.fx.all import audio_loop
        try:
            from moviepy.video.fx import resize
        except:
            resize = None

try:
    import numpy as np
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "numpy"])
    import numpy as np


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
CHANNEL_PROBNY_MN = (os.getenv("CHANNEL_PROBNY_MN") or "").strip()
CHANNEL_BELTOPOR = (os.getenv("CHANNEL_BELTOPOR") or "").strip()
CHANNEL_MINSKACH = (os.getenv("CHANNEL_MINSKACH") or "").strip()

if CHANNEL_MN and not CHANNEL_MN.startswith("@"):
    CHANNEL_MN = "@" + CHANNEL_MN
if CHANNEL_CHP and not CHANNEL_CHP.startswith("@"):
    CHANNEL_CHP = "@" + CHANNEL_CHP
if CHANNEL_AFISHA and not CHANNEL_AFISHA.startswith("@"):
    CHANNEL_AFISHA = "@" + CHANNEL_AFISHA
if CHANNEL_TEST and not CHANNEL_TEST.startswith("@"):
    CHANNEL_TEST = "@" + CHANNEL_TEST
if CHANNEL_PROBNY_MN and not CHANNEL_PROBNY_MN.startswith("@"):
    CHANNEL_PROBNY_MN = "@" + CHANNEL_PROBNY_MN
if CHANNEL_BELTOPOR and not CHANNEL_BELTOPOR.startswith("@"):
    CHANNEL_BELTOPOR = "@" + CHANNEL_BELTOPOR
if CHANNEL_MINSKACH and not CHANNEL_MINSKACH.startswith("@"):
    CHANNEL_MINSKACH = "@" + CHANNEL_MINSKACH

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

# Форматы видео
VIDEO_FORMATS = {
    "4x5": {"width": 720, "height": 900, "ratio": "4:5"},
    "9x16": {"width": 720, "height": 1280, "ratio": "9:16"}
}

# URL для аудиофайлов на GitHub
AUDIO_URLS = {
    "важная": "https://raw.githubusercontent.com/Dimaceo18/testovaya/main/vajnoe.mp3",
    "обычная": "https://raw.githubusercontent.com/Dimaceo18/testovaya/main/obychnaya.mp3"
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
pending_media_groups = defaultdict(lambda: {"photos": [], "video": None, "caption": "", "processed": False})


# =========================
# UI BUTTONS
# =========================
BTN_POST = "📝 Оформить пост"
BTN_ENHANCE = "✨ Улучшить качество"
BTN_WATERMARK = "💧 Водяные знаки"
BTN_PRICES = "💰 Цены"
BTN_AI_TEXT = "🤖 Текст в ИИ"
BTN_MAKE_VIDEO = "🎬 Сделать видео"
BTN_SLIDESHOW = "🖼 Сделать слайд-шоу"

def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(BTN_POST), KeyboardButton(BTN_AI_TEXT))
    kb.row(KeyboardButton(BTN_ENHANCE), KeyboardButton(BTN_WATERMARK))
    kb.row(KeyboardButton(BTN_PRICES), KeyboardButton(BTN_MAKE_VIDEO))
    kb.row(KeyboardButton(BTN_SLIDESHOW))
    return kb

def repost_action_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Оформить пост", callback_data="repost:design"),
        InlineKeyboardButton("🤖 Обработать через ИИ", callback_data="repost:ai"),
        InlineKeyboardButton("📱 Пост для ТГ (500 симв.)", callback_data="repost:tg"),
        InlineKeyboardButton("📱 Пост для Тредс (400 симв.)", callback_data="repost:threads"),
        InlineKeyboardButton("💧 Нанести водяной знак", callback_data="repost:watermark"),
        InlineKeyboardButton("✏️ Редактировать текст", callback_data="repost:edit"),
        InlineKeyboardButton("🎬 Сделать видео из альбома", callback_data="repost:make_album_video"),
        InlineKeyboardButton("🖼 Сделать слайд-шоу", callback_data="repost:slideshow"),
        InlineKeyboardButton("✂️ Обрезать", callback_data="repost:crop")
    )
    return kb

def after_ai_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Оформить пост", callback_data="ai:design"),
        InlineKeyboardButton("💧 Водяной знак", callback_data="ai:watermark"),
        InlineKeyboardButton("📢 Выбрать канал", callback_data="ai:select_channel"),
        InlineKeyboardButton("🔄 Переделать через ИИ", callback_data="ai:redo"),
        InlineKeyboardButton("✏️ Редактировать текст", callback_data="ai:edit"),
        InlineKeyboardButton("◀️ Вернуться назад", callback_data="ai:back")
    )
    return kb

def post_action_kb(post_type: str = "tg"):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🔄 Переделать еще раз", callback_data=f"{post_type}:redo"),
        InlineKeyboardButton("📝 Оформить пост", callback_data=f"{post_type}:design"),
        InlineKeyboardButton("📢 Выбрать канал", callback_data=f"{post_type}:select_channel"),
        InlineKeyboardButton("✏️ Редактировать текст", callback_data=f"{post_type}:edit"),
        InlineKeyboardButton("◀️ Назад", callback_data=f"{post_type}:back")
    )
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
    if CHANNEL_PROBNY_MN:
        kb.add(InlineKeyboardButton("📰 Пробный МН", callback_data="select_channel:probnym"))
    if CHANNEL_BELTOPOR:
        kb.add(InlineKeyboardButton("🪓 Бел.топор", callback_data="select_channel:beltopor"))
    if CHANNEL_MINSKACH:
        kb.add(InlineKeyboardButton("🏙️ Минскач", callback_data="select_channel:minskach"))
    if CHANNEL_TEST:
        kb.add(InlineKeyboardButton("🧪 ТЕСТОВЫЙ КАНАЛ", callback_data="select_channel:test"))
    kb.add(InlineKeyboardButton("📝 Оформить пост перед публикацией", callback_data="select_channel:design_before_publish"))
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
    if CHANNEL_PROBNY_MN:
        kb.add(InlineKeyboardButton("📰 Пробный МН", callback_data=f"post_channel:{post_type}:probnym"))
    if CHANNEL_BELTOPOR:
        kb.add(InlineKeyboardButton("🪓 Бел.топор", callback_data=f"post_channel:{post_type}:beltopor"))
    if CHANNEL_MINSKACH:
        kb.add(InlineKeyboardButton("🏙️ Минскач", callback_data=f"post_channel:{post_type}:minskach"))
    if CHANNEL_TEST:
        kb.add(InlineKeyboardButton("🧪 ТЕСТОВЫЙ КАНАЛ", callback_data=f"post_channel:{post_type}:test"))
    kb.add(InlineKeyboardButton("📝 Оформить пост перед публикацией", callback_data=f"post_channel:{post_type}:design_before_publish"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data=f"post_channel:{post_type}:cancel"))
    return kb

def watermark_type_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📰 МН (MINSK NEWS)", callback_data="watermark:mn"),
        InlineKeyboardButton("🚨 ЧП (Минск ЧП)", callback_data="watermark:chp"),
        InlineKeyboardButton("🖼️ ЛОГО MN", callback_data="watermark:logo_mn"),
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

# Клавиатуры для создания видео из альбома
def album_video_title_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Оставить заголовок", callback_data="album_video:title_keep"),
        InlineKeyboardButton("✏️ Свой заголовок", callback_data="album_video:title_custom"),
        InlineKeyboardButton("⏭️ Без текста", callback_data="album_video:title_no_text"),
        InlineKeyboardButton("❌ Отмена", callback_data="album_video:cancel")
    )
    return kb

def album_video_audio_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎵 Оставить звук", callback_data="album_video:audio_original"),
        InlineKeyboardButton("📢 Важное", callback_data="album_video:audio_важная"),
        InlineKeyboardButton("🎵 Обычное", callback_data="album_video:audio_обычная"),
        InlineKeyboardButton("🔇 Без звука", callback_data="album_video:audio_silent"),
        InlineKeyboardButton("❌ Отмена", callback_data="album_video:cancel")
    )
    return kb

def album_video_format_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📱 4:5", callback_data="album_video:format_4x5"),
        InlineKeyboardButton("📱 9:16", callback_data="album_video:format_9x16"),
        InlineKeyboardButton("❌ Отмена", callback_data="album_video:cancel")
    )
    return kb

def album_video_mode_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎬 На всё видео", callback_data="album_video:mode_full"),
        InlineKeyboardButton("📌 Только начало (5с)", callback_data="album_video:mode_5sec"),
        InlineKeyboardButton("❌ Отмена", callback_data="album_video:cancel")
    )
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

def send_video_with_retry(chat_id, video, caption=None, parse_mode=None, reply_markup=None, width=None, height=None, max_retries=3):
    """Send an MP4 as a playable Telegram video; retry safely with a fresh stream."""
    if caption and len(caption) > 950:
        caption = caption[:947] + "..."
    if hasattr(video, "getvalue"):
        video_bytes = video.getvalue()
    elif isinstance(video, (bytes, bytearray)):
        video_bytes = bytes(video)
    else:
        video_bytes = None
    for attempt in range(max_retries):
        try:
            if video_bytes is not None:
                payload = BytesIO(video_bytes)
                payload.name = "ready_video.mp4"
            else:
                video.seek(0)
                payload = video
            return bot.send_video(
                chat_id, payload, caption=caption, parse_mode=parse_mode,
                reply_markup=reply_markup, width=width, height=height,
                supports_streaming=True, timeout=120
            )
        except Exception as e:
            logger.exception("Send MP4 attempt %s failed: %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(2 + attempt * 2)
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
    if user_id in pending_media_groups:
        pending_media_groups[user_id] = {"photos": [], "video": None, "caption": "", "processed": False}

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

def clean_title_for_card(title: str) -> str:
    if not title:
        return ""
    clean = remove_emojis(title)
    clean = re.sub(r'\s+', ' ', clean)
    clean = clean.strip()
    return clean

def split_title_and_body(text: str) -> Tuple[str, str]:
    """Выделяет заголовок целиком, не обрывая его на первой точке.

    Заголовок отделяется от текста новости переводом строки (или пустой
    строкой). Несколько предложений в первой строке сохраняются полностью.
    Если разделителя нет, весь переданный текст считается заголовком.
    """
    if not text:
        return "", ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\n" in text:
        title, body = text.split("\n", 1)
        return title.strip(), body.strip()
    return text, ""


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

def extract_title_from_text(text: str) -> str:
    if not text:
        return ""
    
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
    clean_text = emoji_pattern.sub('', text).strip()
    
    title, body = split_title_and_body(clean_text)
    
    return title

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

def crop_to_ratio(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    w, h = img.size
    target_ratio = target_w / target_h
    cur_ratio = w / h
    
    if cur_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        return img.crop((0, top, w, top + new_h))


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
    
    clean_title = clean_title_for_card(title_text)
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
# HELPER FUNCTIONS - ДОБАВИТЬ НОВУЮ ФУНКЦИЮ
# =========================

def strip_html_tags(text: str) -> str:
    """Удаляет HTML-теги из текста."""
    if not text:
        return text
    return re.sub(r'<[^>]+>', '', text)


# =========================
# ФУНКЦИИ ДЛЯ ПРОВЕРКИ ТЕСТОВОГО КАНАЛА
# =========================
def is_test_channel(channel_type: str) -> bool:
    """Проверяет, является ли канал тестовым"""
    return channel_type == "test"

def is_test_channel_by_name(channel_name: str) -> bool:
    """Проверяет, является ли канал тестовым по имени"""
    test_names = ["test", "тестовый", "ТЕСТОВЫЙ"]
    return any(name in channel_name.lower() for name in test_names)

def apply_test_watermark_if_needed(photo_bytes: bytes, channel_type: str = None, channel_name: str = None) -> BytesIO:
    """
    Если канал тестовый, наносит логотип MN.
    Иначе возвращает фото как есть.
    """
    is_test = False
    if channel_type:
        is_test = is_test_channel(channel_type)
    elif channel_name:
        is_test = is_test_channel_by_name(channel_name)
    
    if is_test:
        try:
            logger.info(f"Applying logo watermark for test channel")
            return apply_watermark_logo_mn(photo_bytes)
        except Exception as e:
            logger.error(f"Error applying test watermark: {e}")
            return BytesIO(photo_bytes)
    return BytesIO(photo_bytes)


# =========================
# CARD MAKING FUNCTIONS
# =========================

def make_card_mn(photo_bytes: bytes, title_text: str, text_position: str = TEXT_POSITION_TOP) -> BytesIO:
    ensure_fonts()
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    
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
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    
    clean_bold_phrase = strip_html_tags(bold_phrase) if bold_phrase else ""
    clean_bold_phrase = clean_title_for_card(clean_bold_phrase) if clean_bold_phrase else ""
    
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
    
    text = (clean_title or "").strip().upper()
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
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    
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
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    
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
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    img = apply_top_blur_band(img)
    draw = ImageDraw.Draw(img)
    margin_x = int(img.width * 0.055)
    band_h = int(img.height * AM_TOP_BLUR_PCT)
    safe_w = img.width - 2 * margin_x
    
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
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    return create_poster_am2(photo_bytes, clean_title, text_position, date, place, rubric,
                             highlight_word, highlight_color, is_yellow)

def make_card_fdr_story(photo_bytes: bytes, title: str, body_text: str) -> BytesIO:
    ensure_fonts()
    clean_title = strip_html_tags(title)
    clean_title = clean_title_for_card(clean_title)
    clean_body = strip_html_tags(body_text)
    clean_body = clean_markdown(clean_body)
    
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
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    
    clean_highlight = strip_html_tags(highlight_phrase) if highlight_phrase else ""
    clean_highlight = clean_title_for_card(clean_highlight) if clean_highlight else ""
    
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.Resampling.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    draw = ImageDraw.Draw(img)
    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    safe_w = img.width - 2 * margin_x
    
    title_text_upper = clean_title.strip().upper()
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
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    
    clean_bold_phrase = strip_html_tags(bold_phrase) if bold_phrase else ""
    clean_bold_phrase = clean_title_for_card(clean_bold_phrase) if clean_bold_phrase else ""
    
    clean_highlight_phrase = strip_html_tags(highlight_phrase) if highlight_phrase else ""
    clean_highlight_phrase = clean_title_for_card(clean_highlight_phrase) if clean_highlight_phrase else ""
    
    if template == "CHP":
        return make_card_chp(photo_bytes, clean_title, text_position)
    if template == "AM":
        return make_card_am(photo_bytes, clean_title)
    if template == "AM2":
        return make_card_am2(photo_bytes, clean_title, text_position, date, place, rubric,
                            highlight_word, highlight_color, is_yellow)
    if template == "FDR_STORY":
        return make_card_fdr_story(photo_bytes, clean_title, body_text)
    if template == "FDR_POST":
        return make_card_fdr_post(photo_bytes, clean_title, clean_highlight_phrase)
    if template == "MN_TG":
        return make_card_mn_tg(photo_bytes, clean_title, text_position)
    if template == "MN2":
        return make_card_mn2(photo_bytes, clean_title, text_position, clean_bold_phrase)
    return make_card_mn(photo_bytes, clean_title, text_position)


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

def apply_watermark_probnym(photo_bytes: bytes) -> BytesIO:
    try:
        img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
        img_width, img_height = img.size
        watermark = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(watermark)
        font_size = 24
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
        draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, 38))
        result = Image.alpha_composite(img, watermark)
        result = result.convert("RGB")
        output = BytesIO()
        result.save(output, format="JPEG", quality=95, optimize=True)
        output.seek(0)
        return output
    except Exception as e:
        logger.error(f"Error applying probnym watermark: {e}")
        return BytesIO(photo_bytes)

def apply_watermark_logo_mn(photo_bytes: bytes) -> BytesIO:
    """Наносит логотип MN в правом верхнем углу с прозрачностью 15% и размером 10% от ширины фото"""
    try:
        img = Image.open(BytesIO(photo_bytes)).convert("RGBA")
        img_width, img_height = img.size
        
        logo_path = "logomn.png"
        if not os.path.exists(logo_path):
            logger.error(f"❌ Файл логотипа {logo_path} не найден!")
            raise FileNotFoundError(f"Логотип {logo_path} не найден")
        
        logo = Image.open(logo_path).convert("RGBA")
        
        logo_size = int(img_width * 0.10)
        logo_width, logo_height = logo.size
        
        if logo_width > logo_height:
            new_width = logo_size
            new_height = int(logo_height * (logo_size / logo_width))
        else:
            new_height = logo_size
            new_width = int(logo_width * (logo_size / logo_height))
        
        logo = logo.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        alpha = logo.split()[3]
        alpha = alpha.point(lambda p: int(p * 0.15))
        logo.putalpha(alpha)
        
        margin = 20
        x = img_width - new_width - margin
        y = margin
        
        img.paste(logo, (x, y), logo)
        img = img.convert("RGB")
        
        output = BytesIO()
        img.save(output, format="PNG", quality=95, optimize=True)
        output.seek(0)
        return output
        
    except Exception as e:
        logger.error(f"Error applying logo watermark: {e}")
        raise


# =========================
# ФУНКЦИИ DEEPSEEK
# =========================
async def process_text_with_deepseek(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    prompt = f"""Ты редактор новостного сайта. Перепиши новость в строгом городском формате.

📌 Ограничения:
- Весь текст: ~650 символов
- ЗАГОЛОВОК: максимум 150 символов (обязательно!)
- Основной текст: остальные символы

Убери лишнюю воду, сделай интересный заголовок. Не используй символы # и **.

📌 Исходный текст:

{text}"""
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты редактор новостного сайта. Отвечай только готовым новостным текстом, без пояснений."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.7,
                    "max_tokens": 1000
                }
            )
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"]
                result = re.sub(r'^Вот.*?:', '', result, flags=re.IGNORECASE)
                result = re.sub(r'^#+\s+', '', result, flags=re.MULTILINE)
                result = result.strip()
                return result
            return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка при обращении к API: {str(e)}"


async def detect_emoji_with_ai(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return detect_topic_emoji_local(text)
    
    prompt = f"""Определи категорию новости и выбери один подходящий эмодзи.

Категории новостей:
- ДТП, аварии, происшествия → 🚨
- Авиация, Белавиа, рейсы → ✈️
- Транспорт, метро, автобусы → 🚇
- Банки, финансы, кредиты, деньги → 💳
- Скидки, распродажи, акции → 🏷️
- Концерты, афиша, выставки → 🎫
- Погода, шторм, снег, дождь → 🌦️
- Медицина, больницы, здоровье → 🏥
- Технологии, смартфоны, гаджеты → 📱
- Космос, наука, открытия → 🚀
- Образование, школы, университеты → 🎓
- Спорт, футбол, хоккей → ⚽
- Еда, рестораны, кулинария → 🍔
- Строительство, ремонт, ЖКХ → 🏠
- Экология, природа, парки → 🌿
- Бизнес, экономика, рынок → 💼

Текст новости:
{text}

Верни ТОЛЬКО один эмодзи, без пояснений."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты классификатор новостей. Отвечай только одним эмодзи."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 10
                }
            )
            
            if response.status_code == 200:
                result = response.json()["choices"][0]["message"]["content"].strip()
                emoji_pattern = re.compile(r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251\u2600-\u27BF]+')
                if emoji_pattern.match(result):
                    return result
                found = emoji_pattern.search(result)
                if found:
                    return found.group()
                return detect_topic_emoji_local(text)
            else:
                return detect_topic_emoji_local(text)
        except Exception as e:
            logger.error(f"Error detecting emoji with AI: {e}")
            return detect_topic_emoji_local(text)


def detect_topic_emoji_local(text: str) -> str:
    text_lower = text.lower()
    topics = {
        "🚨": ["дтп", "авар", "пожар", "взрыв", "происшеств", "чп", "полици", "милици", "скорая", "мчс", "катастроф", "пострада"],
        "✈️": ["белавиа", "рейс", "аэропорт", "самолет", "полет", "авиа", "борт"],
        "🚇": ["метро", "станци", "маршрут", "автобус", "троллейбус", "трамвай", "транспорт", "перекрыт", "дорог"],
        "💳": ["банк", "технобанк", "карта", "налог", "выплат", "деньги", "финанс", "кредит", "валюта", "рубль"],
        "🏷️": ["скидк", "распрод", "акци", "дешев", "бесплат", "цена", "стоимость", "продаж"],
        "🎫": ["концерт", "афиша", "выставк", "фестиваль", "мероприят", "кино", "театр", "билет", "аншлаг"],
        "🌦️": ["погод", "шторм", "ветер", "снег", "дожд", "гроз", "температур", "мороз", "жара", "тепло", "холод"],
        "🏥": ["больниц", "врач", "здоров", "вакцин", "лекарств", "медицин", "пациент", "операц"],
        "📱": ["смартфон", "айфон", "телефон", "гаджет", "технологи", "приложен"],
        "🚀": ["космос", "спутник", "наук", "исследован", "открыт", "изобрет"],
        "🎓": ["образован", "школ", "университет", "студент", "учител", "экзамен", "урок", "знан"],
        "⚽": ["футбол", "спорт", "хоккей", "чемпионат", "матч", "команд", "побед"],
        "🍔": ["еда", "ресторан", "кафе", "блюд", "кулинар", "продукт", "вкусн"],
        "🏠": ["строительств", "ремонт", "квартир", "жкх", "коммунал", "дом", "общежи"],
        "🌿": ["эколог", "природ", "зелен", "парк", "дерев", "цвет"],
        "💼": ["бизнес", "компани", "предприят", "рынок", "торговл", "экономик", "долг", "сделк"],
    }
    for emoji, keywords in topics.items():
        for keyword in keywords:
            if keyword in text_lower:
                return emoji
    return "📰"


async def process_text_with_deepseek_tg(text: str) -> str:
    if not DEEPSEEK_API_KEY:
        return "❌ API ключ DeepSeek не настроен."
    
    text_length = len(text)
    
    if text_length <= 200:
        prompt = f"""Ты редактор новостного канала. Перефразируй этот короткий текст, сохранив его смысл и длину (не более {text_length + 20} символов).

Правила:
1. Сохрани ВСЮ ключевую информацию
2. НЕ изменяй суть текста
3. Сделай текст более живым и читаемым
4. Заголовок сделай жирным с помощью <b> и отдельной строкой. Заголовок НЕ БОЛЕЕ 150 СИМВОЛОВ!
5. НЕ используй эмодзи в тексте (эмодзи добавится автоматически)
6. НЕ используй многоточие
7. Сохрани примерно ту же длину текста

Формат:
<b>Заголовок (не более 150 символов)</b>

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
                            {"role": "system", "content": "Ты редактор новостного канала. Перефразируй короткий текст, сохраняя смысл и длину. Заголовок не более 150 символов. Отвечай только готовым постом. Используй <b> для заголовка."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.4,
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
                            if first_line and len(first_line) < 150:
                                result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                            else:
                                first_line = first_line[:147] + "..."
                                result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                    
                    title_match = re.search(r'<b>(.*?)</b>', result)
                    if title_match:
                        title = title_match.group(1)
                        if len(title) > 150:
                            new_title = title[:147] + "..."
                            result = result.replace(f"<b>{title}</b>", f"<b>{new_title}</b>")
                    
                    emoji = await detect_emoji_with_ai(result)
                    result = f"{emoji} {result}"
                    
                    return result
                    
            except Exception as e:
                logger.error(f"Error processing short text: {e}")
    
    prompt = f"""Ты редактор новостного канала. Сократи текст новости до 500 символов.

Правила:
1. Текст не более 500 символов
2. Сохрани ВСЮ ключевую информацию
3. Заголовок сделай жирным с помощью <b> и отдельной строкой. Заголовок НЕ БОЛЕЕ 150 СИМВОЛОВ!
4. Разбей текст на абзацы
5. НЕ используй эмодзи в тексте
6. НЕ используй многоточие

Формат:
<b>Заголовок (не более 150 символов)</b>

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
                        {"role": "system", "content": "Ты редактор новостного канала. Сокращай новости до 500 символов. Заголовок не более 150 символов. Отвечай только готовым постом. Используй <b> для заголовка."},
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
                        if first_line and len(first_line) < 150:
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                        else:
                            first_line = first_line[:147] + "..."
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                
                title_match = re.search(r'<b>(.*?)</b>', result)
                if title_match:
                    title = title_match.group(1)
                    if len(title) > 150:
                        new_title = title[:147] + "..."
                        result = result.replace(f"<b>{title}</b>", f"<b>{new_title}</b>")
                
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
                
                emoji = await detect_emoji_with_ai(result)
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
    
    text_length = len(text)
    
    if text_length <= 200:
        prompt = f"""Ты редактор для Threads. Перефразируй этот короткий текст, сохранив его смысл и длину (не более {text_length + 20} символов).

Правила:
1. Сохрани ВСЮ ключевую информацию
2. НЕ изменяй суть текста
3. Сделай текст более живым и вовлекающим для Threads
4. Заголовок сделай жирным с помощью <b> и отдельной строкой. Заголовок НЕ БОЛЕЕ 150 СИМВОЛОВ!
5. НЕ используй эмодзи в тексте (эмодзи добавится автоматически)
6. НЕ используй многоточие
7. Сохрани примерно ту же длину текста

Формат:
<b>Заголовок (не более 150 символов)</b>

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
                            {"role": "system", "content": "Ты редактор для Threads. Перефразируй короткий текст, сохраняя смысл и длину. Заголовок не более 150 символов. Отвечай только готовым постом. Используй <b> для заголовка."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.5,
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
                            if first_line and len(first_line) < 150:
                                result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                            else:
                                first_line = first_line[:147] + "..."
                                result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                    
                    title_match = re.search(r'<b>(.*?)</b>', result)
                    if title_match:
                        title = title_match.group(1)
                        if len(title) > 150:
                            new_title = title[:147] + "..."
                            result = result.replace(f"<b>{title}</b>", f"<b>{new_title}</b>")
                    
                    emoji = await detect_emoji_with_ai(result)
                    result = f"{emoji} {result}"
                    
                    return result
                    
            except Exception as e:
                logger.error(f"Error processing short text for Threads: {e}")
    
    prompt = f"""Ты редактор для Threads. Сократи текст новости до 400 символов.

Правила:
1. Текст не более 400 символов
2. Сохрани ВСЮ ключевую информацию
3. Заголовок сделай жирным с помощью <b> и отдельной строкой. Заголовок НЕ БОЛЕЕ 150 СИМВОЛОВ!
4. Разбей текст на абзацы
5. НЕ используй эмодзи в тексте
6. НЕ используй многоточие

Формат:
<b>Заголовок (не более 150 символов)</b>

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
                        {"role": "system", "content": "Ты редактор для Threads. Сокращай новости до 400 символов. Заголовок не более 150 символов. Отвечай только готовым постом. Используй <b> для заголовка."},
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
                        if first_line and len(first_line) < 150:
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                        else:
                            first_line = first_line[:147] + "..."
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                
                title_match = re.search(r'<b>(.*?)</b>', result)
                if title_match:
                    title = title_match.group(1)
                    if len(title) > 150:
                        new_title = title[:147] + "..."
                        result = result.replace(f"<b>{title}</b>", f"<b>{new_title}</b>")
                
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
                
                emoji = await detect_emoji_with_ai(result)
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
    
    text_length = len(text)
    
    if text_length <= 200:
        prompt = f"""Ты редактор новостного канала. Переделай этот короткий текст в НОВЫЙ пост, сохранив смысл и длину (не более {text_length + 20} символов).

Правила:
1. Сохрани ВСЮ ключевую информацию
2. НЕ изменяй суть текста
3. Заголовок: новый, сделай жирным с помощью <b> и отдельной строкой. Заголовок НЕ БОЛЕЕ 150 СИМВОЛОВ!
4. НЕ используй эмодзи в тексте
5. НЕ используй многоточие

Формат:
<b>Новый заголовок (не более 150 символов)</b>

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
                            {"role": "system", "content": "Ты редактор новостного канала. Переделывай короткие тексты в новые посты, сохраняя смысл и длину. Заголовок не более 150 символов. Используй <b> для заголовка."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.4,
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
                            if first_line and len(first_line) < 150:
                                result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                            else:
                                first_line = first_line[:147] + "..."
                                result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                    
                    title_match = re.search(r'<b>(.*?)</b>', result)
                    if title_match:
                        title = title_match.group(1)
                        if len(title) > 150:
                            new_title = title[:147] + "..."
                            result = result.replace(f"<b>{title}</b>", f"<b>{new_title}</b>")
                    
                    emoji = await detect_emoji_with_ai(result)
                    result = f"{emoji} {result}"
                    
                    return result
                    
            except Exception as e:
                logger.error(f"Error redoing short text: {e}")
    
    prompt = f"""Ты редактор новостного канала. Переделай эту новость в НОВЫЙ пост для Telegram.

Правила:
1. Текст не более 500 символов
2. Сохрани ВСЮ ключевую информацию
3. Заголовок: новый, сделай жирным с помощью <b> и отдельной строкой. Заголовок НЕ БОЛЕЕ 150 СИМВОЛОВ!
4. НЕ используй эмодзи в тексте
5. НЕ используй многоточие

Формат:
<b>Новый заголовок (не более 150 символов)</b>

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
                        {"role": "system", "content": "Ты редактор новостного канала. Переделывай новости в новые посты до 500 символов. Заголовок не более 150 символов. Используй <b> для заголовка."},
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
                        if first_line and len(first_line) < 150:
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                        else:
                            first_line = first_line[:147] + "..."
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                
                title_match = re.search(r'<b>(.*?)</b>', result)
                if title_match:
                    title = title_match.group(1)
                    if len(title) > 150:
                        new_title = title[:147] + "..."
                        result = result.replace(f"<b>{title}</b>", f"<b>{new_title}</b>")
                
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
                
                emoji = await detect_emoji_with_ai(result)
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
    
    text_length = len(text)
    
    if text_length <= 200:
        prompt = f"""Ты редактор для Threads. Переделай этот короткий текст в НОВЫЙ пост, сохранив смысл и длину (не более {text_length + 20} символов).

Правила:
1. Сохрани ВСЮ ключевую информацию
2. НЕ изменяй суть текста
3. Заголовок: новый, интригующий, сделай жирным с помощью <b> и отдельной строкой. Заголовок НЕ БОЛЕЕ 150 СИМВОЛОВ!
4. НЕ используй эмодзи в тексте
5. НЕ используй многоточие

Формат:
<b>Новый заголовок (не более 150 символов)</b>

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
                            {"role": "system", "content": "Ты редактор для Threads. Переделывай короткие тексты в новые посты, сохраняя смысл и длину. Заголовок не более 150 символов. Используй <b> для заголовка."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.5,
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
                            if first_line and len(first_line) < 150:
                                result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                            else:
                                first_line = first_line[:147] + "..."
                                result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                    
                    title_match = re.search(r'<b>(.*?)</b>', result)
                    if title_match:
                        title = title_match.group(1)
                        if len(title) > 150:
                            new_title = title[:147] + "..."
                            result = result.replace(f"<b>{title}</b>", f"<b>{new_title}</b>")
                    
                    emoji = await detect_emoji_with_ai(result)
                    result = f"{emoji} {result}"
                    
                    return result
                    
            except Exception as e:
                logger.error(f"Error redoing short text for Threads: {e}")
    
    prompt = f"""Ты редактор для Threads. Переделай эту новость в НОВЫЙ пост для Threads.

Правила:
1. Текст не более 400 символов
2. Сохрани ВСЮ ключевую информацию
3. Заголовок: новый, интригующий, сделай жирным с помощью <b> и отдельной строкой. Заголовок НЕ БОЛЕЕ 150 СИМВОЛОВ!
4. НЕ используй эмодзи в тексте
5. НЕ используй многоточие

Формат:
<b>Новый заголовок (не более 150 символов)</b>

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
                        {"role": "system", "content": "Ты редактор для Threads. Переделывай новости в новые посты до 400 символов. Заголовок не более 150 символов. Используй <b> для заголовка."},
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
                        if first_line and len(first_line) < 150:
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                        else:
                            first_line = first_line[:147] + "..."
                            result = f"<b>{first_line}</b>\n\n" + '\n'.join(lines[1:]).strip()
                
                title_match = re.search(r'<b>(.*?)</b>', result)
                if title_match:
                    title = title_match.group(1)
                    if len(title) > 150:
                        new_title = title[:147] + "..."
                        result = result.replace(f"<b>{title}</b>", f"<b>{new_title}</b>")
                
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
                
                emoji = await detect_emoji_with_ai(result)
                result = f"{emoji} {result}"
                
                if len(result) > 400:
                    result = result[:400]
                
                return result
                
            return f"❌ Ошибка API: {response.status_code}"
        except Exception as e:
            return f"❌ Ошибка: {str(e)}"


async def extract_article_content(url: str) -> Dict[str, any]:
    if not DEEPSEEK_API_KEY:
        return {
            "text": "❌ API ключ DeepSeek не настроен. Добавьте DEEPSEEK_API_KEY в переменные окружения.",
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
4. Убери подписи к фото, авторские права
5. Убери комментарии и блоки "похожие статьи"
6. Сохрани структуру абзацев (расставь переносы строк между абзацами)
7. НЕ ИЗМЕНЯЙ ТЕКСТ - верни его точно таким же, как на сайте
8. НЕ сокращай, НЕ переписывай, НЕ редактируй текст
9. Верни полный текст статьи без изменений
10. Если на странице есть заголовок статьи - включи его в начало текста

Верни только текст статьи, без пояснений.
"""

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                DEEPSEEK_API_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "Ты помощник по извлечению контента. Ты умеешь читать веб-страницы по ссылкам и извлекать из них чистый текст. Отвечай только извлеченным текстом статьи, без пояснений. НЕ переписывай текст, только извлекай."},
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
            "text": "❌ Превышено время ожидания при извлечении статьи. Попробуйте позже или отправьте текст вручную.",
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
# ОБРАБОТЧИК АЛЬБОМОВ
# =========================
_album_lock = threading.RLock()
_album_timers = {}
ALBUM_QUIET_SECONDS = 5.0

def _receive_album_item(message, uid, is_repost=False):
    """Collect an album safely: concurrent Telegram handlers cannot pop each other's data."""
    key = f"{message.chat.id}:{uid}:{message.media_group_id}"
    file_id = message.photo[-1].file_id if message.photo else None
    media_type = "photo" if file_id else "video"
    item = None
    failure = False
    try:
        if media_type == "photo":
            # Retry transient Telegram file errors instead of silently dropping a photo.
            for attempt in range(3):
                try:
                    item = tg_file_bytes(file_id)
                    if not check_file_size(item):
                        raise ValueError("Фотография превышает ограничение размера")
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(0.7 * (attempt + 1))
        elif message.video:
            item = get_video_info(message.video.file_id, message.video)
    except Exception:
        failure = True
        logger.exception("ALBUM: media download failed id=%s msg=%s", key, message.message_id)
    with _album_lock:
        album = user_album_cache.setdefault(key, {"photos": [], "videos": [], "caption": "",
                                                     "chat_id": message.chat.id, "received": 0, "failures": 0})
        album["received"] += 1
        if message.caption and not album["caption"]:
            album["caption"] = message.caption
        if failure:
            album["failures"] += 1
        elif item is not None:
            album["photos" if media_type == "photo" else "videos"].append((message.message_id, item))
        timer = _album_timers.pop(key, None)
        if timer is not None:
            timer.cancel()
        timer = threading.Timer(ALBUM_QUIET_SECONDS, process_album_with_media,
                                args=(uid, key, message.chat.id, is_repost))
        timer.daemon = True
        _album_timers[key] = timer
        timer.start()
        logger.info("ALBUM: collected id=%s messages=%s photos=%s videos=%s", key,
                    album["received"], len(album["photos"]), len(album["videos"]))

def process_album_with_media(uid: int, media_group_id: str, chat_id: int, is_repost: bool = False):
    # One collector per album, finalized only after a quiet period.
    with _album_lock:
        album_data = user_album_cache.pop(media_group_id, None)
        _album_timers.pop(media_group_id, None)
    if album_data is None:
        return
    album_data["photos"] = [data for _, data in sorted(album_data.get("photos", []))]
    album_data["videos"] = [data for _, data in sorted(album_data.get("videos", []))]
    logger.info("ALBUM: finalized id=%s received=%s photos=%s videos=%s failures=%s", media_group_id,
                album_data.get("received", 0), len(album_data["photos"]),
                len(album_data["videos"]), album_data.get("failures", 0))
    st = user_state.get(uid) or {}
    # A new album is a NEW media batch: never inherit photos/videos/text
    # from an earlier post, including when the current album contains video only.
    for stale in ("album_photos", "album_videos", "photo_bytes", "saved_photo_bytes",
                  "video_info", "video_file_id", "slideshow_photos", "slideshow_videos",
                  "title", "body_raw", "original_text", "original_text_for_ai"):
        st.pop(stale, None)
    
    caption = album_data.get("caption", "")
    photos = album_data.get("photos", [])
    videos = album_data.get("videos", [])
    
    if album_data.get("failures"):
        send_message_with_retry(chat_id, f"⚠️ Не удалось загрузить {album_data['failures']} файлов альбома. Попробуйте переслать альбом ещё раз, если фотографий меньше ожидаемого.")
    if caption:
        title, body = split_title_and_body(caption)
        st["title"] = clean_title_for_card(title)
        st["body_raw"] = body
        st["original_text"] = caption
        st["original_text_for_ai"] = caption
    
    st["media_group"] = {"photos": photos, "videos": videos}
    
    if photos:
        st["photo_bytes"] = photos[0]
        st["saved_photo_bytes"] = photos[0]
        st["album_photos"] = photos
        logger.info(f"Saved {len(photos)} photos for user {uid}")
    
    if videos:
        st["video_info"] = videos[0]
        st["video_file_id"] = videos[0].get('file_id')
        st["album_videos"] = videos
        logger.info(f"Saved {len(videos)} videos for user {uid}, file_id: {st['video_file_id']}")
    
    if videos and not photos:
        st["video_file_id"] = videos[0].get('file_id')
    
    st["card_bytes"] = None
    direct_album_video = st.get("step") == "direct_video_wait"
    st["step"] = "waiting_repost_action"
    user_state[uid] = st
    if direct_album_video and photos:
        st["original_caption"] = caption
        st["album_photos"] = photos
        st["title"] = extract_title_from_text(caption) if caption else ""
        st["step"] = "video_from_album"
        user_state[uid] = st
        send_message_with_retry(chat_id,
            f"🎬 Получено {len(photos)} фото. Создадим из них один MP4-ролик.\n\nВыберите заголовок:",
            reply_markup=album_video_title_kb())
        return

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


# =========================
# ВИДЕО ИЗ АЛЬБОМА
# =========================

def process_album_to_video(uid: int, media_group_id: str, chat_id: int):
    """Создание видео из всех фото альбома"""
    time.sleep(2)
    
    if media_group_id not in user_album_cache:
        bot.send_message(chat_id, "❌ Альбом не найден")
        return
    
    album_data = user_album_cache.pop(media_group_id)
    photos = album_data.get("photos", [])
    caption = album_data.get("caption", "")
    
    if not photos:
        bot.send_message(chat_id, "❌ В альбоме нет фото для видео")
        return
    
    st = user_state.get(uid) or {}
    st["album_photos"] = photos.copy()
    st["photo_bytes"] = photos[0]
    st["original_caption"] = caption
    if caption:
        title = extract_title_from_text(caption)
        st["title"] = title
    st["step"] = "video_from_album"
    user_state[uid] = st
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Оставить заголовок", callback_data="album_video:title_keep"),
        InlineKeyboardButton("✏️ Свой заголовок", callback_data="album_video:title_custom"),
        InlineKeyboardButton("⏭️ Без текста", callback_data="album_video:title_no_text"),
        InlineKeyboardButton("❌ Отмена", callback_data="album_video:cancel")
    )
    
    title_display = st.get("title", "Без заголовка")
    bot.send_message(
        chat_id,
        f"🎬 <b>Создание видео из {len(photos)} фото</b>\n\n"
        f"📌 <b>Заголовок:</b> {title_display}\n\n"
        f"Выберите действие:",
        parse_mode="HTML",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("album_video:") and not c.data.startswith(("album_video:audio_", "album_video:format_", "album_video:mode_")))
def on_album_video_callback(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "cancel":
        clear_state(uid)
        bot.answer_callback_query(c.id, "❌ Отменено")
        bot.delete_message(c.message.chat.id, c.message.message_id)
        send_message_with_retry(c.message.chat.id, "❌ Отменено", reply_markup=main_menu_kb())
        return
    
    if action == "title_keep":
        if not st.get("title"):
            st["title"] = extract_title_from_text(st.get("original_caption", "")) or "Без заголовка"
        st["no_text"] = False
        bot.answer_callback_query(c.id, f"✅ Заголовок: {st['title'][:30]}...")
        bot.delete_message(c.message.chat.id, c.message.message_id)
        show_album_video_audio_choice(c.message.chat.id, uid)
    
    elif action == "title_custom":
        bot.answer_callback_query(c.id, "✏️ Введите заголовок")
        bot.delete_message(c.message.chat.id, c.message.message_id)
        st["step"] = "album_video_waiting_title"
        user_state[uid] = st
        send_message_with_retry(c.message.chat.id, "✏️ Отправьте текст для заголовка:")
    
    elif action == "title_no_text":
        st["title"] = ""
        st["no_text"] = True
        bot.answer_callback_query(c.id, "⏭️ Без текста")
        bot.delete_message(c.message.chat.id, c.message.message_id)
        show_album_video_audio_choice(c.message.chat.id, uid)


def show_album_video_audio_choice(chat_id, uid):
    st = user_state.get(uid) or {}
    title = st.get("title", "")
    no_text = st.get("no_text", False)
    photos = st.get("album_photos", [])
    
    title_display = "Без текста" if no_text else (title or "Без заголовка")
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎵 Оставить звук", callback_data="album_video:audio_original"),
        InlineKeyboardButton("📢 Важное", callback_data="album_video:audio_важная"),
        InlineKeyboardButton("🎵 Обычное", callback_data="album_video:audio_обычная"),
        InlineKeyboardButton("🔇 Без звука", callback_data="album_video:audio_silent"),
        InlineKeyboardButton("❌ Отмена", callback_data="album_video:cancel")
    )
    
    bot.send_message(
        chat_id,
        f"🎬 <b>Шаг 2/4: Выбор аудио</b>\n\n"
        f"📸 Фото: {len(photos)} шт\n"
        f"📌 Заголовок: {title_display}\n\n"
        f"Выберите аудио:",
        parse_mode="HTML",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("album_video:audio_"))
def on_album_video_audio(c):
    uid = c.from_user.id
    action = c.data.split(":")[1].replace("audio_", "")
    st = user_state.get(uid) or {}
    
    if action == "original":
        st["audio_bytes"] = None
        st["audio_selected"] = "оригинальный звук"
        st["keep_original_audio"] = True
        bot.answer_callback_query(c.id, "🎵 Оригинальный звук")
        bot.delete_message(c.message.chat.id, c.message.message_id)
        show_album_video_format_choice(c.message.chat.id, uid)
    
    elif action == "silent":
        st["audio_bytes"] = None
        st["audio_selected"] = "без звука"
        st["keep_original_audio"] = False
        bot.answer_callback_query(c.id, "🔇 Без звука")
        bot.delete_message(c.message.chat.id, c.message.message_id)
        show_album_video_format_choice(c.message.chat.id, uid)
    
    elif action in ["важная", "обычная"]:
        audio_name = "Важное" if action == "важная" else "Обычное"
        bot.answer_callback_query(c.id, f"⏳ Скачиваю {audio_name}...")
        bot.edit_message_text(f"⏳ Скачиваю аудио '{audio_name}'...", c.message.chat.id, c.message.message_id)
        
        audio_bytes = download_audio_from_github(action)
        if audio_bytes:
            st["audio_bytes"] = audio_bytes
            st["audio_selected"] = audio_name
            st["keep_original_audio"] = False
            bot.edit_message_text(f"✅ Аудио '{audio_name}' загружено!", c.message.chat.id, c.message.message_id)
            show_album_video_format_choice(c.message.chat.id, uid)
        else:
            bot.edit_message_text(f"❌ Не удалось загрузить аудио '{audio_name}'", c.message.chat.id, c.message.message_id)
            show_album_video_audio_choice(c.message.chat.id, uid)


def show_album_video_format_choice(chat_id, uid):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📱 4:5", callback_data="album_video:format_4x5"),
        InlineKeyboardButton("📱 9:16", callback_data="album_video:format_9x16"),
        InlineKeyboardButton("❌ Отмена", callback_data="album_video:cancel")
    )
    
    bot.send_message(
        chat_id,
        "📹 <b>Шаг 3/4: Выбор формата</b>\n\nВыберите формат видео:",
        parse_mode="HTML",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("album_video:format_"))
def on_album_video_format(c):
    uid = c.from_user.id
    action = c.data.split(":")[1].replace("format_", "")
    st = user_state.get(uid) or {}
    
    if action == "4x5":
        st["format"] = "4x5"
        bot.answer_callback_query(c.id, "📱 Формат 4:5")
    elif action == "9x16":
        st["format"] = "9x16"
        bot.answer_callback_query(c.id, "📱 Формат 9:16")
    else:
        return
    
    bot.delete_message(c.message.chat.id, c.message.message_id)
    show_album_video_mode_choice(c.message.chat.id, uid)


def show_album_video_mode_choice(chat_id, uid):
    st = user_state.get(uid) or {}
    photos = st.get("album_photos", [])
    
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎬 На всё видео", callback_data="album_video:mode_full"),
        InlineKeyboardButton("📌 Только начало (5с)", callback_data="album_video:mode_5sec"),
        InlineKeyboardButton("❌ Отмена", callback_data="album_video:cancel")
    )
    
    bot.send_message(
        chat_id,
        f"📹 <b>Шаг 4/4: Выбор режима</b>\n\n"
        f"📸 Фото: {len(photos)} шт\n\n"
        f"• 🎬 Заголовок на всё видео\n"
        f"• 📌 Заголовок только в начале (5 секунд)\n\n"
        f"Выберите режим:",
        parse_mode="HTML",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("album_video:mode_"))
def on_album_video_mode(c):
    uid = c.from_user.id
    action = c.data.split(":")[1].replace("mode_", "")
    st = user_state.get(uid) or {}
    
    if action == "full":
        only_first_seconds = 0
        mode_text = "всё видео"
    elif action == "5sec":
        only_first_seconds = 5
        mode_text = "первые 5 секунд"
    else:
        return
    
    bot.answer_callback_query(c.id, f"✅ Режим: {mode_text}")
    bot.delete_message(c.message.chat.id, c.message.message_id)
    
    create_video_from_album(uid, c.message.chat.id, only_first_seconds)


def create_video_from_album(uid, chat_id, only_first_seconds=0):
    st = user_state.get(uid) or {}
    photos = st.get("album_photos", [])
    title = st.get("title", "")
    no_text = st.get("no_text", False)
    audio_bytes = st.get("audio_bytes")
    audio_selected = st.get("audio_selected", "")
    keep_original_audio = st.get("keep_original_audio", True)
    format_name = st.get("format", "4x5")
    duration_per_photo = 3.0
    
    if not photos:
        bot.send_message(chat_id, "❌ Нет фото для создания видео")
        return
    
    status_msg = bot.send_message(chat_id, f"⏳ <b>Создаю видео из {len(photos)} фото...</b>\n⏳ Это займет 20-60 секунд", parse_mode="HTML")
    
    try:
        import tempfile
        import shutil
        
        temp_dir = tempfile.mkdtemp()
        
        format_config = VIDEO_FORMATS.get(format_name, VIDEO_FORMATS["4x5"])
        target_w = format_config["width"]
        target_h = format_config["height"]
        
        photo_paths = []
        
        for i, photo_bytes in enumerate(photos):
            img = Image.open(BytesIO(photo_bytes)).convert("RGB")
            img = crop_to_ratio(img, target_w, target_h)
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS_FACTOR)
            
            apply_text = (not no_text) and (only_first_seconds == 0 or i == 0)
            
            if apply_text:
                img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
                draw = ImageDraw.Draw(img)
                margin_x = int(img.width * 0.06)
                margin_bottom = int(img.height * 0.08)
                safe_w = img.width - 2 * margin_x
                title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
                
                clean_title = clean_title_for_card(title)
                text = (clean_title or "Без заголовка").strip().upper()
                
                font, lines, heights, spacing, total_h = fit_text_block(
                    draw=draw, text=text, font_path=FONT_CHP, safe_w=safe_w,
                    max_block_h=title_max_h, max_lines=6, start_size=int(img.height * 0.11),
                    min_size=16, line_spacing_ratio=0.22
                )
                
                line_height = font.size
                total_text_height = len(lines) * line_height + (len(lines) - 1) * 2
                y = img.height - margin_bottom - total_text_height
                
                for ln in lines:
                    draw.text((margin_x, y), ln, font=font, fill="white")
                    y += line_height + 2
            else:
                img = apply_bottom_gradient_soft(img, height_pct=0.05, max_alpha=30)
            
            path = os.path.join(temp_dir, f"photo_{i}.png")
            img.save(path)
            photo_paths.append(path)
        
        clips = []
        for path in photo_paths:
            clip = ImageSequenceClip([path], durations=[duration_per_photo])
            try:
                if resize:
                    def make_zoom(t):
                        progress = t / duration_per_photo
                        return 1.0 + 0.1 * (progress * progress * (3 - 2 * progress))
                    clip = clip.fx(resize, make_zoom)
            except:
                pass
            clips.append(clip)
        
        final_clip = concatenate_videoclips(clips)
        
        if audio_bytes:
            try:
                audio_path = os.path.join(temp_dir, "audio.mp3")
                with open(audio_path, 'wb') as f:
                    f.write(audio_bytes)
                
                audio_clip = AudioFileClip(audio_path)
                if audio_clip.duration > final_clip.duration:
                    audio_clip = audio_clip.subclip(0, final_clip.duration)
                else:
                    audio_clip = audio_loop(audio_clip, duration=final_clip.duration)
                
                final_clip = final_clip.set_audio(audio_clip)
            except:
                pass
        
        output_path = os.path.join(temp_dir, "slideshow.mp4")
        final_clip.write_videofile(
            output_path,
            fps=24,
            codec='libx264',
            audio_codec='aac',
            threads=4,
            preset='medium',
            ffmpeg_params=['-pix_fmt', 'yuv420p', '-movflags', '+faststart'],
            logger=None
        )
        
        with open(output_path, 'rb') as f:
            result_bytes = f.read()
        
        output = BytesIO()
        output.write(result_bytes)
        output.seek(0)
        
        caption = st.get("original_caption", "")
        if no_text:
            caption += "\n📌 Без текста"
        elif title:
            caption = f"<b>{title}</b>" if not caption else caption
        if audio_selected and audio_selected != "оригинальный звук":
            caption += f"\n🎵 Аудио: {audio_selected}"
        caption += f"\n📸 {len(photos)} фото"
        caption += f"\n📱 Формат: {'4:5' if format_name == '4x5' else '9:16'}"
        
        sent = send_video_with_retry(
            chat_id,
            BytesIO(output.getvalue()),
            caption=html.escape(re.sub(r"</?b>", "", caption)),
            parse_mode="HTML",
            width=target_w,
            height=target_h
        )
        if sent is None:
            raise RuntimeError("Telegram не принял MP4. Проверьте размер файла и логи отправки.")
        bot.edit_message_text("✅ MP4-видео отправлено в чат!", chat_id, status_msg.message_id)
        
        shutil.rmtree(temp_dir)
        clear_state(uid)
        
    except Exception as e:
        logger.error(f"Error creating video from album: {e}")
        traceback.print_exc()
        bot.edit_message_text(f"❌ Ошибка: {e}", chat_id, status_msg.message_id)


# =========================
# ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ СКАЧИВАНИЯ АУДИО
# =========================

def download_audio_from_github(audio_type: str) -> Optional[bytes]:
    try:
        url = AUDIO_URLS.get(audio_type)
        if not url:
            return None
        
        logger.info(f"⬇️ Скачивание аудио {audio_type}...")
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            logger.info(f"✅ Аудио {audio_type} скачано! Размер: {len(response.content) / 1024:.1f} KB")
            return response.content
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания аудио {audio_type}: {e}")
        return None


# =========================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ДЛЯ ПУБЛИКАЦИИ С ВОДЯНЫМ ЗНАКОМ
# =========================

def send_to_channel_with_watermark(channel, photo_data, caption="", parse_mode="HTML", channel_type=None, channel_name=None):
    """
    Отправляет фото в канал с автоматическим нанесением водяного знака
    для тестового канала.
    """
    if is_test_channel(channel_type) or is_test_channel_by_name(channel_name or ""):
        try:
            watermarked = apply_watermark_logo_mn(photo_data)
            logger.info(f"Applied logo watermark for test channel: {channel}")
            return bot.send_photo(channel, watermarked, caption=caption, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"Error applying watermark in send_to_channel_with_watermark: {e}")
            return bot.send_photo(channel, BytesIO(photo_data), caption=caption, parse_mode=parse_mode)
    else:
        return bot.send_photo(channel, BytesIO(photo_data), caption=caption, parse_mode=parse_mode)


# =========================
# CALLBACK ОБРАБОТЧИКИ
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
    
    if wm_type == "logo_mn":
        if not os.path.exists("logomn.png"):
            bot.answer_callback_query(c.id, "❌ Логотип не найден на сервере!")
            send_message_with_retry(
                c.message.chat.id,
                "❌ Файл логотипа `logomn.png` не найден на сервере.\n"
                "Пожалуйста, загрузите его в корневую папку бота.",
                parse_mode="HTML"
            )
            return
    
    bot.answer_callback_query(c.id, f"✅ Наношу водяной знак {wm_type.upper()}...")
    
    try:
        if wm_type == "mn":
            result = apply_watermark_mn(st["photo_bytes"])
            watermark_name = "MINSK NEWS"
        elif wm_type == "chp":
            result = apply_watermark_chp(st["photo_bytes"])
            watermark_name = "ЧП Минск"
        elif wm_type == "logo_mn":
            result = apply_watermark_logo_mn(st["photo_bytes"])
            watermark_name = "ЛОГО MN"
        else:
            bot.answer_callback_query(c.id, "❌ Неизвестный тип водяного знака")
            return
        
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
            
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        bot.answer_callback_query(c.id, "❌ Логотип не найден!")
        send_message_with_retry(
            c.message.chat.id,
            f"❌ {e}\n\nПожалуйста, загрузите файл `logomn.png` в корневую папку бота.",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error applying watermark: {e}")
        bot.answer_callback_query(c.id, "❌ Ошибка при нанесении водяного знака")
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


# =========================
# КАРУСЕЛЬ НОВОСТИ: 5 СЛАЙДОВ
# =========================
SLIDE_FORMATS = {"4x5": (1080, 1350), "9x16": (1080, 1920), "square": (1080, 1080)}

def slideshow_mode_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🖼 Фото слайд-шоу", callback_data="slideshow:mode_photo"),
           InlineKeyboardButton("🎬 Видео слайд-шоу (MP4)", callback_data="slideshow:mode_video"),
           InlineKeyboardButton("❌ Отмена", callback_data="slideshow:cancel"))
    return kb

def slideshow_format_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("📱 4:5", callback_data="slideshow:4x5"),
           InlineKeyboardButton("📱 9:16", callback_data="slideshow:9x16"),
           InlineKeyboardButton("⬜ Квадрат 1:1", callback_data="slideshow:square"),
           InlineKeyboardButton("❌ Отмена", callback_data="slideshow:cancel"))
    return kb

def slideshow_audio_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🔇 Без звука", callback_data="slideshow:audio_silent"),
           InlineKeyboardButton("📢 Важное", callback_data="slideshow:audio_важная"),
           InlineKeyboardButton("🎵 Обычное", callback_data="slideshow:audio_обычная"),
           InlineKeyboardButton("❌ Отмена", callback_data="slideshow:cancel"))
    return kb

def _slide_font(size, bold=False):
    candidates = (["Montserrat-Black.ttf", "Inter-ExtraBold.ttf"] if bold else
                  ["Inter-Regular.ttf", "Montserrat-Regular.ttf", "DejaVuSans.ttf"])
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, ValueError):
            continue
    return ImageFont.load_default()

def _slide_wrap(draw, text, font, width):
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        current = ""
        for word in paragraph.split():
            candidate = (current + " " + word).strip()
            if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
                # Rare unbroken words: wrap character-by-character.
                if draw.textbbox((0, 0), current, font=font)[2] > width:
                    chunk = ""
                    for ch in current:
                        if chunk and draw.textbbox((0, 0), chunk + ch, font=font)[2] > width:
                            lines.append(chunk)
                            chunk = ch
                        else:
                            chunk += ch
                    current = chunk
        if current:
            lines.append(current)
    return lines

def _slide_lines_height(lines, font_size, gap_ratio=0.34):
    return len(lines) * (font_size + round(font_size * gap_ratio))

def _slide_page_layout(title, chunks, fmt, body_size, title_size):
    w, h = SLIDE_FORMATS[fmt]
    margin = 76 if fmt == "square" else 86
    max_w = w - margin * 2
    dummy = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    body_font = _slide_font(body_size)
    title_font = _slide_font(title_size, True)
    title_lines = _slide_wrap(dummy, title.upper(), title_font, max_w)
    # Title is prominent on first page; reserve sufficient space for it.
    title_h = _slide_lines_height(title_lines, title_size, .20)
    if title_h > h * .40:
        return None
    max_body_h = h - (margin + 100) - 112
    if title:
        max_body_h -= title_h + 32
    lines = [_slide_wrap(dummy, chunk, body_font, max_w) for chunk in chunks]
    return lines, title_lines, title_h, max_body_h

def _slide_remove_trailing_source(body):
    """Remove only a trailing source attribution, preserving article text."""
    body = (body or "").strip()
    # Standalone final line: Источник: ... / Источники: ...
    body = re.sub(r"(?im)\n\s*(?:источник|источники)\s*[:：–—-]\s*[^\n]*\s*$", "", body).strip()
    # Attribution appended to the final paragraph (typically after a full stop).
    body = re.sub(r"(?i)(?<=\.)\s+(?:источник|источники)\s*[:：–—-]\s*[^\n]*\s*$", "", body).strip()
    # Link-only attribution, without colon, on the last line.
    body = re.sub(r"(?im)\n\s*(?:источник|источники)\s+https?://\S+\s*$", "", body).strip()
    return body


def _slide_sentences(body):
    """Keep explicit line breaks (especially lists), split prose only at sentences."""
    body = _slide_remove_trailing_source(body)
    if not body:
        return []
    token = "\uE000"
    units = []
    abbreviations = ("т.д.", "т.п.", "т.е.", "т.к.", "и т.д.", "и т.п.",
                     "г.", "ул.", "д.", "стр.", "им.", "руб.", "млн.", "млрд.",
                     "тыс.", "ок.", "рис.", "см.")
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if units and not units[-1].endswith("\n"):
                units[-1] += "\n"
            continue
        protected = re.sub(r"(?<=\d)\.(?=\d)", token, line)
        for abbr in sorted(abbreviations, key=len, reverse=True):
            protected = re.sub(re.escape(abbr), lambda m: m.group().replace(".", token), protected, flags=re.I)
        pieces = re.split(r'(?<=[.!?…])\s+(?=["«„“(]*[А-ЯЁA-Z0-9])', protected)
        pieces = [x.replace(token, ".").strip() for x in pieces if x.strip()]
        if pieces:
            # Each original source line stays a separate visual line.
            # The final sentence in a line carries the newline to the next unit.
            pieces[-1] += "\n"
            units.extend(pieces)
    if units:
        units[-1] = units[-1].rstrip("\n")
    return units

def _slide_join_units(units):
    result = ""
    for unit in units:
        if result and not result.endswith("\n"):
            result += " "
        result += unit
    return result.strip()

def _slideshow_page_count(photo_count):
    """1-5 photos: 5 slides; 6-10 photos: 10 slides. Exactly 5 -> 5."""
    return 10 if photo_count >= 6 else 5

def _slide_paginate(title, body, fmt, page_count=5):
    sentences = _slide_sentences(body)
    if not sentences:
        raise ValueError("В посте отсутствует текст статьи. Добавьте текст после заголовка.")
    # For a single picture, the article must occupy ALL five slides, in order.
    # If fewer than five complete sentences exist, divide longer sentences into
    # contiguous word groups rather than leaving intermediate pages empty.
    if page_count == 5 and len(sentences) < 5:
        words = _slide_join_units(sentences).split()
        if len(words) >= 5:
            sentences = [" ".join(words[(i * len(words)) // 5:((i + 1) * len(words)) // 5])
                         for i in range(5)]
    w, h = SLIDE_FORMATS[fmt]
    margin = 76 if fmt == "square" else 86
    max_w = w - 2 * margin
    draw = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    # A page boundary is permitted only between complete sentences.
    # Find the largest readable font that fits complete sentences on the requested number of pages.
    for body_size in range(56, 19, -1):
        title_size = min(78, max(45, round(body_size * 1.7)))
        title_font = _slide_font(title_size, True)
        title_lines = _slide_wrap(draw, title.upper(), title_font, max_w)
        title_h = _slide_lines_height(title_lines, title_size, .20)
        if title_h > h * .40:
            continue
        body_font = _slide_font(body_size)
        available = [h - 115 - (156 + title_h + 32)] + [h - 115 - (156 + 56)] * (page_count - 1)
        # Use DP to balance page fill while respecting full sentences.
        n = len(sentences)
        prefix = [0]
        for sentence in sentences:
            prefix.append(prefix[-1] + len(sentence.split()))
        cache = {}
        def fits(start, end, page):
            key = (start, end)
            if key not in cache:
                chunk = _slide_join_units(sentences[start:end])
                lines = _slide_wrap(draw, chunk, body_font, max_w)
                cache[key] = _slide_lines_height(lines, body_size)
            return cache[key] <= available[page]
        # Page 0 may have a smaller capacity due to the headline.
        states = {0: (0.0, [])}
        for page in range(page_count):
            nxt = {}
            for start, (cost, bounds) in states.items():
                for end in range(start, n + 1):
                    if end > start and not fits(start, end, page):
                        break
                    # Encourage spreading text across five slides without splitting sentences.
                    words = prefix[end] - prefix[start]
                    target = prefix[-1] / page_count
                    penalty = ((words - target) / max(target, 1)) ** 2
                    if end == start:
                        # Single-photo slideshows use all five pages, without gaps.
                        if page_count == 5 and n >= 5:
                            continue
                        if start < n:
                            continue
                        penalty = 0.0
                    if page_count == 5 and n >= 5 and n - end < page_count - page - 1:
                        continue
                    score = cost + penalty
                    if end not in nxt or score < nxt[end][0]:
                        nxt[end] = (score, bounds + [(start, end)])
            states = nxt
            if not states:
                break
        if n in states:
            bounds = states[n][1]
            pages = [_slide_join_units(sentences[start:end]) for start, end in bounds]
            return pages, body_size, title_size
    raise ValueError(f"Статья слишком длинная для {page_count} слайдов без разрыва предложений. Сократите текст или используйте более короткие предложения.")

def make_news_slideshow(photos, title, body, fmt):
    if not photos:
        raise ValueError("Для слайд-шоу нужна хотя бы одна фотография.")
    if not title.strip():
        raise ValueError("Не найден заголовок поста.")
    page_count = _slideshow_page_count(len(photos))
    pages, body_size, title_size = _slide_paginate(title, body, fmt, page_count)
    w, h = SLIDE_FORMATS[fmt]
    margin = 76 if fmt == "square" else 86
    results = []
    for i, page in enumerate(pages):
        source = photos[i % len(photos)] if len(photos) > 1 else photos[0]
        with Image.open(BytesIO(source)) as source_img:
            image = crop_to_ratio(source_img.convert("RGB"), w, h).resize((w, h), Image.Resampling.LANCZOS)
        # When the article is short, remaining slides are clean original photos:
        # no darkening, no title, no label, no footer, no page counter.
        if not page.strip():
            out = BytesIO()
            image.save(out, format="JPEG", quality=94, optimize=True)
            out.seek(0)
            out.name = f"news_slide_{i+1}.jpg"
            results.append(out)
            continue
        # Darken only slides that actually contain text.
        image = Image.blend(image, Image.new("RGB", (w, h), (7, 12, 20)), .74)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((margin, 56, margin + 188, 107), radius=12, fill=(245, 210, 70))
        label_font = _slide_font(25, True)
        draw.text((margin + 18, 65), "НОВОСТИ", font=label_font, fill=(12, 16, 22))
        draw.line((margin, h - 115, w - margin, h - 115), fill=(220, 220, 220), width=2)
        footer_font = _slide_font(26, True)
        draw.text((margin, h - 91), "MINSK NEWS", font=footer_font, fill=(240, 240, 240))
        count_text = f"{i+1:02d} / {page_count:02d}"
        bb = draw.textbbox((0, 0), count_text, font=footer_font)
        draw.text((w - margin - (bb[2]-bb[0]), h - 91), count_text, font=footer_font, fill=(240, 240, 240))
        y = 156
        if i == 0:
            tf = _slide_font(title_size, True)
            for line in _slide_wrap(draw, title.upper(), tf, w - margin * 2):
                draw.text((margin, y), line, font=tf, fill=(255, 255, 255))
                y += title_size + round(title_size * .20)
            y += 32
        else:
            sf = _slide_font(26, True)
            draw.text((margin, y), "ПРОДОЛЖЕНИЕ", font=sf, fill=(245, 210, 70))
            y += 56
        bf = _slide_font(body_size)
        for line in _slide_wrap(draw, page, bf, w - margin * 2):
            if line:
                draw.text((margin, y), line, font=bf, fill=(255, 255, 255))
            y += body_size + round(body_size * .34)
        if y > h - 115:
            raise ValueError("Текст не помещается в границы слайда.")
        out = BytesIO()
        image.save(out, format="JPEG", quality=91, optimize=True)
        out.seek(0)
        out.name = f"news_slide_{i+1}.jpg"
        results.append(out)
    return results

_slideshow_encoding_lock = threading.Lock()

def make_news_slideshow_video(slides, audio_type="silent", seconds_per_slide=4):
    """Encode the exact same designed JPEG slides as a Telegram-friendly MP4."""
    import tempfile
    import subprocess
    with tempfile.TemporaryDirectory(prefix="news_slides_") as tmp:
        for i, slide in enumerate(slides):
            with open(os.path.join(tmp, f"slide_{i:02d}.jpg"), "wb") as out:
                out.write(slide.getvalue())
        concat_file = os.path.join(tmp, "slides.txt")
        with open(concat_file, "w", encoding="utf-8") as out:
            for i in range(len(slides)):
                out.write(f"file 'slide_{i:02d}.jpg'\n")
                out.write(f"duration {seconds_per_slide}\n")
            out.write(f"file 'slide_{len(slides)-1:02d}.jpg'\n")
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                   "-safe", "0", "-f", "concat", "-i", concat_file]
        if audio_type != "silent":
            data = download_audio_from_github(audio_type)
            if not data:
                raise ValueError("Не удалось загрузить выбранную музыку.")
            audio_path = os.path.join(tmp, "music.mp3")
            with open(audio_path, "wb") as out:
                out.write(data)
            command += ["-stream_loop", "-1", "-i", audio_path]
        # Keep video encoding within the RAM budget of a small Render instance.
        # The designed JPEG slides remain 1080px; only the MP4 is downscaled.
        # 12 fps is enough for still-image slides and greatly reduces encoder load.
        command += ["-t", str(len(slides) * seconds_per_slide),
                    "-vf", "scale=720:-2:flags=fast_bilinear,setsar=1",
                    "-r", "12", "-threads", "1",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "27",
                    "-x264-params", "threads=1:lookahead-threads=1",
                    "-pix_fmt", "yuv420p"]
        if audio_type != "silent":
            command += ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-b:a", "128k"]
        else:
            command += ["-an"]
        output_path = os.path.join(tmp, "news_slideshow.mp4")
        command += ["-movflags", "+faststart", output_path]
        logger.info("SLIDESHOW: FFmpeg started (low RAM 720px/12fps/1 thread); slides=%d, duration=%ds, audio=%s", len(slides), len(slides) * seconds_per_slide, audio_type)
        started = time.monotonic()
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=240)
            logger.info("SLIDESHOW: FFmpeg completed in %.1fs", time.monotonic() - started)
        except subprocess.TimeoutExpired as exc:
            logger.exception("SLIDESHOW: FFmpeg exceeded 240 seconds")
            raise RuntimeError("Обработка видео превысила 4 минуты. Попробуйте меньше фотографий или другой формат.") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("На сервере не установлен FFmpeg.") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("FFmpeg: " + (exc.stderr or "Ошибка кодирования")[-700:]) from exc
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        logger.info("SLIDESHOW: MP4 ready; size=%.1f MB", size_mb)
        if size_mb > 49:
            raise RuntimeError("Видео получилось больше 49 МБ. Нужна дополнительная компрессия.")
        with open(output_path, "rb") as out:
            video = BytesIO(out.read())
        video.name = "news_slideshow.mp4"
        return video

def _slideshow_video_preview(video_info):
    """Extract a current video's first frame for slideshow image slides."""
    file_id = video_info.get("file_id")
    if not file_id:
        raise ValueError("Не найден идентификатор видео")
    with tempfile.TemporaryDirectory(prefix="slideshow_frame_") as tmp:
        source = os.path.join(tmp, "input_video")
        frame = os.path.join(tmp, "frame.jpg")
        with open(source, "wb") as f:
            f.write(tg_file_bytes(file_id))
        proc = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                               "-ss", "0.5", "-i", source, "-frames:v", "1", frame],
                              capture_output=True, timeout=90)
        if proc.returncode != 0 or not os.path.exists(frame):
            raise RuntimeError("Не удалось получить кадр из видео: " + proc.stderr.decode(errors="replace")[-250:])
        with open(frame, "rb") as f:
            return f.read()


def _start_slideshow(chat_id, uid):
    st = user_state.get(uid) or {}
    batch = st.get("media_group") or {}
    photos = list(batch.get("photos") or [])
    videos = list(batch.get("videos") or [])
    # Standalone forwarded media is also stored in media_group. No fallback
    # to album_photos or saved_photo_bytes, which may belong to an old post.
    if not photos and not videos:
        send_message_with_retry(chat_id, "❌ Сначала отправьте НОВЫЙ пост с фото или видео, затем выберите «Слайд-шоу».")
        return
    title = st.get("title") or ""
    body = st.get("body_raw") or ""
    if not body and st.get("original_text"):
        title, body = split_title_and_body(st["original_text"])
    # Snapshot the new batch so later messages cannot mutate this slideshow.
    st["slideshow_photos"] = photos
    st["slideshow_videos"] = videos
    st["slideshow_title"] = title
    st["slideshow_body"] = body
    st["step"] = "slideshow_mode"
    user_state[uid] = st
    if not body.strip():
        st["step"] = "slideshow_wait_text"
        send_message_with_retry(chat_id, "📝 Отправьте полный текст статьи (заголовок первой строкой, далее текст).")
    else:
        send_message_with_retry(chat_id, "🖼 Выберите тип слайд-шоу:", reply_markup=slideshow_mode_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("slideshow:"))
def on_slideshow_callback(c):
    uid = c.from_user.id
    choice = c.data.split(":", 1)[1]
    bot.answer_callback_query(c.id)
    chat_id = c.message.chat.id
    if choice == "cancel":
        clear_state(uid)
        send_message_with_retry(chat_id, "❌ Создание слайд-шоу отменено.")
        return
    st = user_state.get(uid) or {}
    if choice in ("mode_photo", "mode_video"):
        if st.get("step") != "slideshow_mode":
            send_message_with_retry(chat_id, "⚠️ Сначала отправьте пост и выберите создание слайд-шоу.")
            return
        st["slideshow_mode"] = "video" if choice == "mode_video" else "photo"
        st["step"] = "slideshow_format"
        count = _slideshow_page_count((len(st.get("slideshow_photos") or []) + len(st.get("slideshow_videos") or [])))
        send_message_with_retry(chat_id, f"📐 Выберите размер для {count} слайдов:", reply_markup=slideshow_format_kb())
        return
    if choice in SLIDE_FORMATS:
        if st.get("step") != "slideshow_format":
            send_message_with_retry(chat_id, "⚠️ Сначала выберите тип слайд-шоу.")
            return
        st["slideshow_format"] = choice
        if st.get("slideshow_mode") == "video":
            st["step"] = "slideshow_audio"
            send_message_with_retry(chat_id, "🎵 Выберите музыку для видео:", reply_markup=slideshow_audio_kb())
            return
        audio_type = "silent"
    elif choice.startswith("audio_"):
        if st.get("step") != "slideshow_audio":
            return
        audio_type = choice[len("audio_"):]
        if audio_type not in ("silent", "важная", "обычная"):
            return
    else:
        return
    if st.get("step") == "slideshow_processing":
        return
    st["step"] = "slideshow_processing"
    fmt = st["slideshow_format"]
    mode = st.get("slideshow_mode", "photo")
    count = _slideshow_page_count((len(st.get("slideshow_photos") or []) + len(st.get("slideshow_videos") or [])))
    send_message_with_retry(chat_id, f"⏳ Принято {len(st.get('slideshow_photos') or [])} фото. Создаю {count} слайдов...")
    threading.Thread(target=_slideshow_worker, args=(chat_id, uid, st, fmt, mode, count, audio_type), daemon=True).start()
    return

def _slideshow_worker(chat_id, uid, st, fmt, mode, count, audio_type):
    logger.info("SLIDESHOW: start user=%s count=%s format=%s mode=%s", uid, count, fmt, mode)
    try:
        current_photos = list(st.get("slideshow_photos") or [])
        for video_info in st.get("slideshow_videos") or []:
            current_photos.append(_slideshow_video_preview(video_info))
        slides = make_news_slideshow(current_photos, st["slideshow_title"], st["slideshow_body"], fmt)
        logger.info("SLIDESHOW: images rendered: %d", len(slides))
        if mode == "video":
            send_message_with_retry(chat_id, "🎞 Слайды готовы. Кодирую MP4, это может занять 1–3 минуты...")
            if not _slideshow_encoding_lock.acquire(blocking=False):
                raise RuntimeError("Другое слайд-шоу уже кодируется. Повторите запрос после завершения.")
            try:
                video = make_news_slideshow_video(slides, audio_type)
            finally:
                _slideshow_encoding_lock.release()
            logger.info("SLIDESHOW: uploading MP4 to Telegram")
            w, h = SLIDE_FORMATS[fmt]
            w, h = 720, round(h * 720 / w)
            sent = send_video_with_retry(chat_id, video, caption=f"🎬 Новостное слайд-шоу · {len(slides)} слайдов", width=w, height=h)
            if sent is None:
                raise RuntimeError("Telegram не принял готовое MP4-видео. Проверьте размер файла и логи Render.")
            send_message_with_retry(chat_id, "✅ Готово! MP4-видео отправлено.", reply_markup=main_menu_kb())
        else:
            media = [InputMediaPhoto(media=slide) for slide in slides]
            bot.send_media_group(chat_id, media)
            send_message_with_retry(chat_id, f"✅ Готово! Все {len(slides)} слайдов отправлены как фотографии в одном альбоме.", reply_markup=main_menu_kb())
        st["step"] = "idle"
        # Do not allow replaying old media after a completed slideshow.
        for stale in ("slideshow_photos", "slideshow_videos"):
            st.pop(stale, None)
    except Exception as exc:
        logger.exception("Slideshow generation failed user=%s", uid)
        st["step"] = "slideshow_format"
        send_message_with_retry(chat_id, f"❌ Не удалось создать слайд-шоу: {exc}", reply_markup=slideshow_format_kb())

# =========================
# ОСНОВНЫЕ CALLBACK ОБРАБОТЧИКИ
# =========================

# =========================
# ОБРЕЗКА МЕДИА ПО ФОРМАТУ
# =========================
CROP_FORMATS = {"4x5": (720, 900), "9x16": (720, 1280), "square": (720, 720)}

def crop_format_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    for label, key in (("📱 4:5", "4x5"), ("📱 9:16", "9x16"), ("⬜ Квадрат 1:1", "square")):
        kb.add(InlineKeyboardButton(label, callback_data=f"crop:{key}"))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="crop:cancel"))
    return kb

def _start_crop(chat_id, uid):
    st = user_state.get(uid) or {}
    photos = st.get("album_photos") or st.get("media_group", {}).get("photos") or []
    if not photos and st.get("photo_bytes"):
        photos = [st["photo_bytes"]]
    videos = st.get("album_videos") or st.get("media_group", {}).get("videos") or []
    if not videos and st.get("video_info"):
        videos = [st["video_info"]]
    if not photos and not videos:
        send_message_with_retry(chat_id, "❌ Сначала отправьте пост с фото или видео.")
        return
    st["crop_photos"] = list(photos)
    st["crop_videos"] = list(videos)
    st["step"] = "crop_format"
    user_state[uid] = st
    send_message_with_retry(chat_id, f"✂️ Найдено фото: {len(photos)}, видео: {len(videos)}. Выберите формат обрезки:", reply_markup=crop_format_kb())

def _crop_photo_bytes(data, w, h):
    with Image.open(BytesIO(data)) as im:
        im = crop_to_ratio(im.convert("RGB"), w, h).resize((w, h), Image.Resampling.LANCZOS)
        out = BytesIO()
        im.save(out, format="JPEG", quality=92)
        out.seek(0)
        out.name = "cropped.jpg"
        return out

def _crop_video_bytes(data, w, h):
    with tempfile.TemporaryDirectory(prefix="crop_media_") as tmp:
        source = os.path.join(tmp, "input.mp4")
        target = os.path.join(tmp, "cropped.mp4")
        with open(source, "wb") as f:
            f.write(data)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", source,
               "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", target]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError((exc.stderr or "FFmpeg error")[-500:]) from exc
        with open(target, "rb") as f:
            out = BytesIO(f.read())
        out.name = "cropped.mp4"
        return out

def _run_crop(uid, chat_id, fmt):
    st = user_state.get(uid) or {}
    w, h = CROP_FORMATS[fmt]
    photos = st.get("crop_photos", [])
    videos = st.get("crop_videos", [])
    success, failures = 0, []
    # Each media is sent separately to support mixed albums and Telegram size limits.
    for i, photo in enumerate(photos, 1):
        try:
            result = _crop_photo_bytes(photo, w, h)
            if not send_photo_with_retry(chat_id, result, caption=f"✂️ Фото {i} · {fmt}"):
                raise RuntimeError("Telegram не принял фото")
            success += 1
        except Exception as exc:
            logger.exception("Crop photo failed")
            failures.append(f"Фото {i}: {exc}")
    for i, info in enumerate(videos, 1):
        try:
            file_id = info.get("file_id") if isinstance(info, dict) else info
            if not file_id:
                raise ValueError("Нет file_id")
            data = tg_file_bytes(file_id)
            result = _crop_video_bytes(data, w, h)
            if len(result.getvalue()) > MAX_FILE_SIZE:
                raise ValueError("Готовый MP4 превышает лимит отправки 50 МБ")
            if not send_video_with_retry(chat_id, result, caption=f"✂️ Видео {i} · {fmt}", width=w, height=h):
                raise RuntimeError("Telegram не принял видео")
            success += 1
        except Exception as exc:
            logger.exception("Crop video failed")
            failures.append(f"Видео {i}: {exc}")
    st["step"] = "idle"
    message = f"✅ Готово: {success} медиа в формате {fmt}." if success else "❌ Не удалось обрезать медиа."
    if failures:
        message += "\n" + "\n".join(failures[:5])
    send_message_with_retry(chat_id, message, reply_markup=main_menu_kb())

@bot.callback_query_handler(func=lambda c: c.data.startswith("crop:"))
def on_crop_callback(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    choice = c.data.split(":", 1)[1]
    if choice == "cancel":
        (user_state.get(uid) or {}).update(step="idle")
        send_message_with_retry(c.message.chat.id, "✂️ Обрезка отменена.")
        return
    if choice not in CROP_FORMATS or (user_state.get(uid) or {}).get("step") != "crop_format":
        send_message_with_retry(c.message.chat.id, "⚠️ Сначала отправьте пост и выберите «Обрезать».")
        return
    user_state[uid]["step"] = "crop_processing"
    send_message_with_retry(c.message.chat.id, "⏳ Обрезаю все фото и видео, подождите...")
    threading.Thread(target=_run_crop, args=(uid, c.message.chat.id, choice), daemon=True).start()

@bot.callback_query_handler(func=lambda c: c.data.startswith("repost:"))
def on_repost_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "crop":
        bot.answer_callback_query(c.id)
        _start_crop(c.message.chat.id, uid)
        return

    if action == "slideshow":
        bot.answer_callback_query(c.id)
        _start_slideshow(c.message.chat.id, uid)
        return

    if action == "make_album_video":
        if st.get("album_photos") or st.get("media_group", {}).get("photos"):
            photos = st.get("album_photos") or st.get("media_group", {}).get("photos")
            if photos:
                st["album_photos"] = photos
                bot.answer_callback_query(c.id, f"🎬 Создаю видео из {len(photos)} фото...")
                album_id = f"direct_{uid}_{int(time.time())}"
                user_album_cache[album_id] = {
                    "photos": photos,
                    "videos": [],
                    "caption": st.get("original_text", ""),
                    "user_id": uid,
                    "chat_id": c.message.chat.id
                }
                process_album_to_video(uid, album_id, c.message.chat.id)
            else:
                bot.answer_callback_query(c.id, "❌ Нет фото для видео")
        else:
            bot.answer_callback_query(c.id, "❌ Нет фото для видео")
        return
    
    if action == "design":
        if st.get("title"):
            st["step"] = "waiting_template"
            user_state[uid] = st
            bot.answer_callback_query(c.id, f"📝 Использую заголовок: {st['title'][:50]}...")
            send_message_with_retry(c.message.chat.id, 
                f"📝 <b>Заголовок уже сохранён:</b>\n«{st['title']}»\n\nВыбери шаблон оформления:",
                parse_mode="HTML", 
                reply_markup=template_kb())
        else:
            st["step"] = "waiting_title"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "✏️ Введите заголовок")
            send_message_with_retry(c.message.chat.id, "✏️ Отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
    
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
            st["title"] = clean_title_for_card(title)
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
    
    elif action == "edit":
        bot.answer_callback_query(c.id, "✏️ Отправьте новый текст")
        st["step"] = "waiting_edit_repost_text"
        user_state[uid] = st
        
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        
        send_message_with_retry(
            c.message.chat.id,
            "✏️ <b>Отправьте новый текст поста</b>\n\n"
            "Вы можете полностью переписать текст или изменить его.\n"
            "После отправки вы сможете оформить пост или опубликовать его.",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    
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
            
            if st.get("media_group"):
                st["saved_media_group"] = st["media_group"].copy()
                logger.info(f"Saved media group for TG post for user {uid}")
            
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
            
            if st.get("media_group"):
                st["saved_media_group"] = st["media_group"].copy()
                logger.info(f"Saved media group for Threads post for user {uid}")
            
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
        if st.get("title"):
            if st.get("saved_photo_bytes"):
                st["photo_bytes"] = st["saved_photo_bytes"]
            st["step"] = "waiting_template"
            user_state[uid] = st
            bot.answer_callback_query(c.id, f"📝 Использую заголовок: {st['title'][:50]}...")
            send_message_with_retry(c.message.chat.id, 
                f"📝 <b>Заголовок уже сохранён:</b>\n«{st['title']}»\n\nВыбери шаблон оформления:",
                parse_mode="HTML", 
                reply_markup=template_kb())
        else:
            if st.get("saved_photo_bytes"):
                st["photo_bytes"] = st["saved_photo_bytes"]
            st["step"] = "waiting_title"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "✏️ Введите заголовок")
            send_message_with_retry(c.message.chat.id, "✏️ Отправь <b>ЗАГОЛОВОК</b> для поста:", parse_mode="HTML")
    
    elif action == "edit":
        bot.answer_callback_query(c.id, "✏️ Отправьте новый текст")
        st["step"] = "waiting_edit_ai_text"
        user_state[uid] = st
        
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        
        send_message_with_retry(
            c.message.chat.id,
            "✏️ <b>Отправьте новый текст поста</b>\n\n"
            "Вы можете полностью переписать текст или изменить его.\n"
            "После отправки вы сможете оформить пост или опубликовать его.",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    
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
            st["title"] = clean_title_for_card(title)
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


# =========================
# ОБРАБОТЧИКИ ДЛЯ TG И THREADS
# =========================

@bot.callback_query_handler(func=lambda c: c.data.startswith("tg:"))
def on_tg_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
    if action == "design":
        bot.answer_callback_query(c.id, "📝 Переход к оформлению поста")
        
        tg_text = st.get("tg_post_text", "")
        if tg_text:
            clean_text = remove_emojis(tg_text)
            clean_text = re.sub(r'^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]\s*', '', clean_text)
            title, body = split_title_and_body(clean_text)
            st["title"] = clean_title_for_card(title) if title else "Без заголовка"
            st["body_raw"] = body
            st["original_text"] = tg_text
            st["original_text_for_ai"] = tg_text
            st["card_bytes"] = None
        
        if st.get("photo_bytes") or st.get("saved_photo_bytes"):
            if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
                st["photo_bytes"] = st["saved_photo_bytes"]
            st["step"] = "waiting_template"
            user_state[uid] = st
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            send_message_with_retry(
                c.message.chat.id,
                f"📝 <b>Заголовок сохранён:</b>\n«{st['title']}»\n\nВыбери шаблон оформления:",
                parse_mode="HTML",
                reply_markup=template_kb()
            )
        else:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            send_message_with_retry(
                c.message.chat.id,
                "📸 Отправь фото для оформления поста",
                parse_mode="HTML"
            )
        return
    
    if action == "edit":
        bot.answer_callback_query(c.id, "✏️ Отправьте новый текст для Telegram")
        st["step"] = "waiting_edit_tg_text"
        user_state[uid] = st
        
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        
        send_message_with_retry(
            c.message.chat.id,
            "✏️ <b>Отправьте новый текст для поста в Telegram</b>\n\n"
            "Заголовок должен быть не более 150 символов.",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    
    elif action == "redo":
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
        if st.get("tg_post_text"):
            st["original_text"] = st["tg_post_text"]
            st["original_text_for_ai"] = st["tg_post_text"]
            user_state[uid] = st
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
    
    if action == "design":
        bot.answer_callback_query(c.id, "📝 Переход к оформлению поста")
        
        threads_text = st.get("threads_post_text", "")
        if threads_text:
            clean_text = remove_emojis(threads_text)
            clean_text = re.sub(r'^[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF]\s*', '', clean_text)
            title, body = split_title_and_body(clean_text)
            st["title"] = clean_title_for_card(title) if title else "Без заголовка"
            st["body_raw"] = body
            st["original_text"] = threads_text
            st["original_text_for_ai"] = threads_text
            st["card_bytes"] = None
        
        if st.get("photo_bytes") or st.get("saved_photo_bytes"):
            if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
                st["photo_bytes"] = st["saved_photo_bytes"]
            st["step"] = "waiting_template"
            user_state[uid] = st
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            send_message_with_retry(
                c.message.chat.id,
                f"📝 <b>Заголовок сохранён:</b>\n«{st['title']}»\n\nВыбери шаблон оформления:",
                parse_mode="HTML",
                reply_markup=template_kb()
            )
        else:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            send_message_with_retry(
                c.message.chat.id,
                "📸 Отправь фото для оформления поста",
                parse_mode="HTML"
            )
        return
    
    if action == "edit":
        bot.answer_callback_query(c.id, "✏️ Отправьте новый текст для Threads")
        st["step"] = "waiting_edit_threads_text"
        user_state[uid] = st
        
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass
        
        send_message_with_retry(
            c.message.chat.id,
            "✏️ <b>Отправьте новый текст для поста в Threads</b>\n\n"
            "Заголовок должен быть не более 150 символов.",
            parse_mode="HTML",
            reply_markup=main_menu_kb()
        )
    
    elif action == "redo":
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
        if st.get("threads_post_text"):
            st["original_text"] = st["threads_post_text"]
            st["original_text_for_ai"] = st["threads_post_text"]
            user_state[uid] = st
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


# =========================
# ПУБЛИКАЦИЯ В КАНАЛ
# =========================

@bot.callback_query_handler(func=lambda c: c.data.startswith("post_channel:"))
def on_post_channel_select(c):
    uid = c.from_user.id
    _, post_type, channel_type = c.data.split(":", 2)
    st = user_state.get(uid) or {}
    
    if channel_type == "design_before_publish":
        bot.answer_callback_query(c.id, "📝 Переход к оформлению поста")
        
        current_text = st.get("original_text", "")
        if current_text:
            title, body = split_title_and_body(current_text)
            st["title"] = clean_title_for_card(title)
            st["body_raw"] = body
            st["original_text_for_ai"] = current_text
            st["card_bytes"] = None
        
        if st.get("photo_bytes") or st.get("saved_photo_bytes"):
            if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
                st["photo_bytes"] = st["saved_photo_bytes"]
            st["step"] = "waiting_template"
            user_state[uid] = st
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            send_message_with_retry(
                c.message.chat.id,
                f"📝 <b>Заголовок сохранён:</b>\n«{st['title']}»\n\nВыбери шаблон оформления:",
                parse_mode="HTML",
                reply_markup=template_kb()
            )
        else:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            send_message_with_retry(
                c.message.chat.id,
                "📸 Отправь фото для оформления поста",
                parse_mode="HTML"
            )
        return
    
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
            elif st.get("video_info"):
                media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
            elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
                photo_count = len(st["media_group"].get("photos", []))
                video_count = len(st["media_group"].get("videos", []))
                media_info = f"\n📸 <b>Медиа:</b> {photo_count} фото, {video_count} видео"
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
            elif st.get("video_info"):
                media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
            elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
                photo_count = len(st["media_group"].get("photos", []))
                video_count = len(st["media_group"].get("videos", []))
                media_info = f"\n📸 <b>Медиа:</b> {photo_count} фото, {video_count} видео"
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
    elif channel_type == "probnym":
        target_channel = CHANNEL_PROBNY_MN
        channel_name = "Пробный МН"
        subscribe_link = "\n\n<a href='https://t.me/+eI2GN7rcsZliZGYy'>✅ Подписаться на канал</a>"
    elif channel_type == "beltopor":
        target_channel = CHANNEL_BELTOPOR
        channel_name = "Бел.топор"
    elif channel_type == "minskach":
        target_channel = CHANNEL_MINSKACH
        channel_name = "Минскач"
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
        
        if channel_type == "probnym" and post_text:
            post_text = post_text + subscribe_link
        
        if not post_text:
            bot.answer_callback_query(c.id, "❌ Нет текста для публикации")
            return
        
        # ===== ПУБЛИКАЦИЯ С ПРОВЕРКОЙ НА ТЕСТОВЫЙ КАНАЛ =====
        is_test = is_test_channel(channel_type)
        
        if st.get("card_bytes"):
            if is_test:
                try:
                    watermarked_card = apply_watermark_logo_mn(st["card_bytes"])
                    bot.send_photo(target_channel, watermarked_card, caption=post_text, parse_mode="HTML")
                    logger.info(f"Published card with logo watermark to test channel")
                except Exception as e:
                    logger.error(f"Error applying logo to card: {e}")
                    bot.send_photo(target_channel, BytesIO(st["card_bytes"]), caption=post_text, parse_mode="HTML")
            else:
                bot.send_photo(target_channel, BytesIO(st["card_bytes"]), caption=post_text, parse_mode="HTML")
            bot.answer_callback_query(c.id, f"✅ Опубликовано в {channel_name} с оформлением")
        
        elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
            media_group = st.get("media_group", {"photos": [], "videos": []})
            media_list = []
            first = True
            
            for photo in media_group.get("photos", []):
                try:
                    if is_test:
                        watermarked = apply_watermark_logo_mn(photo)
                        photo_bytes_io = watermarked
                        logger.info(f"Applied logo watermark for test channel media group")
                    elif channel_type == "probnym":
                        watermarked = apply_watermark_probnym(photo)
                        photo_bytes_io = watermarked
                    else:
                        photo_bytes_io = BytesIO(photo)
                    
                    if first:
                        media_list.append(InputMediaPhoto(photo_bytes_io, caption=post_text, parse_mode="HTML"))
                        first = False
                    else:
                        media_list.append(InputMediaPhoto(photo_bytes_io))
                except Exception as e:
                    logger.error(f"Error adding photo to media list: {e}")
                    if first:
                        media_list.append(InputMediaPhoto(BytesIO(photo), caption=post_text, parse_mode="HTML"))
                        first = False
                    else:
                        media_list.append(InputMediaPhoto(BytesIO(photo)))
            
            for video in media_group.get("videos", []):
                try:
                    file_id = video.get('file_id')
                    if file_id:
                        if first:
                            media_list.append(InputMediaVideo(file_id, caption=post_text, parse_mode="HTML"))
                            first = False
                        else:
                            media_list.append(InputMediaVideo(file_id))
                except Exception as e:
                    logger.error(f"Error adding video to media list: {e}")
            
            if len(media_list) > 1:
                try:
                    bot.send_media_group(target_channel, media_list)
                except Exception as e:
                    logger.error(f"Error sending media group: {e}")
                    for media in media_list:
                        try:
                            if isinstance(media, InputMediaPhoto):
                                bot.send_photo(target_channel, media.media, caption=media.caption if media == media_list[0] else None, parse_mode="HTML")
                            elif isinstance(media, InputMediaVideo):
                                bot.send_video(target_channel, media.media, caption=media.caption if media == media_list[0] else None, parse_mode="HTML")
                        except Exception as e2:
                            logger.error(f"Error sending individual media: {e2}")
            elif len(media_list) == 1:
                media = media_list[0]
                try:
                    if isinstance(media, InputMediaPhoto):
                        bot.send_photo(target_channel, media.media, caption=media.caption, parse_mode="HTML")
                    elif isinstance(media, InputMediaVideo):
                        bot.send_video(target_channel, media.media, caption=media.caption, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Error sending single media: {e}")
        
        elif st.get("photo_bytes"):
            try:
                if is_test:
                    watermarked_photo = apply_watermark_logo_mn(st["photo_bytes"])
                    photo_to_send = watermarked_photo
                    logger.info(f"Applied logo watermark for test channel")
                elif channel_type == "probnym":
                    watermarked_photo = apply_watermark_probnym(st["photo_bytes"])
                    photo_to_send = watermarked_photo
                else:
                    photo_to_send = BytesIO(st["photo_bytes"])
                
                bot.send_photo(target_channel, photo_to_send, caption=post_text, parse_mode="HTML")
                logger.info(f"Published photo to {channel_name}")
            except Exception as e:
                logger.error(f"Error sending photo: {e}")
        
        elif st.get("video_file_id"):
            try:
                bot.send_video(target_channel, st["video_file_id"], caption=post_text, parse_mode="HTML")
                logger.info(f"Published video to {channel_name}")
            except Exception as e:
                logger.error(f"Error sending video: {e}")
        
        else:
            try:
                bot.send_message(target_channel, post_text, parse_mode="HTML")
                logger.info(f"Published text only to {channel_name}")
            except Exception as e:
                logger.error(f"Error sending text: {e}")
                bot.answer_callback_query(c.id, "❌ Ошибка публикации")
                return
        
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
    
    if channel_type == "design_before_publish":
        bot.answer_callback_query(c.id, "📝 Переход к оформлению поста")
        
        current_text = st.get("original_text", "")
        if current_text:
            title, body = split_title_and_body(current_text)
            st["title"] = clean_title_for_card(title)
            st["body_raw"] = body
            st["original_text_for_ai"] = current_text
            st["card_bytes"] = None
        
        if st.get("photo_bytes") or st.get("saved_photo_bytes"):
            if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
                st["photo_bytes"] = st["saved_photo_bytes"]
            st["step"] = "waiting_template"
            user_state[uid] = st
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            send_message_with_retry(
                c.message.chat.id,
                f"📝 <b>Заголовок сохранён:</b>\n«{st['title']}»\n\nВыбери шаблон оформления:",
                parse_mode="HTML",
                reply_markup=template_kb()
            )
        else:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            send_message_with_retry(
                c.message.chat.id,
                "📸 Отправь фото для оформления поста",
                parse_mode="HTML"
            )
        return
    
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
            full_text = st.get("original_text", "")
            title, body = split_title_and_body(full_text)
            formatted_text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}" if title and body else html.escape(full_text)
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
    elif channel_type == "probnym":
        target_channel = CHANNEL_PROBNY_MN
        channel_name = "Пробный МН"
    elif channel_type == "beltopor":
        target_channel = CHANNEL_BELTOPOR
        channel_name = "Бел.топор"
    elif channel_type == "minskach":
        target_channel = CHANNEL_MINSKACH
        channel_name = "Минскач"
    elif channel_type == "test":
        target_channel = CHANNEL_TEST
        channel_name = "ТЕСТОВЫЙ КАНАЛ"
    else:
        bot.answer_callback_query(c.id, "❌ Неизвестный канал")
        return
    
    try:
        full_text = st.get("original_text", "")
        title = st.get("title", "")
        body = st.get("body_raw", "")
        
        if title and body:
            caption_text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}"
        elif title:
            caption_text = f"<b>{html.escape(title)}</b>"
        elif body:
            caption_text = html.escape(body)
        else:
            caption_text = html.escape(full_text)
        
        # ===== ПУБЛИКАЦИЯ С ПРОВЕРКОЙ НА ТЕСТОВЫЙ КАНАЛ =====
        is_test = is_test_channel(channel_type)
        
        if st.get("card_bytes"):
            if is_test:
                try:
                    watermarked_card = apply_watermark_logo_mn(st["card_bytes"])
                    send_photo_with_retry(
                        target_channel,
                        watermarked_card,
                        caption=caption_text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Published card with logo watermark to test channel (select_channel)")
                except Exception as e:
                    logger.error(f"Error applying logo to card in select_channel: {e}")
                    send_photo_with_retry(
                        target_channel,
                        BytesIO(st["card_bytes"]),
                        caption=caption_text,
                        parse_mode="HTML"
                    )
            else:
                send_photo_with_retry(
                    target_channel,
                    BytesIO(st["card_bytes"]),
                    caption=caption_text,
                    parse_mode="HTML"
                )
            bot.answer_callback_query(c.id, f"✅ Опубликовано в {channel_name} с оформлением")
        
        elif st.get("photo_bytes"):
            if is_test:
                try:
                    watermarked_photo = apply_watermark_logo_mn(st["photo_bytes"])
                    send_photo_with_retry(
                        target_channel,
                        watermarked_photo,
                        caption=caption_text,
                        parse_mode="HTML"
                    )
                    logger.info(f"Published photo with logo watermark to test channel (select_channel)")
                except Exception as e:
                    logger.error(f"Error applying logo to photo in select_channel: {e}")
                    send_photo_with_retry(
                        target_channel,
                        BytesIO(st["photo_bytes"]),
                        caption=caption_text,
                        parse_mode="HTML"
                    )
            else:
                send_photo_with_retry(
                    target_channel,
                    BytesIO(st["photo_bytes"]),
                    caption=caption_text,
                    parse_mode="HTML"
                )
            bot.answer_callback_query(c.id, f"✅ Опубликовано в {channel_name} с фото")
        
        else:
            bot.send_message(target_channel, caption_text, parse_mode="HTML")
            bot.answer_callback_query(c.id, f"✅ Текст опубликован в {channel_name}")
        
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
        logger.error(f"Error publishing to channel: {e}")
        bot.answer_callback_query(c.id, "❌ Ошибка публикации")
        send_message_with_retry(
            c.message.chat.id,
            f"❌ Не удалось опубликовать: {e}",
            reply_markup=main_menu_kb()
        )


@bot.callback_query_handler(func=lambda c: c.data in ["publish", "edit_text", "cancel"])
def on_action(call):
    uid = call.from_user.id
    st = user_state.get(uid)
    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(call.id, "Нет активного превью.")
        return
    if call.data == "publish":
        try:
            title = st.get("title", "")
            body = st.get("body_raw", "")
            
            if title and body:
                caption = f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}"
            elif title:
                caption = f"<b>{html.escape(title)}</b>"
            else:
                caption = html.escape(body)
            
            photo_to_send = st.get("card_bytes")
            if not photo_to_send:
                photo_to_send = st.get("photo_bytes")
            
            if photo_to_send:
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


@bot.callback_query_handler(func=lambda c: c.data == "publish_to_channel")
def on_publish_to_channel(c):
    uid = c.from_user.id
    st = user_state.get(uid) or {}
    
    if not st or st.get("step") not in ["waiting_action", "waiting_after_ai"]:
        bot.answer_callback_query(c.id, "Нет активного поста. Начни с «Оформить пост» или обработай текст через ИИ.")
        return
    
    if not CHANNEL_MN and not CHANNEL_CHP and not CHANNEL_AFISHA and not CHANNEL_PROBNY_MN and not CHANNEL_TEST:
        bot.answer_callback_query(c.id, "❌ Каналы не настроены")
        send_message_with_retry(c.message.chat.id, "❌ Ни один канал для публикации не настроен.", reply_markup=main_menu_kb())
        return
    
    if st.get("title") or st.get("body_raw"):
        full_text = ""
        if st.get("title"):
            full_text += st.get("title", "")
        if st.get("body_raw"):
            if full_text:
                full_text += "\n\n"
            full_text += st.get("body_raw", "")
        st["original_text"] = full_text
    
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except:
        pass
    
    bot.answer_callback_query(c.id, "📢 Выбери канал для публикации")
    send_message_with_retry(
        c.message.chat.id,
        "📢 <b>Выбери канал для публикации:</b>",
        parse_mode="HTML",
        reply_markup=channel_selection_kb()
    )


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
    
    st["card_bytes"] = None
    st["template"] = tpl
    
    if st.get("saved_photo_bytes") and not st.get("photo_bytes"):
        st["photo_bytes"] = st["saved_photo_bytes"]
    
    has_photo = st.get("photo_bytes") is not None
    
    if tpl in ["MN", "CHP", "MN_TG", "MN2"]:
        if has_photo:
            st["step"] = "waiting_text_position"
            user_state[uid] = st
            template_names = {"MN": "МН", "MN_TG": "МН ТГ", "CHP": "ЧП ВМ", "MN2": "МН 2"}
            template_name = template_names.get(tpl, tpl)
            bot.answer_callback_query(c.id, f"Шаблон {template_name} выбран ✅")
            
            title_display = f"\n📌 <b>Заголовок:</b> {st['title']}" if st.get("title") else ""
            send_message_with_retry(c.message.chat.id, 
                f"📰 Выбран шаблон <b>{template_name}</b>{title_display}\n\n📸 Фото уже есть!\n\n<b>Где разместить текст?</b>\n⬆️ Сверху или ⬇️ Снизу",
                parse_mode="HTML", reply_markup=text_position_kb())
        else:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            template_names = {"MN": "МН", "MN_TG": "МН ТГ", "CHP": "ЧП ВМ", "MN2": "МН 2"}
            template_name = template_names.get(tpl, tpl)
            bot.answer_callback_query(c.id, f"Шаблон {template_name} выбран ✅")
            send_message_with_retry(c.message.chat.id, f"📰 Выбран шаблон <b>{template_name}</b>\n\nТеперь пришли фото 📷", parse_mode="HTML")
    
    elif tpl == "AM":
        if has_photo:
            st["step"] = "waiting_text_position"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон АМ выбран ✅")
            title_display = f"\n📌 <b>Заголовок:</b> {st['title']}" if st.get("title") else ""
            send_message_with_retry(c.message.chat.id, 
                f"✨ Выбран шаблон <b>АМ</b>{title_display}\n\n📸 Фото уже есть!\n\n<b>Где разместить текст?</b>\n⬆️ Сверху или ⬇️ Снизу",
                parse_mode="HTML", reply_markup=text_position_kb())
        else:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон АМ выбран ✅")
            send_message_with_retry(c.message.chat.id, f"✨ Выбран шаблон <b>АМ</b>\n\nТеперь пришли фото 📷", parse_mode="HTML")
    
    elif tpl == "AM2":
        if has_photo:
            st["step"] = "waiting_text_position_am2"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон АМ 2 выбран ✅")
            title_display = f"\n📌 <b>Заголовок:</b> {st['title']}" if st.get("title") else ""
            send_message_with_retry(c.message.chat.id, 
                f"🎨 Выбран шаблон <b>АМ 2</b>{title_display}\n\n📐 <b>Выбери расположение текста:</b>",
                parse_mode="HTML", reply_markup=text_position_kb_am2())
        else:
            st["step"] = "waiting_photo_am2"
            user_state[uid] = st
            bot.answer_callback_query(c.id, "Шаблон АМ 2 выбран ✅")
            send_message_with_retry(c.message.chat.id, f"🎨 Выбран шаблон <b>АМ 2</b>\n\n📸 Пришли фото:", parse_mode="HTML")
    
    elif tpl == "FDR_POST":
        if has_photo:
            if st.get("title"):
                st["step"] = "waiting_highlight_phrase_fdr_post"
                user_state[uid] = st
                bot.answer_callback_query(c.id, "Шаблон 'Пост ФДР' выбран ✅")
                send_message_with_retry(c.message.chat.id, 
                    f"💜 Выбран шаблон <b>Пост ФДР</b>\n\n<b>Заголовок сохранён:</b>\n«{st['title']}»\n\n✏️ Отправь слова для выделения цветом (через пробел):",
                    parse_mode="HTML")
            else:
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
            if st.get("title"):
                st["step"] = "waiting_body_fdr"
                user_state[uid] = st
                bot.answer_callback_query(c.id, "Шаблон 'Сторис ФДР' выбран ✅")
                send_message_with_retry(c.message.chat.id, 
                    f"📱 Выбран шаблон <b>Сторис ФДР</b>\n\n<b>Заголовок сохранён:</b>\n«{st['title']}»\n\n✏️ Теперь отправь основной текст для сторис:",
                    parse_mode="HTML")
            else:
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
    position_text = "сверху" if position == "top" else "снизу"
    
    if st.get("title") and st.get("photo_bytes"):
        try:
            card = make_card(st["photo_bytes"], st["title"], st.get("template", "MN"), 
                            text_position=position,
                            bold_phrase=st.get("bold_phrase", ""))
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.delete_message(c.message.chat.id, c.message.message_id)
            send_photo_with_retry(c.message.chat.id, BytesIO(st["card_bytes"]), 
                                caption=f"✅ Текст расположен <b>{position_text}</b>\n\n{caption}", 
                                parse_mode="HTML", reply_markup=preview_kb())
            bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")
        except Exception as e:
            logger.error(f"Error creating card: {e}")
            bot.answer_callback_query(c.id, f"❌ Ошибка: {e}")
            send_message_with_retry(c.message.chat.id, f"❌ Ошибка при создании карточки: {e}")
    else:
        st["step"] = "waiting_title"
        user_state[uid] = st
        bot.answer_callback_query(c.id, f"Текст будет {position_text} ✅")
        send_message_with_retry(c.message.chat.id, 
            f"✅ Текст будет расположен <b>{position_text}</b> фотографии.\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b> (он будет на фото):",
            parse_mode="HTML")
    
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
    st["card_bytes"] = None
    
    if st.get("title") and st.get("photo_bytes"):
        st["step"] = "waiting_date_place_choice_am2"
        user_state[uid] = st
        pos_text = "сверху" if position == "top" else "снизу"
        bot.answer_callback_query(c.id, f"Текст будет {pos_text} ✅")
        send_message_with_retry(c.message.chat.id, f"✅ Текст будет расположен <b>{pos_text}</b>\n\n<b>Заголовок сохранён:</b>\n«{st['title']}»\n\n📅 <b>Добавить дату и место?</b>", parse_mode="HTML", reply_markup=add_date_place_kb())
    else:
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
    st["card_bytes"] = None
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
            st["card_bytes"] = card.getvalue()
            user_state[uid] = st
            bot.send_photo(c.message.chat.id, photo=BytesIO(st["card_bytes"]),
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
    st["card_bytes"] = None
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
        st["title"] = clean_title_for_card(title) if title else "Статья"
        st["body_raw"] = body
        st["card_bytes"] = None
        st["step"] = "waiting_template"
        user_state[uid] = st
        
        bot.answer_callback_query(c.id, "📝 Выбери шаблон для оформления")
        send_message_with_retry(c.message.chat.id, f"📝 <b>Заголовок сохранён:</b>\n«{st['title']}»\n\nВыбери шаблон оформления.", parse_mode="HTML", reply_markup=template_kb())
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
            st["title"] = clean_title_for_card(title)
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
        title, body = split_title_and_body(st["original_text"])
        st["title"] = clean_title_for_card(title)
        st["body_raw"] = body
        user_state[uid] = st
        send_message_with_retry(c.message.chat.id, "📢 <b>Выбери канал для публикации текста:</b>", parse_mode="HTML", reply_markup=channel_selection_kb())
        try:
            bot.delete_message(c.message.chat.id, c.message.message_id)
        except:
            pass


# =========================
# ВИДЕО ИЗ ОТДЕЛЬНОГО РОЛИКА
# =========================
def direct_video_title_kb(has_title):
    kb = InlineKeyboardMarkup(row_width=2)
    if has_title:
        kb.add(InlineKeyboardButton("📝 Из подписи", callback_data="dv:title_keep"))
    kb.add(InlineKeyboardButton("✏️ Свой", callback_data="dv:title_custom"),
           InlineKeyboardButton("⏭ Без текста", callback_data="dv:title_none"),
           InlineKeyboardButton("❌ Отмена", callback_data="dv:cancel"))
    return kb

def direct_video_audio_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🎵 Оригинал", callback_data="dv:audio_original"),
           InlineKeyboardButton("📢 Важное", callback_data="dv:audio_важная"),
           InlineKeyboardButton("🎵 Обычное", callback_data="dv:audio_обычная"),
           InlineKeyboardButton("🔇 Без звука", callback_data="dv:audio_silent"))
    return kb

def direct_video_format_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("📱 4:5", callback_data="dv:format_4x5"),
           InlineKeyboardButton("📱 9:16", callback_data="dv:format_9x16"))
    return kb

def direct_video_mode_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("🎬 На всё видео", callback_data="dv:mode_full"),
           InlineKeyboardButton("📌 Первые 5 секунд", callback_data="dv:mode_5sec"))
    return kb

def render_direct_video(uid, chat_id):
    st = user_state.get(uid, {})
    import tempfile
    from pathlib import Path
    status = bot.send_message(chat_id, "⏳ Обрабатываю видео, подождите...")
    try:
        with tempfile.TemporaryDirectory(prefix="video_bot_") as folder:
            folder = Path(folder)
            src = folder / "input.mp4"
            src.write_bytes(tg_file_bytes(st["direct_video_file_id"]))
            dest = folder / "output.mp4"
            fmt = VIDEO_FORMATS[st.get("direct_video_format", "4x5")]
            w, h = fmt["width"], fmt["height"]
            title = st.get("direct_video_title", "")
            no_text = st.get("direct_video_no_text", False)
            overlay = folder / "overlay.png"
            if not no_text and title:
                layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                alpha = Image.new("L", (1, int(h * CHP_GRADIENT_PCT)))
                for y in range(alpha.height):
                    alpha.putpixel((0, y), int(220 * y / max(1, alpha.height - 1)))
                alpha = alpha.resize((w, alpha.height))
                black = Image.new("RGBA", (w, alpha.height), (0, 0, 0, 0))
                black.putalpha(alpha)
                layer.alpha_composite(black, (0, h - alpha.height))
                draw = ImageDraw.Draw(layer)
                clean = clean_title_for_card(title).upper()
                font, lines, heights, spacing, total_h = fit_text_block(
                    draw, clean, FONT_CHP, int(w * .88), int(h * MN_TITLE_ZONE_PCT),
                    max_lines=6, start_size=int(h * .11), min_size=16, line_spacing_ratio=.22)
                line_h = font.size
                y = h - int(h * .08) - len(lines)*line_h - max(0,len(lines)-1)*2
                for line in lines:
                    draw.text((int(w * .06), y), line, font=font, fill="white")
                    y += line_h + 2
                layer.save(overlay)
            vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,eq=brightness=-0.035"
            cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
            if overlay.exists():
                cmd += ["-loop", "1", "-i", str(overlay)]
            audio_type = st.get("direct_video_audio", "original")
            audio_path = folder / "music.mp3"
            if audio_type in ("важная", "обычная"):
                response = requests.get(AUDIO_URLS[audio_type], timeout=30)
                response.raise_for_status()
                audio_path.write_bytes(response.content)
                cmd += ["-stream_loop", "-1", "-i", str(audio_path)]
            if overlay.exists():
                duration = st.get("direct_video_mode", "full")
                enabled = "" if duration == "full" else ":enable='lt(t,5)'"
                cmd += ["-filter_complex", f"[0:v]{vf}[base];[base][1:v]overlay=0:0:shortest=1{enabled}[v]", "-map", "[v]"]
            else:
                cmd += ["-vf", vf, "-map", "0:v:0"]
            if audio_type in ("важная", "обычная"):
                audio_idx = 2 if overlay.exists() else 1
                cmd += ["-map", f"{audio_idx}:a:0", "-shortest"]
            elif audio_type == "original":
                cmd += ["-map", "0:a?", "-shortest"]
            else:
                cmd += ["-an"]
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-pix_fmt", "yuv420p",
                    "-r", "25", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest)]
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            if not dest.exists() or dest.stat().st_size == 0:
                raise RuntimeError("FFmpeg не создал файл")
            with dest.open("rb") as video:
                bot.send_video(chat_id, video, caption=st.get("direct_video_caption", "")[:950],
                               supports_streaming=True, width=w, height=h, timeout=180)
        bot.edit_message_text("✅ Видео готово!", chat_id, status.message_id)
        clear_state(uid)
    except Exception as exc:
        logger.exception("Direct video processing failed")
        bot.edit_message_text(f"❌ Не удалось обработать видео: {str(exc)[:350]}", chat_id, status.message_id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("dv:"))
def on_direct_video_callback(c):
    bot.answer_callback_query(c.id)
    uid = c.from_user.id
    st = user_state.get(uid, {})
    if c.data == "dv:cancel":
        clear_state(uid)
        bot.send_message(c.message.chat.id, "❌ Отменено")
        return
    if not st.get("direct_video_file_id"):
        bot.send_message(c.message.chat.id, "Сначала нажмите 🎬 Сделать видео и отправьте ролик.")
        return
    action, value = c.data[3:].split("_", 1) if "_" in c.data[3:] else (c.data[3:], "")
    if action == "title":
        if value == "custom":
            st["step"] = "direct_video_title_input"
            bot.send_message(c.message.chat.id, "✏️ Пришлите заголовок одним сообщением:")
            return
        if value == "none":
            st["direct_video_title"] = ""
            st["direct_video_no_text"] = True
        else:
            st["direct_video_no_text"] = False
        st["step"] = "direct_video_audio"
        bot.send_message(c.message.chat.id, "🎵 Выберите звук:", reply_markup=direct_video_audio_kb())
    elif action == "audio":
        st["direct_video_audio"] = value
        st["step"] = "direct_video_format"
        bot.send_message(c.message.chat.id, "📱 Выберите формат:", reply_markup=direct_video_format_kb())
    elif action == "format":
        st["direct_video_format"] = value
        st["step"] = "direct_video_mode"
        bot.send_message(c.message.chat.id, "🎬 Где показывать заголовок?", reply_markup=direct_video_mode_kb())
    elif action == "mode":
        st["direct_video_mode"] = value
        st["step"] = "direct_video_processing"
        threading.Thread(target=render_direct_video, args=(uid, c.message.chat.id), daemon=True).start()
    user_state[uid] = st

# =========================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# =========================
@bot.message_handler(content_types=["text", "photo", "video", "document", "audio", "animation", "voice", "video_note"], 
                     func=lambda message: message.forward_from_chat is not None or (message.forward_from is not None))
def handle_forwarded_message(message):
    uid = message.from_user.id
    
    original_text = ""
    if message.caption:
        original_text = message.caption
    elif message.text:
        original_text = message.text
    
    if getattr(message, "media_group_id", None):
        _receive_album_item(message, uid, is_repost=True)
        return
    
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
    
    if original_text:
        title, body = split_title_and_body(original_text)
        st["title"] = clean_title_for_card(title)
        st["body_raw"] = body
        st["original_text"] = original_text
        st["original_text_for_ai"] = original_text
    else:
        st["original_text"] = ""
        st["original_text_for_ai"] = ""
    
    st["original_url"] = source_url
    st["step"] = "waiting_repost_action"
    for stale in ("album_photos", "album_videos", "slideshow_photos", "slideshow_videos",
                  "saved_photo_bytes", "body_raw", "title"):
        st.pop(stale, None)
    if original_text:
        st["title"], st["body_raw"] = split_title_and_body(original_text)
    st["photo_bytes"] = None
    st["video_info"] = None
    st["video_file_id"] = None
    st["media_group"] = {"photos": [], "videos": []}
    st["card_bytes"] = None
    
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
            st["video_file_id"] = message.video.file_id
            st["media_group"]["videos"].append(video_info)
            logger.info(f"Saved video for user {uid}, file_id: {message.video.file_id}")
        except Exception as e:
            logger.error(f"Error extracting video from forward: {e}")
    
    if not st["photo_bytes"] and (message.video or message.document or message.animation):
        st["has_media"] = True
        st["media_type"] = "video" if message.video else "document"
    
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
    
    title_display = ""
    if st.get("title"):
        title_display = f"\n📌 <b>Заголовок:</b> {st['title']}"
    
    send_message_with_retry(message.chat.id,
        f"📎 <b>Пересланный пост обнаружен!</b>\n\n{source_text}{'<br>'.join(media_status)}"
        f"{title_display}\n📝 <b>Текст:</b> {text_preview}...\n\n<b>Что сделать с этим постом?</b>",
        parse_mode="HTML", reply_markup=repost_action_kb())


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
        st["card_bytes"] = None
        
        if result.get("title"):
            st["title"] = clean_title_for_card(result.get("title"))
            st["body_raw"] = result.get("text", "")
        else:
            title, body = split_title_and_body(result.get("text", ""))
            st["title"] = clean_title_for_card(title)
            st["body_raw"] = body
        
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
                f"🎯 <b>Что сделать с этой статьей?</b>\n\n📌 <b>Заголовок:</b> {st['title']}",
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
                f"🎯 <b>Что сделать с этой статьей?</b>\n\n📌 <b>Заголовок:</b> {st['title']}",
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


@bot.message_handler(content_types=["text"])
def on_text(message):
    uid = message.from_user.id
    text = message.text.strip() if message.text else ""
    st = user_state.get(uid) or {"template": "MN", "step": "idle"}
    
    if text == BTN_SLIDESHOW:
        _start_slideshow(message.chat.id, uid)
        return
    if st.get("step") == "slideshow_wait_text":
        title, body = split_title_and_body(text)
        st["slideshow_title"] = title
        st["slideshow_body"] = body
        st["step"] = "slideshow_mode"
        user_state[uid] = st
        bot.reply_to(message, "🖼 Выберите тип слайд-шоу:", reply_markup=slideshow_mode_kb())
        return
    if text == BTN_MAKE_VIDEO:
        user_state[uid] = {"step": "direct_video_wait", "template": "MN"}
        bot.reply_to(message, "🎬 Пришлите видео, одно фото или пост с несколькими фото. Из фотографий соберу MP4-слайд-шоу, затем предложу заголовок, звук и формат.")
        return
    if st.get("step") == "direct_video_title_input":
        st["direct_video_title"] = text
        st["step"] = "direct_video_audio"
        user_state[uid] = st
        bot.reply_to(message, "🎵 Выберите звук:", reply_markup=direct_video_audio_kb())
        return
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
        title, body = split_title_and_body(text)
        st["title"] = clean_title_for_card(title)
        st["body_raw"] = body
        st["card_bytes"] = None
        st["step"] = "waiting_repost_action"
        user_state[uid] = st
        send_message_with_retry(message.chat.id,
            f"📎 <b>Ссылка на пост обнаружена!</b>\n\n🔗 t.me/{username}/{post_id}\n"
            f"{'📌 <b>Заголовок:</b> ' + st['title'] if st['title'] else ''}",
            parse_mode="HTML", reply_markup=repost_action_kb())
        return
    
    step = st.get("step")
    
    # РЕДАКТИРОВАНИЕ ТЕКСТА
    if step == "waiting_edit_repost_text":
        if not text:
            bot.reply_to(message, "❌ Текст не может быть пустым")
            return
        
        st["original_text"] = text
        st["original_text_for_ai"] = text
        title, body = split_title_and_body(text)
        st["title"] = clean_title_for_card(title)
        st["body_raw"] = body
        st["step"] = "waiting_repost_action"
        user_state[uid] = st
        
        title_display = f"\n📌 <b>Заголовок:</b> {st['title']}" if st.get("title") else ""
        
        bot.reply_to(
            message,
            f"✅ <b>Текст обновлен!</b>{title_display}\n\n"
            f"📝 Текст: {text[:200]}...\n\n"
            f"Что дальше?",
            parse_mode="HTML",
            reply_markup=repost_action_kb()
        )
        return
    
    if step == "waiting_edit_ai_text":
        if not text:
            bot.reply_to(message, "❌ Текст не может быть пустым")
            return
        
        st["original_text"] = text
        st["original_text_for_ai"] = text
        title, body = split_title_and_body(text)
        st["title"] = clean_title_for_card(title)
        st["body_raw"] = body
        st["step"] = "waiting_after_ai"
        user_state[uid] = st
        
        formatted_text = format_ai_response(text)[2]
        
        bot.reply_to(
            message,
            f"✅ <b>Текст обновлен!</b>\n\n{formatted_text}\n\n"
            f"Что дальше?",
            parse_mode="HTML",
            reply_markup=after_ai_kb()
        )
        return
    
    if step == "waiting_edit_tg_text":
        if not text:
            bot.reply_to(message, "❌ Текст не может быть пустым")
            return
        
        clean_text = remove_emojis(text)
        title, body = split_title_and_body(clean_text)
        
        if len(title) > 150:
            title = title[:147] + "..."
        
        formatted_text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}"
        st["tg_post_text"] = formatted_text
        st["title"] = clean_title_for_card(title)
        st["body_raw"] = body
        st["step"] = "waiting_post_action"
        user_state[uid] = st
        
        media_info = ""
        if st.get("photo_bytes"):
            media_info = "\n📸 <b>Медиа:</b> фото сохранено"
        elif st.get("video_info"):
            media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
        elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
            photo_count = len(st["media_group"].get("photos", []))
            video_count = len(st["media_group"].get("videos", []))
            media_info = f"\n📸 <b>Медиа:</b> {photo_count} фото, {video_count} видео"
        
        bot.reply_to(
            message,
            f"✅ <b>Текст обновлен!</b>\n\n{formatted_text}{media_info}\n\n"
            f"Что дальше?",
            parse_mode="HTML",
            reply_markup=post_action_kb("tg")
        )
        return
    
    if step == "waiting_edit_threads_text":
        if not text:
            bot.reply_to(message, "❌ Текст не может быть пустым")
            return
        
        clean_text = remove_emojis(text)
        title, body = split_title_and_body(clean_text)
        
        if len(title) > 150:
            title = title[:147] + "..."
        
        formatted_text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}"
        st["threads_post_text"] = formatted_text
        st["title"] = clean_title_for_card(title)
        st["body_raw"] = body
        st["step"] = "waiting_post_action"
        user_state[uid] = st
        
        media_info = ""
        if st.get("photo_bytes"):
            media_info = "\n📸 <b>Медиа:</b> фото сохранено"
        elif st.get("video_info"):
            media_info = "\n🎬 <b>Медиа:</b> видео сохранено"
        elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
            photo_count = len(st["media_group"].get("photos", []))
            video_count = len(st["media_group"].get("videos", []))
            media_info = f"\n📸 <b>Медиа:</b> {photo_count} фото, {video_count} видео"
        
        bot.reply_to(
            message,
            f"✅ <b>Текст обновлен!</b>\n\n{formatted_text}{media_info}\n\n"
            f"Что дальше?",
            parse_mode="HTML",
            reply_markup=post_action_kb("threads")
        )
        return
    
    if step == "waiting_ai_text":
        processing_msg = bot.reply_to(message, "🤖 Обрабатываю текст в ИИ...")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_text_with_deepseek(text))
            bot.delete_message(message.chat.id, processing_msg.message_id)
            title, body = split_title_and_body(result)
            st["title"] = clean_title_for_card(title)
            st["body_raw"] = body
            st["original_text"] = result
            st["original_text_for_ai"] = result
            user_state[uid] = st
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
        st["title"] = clean_title_for_card(text)
        if "body_raw" not in st:
            st["body_raw"] = ""
        if st.get("body_raw"):
            st["original_text"] = f"{st['title']}\n\n{st['body_raw']}"
        else:
            st["original_text"] = st['title']
        st["original_text_for_ai"] = st["original_text"]
        st["card_bytes"] = None
        
        st["step"] = "waiting_template"
        user_state[uid] = st
        
        bot.reply_to(message, 
            f"✅ <b>Заголовок сохранён:</b>\n«{st['title']}»\n\nТеперь выбери шаблон оформления:",
            parse_mode="HTML", 
            reply_markup=template_kb())
        return
    
    if step == "waiting_title_am2":
        if not text:
            bot.reply_to(message, "❌ Заголовок не может быть пустым")
            return
        st["title"] = clean_title_for_card(text)
        st["body_raw"] = text        
        st["original_text"] = text
        st["original_text_for_ai"] = text
        st["card_bytes"] = None
        st["step"] = "waiting_date_place_choice_am2"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Заголовок сохранён!\n\n📅 <b>Добавить дату и место?</b>", parse_mode="HTML", reply_markup=add_date_place_kb())
        return
    
    if step == "waiting_date_am2":
        st["date"] = text
        st["card_bytes"] = None
        st["step"] = "waiting_place_am2"
        user_state[uid] = st
        bot.reply_to(message, f"✅ Дата: {text}\n\n✏️ <b>Введи МЕСТО</b>:", parse_mode="HTML")
        return
    
    if step == "waiting_place_am2":
        st["place"] = text
        st["card_bytes"] = None
        st["step"] = "waiting_highlight_word_am2"
        user_state[uid] = st
        try:
            card = create_poster_am2(st["photo_bytes"], st.get("title", ""), st.get("text_position", "top"), st.get("date", ""), st.get("place", ""), "", "", None, False)
            st["card_bytes"] = card.getvalue()
            user_state[uid] = st
            bot.send_photo(message.chat.id, photo=BytesIO(st["card_bytes"]),
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
            st["card_bytes"] = None
            st["step"] = "waiting_rubric_am2"
            user_state[uid] = st
            bot.reply_to(message, f"✏️ <b>Введи РУБРИКУ</b>:", parse_mode="HTML")
        else:
            title = st.get("title", "").lower()
            if text.lower() in title:
                st["temp_highlight_word"] = text
                st["card_bytes"] = None
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
        st["title"] = clean_title_for_card(text)
        st["body_raw"] = text
        st["original_text"] = text
        st["original_text_for_ai"] = text
        st["card_bytes"] = None
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
        st["title"] = clean_title_for_card(text)
        st["original_text"] = text
        st["original_text_for_ai"] = text
        st["card_bytes"] = None
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


@bot.message_handler(content_types=["photo", "video", "document"])
def on_photo_or_document(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    
    if message.forward_from_chat or message.forward_from:
        return
    
    if getattr(message, "media_group_id", None):
        _receive_album_item(message, uid, is_repost=False)
        return
    
    if st.get("step") == "direct_video_wait" and message.photo:
        try:
            photo = tg_file_bytes(message.photo[-1].file_id)
            st["album_photos"] = [photo]
            st["photo_bytes"] = photo
            st["original_caption"] = message.caption or ""
            st["title"] = extract_title_from_text(message.caption or "")
            st["step"] = "video_from_album"
            user_state[uid] = st
            bot.reply_to(message, "🎬 Создадим MP4 из фотографии. Выберите заголовок:", reply_markup=album_video_title_kb())
        except Exception as exc:
            logger.exception("Failed to load photo for video")
            bot.reply_to(message, f"❌ Не удалось загрузить фото: {exc}")
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
    
    if st.get("step") == "direct_video_wait" and message.video:
        if getattr(message.video, "file_size", 0) > MAX_FILE_SIZE:
            bot.reply_to(message, "❌ Видео превышает лимит 50 МБ.")
            return
        st.update(direct_video_file_id=message.video.file_id,
                  direct_video_caption=message.caption or "",
                  direct_video_title=extract_title_from_text(message.caption or ""),
                  step="direct_video_title")
        user_state[uid] = st
        bot.reply_to(message, "📝 Выберите заголовок для видео:", reply_markup=direct_video_title_kb(bool(st["direct_video_title"])))
        return
    step = st.get("step")
    
    if step == "waiting_photo_first" or step == "waiting_photo" or step == "waiting_photo_am2" or step == "waiting_photo_fdr_post" or step == "waiting_photo_fdr_story":
        try:
            if message.photo:
                file_id = message.photo[-1].file_id
                photo_bytes = tg_file_bytes(file_id)
                if not check_file_size(photo_bytes):
                    bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                    return
                
                st["photo_bytes"] = photo_bytes
                st["saved_photo_bytes"] = photo_bytes
                st["media_group"] = st.get("media_group", {"photos": [], "videos": []})
                st["media_group"]["photos"].append(photo_bytes)
                st["card_bytes"] = None
                
                if message.caption:
                    st["original_text"] = message.caption
                    st["original_text_for_ai"] = message.caption
                    title, body = split_title_and_body(message.caption)
                    st["title"] = clean_title_for_card(title)
                    st["body_raw"] = body
                    user_state[uid] = st
                    
                    if st.get("title"):
                        st["step"] = "waiting_template"
                        user_state[uid] = st
                        bot.reply_to(message, f"📸 Фото сохранено!\n\n📌 <b>Заголовок из подписи:</b>\n«{st['title']}»\n\nТеперь выбери шаблон оформления:", reply_markup=template_kb())
                        return
                
                st["step"] = "waiting_title"
                user_state[uid] = st
                bot.reply_to(message, "📸 Фото сохранено!\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b> для поста (он будет на фото):", parse_mode="HTML")
                return
            
            if message.video:
                video_info = get_video_info(message.video.file_id, message.video)
                st["video_info"] = video_info
                st["video_file_id"] = message.video.file_id
                st["media_group"] = st.get("media_group", {"photos": [], "videos": []})
                st["media_group"]["videos"].append(video_info)
                st["card_bytes"] = None
                
                if message.caption:
                    st["original_text"] = message.caption
                    st["original_text_for_ai"] = message.caption
                    title, body = split_title_and_body(message.caption)
                    st["title"] = clean_title_for_card(title)
                    st["body_raw"] = body
                    user_state[uid] = st
                    
                    if st.get("title"):
                        st["step"] = "waiting_template"
                        user_state[uid] = st
                        bot.reply_to(message, f"🎬 Видео сохранено!\n\n📌 <b>Заголовок из подписи:</b>\n«{st['title']}»\n\nТеперь выбери шаблон оформления:", reply_markup=template_kb())
                        return
                
                st["step"] = "waiting_title"
                user_state[uid] = st
                bot.reply_to(message, "🎬 Видео сохранено!\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b> для поста (он будет на фото):", parse_mode="HTML")
                return
                
        except Exception as e:
            logger.error(f"Error processing media: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
            return
    
    try:
        if message.photo:
            # Each standalone photo starts a fresh media batch.
            for stale in ("album_photos", "album_videos", "slideshow_photos", "slideshow_videos",
                          "video_info", "video_file_id", "title", "body_raw", "original_text"):
                st.pop(stale, None)
            st["media_group"] = {"photos": [], "videos": []}
            file_id = message.photo[-1].file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Файл слишком большой. Максимальный размер 20MB.")
                return
            st["photo_bytes"] = photo_bytes
            st["saved_photo_bytes"] = photo_bytes
            st["media_group"] = st.get("media_group", {"photos": [], "videos": []})
            st["media_group"]["photos"].append(photo_bytes)
            st["card_bytes"] = None
            
            if message.caption:
                st["original_text"] = message.caption
                st["original_text_for_ai"] = message.caption
                title, body = split_title_and_body(message.caption)
                st["title"] = clean_title_for_card(title)
                st["body_raw"] = body
        
        if message.video:
            for stale in ("album_photos", "album_videos", "slideshow_photos", "slideshow_videos",
                          "photo_bytes", "saved_photo_bytes", "title", "body_raw", "original_text"):
                st.pop(stale, None)
            st["media_group"] = {"photos": [], "videos": []}
            video_info = get_video_info(message.video.file_id, message.video)
            st["video_info"] = video_info
            st["video_file_id"] = message.video.file_id
            st["media_group"] = st.get("media_group", {"photos": [], "videos": []})
            st["media_group"]["videos"].append(video_info)
            st["card_bytes"] = None
            if message.caption:
                st["original_text"] = message.caption
                st["original_text_for_ai"] = message.caption
                title, body = split_title_and_body(message.caption)
                st["title"] = clean_title_for_card(title)
                st["body_raw"] = body
            logger.info(f"Saved video for user {uid}, file_id: {message.video.file_id}")
        
        if st.get("title"):
            st["step"] = "waiting_template"
            user_state[uid] = st
            title_display = f"\n📌 <b>Заголовок:</b> {st['title']}" if st.get("title") else ""
            bot.reply_to(message, f"📸 Медиа сохранено!{title_display}\n\nТеперь выбери шаблон оформления:", reply_markup=template_kb())
        else:
            st["step"] = "waiting_title"
            user_state[uid] = st
            bot.reply_to(message, "📸 Медиа сохранено!\n\n✏️ Теперь отправь <b>ЗАГОЛОВОК</b> для поста (он будет на фото):", parse_mode="HTML")
        return
    except Exception as e:
        logger.error(f"Error processing media: {e}")
        bot.reply_to(message, f"❌ Ошибка: {e}")
        return


# =========================
# КОМАНДЫ
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
    if CHANNEL_PROBNY_MN:
        channels_list.append("📰 Пробный МН")
    if CHANNEL_BELTOPOR:
        channels_list.append("🪓 Бел.топор")
    if CHANNEL_MINSKACH:
        channels_list.append("🏙️ Минскач")
    if CHANNEL_TEST:
        channels_list.append("🧪 ТЕСТОВЫЙ")
    channels_text = ", ".join(channels_list) if channels_list else "не настроены"
    
    send_message_with_retry(message.chat.id,
        f"👋 <b>Привет! Я бот для оформления постов</b>\n\n"
        f"<b>📝 Основные функции:</b>\n"
        f"• 📝 Оформление постов с фото (7 шаблонов)\n"
        f"• ✨ Улучшение качества фото\n"
        f"• 💧 Водяные знаки (MINSK NEWS, ЧП Минск, ЛОГО MN)\n"
        f"• 🤖 Текст в ИИ (сокращение до 650 символов)\n"
        f"• 📱 Пост для ТГ (500 символов, заголовок до 150 символов)\n"
        f"• 📱 Пост для Тредс (400 символов, заголовок до 150 символов)\n"
        f"• 📰 Извлечение статьи по ссылке (точное копирование)\n"
        f"• 📎 Репосты из каналов\n"
        f"• ✏️ Редактирование текста после ИИ\n"
        f"• 📝 Оформление поста перед публикацией\n\n"
        f"<b>📌 Доступные каналы:</b> {channels_text}\n\n"
        f"<b>💡 Как это работает:</b>\n"
        f"1️⃣ Нажми «Оформить пост»\n"
        f"2️⃣ Отправь фото\n"
        f"3️⃣ Введи ЗАГОЛОВОК (он будет на фото)\n"
        f"4️⃣ Выбери шаблон\n"
        f"5️⃣ Выбери расположение текста (сверху/снизу)\n"
        f"6️⃣ Получи готовый пост!\n\n"
        f"Выбери действие 👇",
        parse_mode="HTML", reply_markup=main_menu_kb())


@bot.message_handler(commands=["post"])
def cmd_post(message):
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_photo_first"
    st["title"] = ""
    st["body_raw"] = ""
    st["photo_bytes"] = None
    st["saved_photo_bytes"] = None
    st["card_bytes"] = None
    st["template"] = "MN"
    st["text_position"] = TEXT_POSITION_TOP
    user_state[uid] = st
    send_message_with_retry(message.chat.id, "📸 Отправь фото для оформления поста (заголовок будет нанесён на фото):", reply_markup=main_menu_kb())


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
                if "409" in str(e) or "Conflict" in str(e):
                    logger.error("Telegram 409: another process is polling this token. Stop duplicate Render services/workers or local copies. Waiting 90 seconds before retry.")
                    time.sleep(90 + random.uniform(0, 10))
                else:
                    time.sleep(10)
                continue
                
    except Exception as e:
        logger.error(f"❌ Bot crashed: {e}")
        raise
