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

# Проверяем и устанавливаем moviepy для работы с видео
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

# Для хранения данных видео-сессий
user_video_sessions: Dict[int, Dict] = {}
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

def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(BTN_POST), KeyboardButton(BTN_AI_TEXT))
    kb.row(KeyboardButton(BTN_ENHANCE), KeyboardButton(BTN_WATERMARK))
    kb.row(KeyboardButton(BTN_PRICES), KeyboardButton(BTN_MAKE_VIDEO))
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
        InlineKeyboardButton("🎬 Сделать видео", callback_data="repost:make_video")
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

# Клавиатуры для создания видео
def video_title_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Оставить заголовок", callback_data="video:title_keep"),
        InlineKeyboardButton("✏️ Свой заголовок", callback_data="video:title_custom"),
        InlineKeyboardButton("🤖 Улучшить через ИИ", callback_data="video:title_ai"),
        InlineKeyboardButton("⏭️ Без текста", callback_data="video:title_no_text"),
        InlineKeyboardButton("❌ Отмена", callback_data="video:cancel")
    )
    return kb

def video_audio_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎵 Оставить звук", callback_data="video:audio_original"),
        InlineKeyboardButton("📢 Важное", callback_data="video:audio_важная"),
        InlineKeyboardButton("🎵 Обычное", callback_data="video:audio_обычная"),
        InlineKeyboardButton("🔇 Без звука", callback_data="video:audio_silent"),
        InlineKeyboardButton("❌ Отмена", callback_data="video:cancel")
    )
    return kb

def video_format_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📱 4:5", callback_data="video:format_4x5"),
        InlineKeyboardButton("📱 9:16", callback_data="video:format_9x16"),
        InlineKeyboardButton("❌ Отмена", callback_data="video:cancel")
    )
    return kb

def video_mode_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎬 На всё видео", callback_data="video:mode_full"),
        InlineKeyboardButton("📌 Только начало (5с)", callback_data="video:mode_5sec"),
        InlineKeyboardButton("❌ Отмена", callback_data="video:cancel")
    )
    return kb

