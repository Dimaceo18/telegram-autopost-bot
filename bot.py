# -*- coding: utf-8 -*-
import os
import re
import html
import time
import hashlib
import logging
from io import BytesIO
from typing import Dict, List, Optional
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
import telebot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# =========================
# ЛОГИ
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# =========================
# ENV
# =========================
TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL = os.getenv("CHANNEL_USERNAME", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не установлен")

if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL

# =========================
# БОТ
# =========================
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# =========================
# РАЗМЕРЫ
# =========================
TARGET_W, TARGET_H = 750, 938       # 4:5
STORY_W, STORY_H = 720, 1280        # 9:16

# =========================
# ШРИФТЫ
# =========================
FONT_MN = "CaviarDreams.ttf"
FONT_CHP = "Montserrat-Black.ttf"
FONT_AM = "IntroInline.ttf"
FONT_STORY = "Montserrat-Black.ttf"
FOOTER_TEXT = "MINSK NEWS"

# =========================
# КНОПКИ
# =========================
BTN_POST = "📝 Оформить пост"
BTN_NEWS = "📰 Получить новости"

# =========================
# ИСТОЧНИКИ
# =========================
NEWS_SOURCES = [
    {"id": "onliner",    "name": "Onliner",    "kind": "rss",  "url": "https://www.onliner.by/feed"},
    {"id": "sputnik",    "name": "Sputnik",    "kind": "rss",  "url": "https://sputnik.by/export/rss2/index.xml"},
    {"id": "telegraf",   "name": "Telegraf",   "kind": "rss",  "url": "https://telegraf.news/feed/"},
    {"id": "tochka",     "name": "Tochka",     "kind": "html", "url": "https://tochka.by/articles/"},
    {"id": "smartpress", "name": "Smartpress", "kind": "html", "url": "https://smartpress.by/news/"},
    {"id": "sb",         "name": "SB.by",      "kind": "html", "url": "https://www.sb.by/news/"},
    {"id": "minsknews",  "name": "Minsknews",  "kind": "html", "url": "https://minsknews.by/"},
    {"id": "mlyn",       "name": "Mlyn",       "kind": "html", "url": "https://mlyn.by/"},
    {"id": "ont",        "name": "ONT",        "kind": "html", "url": "https://ont.by/news"},
]

# =========================
# ПАМЯТЬ
# =========================
user_state: Dict[int, dict] = {}

# =========================
# HTTP SESSION
# =========================
SESSION = requests.Session()
retry_strategy = Retry(
    total=3,
    connect=3,
    read=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"]
)
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0 Safari/537.36"
})

# =========================
# ОБЩИЕ УТИЛИТЫ
# =========================
def ensure_fonts() -> None:
    missing = []
    for path in [FONT_MN, FONT_CHP, FONT_AM, FONT_STORY]:
        if not os.path.exists(path):
            missing.append(path)
    if missing:
        raise RuntimeError("Не найдены файлы шрифтов: " + ", ".join(missing))

def http_get(url: str, timeout: int = 25) -> str:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def http_get_bytes(url: str, timeout: int = 25) -> bytes:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content

def tg_file_bytes(file_id: str) -> bytes:
    file_info = bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
    return http_get_bytes(file_url)

def escape_html(s: Optional[str]) -> str:
    return html.escape(s or "")

def build_caption_html(title: str, body: str) -> str:
    return f"<b>{escape_html(title)}</b>\n\n{escape_html(body)}"

def split_long_plain_text(text: str, max_len: int = 3500) -> List[str]:
    text = text.strip()
    if not text:
        return []
    parts = []
    while len(text) > max_len:
        cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = text.rfind(" ", 0, max_len)
        if cut == -1:
            cut = max_len
        part = text[:cut].strip()
        if part:
            parts.append(part)
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts

def is_admin(user_id: int) -> bool:
    return (ADMIN_ID == 0) or (user_id == ADMIN_ID)

def reset_user(uid: int, template: str = "MN", mn_layout: str = "top") -> None:
    user_state[uid] = {
        "step": "idle",
        "template": template,
        "mn_layout": mn_layout
    }

