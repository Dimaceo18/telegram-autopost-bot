import os
import re
import html
import time
import hashlib
import json
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

from bs4 import BeautifulSoup  # NEW


# =========================
# ENV
# =========================
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
SUGGEST_URL = (os.getenv("SUGGEST_URL") or "").strip()

ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set (Render -> Environment -> BOT_TOKEN)")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN contains spaces. Copy the token without spaces/newlines.")


# =========================
# BOT
# =========================
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
requests_session = requests.Session()
requests_session.headers.update(
    {"User-Agent": "Mozilla/5.0 (compatible; MINSK-NEWS-BOT/1.0)"}
)

# =========================
# CARD CONFIG
# =========================
CARD_W = 1080
CARD_H = 1350
TARGET_W = 720
TARGET_H = 1280
PHOTO_AREA_Y1 = 0
PHOTO_AREA_Y2 = CARD_H

TITLE_TOP_PAD = 80
TITLE_SIDE_PAD = 78
TITLE_BOTTOM_SAFE = 260

FOOTER_H = 64
FOOTER_TEXT = "MINSK NEWS"

CHP_GRADIENT_H = 520
CHP_TITLE_SIDE_PAD = 60
CHP_TITLE_BOTTOM_PAD = 92

SOURCE_FOOTER_H = 70
SOURCE_FOOTER_TEXT = "MINSK NEWS"

STORY_HEADER_RATIO = 0.295
STORY_PHOTO_RATIO = 0.425
STORY_TEXT_RATIO = 1.0 - STORY_HEADER_RATIO - STORY_PHOTO_RATIO

MAX_PREVIEW_TEXT = 750
SUMMARY_SENTENCES = 3

JPEG_QUALITY = 92

# =========================
# NEWS SOURCES
# =========================
NEWS_SOURCES = [
    {"name": "Onliner", "rss": "https://people.onliner.by/feed"},
    {"name": "Onliner Auto", "rss": "https://auto.onliner.by/feed"},
    {"name": "Sputnik Беларусь", "rss": "https://sputnik.by/export/rss2/archive/index.xml"},
    {"name": "Minsk News", "rss": "https://minsknews.by/feed/"},
    {"name": "Smartpress", "rss": "https://smartpress.by/rss/"},
    {"name": "Mlyn", "rss": "https://mlyn.by/feed/"},
    {"name": "Sb.by", "rss": "https://www.sb.by/rss/?rubric=news"},
    {"name": "Ont.by", "rss": "https://ont.by/news/rss"},
    {"name": "Tochka.by", "rss": "https://tochka.by/rss"},
]

MAX_ITEMS_PER_SOURCE = 8
NEWS_CACHE_TTL_SEC = 10 * 60

news_cache: Dict[str, Tuple[float, List[dict]]] = {}
article_cache: Dict[str, dict] = {}
preview_index: Dict[str, dict] = {}
user_state: Dict[int, dict] = {}

# =========================
# FONTS
# =========================
FONT_REG_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]
FONT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]

USER_FONT_DIR = os.path.join(os.getcwd(), "fonts")
MONTSERRAT_BOLD_CANDIDATES = [
    os.path.join(USER_FONT_DIR, "Montserrat-Bold.ttf"),
    os.path.join(os.getcwd(), "Montserrat-Bold.ttf"),
    "/mnt/data/Montserrat-Bold.ttf",
]

FONT_REG_PATH = next((p for p in FONT_REG_PATHS if os.path.exists(p)), None)
FONT_BOLD_PATH = next((p for p in FONT_BOLD_PATHS if os.path.exists(p)), None)
MONTSERRAT_BOLD_PATH = next((p for p in MONTSERRAT_BOLD_CANDIDATES if os.path.exists(p)), None)

if FONT_REG_PATH is None or FONT_BOLD_PATH is None:
    raise RuntimeError("System fonts not found. Need DejaVuSans or LiberationSans installed.")

def load_font(size: int, bold: bool = False, montserrat_bold: bool = False) -> ImageFont.FreeTypeFont:
    if montserrat_bold and MONTSERRAT_BOLD_PATH:
        return ImageFont.truetype(MONTSERRAT_BOLD_PATH, size=size)
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    return ImageFont.truetype(path, size=size)

# =========================
# HELPERS: UI
# =========================
def main_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📰 Новости"), KeyboardButton("🖼 Оформить"))
    kb.row(KeyboardButton("📨 Предложить новость"))
    return kb

def suggest_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    url = SUGGEST_URL.strip() if SUGGEST_URL else ""
    if not url:
        if BOT_USERNAME:
            url = f"https://t.me/{BOT_USERNAME}"
        else:
            url = "https://t.me"
    kb.add(InlineKeyboardButton("Предложить новость", url=url))
    return kb