def video_slideshow_duration_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⏱️ 3 секунды", callback_data="video:slideshow_3"),
        InlineKeyboardButton("⏱️ 5 секунд", callback_data="video:slideshow_5"),
        InlineKeyboardButton("❌ Отмена", callback_data="video:cancel")
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
    if caption and len(caption) > 950:
        caption = caption[:947] + "..."
    
    for attempt in range(max_retries):
        try:
            return bot.send_video(
                chat_id=chat_id,
                video=video,
                caption=caption,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                width=width,
                height=height
            )
        except Exception as e:
            logger.error(f"Send video attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 + attempt * 2)
            else:
                try:
                    return bot.send_video(
                        chat_id=chat_id,
                        video=video,
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
    if user_id in user_video_sessions:
        user_video_sessions[user_id] = {"step": "idle"}

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
    
    if len(title) > 150:
        title = title[:147] + "..."
    
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
# CARD MAKING FUNCTIONS - ЗАМЕНИТЬ ВЕСЬ ЭТОТ БЛОК
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
# AM2 FUNCTIONS - ЗАМЕНИТЬ create_poster_am2
# =========================

def create_poster_am2(image_bytes: bytes, title_text: str, text_position: str,
                      date: str = "", place: str = "", rubric: str = "",
                      highlight_word: str = "", highlight_color: tuple = None, is_yellow: bool = False) -> BytesIO:
    clean_title = strip_html_tags(title_text)
    clean_title = clean_title_for_card(clean_title)
    
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
# ВИДЕО ФУНКЦИИ (из второго бота)
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

def process_video_frame(frame: np.ndarray, title_text: str, format_name: str = "4x5", no_text: bool = False) -> np.ndarray:
    """Обработка одного кадра для видео с выбором формата"""
    try:
        img = Image.fromarray(frame).convert("RGB")
        
        format_config = VIDEO_FORMATS.get(format_name, VIDEO_FORMATS["4x5"])
        target_w = format_config["width"]
        target_h = format_config["height"]
        
        img = crop_to_4x5(img)
        img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS_FACTOR)
        
        if no_text:
            img = apply_bottom_gradient_soft(img, height_pct=0.05, max_alpha=30)
            return np.array(img)
        
        img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
        
        draw = ImageDraw.Draw(img)
        margin_x = int(img.width * 0.06)
        margin_bottom = int(img.height * 0.08)
        safe_w = img.width - 2 * margin_x
        title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
        
        clean_title = clean_title_for_card(title_text)
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
        
        return np.array(img)
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки кадра: {e}")
        return frame

def process_video_fast(video_bytes: bytes, title_text: str, only_first_seconds: int = 0, audio_bytes: Optional[bytes] = None, keep_original_audio: bool = True, format_name: str = "4x5", no_text: bool = False) -> BytesIO:
    """Быстрая обработка видео с оптимизациями и возможностью добавления аудио"""
    temp_input = None
    temp_output = None
    temp_audio = None
    
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            f.write(video_bytes)
            temp_input = f.name
        
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
            temp_output = f.name
        
        logger.info(f"📹 Загрузка видео...")
        video = VideoFileClip(temp_input)
        logger.info(f"📹 Видео загружено: {video.duration}с, {video.size}")
        
        original_audio = video.audio
        
        if only_first_seconds > 0:
            logger.info(f"📹 Обрабатываем только первые {only_first_seconds} секунд, остальное без изменений")
            
            if video.duration > only_first_seconds:
                first_part = video.subclip(0, only_first_seconds)
                second_part = video.subclip(only_first_seconds, video.duration)
                
                def process_frame(frame):
                    return process_video_frame(frame, title_text, format_name, no_text)
                
                processed_first = first_part.fl_image(process_frame)
                processed_video = concatenate_videoclips([processed_first, second_part])
                
                first_part.close()
                second_part.close()
                processed_first.close()
            else:
                logger.info(f"📹 Видео короче {only_first_seconds}с, обрабатываем полностью")
                def process_frame(frame):
                    return process_video_frame(frame, title_text, format_name, no_text)
                processed_video = video.fl_image(process_frame)
        else:
            logger.info(f"📹 Обрабатываем всё видео")
            def process_frame(frame):
                return process_video_frame(frame, title_text, format_name, no_text)
            processed_video = video.fl_image(process_frame)
        
        if audio_bytes:
            try:
                logger.info(f"🎵 Добавление нового аудио...")
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
                    f.write(audio_bytes)
                    temp_audio = f.name
                
                audio_clip = AudioFileClip(temp_audio)
                if audio_clip.duration > processed_video.duration:
                    audio_clip = audio_clip.subclip(0, processed_video.duration)
                else:
                    audio_clip = audio_loop(audio_clip, duration=processed_video.duration)
                
                processed_video = processed_video.set_audio(audio_clip)
                logger.info(f"✅ Новое аудио добавлено")
            except Exception as e:
                logger.error(f"❌ Ошибка добавления аудио: {e}")
        elif not keep_original_audio:
            logger.info(f"🔇 Удаляем звук из видео")
            processed_video = processed_video.without_audio()
        elif original_audio is not None:
            try:
                logger.info(f"🎵 Сохраняем оригинальное аудио...")
                processed_video = processed_video.set_audio(original_audio)
                logger.info(f"✅ Оригинальное аудио сохранено")
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения аудио: {e}")
        
        logger.info(f"💾 Сохранение видео...")
        processed_video.write_videofile(
            temp_output,
            codec='libx264',
            audio_codec='aac',
            fps=video.fps,
            bitrate='5000k',
            threads=4,
            preset='medium',
            logger=None
        )
        
        video.close()
        processed_video.close()
        if original_audio:
            original_audio.close()
        
        with open(temp_output, 'rb') as f:
            result_bytes = f.read()
        
        logger.info(f"✅ Видео обработано! Размер: {len(result_bytes) / (1024*1024):.2f} MB")
        
        output = BytesIO()
        output.write(result_bytes)
        output.seek(0)
        return output
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обработке видео: {e}")
        traceback.print_exc()
        output = BytesIO(video_bytes)
        output.seek(0)
        return output
    
    finally:
        try:
            if temp_input and os.path.exists(temp_input):
                os.unlink(temp_input)
            if temp_output and os.path.exists(temp_output):
                os.unlink(temp_output)
            if temp_audio and os.path.exists(temp_audio):
                os.unlink(temp_audio)
        except:
            pass

def create_slideshow_video(photos: List[bytes], title_text: str, audio_bytes: Optional[bytes] = None, only_first_seconds: int = 0, duration_per_photo: float = 3.0, format_name: str = "4x5", no_text: bool = False) -> Optional[BytesIO]:
    """Создание слайд-шоу с возможностью выбора времени показа каждого слайда и формата"""
    temp_dir = tempfile.mkdtemp()
    
    try:
        logger.info(f"📸 Создание слайдшоу из {len(photos)} фото, время слайда: {duration_per_photo}с, формат: {format_name}, no_text: {no_text}")
        
        if len(photos) < 1:
            logger.error(f"❌ Нет фото для слайдшоу")
            return None
        
        format_config = VIDEO_FORMATS.get(format_name, VIDEO_FORMATS["4x5"])
        target_w = format_config["width"]
        target_h = format_config["height"]
        
        photo_paths = []
        for i, photo_bytes in enumerate(photos):
            img = Image.open(BytesIO(photo_bytes)).convert("RGB")
            img = crop_to_4x5(img)
            img = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            img = ImageEnhance.Brightness(img).enhance(BRIGHTNESS_FACTOR)
            
            if no_text or i > 0:
                img = apply_bottom_gradient_soft(img, height_pct=0.05, max_alpha=30)
            else:
                img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
                
                if only_first_seconds == 0 and not no_text:
                    draw = ImageDraw.Draw(img)
                    margin_x = int(img.width * 0.06)
                    margin_bottom = int(img.height * 0.08)
                    safe_w = img.width - 2 * margin_x
                    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
                    
                    clean_title = clean_title_for_card(title_text)
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
            logger=None
        )
        
        with open(output_path, 'rb') as f:
            result_bytes = f.read()
        
        output = BytesIO()
        output.write(result_bytes)
        output.seek(0)
        
        logger.info(f"✅ Слайдшоу создано! Размер: {len(result_bytes) / (1024*1024):.2f} MB")
        return output
        
    except Exception as e:
        logger.error(f"❌ Ошибка создания слайдшоу: {e}")
        traceback.print_exc()
        return None
    
    finally:
        try:
            shutil.rmtree(temp_dir)
        except:
            pass