def safe_filename_hash(title: str, link: str) -> str:
    return hashlib.sha256(f"{title}|{link}".encode("utf-8")).hexdigest()[:16]

# =========================
# ИЗОБРАЖЕНИЯ
# =========================
def crop_to_4x5(img: Image.Image) -> Image.Image:
    w, h = img.size
    target_ratio = 4 / 5
    current_ratio = w / h
    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        return img.crop((0, top, w, top + new_h))

def fit_cover(img: Image.Image, width: int, height: int) -> Image.Image:
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    dst_ratio = width / height

    if src_ratio > dst_ratio:
        new_h = height
        new_w = int(height * src_ratio)
    else:
        new_w = width
        new_h = int(width / src_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return img.crop((left, top, left + width, top + height))

def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    words = text.split()
    if not words:
        return []

    lines = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        if draw.textlength(test, font=font) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines

def text_bbox_h(font: ImageFont.FreeTypeFont) -> int:
    box = font.getbbox("Ag")
    return box[3] - box[1]

def save_jpeg_bytes(img: Image.Image, quality: int = 95) -> BytesIO:
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    out.seek(0)
    return out

# =========================
# ШАБЛОНЫ
# =========================
def make_card_mn(photo_bytes: bytes, title: str, layout: str = "top") -> BytesIO:
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.55)

    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_MN, 72)
    footer_font = ImageFont.truetype(FONT_MN, 28)

    text = (title or "").upper().strip()
    lines = wrap_text(draw, text, font, int(img.width * 0.9))
    line_h = text_bbox_h(font)
    spacing = 12
    block_h = len(lines) * line_h + max(0, len(lines) - 1) * spacing

    if layout == "bottom":
        y = img.height - block_h - 130
        footer_y = 45
    else:
        y = 50
        footer_y = img.height - 55

    for line in lines:
        w = draw.textlength(line, font=font)
        x = (img.width - w) / 2
        draw.text((x, y), line, font=font, fill="white")
        y += line_h + spacing

    fw = draw.textlength(FOOTER_TEXT, font=footer_font)
    draw.text(((img.width - fw) / 2, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    return save_jpeg_bytes(img)

def make_card_chp(photo_bytes: bytes, title: str) -> BytesIO:
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.9)

    rgba = img.convert("RGBA")
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))

    grad = Image.new("L", (1, rgba.height), 0)
    for y in range(rgba.height):
        if y < rgba.height * 0.45:
            alpha = 0
        else:
            alpha = int(min(210, ((y - rgba.height * 0.45) / (rgba.height * 0.55)) * 210))
        grad.putpixel((0, y), alpha)
    grad = grad.resize(rgba.size)
    black = Image.new("RGBA", rgba.size, (0, 0, 0, 220))
    overlay = Image.composite(black, overlay, grad)
    rgba = Image.alpha_composite(rgba, overlay)
    img = rgba.convert("RGB")

    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_CHP, 68)
    lines = wrap_text(draw, (title or "").upper(), font, int(img.width * 0.9))
    line_h = text_bbox_h(font)
    spacing = 8
    block_h = len(lines) * line_h + max(0, len(lines) - 1) * spacing

    y = img.height - block_h - 70
    for line in lines:
        w = draw.textlength(line, font=font)
        x = (img.width - w) / 2
        draw.text((x, y), line, font=font, fill="white")
        y += line_h + spacing

    return save_jpeg_bytes(img)

def make_card_am(photo_bytes: bytes, title: str) -> BytesIO:
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)

    blurred_top = img.crop((0, 0, img.width, 220)).filter(ImageFilter.GaussianBlur(18))
    dark = Image.new("RGB", blurred_top.size, (0, 0, 0))
    blurred_top = Image.blend(blurred_top, dark, 0.25)
    img.paste(blurred_top, (0, 0))

    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_AM, 60)
    lines = wrap_text(draw, (title or "").upper(), font, int(img.width * 0.9))
    line_h = text_bbox_h(font)
    spacing = 8
    y = 40

    for line in lines:
        w = draw.textlength(line, font=font)
        x = (img.width - w) / 2
        draw.text((x, y), line, font=font, fill="white")
        y += line_h + spacing

    return save_jpeg_bytes(img)