def admin_news_list_kb(items: List[dict], page: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    start = page * 10
    end = start + 10
    for item in items[start:end]:
        key = item["key"]
        source = item.get("source_name", "Источник")
        title = html.escape(truncate(item["title"], 80))
        btn_text = f"{source}: {title}"
        kb.add(InlineKeyboardButton(btn_text, callback_data=f"open:{key}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"page:{page-1}"))
    if end < len(items):
        nav.append(InlineKeyboardButton("Вперед ➡️", callback_data=f"page:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.add(InlineKeyboardButton("🔄 Обновить", callback_data="refresh_news"))
    return kb

def preview_action_kb(item_key: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🖼 Оформить", callback_data=f"format:{item_key}"),
        InlineKeyboardButton("📤 Опубликовать", callback_data=f"publish_raw:{item_key}")
    )
    kb.row(
        InlineKeyboardButton("✍️ Краткое резюме", callback_data=f"summary:{item_key}"),
        InlineKeyboardButton("🔗 Источник", callback_data=f"source:{item_key}")
    )
    return kb

def approve_kb(post_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data=f"approve:{post_id}"),
        InlineKeyboardButton("✏️ Изменить", callback_data=f"edit:{post_id}")
    )
    kb.row(InlineKeyboardButton("❌ Отмена", callback_data=f"cancel:{post_id}"))
    return kb

# =========================
# HELPERS: TEXT / TIME
# =========================
def now_msk() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=3)

def sha1s(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]

def clean_html_to_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = html.unescape(text)
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines).strip()

def strip_tags(raw_html: str) -> str:
    return clean_html_to_text(raw_html)

def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].strip()
    return (cut or text[:limit]).rstrip(" ,.;:") + "…"

def smart_join_paragraphs(text: str) -> str:
    parts = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    return "\n\n".join(parts)

def make_summary(text: str, max_sentences: int = SUMMARY_SENTENCES, max_chars: int = 420) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return ""
    sents = re.split(r"(?<=[.!?])\s+", text)
    picked = []
    total = 0
    for s in sents:
        s = s.strip()
        if not s:
            continue
        if total + len(s) > max_chars and picked:
            break
        picked.append(s)
        total += len(s)
        if len(picked) >= max_sentences:
            break
    if not picked:
        return truncate(text, max_chars)
    summary = " ".join(picked)
    return truncate(summary, max_chars)

def parse_pub_date(entry: dict) -> datetime:
    candidates = [
        entry.get("pubDate"),
        entry.get("published"),
        entry.get("updated"),
        entry.get("dc:date"),
    ]
    for value in candidates:
        if not value:
            continue
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)

# =========================
# IMAGE HELPERS
# =========================
def open_image_from_bytes(data: bytes) -> Image.Image:
    im = Image.open(BytesIO(data))
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA")
    return im

def fit_cover(im: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = im.size
    scale = max(target_w / src_w, target_h / src_h)
    nw, nh = int(src_w * scale), int(src_h * scale)
    resized = im.resize((nw, nh), Image.LANCZOS)
    left = max(0, (nw - target_w) // 2)
    top = max(0, (nh - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))

def fit_contain(im: Image.Image, target_w: int, target_h: int, bg=(0, 0, 0)) -> Image.Image:
    src_w, src_h = im.size
    scale = min(target_w / src_w, target_h / src_h)
    nw, nh = max(1, int(src_w * scale)), max(1, int(src_h * scale))
    resized = im.resize((nw, nh), Image.LANCZOS).convert("RGB")
    canvas = Image.new("RGB", (target_w, target_h), bg)
    x = (target_w - nw) // 2
    y = (target_h - nh) // 2
    canvas.paste(resized, (x, y))
    return canvas

def add_dark_overlay(im: Image.Image, alpha: int = 70) -> Image.Image:
    base = im.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, alpha))
    return Image.alpha_composite(base, overlay).convert("RGB")