# =========================
# ОБРАБОТЧИКИ ВИДЕО
# =========================

def init_video_session(user_id: int):
    """Инициализация сессии для видео"""
    if user_id not in user_video_sessions:
        user_video_sessions[user_id] = {
            "step": "idle",
            "video_bytes": None,
            "photos": [],
            "title": "",
            "auto_title": "",
            "audio_bytes": None,
            "audio_selected": "",
            "keep_original_audio": True,
            "format": "4x5",
            "mode": "full",
            "slideshow_duration": 3.0,
            "no_text": False,
            "original_caption": "",
            "is_slideshow": False,
            "is_video": False
        }
    return user_video_sessions[user_id]

def handle_start_video(message):
    """Начало создания видео"""
    uid = message.from_user.id
    session = init_video_session(uid)
    session["step"] = "waiting_media"
    
    send_message_with_retry(
        message.chat.id,
        "🎬 <b>Создание видео</b>\n\n"
        "Отправьте <b>фото</b> (для слайд-шоу) или <b>видео</b> (для обработки).\n"
        "Можно отправить несколько фото для слайд-шоу.\n\n"
        "Когда закончите отправлять фото, нажмите /done_video",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )

def handle_video_media(message):
    """Обработка медиа для видео"""
    uid = message.from_user.id
    
    if uid not in user_video_sessions:
        send_message_with_retry(message.chat.id, "❌ Сначала нажмите '🎬 Сделать видео'", reply_markup=main_menu_kb())
        return
    
    session = user_video_sessions[uid]
    
    if session["step"] != "waiting_media":
        return
    
    # Если это медиагруппа
    if hasattr(message, 'media_group_id') and message.media_group_id:
        handle_video_media_group(message)
        return
    
    # Если это видео
    if message.video:
        try:
            file_id = message.video.file_id
            video_bytes = tg_file_bytes(file_id)
            if not check_file_size(video_bytes):
                bot.reply_to(message, "❌ Видео слишком большое. Максимальный размер 50MB.")
                return
            
            session["video_bytes"] = video_bytes
            session["is_video"] = True
            session["original_caption"] = message.caption or ""
            
            # Извлекаем заголовок
            if message.caption:
                auto_title = extract_title_from_text(message.caption)
                session["auto_title"] = auto_title
                session["title"] = auto_title
            
            show_video_title_choice(message.chat.id, uid)
        except Exception as e:
            logger.error(f"Error processing video: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")
        return
    
    # Если это фото
    if message.photo:
        try:
            file_id = message.photo[-1].file_id
            photo_bytes = tg_file_bytes(file_id)
            if not check_file_size(photo_bytes):
                bot.reply_to(message, "❌ Фото слишком большое. Максимальный размер 20MB.")
                return
            
            session["photos"].append(photo_bytes)
            session["is_slideshow"] = True
            if message.caption and not session["original_caption"]:
                session["original_caption"] = message.caption
                auto_title = extract_title_from_text(message.caption)
                session["auto_title"] = auto_title
                session["title"] = auto_title
            
            count = len(session["photos"])
            bot.reply_to(message, f"✅ Фото {count} добавлено!\nОтправьте еще фото или нажмите /done_video")
        except Exception as e:
            logger.error(f"Error processing photo: {e}")
            bot.reply_to(message, f"❌ Ошибка: {e}")