def make_card_fdr(photo_bytes: bytes, title: str, body: str) -> BytesIO:
    canvas = Image.new("RGB", (STORY_W, STORY_H), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)

    photo = Image.open(BytesIO(photo_bytes)).convert("RGB")
    photo = fit_cover(photo, STORY_W, 420)
    canvas.paste(photo, (0, 0))

    purple = (122, 58, 240)
    header = Image.new("RGB", (STORY_W, 230), purple)
    canvas.paste(header, (0, 420))

    title_font = ImageFont.truetype(FONT_STORY, 50)
    body_font = ImageFont.truetype(FONT_STORY, 30)

    title_lines = wrap_text(draw, (title or "").strip(), title_font, STORY_W - 80)
    title_line_h = text_bbox_h(title_font)
    y = 455
    for line in title_lines[:4]:
        w = draw.textlength(line, font=title_font)
        x = (STORY_W - w) / 2
        draw.text((x, y), line, font=title_font, fill="white")
        y += title_line_h + 8

    body_lines = wrap_text(draw, (body or "").strip(), body_font, STORY_W - 80)
    body_line_h = text_bbox_h(body_font)
    y = 690
    max_lines = 12
    for line in body_lines[:max_lines]:
        draw.text((40, y), line, font=body_font, fill="white")
        y += body_line_h + 10

    return save_jpeg_bytes(canvas)

def make_card(photo_bytes: bytes, title: str, template: str, body: str = "", mn_layout: str = "top") -> BytesIO:
    if template == "CHP":
        return make_card_chp(photo_bytes, title)
    if template == "AM":
        return make_card_am(photo_bytes, title)
    if template == "FDR_STORY":
        return make_card_fdr(photo_bytes, title, body)
    return make_card_mn(photo_bytes, title, mn_layout)

# =========================
# КЛАВИАТУРЫ
# =========================
def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(BTN_POST), KeyboardButton(BTN_NEWS))
    return kb

def template_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📰 МН", callback_data="tpl:MN"),
        InlineKeyboardButton("🚨 ЧП ВМ", callback_data="tpl:CHP")
    )
    kb.row(
        InlineKeyboardButton("✨ АМ", callback_data="tpl:AM"),
        InlineKeyboardButton("📱 Сторис ФДР", callback_data="tpl:FDR_STORY")
    )
    return kb

def mn_layout_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("⬆️ Текст вверху", callback_data="mnlayout:top"),
        InlineKeyboardButton("⬇️ Текст внизу", callback_data="mnlayout:bottom")
    )
    return kb

def news_item_kb(key: str, link: str):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Открыть", callback_data=f"nfmt:{key}"),
        InlineKeyboardButton("🗑 Пропустить", callback_data=f"nskip:{key}")
    )
    kb.row(InlineKeyboardButton("🔗 Источник", url=link))
    return kb