def create_vertical_gradient(size: Tuple[int, int], top_rgba, bottom_rgba) -> Image.Image:
    w, h = size
    base = Image.new("RGBA", (w, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(top_rgba[0] * (1 - t) + bottom_rgba[0] * t)
        g = int(top_rgba[1] * (1 - t) + bottom_rgba[1] * t)
        b = int(top_rgba[2] * (1 - t) + bottom_rgba[2] * t)
        a = int(top_rgba[3] * (1 - t) + bottom_rgba[3] * t)
        for x in range(w):
            px[x, y] = (r, g, b, a)
    return base

def rounded_blur_background(im: Image.Image, radius: int = 18, blur: int = 24) -> Image.Image:
    bg = im.convert("RGB").resize((CARD_W, CARD_H), Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(blur))
    bg = ImageEnhance.Brightness(bg).enhance(0.72)
    return bg

def draw_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: Tuple[int, int, int, int],
    font_path_bold: bool = True,
    min_size: int = 26,
    max_size: int = 72,
    fill=(255, 255, 255),
    align: str = "left",
    line_spacing: float = 1.10,
) -> Tuple[ImageFont.FreeTypeFont, List[str], int]:
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1
    words = (text or "").strip().split()
    if not words:
        f = load_font(min_size, bold=font_path_bold)
        return f, [], 0

    def wrap_for_font(font):
        lines = []
        cur = words[0]
        for w in words[1:]:
            test = cur + " " + w
            if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        return lines

    chosen_font = load_font(min_size, bold=font_path_bold)
    chosen_lines = [text]
    chosen_total_h = 0

    for size in range(max_size, min_size - 1, -2):
        font = load_font(size, bold=font_path_bold)
        lines = wrap_for_font(font)
        bbox = draw.textbbox((0, 0), "Ag", font=font)
        line_h = bbox[3] - bbox[1]
        total_h = int(len(lines) * line_h + max(0, len(lines) - 1) * line_h * (line_spacing - 1))
        if total_h <= max_h:
            chosen_font = font
            chosen_lines = lines
            chosen_total_h = total_h
            break

    y = y1 + (max_h - chosen_total_h) // 2
    bbox = draw.textbbox((0, 0), "Ag", font=chosen_font)
    line_h = bbox[3] - bbox[1]
    for line in chosen_lines:
        line_w = draw.textbbox((0, 0), line, font=chosen_font)[2]
        if align == "center":
            x = x1 + (max_w - line_w) // 2
        elif align == "right":
            x = x2 - line_w
        else:
            x = x1
        draw.text((x, y), line, font=chosen_font, fill=fill)
        y += int(line_h * line_spacing)

    return chosen_font, chosen_lines, chosen_total_h

def draw_footer(draw: ImageDraw.ImageDraw, width: int, height: int, text: str):
    y1 = height - FOOTER_H
    draw.rectangle([0, y1, width, height], fill=(8, 8, 8))
    font = load_font(30, bold=False)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((width - tw) // 2, y1 + (FOOTER_H - th) // 2 - 1), text, font=font, fill=(255, 255, 255))

def apply_source_button(caption: str, source_url: str) -> Tuple[str, InlineKeyboardMarkup]:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Источник", url=source_url))
    kb.add(InlineKeyboardButton("Предложить новость", url=SUGGEST_URL if SUGGEST_URL else f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else "https://t.me"))
    return caption, kb

def save_jpeg_to_bytes(im: Image.Image, quality: int = JPEG_QUALITY) -> BytesIO:
    bio = BytesIO()
    rgb = im.convert("RGB")
    rgb.save(bio, format="JPEG", quality=quality, optimize=True)
    bio.seek(0)
    return bio

# =========================
# CARD MAKERS
# =========================
def make_card_mn(photo_bytes: bytes, title: str) -> BytesIO:
    photo = open_image_from_bytes(photo_bytes).convert("RGB")
    bg = fit_cover(photo, CARD_W, CARD_H)
    bg = add_dark_overlay(bg, alpha=95)

    draw = ImageDraw.Draw(bg)
    text_box = (
        TITLE_SIDE_PAD,
        TITLE_TOP_PAD,
        CARD_W - TITLE_SIDE_PAD,
        CARD_H - TITLE_BOTTOM_SAFE,
    )
    draw_text_block(
        draw,
        title,
        text_box,
        font_path_bold=True,
        min_size=34,
        max_size=78,
        fill=(255, 255, 255),
        align="left",
        line_spacing=1.08,
    )
    draw_footer(draw, CARD_W, CARD_H, FOOTER_TEXT)
    return save_jpeg_to_bytes(bg)

def make_card_chp_vm(photo_bytes: bytes, title: str) -> BytesIO:
    photo = open_image_from_bytes(photo_bytes).convert("RGB")
    base = fit_cover(photo, CARD_W, CARD_H).convert("RGBA")

    gradient = create_vertical_gradient(
        (CARD_W, CHP_GRADIENT_H),
        (0, 0, 0, 0),
        (0, 0, 0, 210),
    )
    gradient_canvas = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    gradient_canvas.paste(gradient, (0, CARD_H - CHP_GRADIENT_H), gradient)
    base = Image.alpha_composite(base, gradient_canvas)

    draw = ImageDraw.Draw(base)
    text_box = (
        CHP_TITLE_SIDE_PAD,
        CARD_H - CHP_GRADIENT_H + 80,
        CARD_W - CHP_TITLE_SIDE_PAD,
        CARD_H - CHP_TITLE_BOTTOM_PAD,
    )
    draw_text_block(
        draw,
        title,
        text_box,
        font_path_bold=True,
        min_size=36,
        max_size=88,
        fill=(255, 255, 255),
        align="left",
        line_spacing=1.02,
    )
    return save_jpeg_to_bytes(base.convert("RGB"))

def _wrap_text_for_width(draw, text, font, max_w):
    words = (text or "").split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        if draw.textbbox((0, 0), test, font=font)[2] <= max_w:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines

def _draw_story_text(draw, text, box, font, fill=(255, 255, 255), align="center", line_gap=10):
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1
    lines = _wrap_text_for_width(draw, text, font, max_w)
    if not lines:
        return
    line_h = draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]
    total_h = len(lines) * line_h + max(0, len(lines) - 1) * line_gap
    y = y1 + max(0, (max_h - total_h) // 2)
    for line in lines:
        line_w = draw.textbbox((0, 0), line, font=font)[2]
        if align == "center":
            x = x1 + (max_w - line_w) // 2
        elif align == "left":
            x = x1
        else:
            x = x2 - line_w
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h + line_gap

def _fit_story_text(draw, text, box, min_size, max_size, bold=False, montserrat=False, line_gap_ratio=0.18):
    x1, y1, x2, y2 = box
    max_w = x2 - x1
    max_h = y2 - y1
    selected_font = load_font(min_size, bold=bold, montserrat_bold=montserrat)
    selected_gap = 8
    for size in range(max_size, min_size - 1, -2):
        font = load_font(size, bold=bold, montserrat_bold=montserrat)
        lines = _wrap_text_for_width(draw, text, font, max_w)
        if not lines:
            continue
        line_h = draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1]
        gap = max(6, int(line_h * line_gap_ratio))
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * gap
        if total_h <= max_h:
            selected_font = font
            selected_gap = gap
            break
    return selected_font, selected_gap

def make_card_fdr_story(photo_bytes: bytes, title: str, body_text: str) -> BytesIO:
    canvas = Image.new("RGB", (TARGET_W, TARGET_H), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    header_h = int(TARGET_H * STORY_HEADER_RATIO)
    photo_h = int(TARGET_H * STORY_PHOTO_RATIO)
    text_h = TARGET_H - header_h - photo_h

    purple_top = (118, 54, 255, 255)
    purple_bottom = (74, 24, 163, 255)
    header_gradient = create_vertical_gradient((TARGET_W, header_h), purple_top, purple_bottom).convert("RGB")
    canvas.paste(header_gradient, (0, 0))

    photo = open_image_from_bytes(photo_bytes).convert("RGB")
    story_photo = fit_cover(photo, TARGET_W, photo_h)
    canvas.paste(story_photo, (0, header_h))

    draw.rectangle([0, header_h + photo_h, TARGET_W, TARGET_H], fill=(0, 0, 0))

    side_pad = 58
    header_box = (
        side_pad,
        34,
        TARGET_W - side_pad,
        header_h - 34
    )
    text_box = (
        side_pad,
        header_h + photo_h + 26,
        TARGET_W - side_pad,
        TARGET_H - 26
    )

    title_font, title_gap = _fit_story_text(
        draw,
        title,
        header_box,
        min_size=32,
        max_size=58,
        bold=True,
        montserrat=True,
        line_gap_ratio=0.14
    )
    _draw_story_text(
        draw,
        title,
        header_box,
        title_font,
        fill=(255, 255, 255),
        align="center",
        line_gap=title_gap
    )

    body_font, body_gap = _fit_story_text(
        draw,
        body_text,
        text_box,
        min_size=24,
        max_size=38,
        bold=False,
        montserrat=False,
        line_gap_ratio=0.22
    )
    _draw_story_text(
        draw,
        body_text,
        text_box,
        body_font,
        fill=(255, 255, 255),
        align="left",
        line_gap=body_gap
    )

    return save_jpeg_to_bytes(canvas)

# =========================
# NEWS FETCH
# =========================
def extract_image_from_html(html_text: str, base_url: str = "") -> Optional[str]:
    if not html_text:
        return None
    soup = BeautifulSoup(html_text, "html.parser")

    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        if prop in ("og:image", "twitter:image", "twitter:image:src"):
            content = (meta.get("content") or "").strip()
            if content:
                return urljoin(base_url, content)

    img = soup.find("img")
    if img:
        src = (img.get("src") or img.get("data-src") or "").strip()
        if src:
            return urljoin(base_url, src)

    return None

def fetch_rss_items(source: dict) -> List[dict]:
    rss_url = source["rss"]
    now_ts = time.time()
    cached = news_cache.get(rss_url)
    if cached and now_ts - cached[0] < NEWS_CACHE_TTL_SEC:
        return cached[1]

    items: List[dict] = []
    try:
        r = requests_session.get(rss_url, timeout=18)
        r.raise_for_status()
        content = r.content
        root = ET.fromstring(content)

        channel = root.find("channel")
        raw_items = []
        if channel is not None:
            raw_items = channel.findall("item")
        else:
            raw_items = root.findall(".//item")

        for it in raw_items[:MAX_ITEMS_PER_SOURCE]:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            desc = it.findtext("description") or ""
            pub = it.findtext("pubDate") or it.findtext("published") or it.findtext("updated") or ""
            if not title or not link:
                continue
            image_url = None

            enclosure = it.find("enclosure")
            if enclosure is not None:
                enc_type = (enclosure.attrib.get("type") or "").lower()
                enc_url = (enclosure.attrib.get("url") or "").strip()
                if enc_url and ("image" in enc_type or enc_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
                    image_url = enc_url

            if not image_url:
                media = it.find("{http://search.yahoo.com/mrss/}content")
                if media is not None:
                    media_url = (media.attrib.get("url") or "").strip()
                    if media_url:
                        image_url = media_url

            if not image_url:
                media_thumb = it.find("{http://search.yahoo.com/mrss/}thumbnail")
                if media_thumb is not None:
                    thumb_url = (media_thumb.attrib.get("url") or "").strip()
                    if thumb_url:
                        image_url = thumb_url

            if not image_url and desc:
                image_url = extract_image_from_html(desc, base_url=link)

            item = {
                "title": strip_tags(title),
                "link": link,
                "description": strip_tags(desc),
                "pubDate": pub,
                "source_name": source["name"],
                "image_url": image_url,
            }
            items.append(item)

    except Exception as e:
        print(f"[RSS ERROR] {source['name']}: {e}")

    news_cache[rss_url] = (now_ts, items)
    return items

def collect_latest_news() -> List[dict]:
    all_items = []
    for src in NEWS_SOURCES:
        all_items.extend(fetch_rss_items(src))
    all_items.sort(key=parse_pub_date, reverse=True)

    prepared = []
    preview_index.clear()
    for item in all_items:
        key = sha1s(item["link"])
        item["key"] = key
        preview_index[key] = item
        prepared.append(item)
    return prepared

# =========================
# ARTICLE FETCH / PARSE
# =========================
def download_image_bytes(url: str) -> Optional[bytes]:
    if not url:
        return None
    try:
        r = requests_session.get(url, timeout=20)
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "image" not in ctype and not url.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            return None
        return r.content
    except Exception as e:
        print(f"[IMG ERROR] {url}: {e}")
        return None

def absolute_url(base: str, url: str) -> str:
    try:
        return urljoin(base, url)
    except Exception:
        return url

def choose_best_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    selectors = [
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('meta[name="twitter:image:src"]', "content"),
        ('link[rel="image_src"]', "href"),
    ]
    for sel, attr in selectors:
        tag = soup.select_one(sel)
        if tag and tag.get(attr):
            return absolute_url(base_url, tag.get(attr).strip())

    for img in soup.find_all("img"):
        src = (img.get("src") or img.get("data-src") or img.get("data-original") or "").strip()
        if not src:
            continue
        src_abs = absolute_url(base_url, src)
        low = src_abs.lower()
        if any(x in low for x in ["logo", "sprite", "icon", "avatar"]):
            continue
        return src_abs
    return None

def extract_main_text_generic(soup: BeautifulSoup) -> str:
    for bad in soup(["script", "style", "noscript", "iframe", "svg", "form", "aside", "footer", "nav"]):
        bad.decompose()

    candidates = []
    selectors = [
        "article",
        "main",
        '[itemprop="articleBody"]',
        ".article-body",
        ".article__body",
        ".news-text",
        ".news__body",
        ".post-content",
        ".entry-content",
        ".content",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text("\n", strip=True)
            if len(txt) > 400:
                candidates.append(txt)

    if not candidates:
        paras = soup.find_all("p")
        text = "\n".join(p.get_text(" ", strip=True) for p in paras if len(p.get_text(" ", strip=True)) > 40)
        return smart_join_paragraphs(text)

    candidates.sort(key=len, reverse=True)
    return smart_join_paragraphs(candidates[0])

def fetch_article(link: str) -> dict:
    cached = article_cache.get(link)
    if cached:
        return cached

    data = {
        "url": link,
        "title": "",
        "text": "",
        "summary": "",
        "image_url": None,
        "image_bytes": None,
    }

    try:
        r = requests_session.get(link, timeout=20)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or r.encoding
        html_text = r.text
        soup = BeautifulSoup(html_text, "html.parser")

        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title and og_title.get("content"):
            title = og_title["content"].strip() or title

        text = extract_main_text_generic(soup)
        summary = make_summary(text, max_sentences=3, max_chars=420)
        image_url = choose_best_image(soup, link)
        image_bytes = download_image_bytes(image_url) if image_url else None

        data.update({
            "title": title,
            "text": text,
            "summary": summary,
            "image_url": image_url,
            "image_bytes": image_bytes,
        })
    except Exception as e:
        print(f"[ARTICLE ERROR] {link}: {e}")

    article_cache[link] = data
    return data

# =========================
# STATE
# =========================
def set_state(user_id: int, **kwargs):
    st = user_state.get(user_id, {})
    st.update(kwargs)
    user_state[user_id] = st

def get_state(user_id: int) -> dict:
    return user_state.get(user_id, {})

def clear_state(user_id: int):
    user_state.pop(user_id, None)

# =========================
# SEND HELPERS
# =========================
def send_preview_message(chat_id: int, item: dict):
    article = fetch_article(item["link"])
    title = item["title"]
    source = item.get("source_name", "Источник")
    text = article.get("text") or item.get("description") or ""
    preview = truncate(text, MAX_PREVIEW_TEXT)
    caption = (
        f"<b>{html.escape(title)}</b>\n\n"
        f"{html.escape(preview)}\n\n"
        f"<i>{html.escape(source)}</i>"
    )

    img = article.get("image_bytes")
    kb = preview_action_kb(item["key"])
    if img:
        bot.send_photo(chat_id, img, caption=caption, reply_markup=kb)
    else:
        bot.send_message(chat_id, caption, reply_markup=kb, disable_web_page_preview=False)

def build_publish_caption(title: str, body: str) -> str:
    body = (body or "").strip()
    return f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}"

def post_to_channel_as_photo(photo_bytes: bytes, caption: str, source_url: str):
    caption, kb = apply_source_button(caption, source_url)
    return bot.send_photo(CHANNEL, photo_bytes, caption=caption, reply_markup=kb)

def post_to_channel_as_text(caption: str, source_url: str):
    caption, kb = apply_source_button(caption, source_url)
    return bot.send_message(CHANNEL, caption, reply_markup=kb, disable_web_page_preview=False)

# =========================
# COMMANDS
# =========================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.send_message(
        message.chat.id,
        "Привет! Выбери действие:",
        reply_markup=main_menu()
    )

@bot.message_handler(commands=["news"])
def cmd_news(message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "Эта команда доступна только администратору.")
        return
    items = collect_latest_news()
    if not items:
        bot.reply_to(message, "Не удалось загрузить новости.")
        return
    bot.send_message(
        message.chat.id,
        f"Найдено новостей: {len(items)}. Выбери:",
        reply_markup=admin_news_list_kb(items, 0)
    )

# =========================
# TEXT MENU ACTIONS
# =========================
@bot.message_handler(func=lambda m: m.text == "📰 Новости")
def menu_news(message):
    if ADMIN_ID and message.from_user.id != ADMIN_ID:
        bot.reply_to(message, "Эта кнопка доступна только администратору.")
        return
    items = collect_latest_news()
    if not items:
        bot.reply_to(message, "Не удалось загрузить новости.")
        return
    bot.send_message(
        message.chat.id,
        f"Найдено новостей: {len(items)}. Выбери:",
        reply_markup=admin_news_list_kb(items, 0)
    )

@bot.message_handler(func=lambda m: m.text == "📨 Предложить новость")
def menu_suggest(message):
    url = SUGGEST_URL if SUGGEST_URL else f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else "https://t.me"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Отправить новость / фото / видео", url=url))
    kb.add(InlineKeyboardButton("Связь с редакцией", url=url))
    bot.send_message(
        message.chat.id,
        "Отправляйте фото, видео и текст через кнопку ниже:",
        reply_markup=kb
    )

@bot.message_handler(func=lambda m: m.text == "🖼 Оформить")
def menu_format(message):
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row(KeyboardButton("МН"), KeyboardButton("ЧП ВМ"))
    kb.row(KeyboardButton("Сторис ФДР"))
    kb.row(KeyboardButton("⬅️ Отмена"))
    set_state(message.from_user.id, flow="choose_template")
    bot.send_message(message.chat.id, "Выбери шаблон:", reply_markup=kb)

# =========================
# CALLBACKS
# =========================
@bot.callback_query_handler(func=lambda call: True)
def on_callback(call):
    data = call.data or ""

    if data.startswith("page:"):
        page = int(data.split(":")[1])
        items = collect_latest_news()
        bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id,
            reply_markup=admin_news_list_kb(items, page)
        )
        bot.answer_callback_query(call.id)
        return

    if data == "refresh_news":
        items = collect_latest_news()
        bot.edit_message_reply_markup(
            call.message.chat.id, call.message.message_id,
            reply_markup=admin_news_list_kb(items, 0)
        )
        bot.answer_callback_query(call.id, "Обновлено")
        return

    if data.startswith("open:"):
        key = data.split(":", 1)[1]
        item = preview_index.get(key)
        if not item:
            bot.answer_callback_query(call.id, "Новость не найдена")
            return
        send_preview_message(call.message.chat.id, item)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("source:"):
        key = data.split(":", 1)[1]
        item = preview_index.get(key)
        if item:
            bot.answer_callback_query(call.id, item["link"], show_alert=True)
        else:
            bot.answer_callback_query(call.id, "Источник не найден")
        return

    if data.startswith("summary:"):
        key = data.split(":", 1)[1]
        item = preview_index.get(key)
        if not item:
            bot.answer_callback_query(call.id, "Новость не найдена")
            return
        article = fetch_article(item["link"])
        summary = article.get("summary") or make_summary(article.get("text") or item.get("description") or "")
        bot.send_message(
            call.message.chat.id,
            f"<b>{html.escape(item['title'])}</b>\n\n{html.escape(summary)}"
        )
        bot.answer_callback_query(call.id)
        return

    if data.startswith("publish_raw:"):
        key = data.split(":", 1)[1]
        item = preview_index.get(key)
        if not item:
            bot.answer_callback_query(call.id, "Новость не найдена")
            return
        article = fetch_article(item["link"])
        title = item["title"]
        body = article.get("text") or item.get("description") or ""
        body = truncate(body, 3000)
        caption = build_publish_caption(title, body)

        try:
            if article.get("image_bytes"):
                post_to_channel_as_photo(article["image_bytes"], caption, item["link"])
            else:
                post_to_channel_as_text(caption, item["link"])
            bot.answer_callback_query(call.id, "Опубликовано")
        except Exception as e:
            print(f"[PUBLISH RAW ERROR] {e}")
            bot.answer_callback_query(call.id, "Ошибка публикации", show_alert=True)
        return

    if data.startswith("format:"):
        key = data.split(":", 1)[1]
        item = preview_index.get(key)
        if not item:
            bot.answer_callback_query(call.id, "Новость не найдена")
            return
        kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row(KeyboardButton("МН"), KeyboardButton("ЧП ВМ"))
        kb.row(KeyboardButton("Сторис ФДР"))
        kb.row(KeyboardButton("⬅️ Отмена"))
        set_state(call.from_user.id, flow="format_from_news", news_key=key)
        bot.send_message(call.message.chat.id, "Выбери шаблон оформления:", reply_markup=kb)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("approve:"):
        post_id = data.split(":", 1)[1]
        st = get_state(call.from_user.id)
        post = st.get("pending_posts", {}).get(post_id)
        if not post:
            bot.answer_callback_query(call.id, "Пост не найден")
            return
        try:
            if post["type"] == "photo":
                post_to_channel_as_photo(post["photo_bytes"], post["caption"], post["source_url"])
            elif post["type"] == "story_photo":
                bot.send_photo(CHANNEL, post["photo_bytes"])
            else:
                post_to_channel_as_text(post["caption"], post["source_url"])
            bot.answer_callback_query(call.id, "Опубликовано")
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception:
                pass
        except Exception as e:
            print(f"[APPROVE ERROR] {e}")
            bot.answer_callback_query(call.id, "Ошибка публикации", show_alert=True)
        return

    if data.startswith("edit:"):
        post_id = data.split(":", 1)[1]
        st = get_state(call.from_user.id)
        post = st.get("pending_posts", {}).get(post_id)
        if not post:
            bot.answer_callback_query(call.id, "Пост не найден")
            return

        if post.get("template") == "fdr_story":
            set_state(
                call.from_user.id,
                flow="edit_fdr_story_title",
                edit_post_id=post_id
            )
            bot.send_message(
                call.message.chat.id,
                "Отправь новый заголовок для сторис:",
                reply_markup=telebot.types.ReplyKeyboardRemove()
            )
            bot.answer_callback_query(call.id)
            return

        set_state(
            call.from_user.id,
            flow="edit_caption",
            edit_post_id=post_id
        )
        bot.send_message(
            call.message.chat.id,
            "Пришли новый текст поста целиком:",
            reply_markup=telebot.types.ReplyKeyboardRemove()
        )
        bot.answer_callback_query(call.id)
        return

    if data.startswith("cancel:"):
        post_id = data.split(":", 1)[1]
        st = get_state(call.from_user.id)
        pending = st.get("pending_posts", {})
        if post_id in pending:
            pending.pop(post_id, None)
            set_state(call.from_user.id, pending_posts=pending)
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Отменено")
        return

# =========================
# MESSAGE FLOWS
# =========================
@bot.message_handler(content_types=["photo"])
def on_photo(message):
    st = get_state(message.from_user.id)
    flow = st.get("flow")

    if flow == "await_manual_photo":
        try:
            file_info = bot.get_file(message.photo[-1].file_id)
            file_bytes = bot.download_file(file_info.file_path)
        except Exception as e:
            print(f"[PHOTO DOWNLOAD ERROR] {e}")
            bot.reply_to(message, "Не удалось скачать фото.")
            return

        template = st.get("template")
        if template == "mn":
            set_state(message.from_user.id, photo_bytes=file_bytes, flow="await_manual_title")
            bot.send_message(message.chat.id, "Отправь заголовок:")
            return
        elif template == "chp_vm":
            set_state(message.from_user.id, photo_bytes=file_bytes, flow="await_manual_title")
            bot.send_message(message.chat.id, "Отправь заголовок:")
            return
        elif template == "fdr_story":
            set_state(message.from_user.id, photo_bytes=file_bytes, flow="await_fdr_story_title")
            bot.send_message(message.chat.id, "Отправь заголовок:")
            return

    bot.reply_to(message, "Фото получено, но сейчас я его не жду. Нажми «🖼 Оформить».")

@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(message):
    text = (message.text or "").strip()
    st = get_state(message.from_user.id)
    flow = st.get("flow")

    if text == "⬅️ Отмена":
        clear_state(message.from_user.id)
        bot.send_message(message.chat.id, "Действие отменено.", reply_markup=main_menu())
        return

    if flow == "choose_template":
        if text == "МН":
            set_state(message.from_user.id, template="mn", flow="await_manual_photo")
            bot.send_message(message.chat.id, "Пришли фото:", reply_markup=telebot.types.ReplyKeyboardRemove())
            return
        elif text == "ЧП ВМ":
            set_state(message.from_user.id, template="chp_vm", flow="await_manual_photo")
            bot.send_message(message.chat.id, "Пришли фото:", reply_markup=telebot.types.ReplyKeyboardRemove())
            return
        elif text == "Сторис ФДР":
            set_state(message.from_user.id, template="fdr_story", flow="await_manual_photo")
            bot.send_message(message.chat.id, "Пришли фото:", reply_markup=telebot.types.ReplyKeyboardRemove())
            return
        else:
            bot.send_message(message.chat.id, "Выбери шаблон кнопкой ниже.")
            return

    if flow == "format_from_news":
        key = st.get("news_key")
        item = preview_index.get(key)
        if not item:
            bot.send_message(message.chat.id, "Новость не найдена.", reply_markup=main_menu())
            clear_state(message.from_user.id)
            return

        article = fetch_article(item["link"])
        photo_bytes = article.get("image_bytes")
        if not photo_bytes:
            extra = download_image_bytes(item.get("image_url")) if item.get("image_url") else None
            photo_bytes = extra

        if text == "МН":
            if not photo_bytes:
                set_state(message.from_user.id, template="mn", flow="await_manual_photo")
                bot.send_message(message.chat.id, "Фото не найдено. Пришли фото вручную:", reply_markup=telebot.types.ReplyKeyboardRemove())
                return
            title = item["title"]
            card = make_card_mn(photo_bytes, title)
            caption = build_publish_caption(title, article.get("text") or item.get("description") or "")
            post_id = sha1s(str(time.time()) + title)
            pending = st.get("pending_posts", {})
            pending[post_id] = {
                "type": "photo",
                "template": "mn",
                "photo_bytes": card.getvalue(),
                "caption": caption,
                "source_url": item["link"],
            }
            set_state(message.from_user.id, pending_posts=pending)
            bot.send_photo(message.chat.id, card, caption=caption, reply_markup=approve_kb(post_id))
            clear_state(message.from_user.id)
            set_state(message.from_user.id, pending_posts=pending)
            return

        elif text == "ЧП ВМ":
            if not photo_bytes:
                set_state(message.from_user.id, template="chp_vm", flow="await_manual_photo")
                bot.send_message(message.chat.id, "Фото не найдено. Пришли фото вручную:", reply_markup=telebot.types.ReplyKeyboardRemove())
                return
            title = item["title"]
            card = make_card_chp_vm(photo_bytes, title)
            caption = build_publish_caption(title, article.get("text") or item.get("description") or "")
            post_id = sha1s(str(time.time()) + title)
            pending = st.get("pending_posts", {})
            pending[post_id] = {
                "type": "photo",
                "template": "chp_vm",
                "photo_bytes": card.getvalue(),
                "caption": caption,
                "source_url": item["link"],
            }
            set_state(message.from_user.id, pending_posts=pending)
            bot.send_photo(message.chat.id, card, caption=caption, reply_markup=approve_kb(post_id))
            clear_state(message.from_user.id)
            set_state(message.from_user.id, pending_posts=pending)
            return

        elif text == "Сторис ФДР":
            if not photo_bytes:
                set_state(message.from_user.id, template="fdr_story", flow="await_manual_photo")
                bot.send_message(message.chat.id, "Фото не найдено. Пришли фото вручную:", reply_markup=telebot.types.ReplyKeyboardRemove())
                return
            set_state(
                message.from_user.id,
                template="fdr_story",
                flow="await_fdr_story_title",
                photo_bytes=photo_bytes,
                source_url=item["link"],
                news_title=item["title"],
                news_body=article.get("text") or item.get("description") or ""
            )
            bot.send_message(message.chat.id, "Отправь заголовок:", reply_markup=telebot.types.ReplyKeyboardRemove())
            return

        else:
            bot.send_message(message.chat.id, "Выбери шаблон кнопкой ниже.")
            return

    if flow == "await_manual_title":
        template = st.get("template")
        photo_bytes = st.get("photo_bytes")
        title = text

        if not photo_bytes:
            bot.send_message(message.chat.id, "Фото потерялось. Пришли заново.", reply_markup=main_menu())
            clear_state(message.from_user.id)
            return

        if template == "mn":
            card = make_card_mn(photo_bytes, title)
            caption = f"<b>{html.escape(title)}</b>"
            post_id = sha1s(str(time.time()) + title)
            pending = st.get("pending_posts", {})
            pending[post_id] = {
                "type": "photo",
                "template": "mn",
                "photo_bytes": card.getvalue(),
                "caption": caption,
                "source_url": "https://t.me",
            }
            set_state(message.from_user.id, pending_posts=pending)
            bot.send_photo(message.chat.id, card, caption=caption, reply_markup=approve_kb(post_id))
            clear_state(message.from_user.id)
            set_state(message.from_user.id, pending_posts=pending)
            return

        elif template == "chp_vm":
            card = make_card_chp_vm(photo_bytes, title)
            caption = f"<b>{html.escape(title)}</b>"
            post_id = sha1s(str(time.time()) + title)
            pending = st.get("pending_posts", {})
            pending[post_id] = {
                "type": "photo",
                "template": "chp_vm",
                "photo_bytes": card.getvalue(),
                "caption": caption,
                "source_url": "https://t.me",
            }
            set_state(message.from_user.id, pending_posts=pending)
            bot.send_photo(message.chat.id, card, caption=caption, reply_markup=approve_kb(post_id))
            clear_state(message.from_user.id)
            set_state(message.from_user.id, pending_posts=pending)
            return

    if flow == "await_fdr_story_title":
        set_state(message.from_user.id, story_title=text, flow="await_fdr_story_body")
        bot.send_message(message.chat.id, "Отправь основной текст:")
        return

    if flow == "await_fdr_story_body":
        photo_bytes = st.get("photo_bytes")
        title = st.get("story_title") or st.get("news_title") or ""
        body_text = text
        source_url = st.get("source_url") or "https://t.me"

        if not photo_bytes:
            bot.send_message(message.chat.id, "Фото потерялось. Пришли заново.", reply_markup=main_menu())
            clear_state(message.from_user.id)
            return

        story = make_card_fdr_story(photo_bytes, title, body_text)
        post_id = sha1s(str(time.time()) + title + body_text)
        pending = st.get("pending_posts", {})
        pending[post_id] = {
            "type": "story_photo",
            "template": "fdr_story",
            "photo_bytes": story.getvalue(),
            "caption": "",
            "source_url": source_url,
            "story_title": title,
            "story_body": body_text,
            "raw_photo_bytes": photo_bytes,
        }
        set_state(message.from_user.id, pending_posts=pending)
        bot.send_photo(
            message.chat.id,
            story,
            caption="Сторис готова.",
            reply_markup=approve_kb(post_id)
        )
        clear_state(message.from_user.id)
        set_state(message.from_user.id, pending_posts=pending)
        return

    if flow == "edit_caption":
        post_id = st.get("edit_post_id")
        pending = st.get("pending_posts", {})
        post = pending.get(post_id)
        if not post:
            bot.send_message(message.chat.id, "Пост не найден.", reply_markup=main_menu())
            clear_state(message.from_user.id)
            return
        post["caption"] = text
        set_state(message.from_user.id, pending_posts=pending)
        bot.send_message(
            message.chat.id,
            "Текст обновлён. Нажми кнопку под превью для публикации.",
            reply_markup=main_menu()
        )
        clear_state(message.from_user.id)
        set_state(message.from_user.id, pending_posts=pending)
        return

    if flow == "edit_fdr_story_title":
        post_id = st.get("edit_post_id")
        pending = st.get("pending_posts", {})
        post = pending.get(post_id)
        if not post:
            bot.send_message(message.chat.id, "Сторис не найдена.", reply_markup=main_menu())
            clear_state(message.from_user.id)
            return
        post["story_title"] = text
        pending[post_id] = post
        set_state(
            message.from_user.id,
            pending_posts=pending,
            flow="edit_fdr_story_body",
            edit_post_id=post_id
        )
        bot.send_message(message.chat.id, "Отправь новый основной текст для сторис:")
        return

    if flow == "edit_fdr_story_body":
        post_id = st.get("edit_post_id")
        pending = st.get("pending_posts", {})
        post = pending.get(post_id)
        if not post:
            bot.send_message(message.chat.id, "Сторис не найдена.", reply_markup=main_menu())
            clear_state(message.from_user.id)
            return

        post["story_body"] = text
        raw_photo = post.get("raw_photo_bytes")
        title = post.get("story_title", "")
        body_text = post.get("story_body", "")

        if not raw_photo:
            bot.send_message(message.chat.id, "Исходное фото для сторис не найдено.", reply_markup=main_menu())
            clear_state(message.from_user.id)
            return

        story = make_card_fdr_story(raw_photo, title, body_text)
        post["photo_bytes"] = story.getvalue()
        pending[post_id] = post
        set_state(message.from_user.id, pending_posts=pending)

        bot.send_photo(
            message.chat.id,
            story,
            caption="Сторис обновлена.",
            reply_markup=approve_kb(post_id)
        )
        clear_state(message.from_user.id)
        set_state(message.from_user.id, pending_posts=pending)
        return

    bot.send_message(message.chat.id, "Выбери действие:", reply_markup=main_menu())

# =========================
# RUN
# =========================
if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