def handle_video_media_group(message):
    """Обработка медиагруппы для видео"""
    # Сохраняем в кэш
    media_group_id = message.media_group_id
    
    if media_group_id not in pending_media_groups:
        pending_media_groups[media_group_id] = {
            "photos": [],
            "video": None,
            "caption": "",
            "user_id": message.from_user.id,
            "chat_id": message.chat.id,
            "processed": False
        }
    
    group = pending_media_groups[media_group_id]
    if message.caption and not group["caption"]:
        group["caption"] = message.caption
    
    if message.photo:
        try:
            file_id = message.photo[-1].file_id
            photo_bytes = tg_file_bytes(file_id)
            if check_file_size(photo_bytes):
                group["photos"].append(photo_bytes)
        except Exception as e:
            logger.error(f"Error adding photo to group: {e}")
    
    if message.video:
        try:
            file_id = message.video.file_id
            video_bytes = tg_file_bytes(file_id)
            if check_file_size(video_bytes):
                group["video"] = video_bytes
        except Exception as e:
            logger.error(f"Error adding video to group: {e}")
    
    # Запускаем обработку через 3 секунды
    threading.Thread(target=process_video_media_group, args=(media_group_id,), daemon=True).start()

def process_video_media_group(media_group_id: str):
    """Обработка собранной медиагруппы"""
    time.sleep(3)
    
    group = pending_media_groups.get(media_group_id)
    if not group or group.get("processed"):
        return
    
    group["processed"] = True
    user_id = group["user_id"]
    chat_id = group["chat_id"]
    
    session = init_video_session(user_id)
    
    if group.get("video"):
        session["video_bytes"] = group["video"]
        session["is_video"] = True
        session["original_caption"] = group["caption"]
        if group["caption"]:
            auto_title = extract_title_from_text(group["caption"])
            session["auto_title"] = auto_title
            session["title"] = auto_title
        
        bot.send_message(chat_id, "✅ Видео получено!")
        show_video_title_choice(chat_id, user_id)
    
    elif group.get("photos"):
        session["photos"] = group["photos"]
        session["is_slideshow"] = True
        session["original_caption"] = group["caption"]
        if group["caption"]:
            auto_title = extract_title_from_text(group["caption"])
            session["auto_title"] = auto_title
            session["title"] = auto_title
        
        bot.send_message(chat_id, f"✅ Получено {len(group['photos'])} фото!")
        show_video_title_choice(chat_id, user_id)
    
    # Удаляем из кэша
    del pending_media_groups[media_group_id]

def show_video_title_choice(chat_id: int, user_id: int):
    """Показать выбор заголовка для видео"""
    session = user_video_sessions[user_id]
    auto_title = session.get("auto_title", "")
    
    if auto_title:
        text = f"📹 <b>Шаг 1/4: Выбор заголовка</b>\n\n<b>Найденный заголовок:</b>\n{auto_title}\n\nВыберите действие:"
    else:
        text = "📹 <b>Шаг 1/4: Выбор заголовка</b>\n\nТекст не найден.\n\nВыберите действие:"
    
    send_message_with_retry(chat_id, text, parse_mode="HTML", reply_markup=video_title_kb())

def show_video_audio_choice(chat_id: int, user_id: int):
    """Показать выбор аудио для видео"""
    session = user_video_sessions[user_id]
    title = session.get("title", "")
    no_text = session.get("no_text", False)
    
    title_display = "Без текста" if no_text else (title or "Без заголовка")
    
    text = f"✅ Заголовок: <b>{title_display}</b>\n\n📹 <b>Шаг 2/4: Выбор аудио</b>\n\nВыберите вариант:"
    send_message_with_retry(chat_id, text, parse_mode="HTML", reply_markup=video_audio_kb())

def show_video_format_choice(chat_id: int, user_id: int):
    """Показать выбор формата для видео"""
    text = "📹 <b>Шаг 3/4: Выбор формата</b>\n\nВыберите формат видео:"
    send_message_with_retry(chat_id, text, parse_mode="HTML", reply_markup=video_format_kb())

def show_video_mode_choice(chat_id: int, user_id: int):
    """Показать выбор режима обработки видео"""
    session = user_video_sessions[user_id]
    format_name = session.get("format", "4x5")
    format_display = "4:5" if format_name == "4x5" else "9:16"
    
    if session.get("is_slideshow"):
        # Для слайд-шоу показываем выбор времени слайда
        text = f"📹 <b>Выбор времени слайда</b>\n\n📱 Формат: {format_display}\n\nВыберите время показа каждого слайда:"
        send_message_with_retry(chat_id, text, parse_mode="HTML", reply_markup=video_slideshow_duration_kb())
    else:
        text = f"📹 <b>Шаг 4/4: Выбор режима обработки</b>\n\n📱 Формат: {format_display}\n\n• 🎬 Заголовок на всё видео\n• 📌 Заголовок только в начале (5 секунд)\n\nВыберите режим:"
        send_message_with_retry(chat_id, text, parse_mode="HTML", reply_markup=video_mode_kb())