def preview_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("✏️ Изменить текст", callback_data="edit_body")
    )
    kb.row(
        InlineKeyboardButton("✏️ Изменить заголовок", callback_data="edit_title"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel")
    )
    return kb

# =========================
# ПАРСИНГ НОВОСТЕЙ
# =========================
def extract_rss_image(item) -> str:
    enclosure = item.find("enclosure")
    if enclosure is not None and enclosure.get("url"):
        return enclosure.get("url", "").strip()

    media_ns = "{http://search.yahoo.com/mrss/}"
    media_content = item.find(f"{media_ns}content")
    if media_content is not None and media_content.get("url"):
        return media_content.get("url", "").strip()

    media_thumbnail = item.find(f"{media_ns}thumbnail")
    if media_thumbnail is not None and media_thumbnail.get("url"):
        return media_thumbnail.get("url", "").strip()

    desc = item.findtext("description", "")
    soup = BeautifulSoup(desc, "html.parser")
    img = soup.find("img")
    if img and img.get("src"):
        return img["src"].strip()

    return ""

def parse_rss(url: str, source_name: str) -> List[dict]:
    try:
        xml_text = http_get(url)
        root = ET.fromstring(xml_text)
        items = []
        for item in root.findall(".//item")[:15]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()

            if not title or not link:
                continue

            summary = BeautifulSoup(desc, "html.parser").get_text(" ", strip=True)[:300]
            image = extract_rss_image(item)

            items.append({
                "source": source_name,
                "title": title,
                "url": link,
                "summary": summary,
                "image": image
            })
        return items
    except Exception as e:
        logger.error(f"RSS error {source_name}: {e}")
        return []

def parse_html_source(url: str, source_name: str) -> List[dict]:
    try:
        html_text = http_get(url)
        soup = BeautifulSoup(html_text, "html.parser")
        items = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            title = a.get_text(" ", strip=True)

            if not href or not title:
                continue

            if len(title) < 30:
                continue

            low = title.lower()
            if any(x in low for x in ["рубрика", "категория", "страница", "читать также", "подписывайтесь"]):
                continue

            if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:"):
                continue

            if not href.startswith("http"):
                href = urljoin(url, href)

            key = (title, href)
            if key in seen:
                continue
            seen.add(key)

            items.append({
                "source": source_name,
                "title": title,
                "url": href,
                "summary": "",
                "image": ""
            })

            if len(items) >= 15:
                break

        return items
    except Exception as e:
        logger.error(f"HTML error {source_name}: {e}")
        return []

def extract_main_image(soup: BeautifulSoup, page_url: str) -> str:
    candidates = []

    meta_props = [
        ("meta", {"property": "og:image"}, "content"),
        ("meta", {"name": "og:image"}, "content"),
        ("meta", {"property": "twitter:image"}, "content"),
        ("meta", {"name": "twitter:image"}, "content"),
    ]
    for tag_name, attrs, attr_name in meta_props:
        tag = soup.find(tag_name, attrs=attrs)
        if tag and tag.get(attr_name):
            candidates.append(tag.get(attr_name))

    img = soup.find("article")
    if img:
        first_img = img.find("img")
        if first_img and first_img.get("src"):
            candidates.append(first_img.get("src"))

    any_img = soup.find("img")
    if any_img and any_img.get("src"):
        candidates.append(any_img.get("src"))

    for c in candidates:
        if c:
            return urljoin(page_url, c.strip())

    return ""

def fetch_article_data(url: str) -> dict:
    try:
        html_text = http_get(url)
        soup = BeautifulSoup(html_text, "html.parser")

        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()

        image = extract_main_image(soup, url)

        article = soup.find("article")
        main = article or soup.find("main") or soup.body

        paragraphs = main.find_all("p") if main else soup.find_all("p")

        text_parts = []
        for p in paragraphs:
            t = p.get_text(" ", strip=True)
            if len(t) < 45:
                continue
            low = t.lower()
            if any(x in low for x in ["подписывайтесь", "реклама", "источник:", "telegram", "телеграм-канал"]):
                continue
            text_parts.append(t)
            if len(text_parts) >= 30:
                break

        full_text = "\n\n".join(text_parts).strip()

        if not full_text:
            full_text = "Не удалось получить текст статьи."

        return {
            "text": full_text,
            "image": image
        }
    except Exception as e:
        logger.error(f"Error fetching article {url}: {e}")
        return {
            "text": "Не удалось получить текст статьи.",
            "image": ""
        }

def fetch_all_news() -> List[dict]:
    all_news = []
    for src in NEWS_SOURCES:
        try:
            if src["kind"] == "rss":
                items = parse_rss(src["url"], src["name"])
            else:
                items = parse_html_source(src["url"], src["name"])
            all_news.extend(items)
        except Exception as e:
            logger.error(f"Source error {src['name']}: {e}")

    seen = set()
    unique = []
    for item in all_news:
        key = (item.get("title", "").strip(), item.get("url", "").strip())
        if not key[0] or not key[1]:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    return unique[:20]

# =========================
# ОТПРАВКА ПОЛНОЙ НОВОСТИ
# =========================
def send_full_news(chat_id: int, title: str, text: str, photo_url: str, link: str) -> None:
    try:
        if photo_url:
            try:
                photo = BytesIO(http_get_bytes(photo_url, timeout=20))
                bot.send_photo(chat_id, photo)
            except Exception as e:
                logger.warning(f"Не удалось отправить фото статьи: {e}")

        header = f"<b>{escape_html(title)}</b>\n\n"
        source_line = f"\n\nИсточник: {escape_html(link)}" if link else ""
        plain_text = (text or "").strip()

        chunks = split_long_plain_text(plain_text, max_len=3300)
        if not chunks:
            chunks = ["Не удалось получить текст статьи."]

        first_msg = header + escape_html(chunks[0]) + source_line
        bot.send_message(chat_id, first_msg, disable_web_page_preview=True)

        for chunk in chunks[1:]:
            bot.send_message(chat_id, escape_html(chunk), disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Ошибка send_full_news: {e}")
        bot.send_message(chat_id, f"Ошибка отправки новости: {escape_html(str(e))}")

# =========================
# ХЕНДЛЕРЫ КОМАНД
# =========================
@bot.message_handler(commands=["start", "help"])
def cmd_start(msg):
    if not is_admin(msg.from_user.id):
        bot.reply_to(msg, "⛔️ Нет доступа.")
        return
    reset_user(msg.from_user.id)
    bot.send_message(msg.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())

@bot.message_handler(commands=["post"])
def cmd_post(msg):
    if not is_admin(msg.from_user.id):
        return
    st = user_state.get(msg.from_user.id, {})
    st["step"] = "waiting_template"
    st.setdefault("template", "MN")
    st.setdefault("mn_layout", "top")
    user_state[msg.from_user.id] = st
    bot.send_message(msg.chat.id, "Выбери шаблон оформления:", reply_markup=template_kb())

@bot.message_handler(commands=["news"])
def cmd_news(msg):
    if not is_admin(msg.from_user.id):
        return

    bot.send_message(msg.chat.id, "Собираю новости… 🧲")
    items = fetch_all_news()
    if not items:
        bot.send_message(msg.chat.id, "Не удалось получить новости.")
        return

    by_key = {}
    for it in items:
        title = it.get("title", "").strip()
        link = it.get("url", "").strip()
        if not title or not link:
            continue

        key = safe_filename_hash(title, link)
        by_key[key] = it

        bot.send_message(
            msg.chat.id,
            f"<b>{escape_html(title)}</b>\n\n{escape_html(it.get('source', ''))}",
            reply_markup=news_item_kb(key, link),
            disable_web_page_preview=True
        )

    if msg.from_user.id not in user_state:
        reset_user(msg.from_user.id)

    user_state[msg.from_user.id]["news_cache"] = {
        "by_key": by_key,
        "ts": time.time()
    }

# =========================
# CALLBACKS
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("tpl:"))
def cb_tpl_pick(c):
    if not is_admin(c.from_user.id):
        return

    uid = c.from_user.id
    tpl = c.data.split(":", 1)[1]
    st = user_state.get(uid, {})
    st["template"] = tpl

    if tpl == "MN":
        st["step"] = "waiting_mn_layout"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок ✅")
        bot.send_message(c.message.chat.id, "Выбери расположение текста:", reply_markup=mn_layout_kb())
        return

    st["step"] = "waiting_photo"
    user_state[uid] = st
    bot.answer_callback_query(c.id, "Ок ✅")
    bot.send_message(c.message.chat.id, "Пришли фото 📷")

@bot.callback_query_handler(func=lambda c: c.data.startswith("mnlayout:"))
def cb_mn_layout(c):
    if not is_admin(c.from_user.id):
        return

    uid = c.from_user.id
    layout = c.data.split(":", 1)[1]
    st = user_state.get(uid, {})
    st["template"] = "MN"
    st["mn_layout"] = layout
    st["step"] = "waiting_photo"
    user_state[uid] = st

    bot.answer_callback_query(c.id, "Ок ✅")
    bot.send_message(c.message.chat.id, "Пришли фото 📷")

@bot.callback_query_handler(func=lambda c: c.data.startswith(("nfmt:", "nskip:")))
def cb_news_actions(c):
    if not is_admin(c.from_user.id):
        return

    uid = c.from_user.id
    st = user_state.get(uid, {})
    cache = st.get("news_cache", {}).get("by_key", {})
    action, key = c.data.split(":", 1)

    if action == "nskip":
        bot.answer_callback_query(c.id, "Пропущено")
        try:
            bot.edit_message_text(
                "🗑 Пропущено.",
                c.message.chat.id,
                c.message.message_id
            )
        except Exception:
            pass
        return

    item = cache.get(key)
    if not item:
        bot.answer_callback_query(c.id, "Новость не найдена")
        return

    title = item.get("title", "")
    link = item.get("url", "")
    image = item.get("image", "")
    article = fetch_article_data(link)
    text = article.get("text") or item.get("summary") or "Не удалось получить текст статьи."
    if not image:
        image = article.get("image", "")

    send_full_news(c.message.chat.id, title, text, image, link)
    bot.answer_callback_query(c.id, "Готово ✅")

@bot.callback_query_handler(func=lambda c: c.data in ["publish", "edit_body", "edit_title", "cancel"])
def cb_preview_actions(c):
    if not is_admin(c.from_user.id):
        return

    uid = c.from_user.id
    st = user_state.get(uid, {})

    if st.get("step") != "waiting_action":
        bot.answer_callback_query(c.id, "Нет активного превью")
        return

    action = c.data

    if action == "publish":
        if not CHANNEL:
            bot.answer_callback_query(c.id, "Канал не задан")
            bot.send_message(c.message.chat.id, "❌ Не задан CHANNEL_USERNAME в переменных окружения.")
            return

        try:
            caption = build_caption_html(st.get("title", ""), st.get("body_raw", ""))
            bot.send_photo(
                CHANNEL,
                BytesIO(st["card_bytes"]),
                caption=caption
            )
            bot.answer_callback_query(c.id, "Опубликовано ✅")
            reset_user(uid, template=st.get("template", "MN"), mn_layout=st.get("mn_layout", "top"))
            bot.send_message(c.message.chat.id, "Готово ✅", reply_markup=main_menu_kb())
        except Exception as e:
            logger.error(f"Publish error: {e}")
            bot.answer_callback_query(c.id, "Ошибка публикации")
            bot.send_message(c.message.chat.id, f"❌ Ошибка публикации: {escape_html(str(e))}")

    elif action == "edit_body":
        st["step"] = "waiting_body_fdr" if st.get("template") == "FDR_STORY" else "waiting_body"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок")
        bot.send_message(c.message.chat.id, "Пришли новый текст:")

    elif action == "edit_title":
        st["step"] = "waiting_title_fdr" if st.get("template") == "FDR_STORY" else "waiting_title"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок")
        bot.send_message(c.message.chat.id, "Пришли новый заголовок:")

    elif action == "cancel":
        bot.answer_callback_query(c.id, "Отменено")
        reset_user(uid, template=st.get("template", "MN"), mn_layout=st.get("mn_layout", "top"))
        bot.send_message(c.message.chat.id, "Отменил ❌", reply_markup=main_menu_kb())

# =========================
# ФОТО
# =========================
@bot.message_handler(content_types=["photo"])
def on_photo(msg):
    if not is_admin(msg.from_user.id):
        return

    uid = msg.from_user.id
    st = user_state.get(uid)
    if not st or st.get("step") != "waiting_photo":
        return

    try:
        st["photo_bytes"] = tg_file_bytes(msg.photo[-1].file_id)
        st["step"] = "waiting_title_fdr" if st.get("template") == "FDR_STORY" else "waiting_title"
        user_state[uid] = st
        bot.reply_to(msg, "Фото получено ✅ Теперь отправь ЗАГОЛОВОК.")
    except Exception as e:
        logger.error(f"Photo download error: {e}")
        bot.reply_to(msg, f"Ошибка загрузки фото: {escape_html(str(e))}")

@bot.message_handler(content_types=["document"])
def on_document(msg):
    if not is_admin(msg.from_user.id):
        return

    uid = msg.from_user.id
    st = user_state.get(uid)
    if not st or st.get("step") != "waiting_photo":
        return

    mime = msg.document.mime_type or ""
    if not mime.startswith("image/"):
        bot.reply_to(msg, "Пришли картинку JPG/PNG.")
        return

    try:
        st["photo_bytes"] = tg_file_bytes(msg.document.file_id)
        st["step"] = "waiting_title_fdr" if st.get("template") == "FDR_STORY" else "waiting_title"
        user_state[uid] = st
        bot.reply_to(msg, "Картинка получена ✅ Теперь отправь ЗАГОЛОВОК.")
    except Exception as e:
        logger.error(f"Document image download error: {e}")
        bot.reply_to(msg, f"Ошибка загрузки картинки: {escape_html(str(e))}")

# =========================
# ТЕКСТ
# =========================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def on_text(msg):
    if not is_admin(msg.from_user.id):
        return

    uid = msg.from_user.id
    text = (msg.text or "").strip()

    if text == BTN_POST:
        return cmd_post(msg)

    if text == BTN_NEWS:
        return cmd_news(msg)

    st = user_state.get(uid, {"step": "idle", "template": "MN", "mn_layout": "top"})
    step = st.get("step")

    if step == "waiting_template":
        bot.send_message(msg.chat.id, "Выбери шаблон кнопками:", reply_markup=template_kb())
        return

    if step == "waiting_mn_layout":
        bot.send_message(msg.chat.id, "Выбери расположение текста:", reply_markup=mn_layout_kb())
        return

    if step == "waiting_title_fdr":
        st["title"] = text
        st["step"] = "waiting_body_fdr"
        user_state[uid] = st
        bot.reply_to(msg, "Заголовок сохранён ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ для сторис.")
        return

    if step == "waiting_body_fdr":
        if not st.get("photo_bytes"):
            bot.reply_to(msg, "❌ Фото потерялось. Начни заново с /post")
            return
        st["body_raw"] = text
        try:
            card = make_card(
                st["photo_bytes"],
                st["title"],
                "FDR_STORY",
                text,
                st.get("mn_layout", "top")
            )
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_action"
            user_state[uid] = st

            bot.send_photo(
                msg.chat.id,
                BytesIO(st["card_bytes"]),
                caption=build_caption_html(st["title"], text),
                reply_markup=preview_kb()
            )
            bot.reply_to(msg, "Сторис готова ✅")
        except Exception as e:
            logger.error(f"FDR card error: {e}")
            bot.reply_to(msg, f"Ошибка создания сторис: {escape_html(str(e))}")
        return

    if step == "waiting_title":
        if not st.get("photo_bytes"):
            bot.reply_to(msg, "❌ Фото потерялось. Начни заново с /post")
            return

        st["title"] = text
        try:
            card = make_card(
                st["photo_bytes"],
                text,
                st.get("template", "MN"),
                "",
                st.get("mn_layout", "top")
            )
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_body"
            user_state[uid] = st
            bot.reply_to(msg, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
        except Exception as e:
            logger.error(f"Card build error: {e}")
            bot.reply_to(msg, f"Ошибка создания карточки: {escape_html(str(e))}")
        return

    if step == "waiting_body":
        st["body_raw"] = text
        st["step"] = "waiting_action"
        user_state[uid] = st

        try:
            bot.send_photo(
                msg.chat.id,
                BytesIO(st["card_bytes"]),
                caption=build_caption_html(st["title"], text),
                reply_markup=preview_kb()
            )
            bot.reply_to(msg, "Превью готово ✅")
        except Exception as e:
            logger.error(f"Preview send error: {e}")
            bot.reply_to(msg, f"Ошибка отправки превью: {escape_html(str(e))}")
        return

    if step == "waiting_action":
        bot.reply_to(msg, "Нажми кнопку под превью ✅✏️❌")
        return

    bot.send_message(msg.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())

# =========================
# RUN
# =========================
if __name__ == "__main__":
    ensure_fonts()
    logger.info("Бот запущен")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