def process_video_final(user_id: int, chat_id: int):
    """Финальная обработка видео"""
    session = user_video_sessions[user_id]
    
    title = session.get("title", "")
    no_text = session.get("no_text", False)
    audio_bytes = session.get("audio_bytes")
    audio_selected = session.get("audio_selected", "")
    keep_original_audio = session.get("keep_original_audio", True)
    format_name = session.get("format", "4x5")
    mode = session.get("mode", "full")
    only_first_seconds = 0 if mode == "full" else 5
    duration_per_photo = session.get("slideshow_duration", 3.0)
    
    status_msg = bot.send_message(chat_id, "⏳ <b>Обрабатываю видео...</b>\n⏳ Это займет 20-60 секунд", parse_mode="HTML")
    
    try:
        if session.get("is_video") and session.get("video_bytes"):
            # Обработка видео
            result = process_video_fast(
                session["video_bytes"],
                title,
                only_first_seconds,
                audio_bytes,
                keep_original_audio,
                format_name,
                no_text
            )
            
            if result and len(result.getvalue()) > 0:
                caption = session.get("original_caption", "")
                if no_text:
                    caption += "\n📌 Без текста"
                elif title:
                    caption = f"<b>{title}</b>" if not caption else caption
                if audio_selected:
                    caption += f"\n🎵 Аудио: {audio_selected}"
                
                format_config = VIDEO_FORMATS.get(format_name, VIDEO_FORMATS["4x5"])
                send_video_with_retry(
                    chat_id,
                    BytesIO(result.getvalue()),
                    caption=caption,
                    parse_mode="HTML",
                    width=format_config["width"],
                    height=format_config["height"]
                )
                bot.edit_message_text("✅ Видео готово!", chat_id, status_msg.message_id)
            else:
                bot.edit_message_text("❌ Ошибка обработки видео", chat_id, status_msg.message_id)
        
        elif session.get("is_slideshow") and session.get("photos"):
            # Создание слайд-шоу
            result = create_slideshow_video(
                session["photos"],
                title,
                audio_bytes,
                only_first_seconds,
                duration_per_photo,
                format_name,
                no_text
            )
            
            if result and len(result.getvalue()) > 0:
                caption = session.get("original_caption", "")
                if no_text:
                    caption += "\n📌 Без текста"
                elif title:
                    caption = f"<b>{title}</b>" if not caption else caption
                if audio_selected:
                    caption += f"\n🎵 Аудио: {audio_selected}"
                caption += f"\n⏱️ Время слайда: {duration_per_photo}с"
                
                format_config = VIDEO_FORMATS.get(format_name, VIDEO_FORMATS["4x5"])
                send_video_with_retry(
                    chat_id,
                    BytesIO(result.getvalue()),
                    caption=caption,
                    parse_mode="HTML",
                    width=format_config["width"],
                    height=format_config["height"]
                )
                bot.edit_message_text("✅ Слайд-шоу готово!", chat_id, status_msg.message_id)
            else:
                bot.edit_message_text("❌ Ошибка создания слайд-шоу", chat_id, status_msg.message_id)
        else:
            bot.edit_message_text("❌ Нет медиа для обработки", chat_id, status_msg.message_id)
    
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        traceback.print_exc()
        bot.edit_message_text(f"❌ Ошибка: {e}", chat_id, status_msg.message_id)
    
    # Очищаем сессию
    session["step"] = "idle"


# =========================
# CALLBACK ОБРАБОТЧИКИ ВИДЕО
# =========================

def handle_video_callback(call):
    """Обработчик callback'ов для видео"""
    uid = call.from_user.id
    data = call.data
    chat_id = call.message.chat.id
    
    logger.info(f"📨 Видео callback: {data} от пользователя {uid}")
    
    if data == "video:cancel":
        if uid in user_video_sessions:
            user_video_sessions[uid] = {"step": "idle"}
        bot.answer_callback_query(call.id, "Отменено")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        send_message_with_retry(chat_id, "❌ Отменено", reply_markup=main_menu_kb())
        return
    
    if uid not in user_video_sessions:
        bot.answer_callback_query(call.id, "❌ Сессия не найдена")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        send_message_with_retry(chat_id, "❌ Сессия истекла. Нажмите '🎬 Сделать видео' заново.", reply_markup=main_menu_kb())
        return
    
    session = user_video_sessions[uid]
    
    # Обработка выбора заголовка
    if data == "video:title_keep":
        if session.get("auto_title"):
            session["title"] = session["auto_title"]
            session["no_text"] = False
            bot.answer_callback_query(call.id, f"✅ Заголовок: {session['title'][:50]}...")
            try:
                bot.delete_message(chat_id, call.message.message_id)
            except:
                pass
            show_video_audio_choice(chat_id, uid)
        else:
            bot.answer_callback_query(call.id, "❌ Нет заголовка")
    
    elif data == "video:title_custom":
        bot.answer_callback_query(call.id, "✏️ Введите заголовок")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        session["step"] = "waiting_title"
        send_message_with_retry(chat_id, "✏️ Отправьте текст для заголовка:", parse_mode="HTML")
    
    elif data == "video:title_ai":
        if not DEEPSEEK_API_KEY:
            bot.answer_callback_query(call.id, "❌ API ключ DeepSeek не настроен")
            return
        
        auto_title = session.get("auto_title", "")
        if not auto_title:
            bot.answer_callback_query(call.id, "❌ Нет заголовка для улучшения")
            return
        
        bot.answer_callback_query(call.id, "🤖 Улучшаю заголовок...")
        bot.edit_message_text("🤖 <b>Улучшаю заголовок через ИИ...</b>\n⏳ Это займет несколько секунд", chat_id, call.message.message_id, parse_mode="HTML")
        
        # Запускаем асинхронную обработку в отдельном потоке
        def process_ai():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                async def improve():
                    return await improve_title_with_ai(auto_title)
                
                improved = loop.run_until_complete(improve())
                loop.close()
                return improved
            except Exception as e:
                logger.error(f"AI error: {e}")
                return None
        
        def ai_callback(improved):
            if improved and improved != auto_title:
                session["title"] = improved
                session["no_text"] = False
                bot.edit_message_text(
                    f"🤖 <b>ИИ предложил:</b>\n\n{improved}\n\n✅ Заголовок сохранен!",
                    chat_id,
                    call.message.message_id,
                    parse_mode="HTML"
                )
                show_video_audio_choice(chat_id, uid)
            else:
                bot.edit_message_text(
                    f"❌ Не удалось улучшить заголовок.\nИспользую оригинал:\n\n{auto_title}",
                    chat_id,
                    call.message.message_id,
                    parse_mode="HTML"
                )
                session["title"] = auto_title
                session["no_text"] = False
                show_video_audio_choice(chat_id, uid)
        
        threading.Thread(target=lambda: ai_callback(process_ai()), daemon=True).start()
    
    elif data == "video:title_no_text":
        session["title"] = ""
        session["no_text"] = True
        bot.answer_callback_query(call.id, "⏭️ Без текста")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        show_video_audio_choice(chat_id, uid)
    
    # Обработка выбора аудио
    elif data == "video:audio_original":
        session["audio_bytes"] = None
        session["audio_selected"] = "оригинальный звук"
        session["keep_original_audio"] = True
        bot.answer_callback_query(call.id, "🎵 Оригинальный звук")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        show_video_format_choice(chat_id, uid)
    
    elif data == "video:audio_silent":
        session["audio_bytes"] = None
        session["audio_selected"] = "без звука"
        session["keep_original_audio"] = False
        bot.answer_callback_query(call.id, "🔇 Без звука")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        show_video_format_choice(chat_id, uid)
    
    elif data in ["video:audio_важная", "video:audio_обычная"]:
        audio_type = "важная" if data == "video:audio_важная" else "обычная"
        audio_name = "Важное" if audio_type == "важная" else "Обычное"
        bot.answer_callback_query(call.id, f"⏳ Скачиваю {audio_name}...")
        bot.edit_message_text(f"⏳ Скачиваю аудио '{audio_name}'...", chat_id, call.message.message_id)
        
        def download_audio():
            return download_audio_from_github(audio_type)
        
        def audio_callback(audio_bytes):
            if audio_bytes:
                session["audio_bytes"] = audio_bytes
                session["audio_selected"] = audio_name
                session["keep_original_audio"] = False
                bot.edit_message_text(f"✅ Аудио '{audio_name}' загружено!", chat_id, call.message.message_id)
                show_video_format_choice(chat_id, uid)
            else:
                bot.edit_message_text(f"❌ Не удалось загрузить аудио '{audio_name}'", chat_id, call.message.message_id)
                show_video_audio_choice(chat_id, uid)
        
        threading.Thread(target=lambda: audio_callback(download_audio()), daemon=True).start()
    
    # Обработка выбора формата
    elif data == "video:format_4x5":
        session["format"] = "4x5"
        bot.answer_callback_query(call.id, "📱 Формат 4:5")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        show_video_mode_choice(chat_id, uid)
    
    elif data == "video:format_9x16":
        session["format"] = "9x16"
        bot.answer_callback_query(call.id, "📱 Формат 9:16")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        show_video_mode_choice(chat_id, uid)
    
    # Обработка выбора времени слайда - ИСПРАВЛЕНО
    elif data == "video:slideshow_3":
        session["slideshow_duration"] = 3.0
        bot.answer_callback_query(call.id, "⏱️ Выбрано 3 секунды")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        show_video_mode_choice(chat_id, uid)
        return
    
    elif data == "video:slideshow_5":
        session["slideshow_duration"] = 5.0
        bot.answer_callback_query(call.id, "⏱️ Выбрано 5 секунд")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        show_video_mode_choice(chat_id, uid)
        return
    
    # Обработка выбора режима
    elif data == "video:mode_full":
        session["mode"] = "full"
        bot.answer_callback_query(call.id, "🎬 На всё видео")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        process_video_final(uid, chat_id)
    
    elif data == "video:mode_5sec":
        session["mode"] = "5sec"
        bot.answer_callback_query(call.id, "📌 Только начало")
        try:
            bot.delete_message(chat_id, call.message.message_id)
        except:
            pass
        process_video_final(uid, chat_id)

async def improve_title_with_ai(title: str) -> Optional[str]:
    """Улучшение заголовка через DeepSeek AI"""
    if not DEEPSEEK_API_KEY:
        return None
    
    try:
        prompt = f"""Переделай этот заголовок в новостной, но более интересный и кликбейтный формат. 
Сделай его более ярким, интригующим, добавь эмоциональную окраску. 
Сохрани смысл, но сделай его более привлекательным для читателей.

Оригинальный заголовок: {title}

Ответь только новым заголовком, без пояснений и кавычек."""

        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ты профессиональный копирайтер и редактор новостей."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.8,
            "max_tokens": 100
        }
        
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            improved_title = result['choices'][0]['message']['content'].strip()
            improved_title = improved_title.strip('"\'')
            return improved_title
        else:
            logger.error(f"❌ Ошибка DeepSeek API: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Ошибка при работе с DeepSeek: {e}")
        return None


# =========================
# ФУНКЦИИ DEEPSEEK (все функции AI из вашего бота)
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


@bot.callback_query_handler(func=lambda c: c.data.startswith("repost:"))
def on_repost_action(c):
    uid = c.from_user.id
    action = c.data.split(":")[1]
    st = user_state.get(uid) or {}
    
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
    
    elif action == "make_video":
        bot.answer_callback_query(c.id, "🎬 Переход к созданию видео")
        
        # Сохраняем текущие данные в сессию видео
        if st.get("photo_bytes"):
            init_video_session(uid)
            user_video_sessions[uid]["photos"] = [st["photo_bytes"]]
            user_video_sessions[uid]["is_slideshow"] = True
            user_video_sessions[uid]["original_caption"] = st.get("original_text", "")
            if st.get("title"):
                user_video_sessions[uid]["title"] = st["title"]
                user_video_sessions[uid]["auto_title"] = st["title"]
            
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            show_video_title_choice(c.message.chat.id, uid)
        
        elif st.get("video_file_id"):
            try:
                video_bytes = tg_file_bytes(st["video_file_id"])
                init_video_session(uid)
                user_video_sessions[uid]["video_bytes"] = video_bytes
                user_video_sessions[uid]["is_video"] = True
                user_video_sessions[uid]["original_caption"] = st.get("original_text", "")
                if st.get("title"):
                    user_video_sessions[uid]["title"] = st["title"]
                    user_video_sessions[uid]["auto_title"] = st["title"]
                
                try:
                    bot.delete_message(c.message.chat.id, c.message.message_id)
                except:
                    pass
                show_video_title_choice(c.message.chat.id, uid)
            except Exception as e:
                logger.error(f"Error getting video: {e}")
                bot.answer_callback_query(c.id, f"❌ Ошибка: {e}")
                send_message_with_retry(c.message.chat.id, f"❌ Не удалось загрузить видео: {e}")
        
        elif st.get("album_photos"):
            init_video_session(uid)
            user_video_sessions[uid]["photos"] = st["album_photos"]
            user_video_sessions[uid]["is_slideshow"] = True
            user_video_sessions[uid]["original_caption"] = st.get("original_text", "")
            if st.get("title"):
                user_video_sessions[uid]["title"] = st["title"]
                user_video_sessions[uid]["auto_title"] = st["title"]
            
            try:
                bot.delete_message(c.message.chat.id, c.message.message_id)
            except:
                pass
            show_video_title_choice(c.message.chat.id, uid)
        
        else:
            bot.answer_callback_query(c.id, "❌ Нет медиа для видео")
            send_message_with_retry(c.message.chat.id, "❌ Нет фото или видео для создания видео.\nСначала отправьте медиа.")
    
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
            logger.info(f"📝 Оформление TG поста с текстом от ИИ: {title[:50] if title else 'нет'}...")
        
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
            logger.info(f"📝 Оформление Threads поста с текстом от ИИ: {title[:50] if title else 'нет'}...")
        
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
            logger.info(f"📝 Использую текст после ИИ: {title[:50]}...")
        
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
        
        if st.get("card_bytes"):
            bot.send_photo(target_channel, BytesIO(st["card_bytes"]), caption=post_text, parse_mode="HTML")
            bot.answer_callback_query(c.id, f"✅ Опубликовано в {channel_name} с оформлением")
            has_media = True
        
        elif st.get("media_group", {}).get("photos") or st.get("media_group", {}).get("videos"):
            media_group = st.get("media_group", {"photos": [], "videos": []})
            media_list = []
            first = True
            
            for photo in media_group.get("photos", []):
                try:
                    if channel_type == "probnym":
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
                    has_media = True
                    logger.info(f"Published album with {len(media_list)} media items to {channel_name}")
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
                    has_media = True
            elif len(media_list) == 1:
                media = media_list[0]
                try:
                    if isinstance(media, InputMediaPhoto):
                        bot.send_photo(target_channel, media.media, caption=media.caption, parse_mode="HTML")
                    elif isinstance(media, InputMediaVideo):
                        bot.send_video(target_channel, media.media, caption=media.caption, parse_mode="HTML")
                    has_media = True
                except Exception as e:
                    logger.error(f"Error sending single media: {e}")
        
        elif st.get("photo_bytes"):
            try:
                if channel_type == "probnym":
                    watermarked_photo = apply_watermark_probnym(st["photo_bytes"])
                    photo_to_send = watermarked_photo
                else:
                    photo_to_send = BytesIO(st["photo_bytes"])
                
                bot.send_photo(target_channel, photo_to_send, caption=post_text, parse_mode="HTML")
                has_media = True
                logger.info(f"Published photo to {channel_name}")
            except Exception as e:
                logger.error(f"Error sending photo: {e}")
        
        elif st.get("video_file_id"):
            try:
                bot.send_video(target_channel, st["video_file_id"], caption=post_text, parse_mode="HTML")
                has_media = True
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
            logger.info(f"📝 Использую текст после ИИ: {title[:50]}...")
        
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
        
        if st.get("card_bytes"):
            send_photo_with_retry(
                target_channel,
                BytesIO(st["card_bytes"]),
                caption=caption_text,
                parse_mode="HTML"
            )
            bot.answer_callback_query(c.id, f"✅ Опубликовано в {channel_name} с оформлением")
        
        elif st.get("photo_bytes"):
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
# ОБРАБОТЧИК ВИДЕО CALLBACK (НОВЫЙ)
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("video:"))
def on_video_callback(c):
    handle_video_callback(c)


# =========================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# =========================
# ... (ВСЕ ВАШИ ОБРАБОТЧИКИ СООБЩЕНИЙ ИЗ ВАШЕГО БОТА ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ)
# Здесь должны быть все ваши обработчики: handle_forwarded_message, handle_article_link, on_text, on_photo_or_document и т.д.

# =========================
# КОМАНДЫ
# =========================
# ... (ВСЕ ВАШИ КОМАНДЫ ИЗ ВАШЕГО БОТА ОСТАЮТСЯ БЕЗ ИЗМЕНЕНИЙ)
# Добавлены только новые команды для видео:


@bot.message_handler(commands=["make_video"])
def cmd_make_video(message):
    handle_start_video(message)


@bot.message_handler(commands=["done_video"])
def cmd_done_video(message):
    uid = message.from_user.id
    if uid in user_video_sessions and user_video_sessions[uid].get("step") == "waiting_media":
        session = user_video_sessions[uid]
        if session.get("photos"):
            count = len(session["photos"])
            bot.reply_to(message, f"✅ Собрано {count} фото! Перехожу к выбору заголовка.")
            show_video_title_choice(message.chat.id, uid)
        else:
            bot.reply_to(message, "❌ Нет фото. Отправьте хотя бы одно фото.")
    else:
        bot.reply_to(message, "❌ Нет активной сессии или нет фото.")


# =========================
# MAIN
# =========================
# ... (ВАШ MAIN БЕЗ ИЗМЕНЕНИЙ, НО С ДОБАВЛЕНИЕМ ВИДЕО-ОБРАБОТЧИКА)


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
