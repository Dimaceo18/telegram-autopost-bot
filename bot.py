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

# =========================
# НАСТРОЙКИ ЛОГИРОВАНИЯ
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# =========================
# ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# =========================
TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHANNEL = os.getenv("CHANNEL_USERNAME", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TOKEN:
    raise ValueError("BOT_TOKEN не установлен!")
if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL

bot = telebot.TeleBot(TOKEN)

# =========================
# РАЗМЕРЫ И ШРИФТЫ
# =========================
TARGET_W, TARGET_H = 750, 938
STORY_W, STORY_H = 720, 1280

FONT_MN = "CaviarDreams.ttf"
FONT_CHP = "Montserrat-Black.ttf"
FONT_AM = "IntroInline.ttf"
FONT_STORY = "Montserrat-Black.ttf"
FOOTER_TEXT = "MINSK NEWS"

# =========================
# КНОПКИ МЕНЮ
# =========================
BTN_POST = "📝 Оформить пост"
BTN_NEWS = "📰 Получить новости"

# =========================
# ИСТОЧНИКИ НОВОСТЕЙ
# =========================
NEWS_SOURCES = [
    {"id": "onliner", "name": "Onliner", "kind": "rss", "url": "https://www.onliner.by/feed"},
    {"id": "sputnik", "name": "Sputnik", "kind": "rss", "url": "https://sputnik.by/export/rss2/index.xml"},
    {"id": "telegraf", "name": "Telegraf", "kind": "rss", "url": "https://telegraf.news/feed/"},
    {"id": "tochka", "name": "Tochka", "kind": "html", "url": "https://tochka.by/articles/"},
    {"id": "smartpress", "name": "Smartpress", "kind": "html", "url": "https://smartpress.by/news/"},
    {"id": "sb", "name": "SB.by", "kind": "html", "url": "https://www.sb.by/news/"},
    {"id": "minsknews", "name": "Minsknews", "kind": "html", "url": "https://minsknews.by/"},
    {"id": "mlyn", "name": "Mlyn", "kind": "html", "url": "https://mlyn.by/"},
    {"id": "ont", "name": "ONT", "kind": "html", "url": "https://ont.by/news"},
]

user_state = {}
SESSION = requests.Session()

# Настройка повторных попыток
retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
SESSION.mount("http://", adapter)
SESSION.mount("https://", adapter)
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

# =========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================
def http_get(url, timeout=25):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def http_get_bytes(url, timeout=25):
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content

def tg_file_bytes(file_id):
    file_info = bot.get_file(file_id)
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
    return http_get_bytes(url)

def build_caption_html(title, body):
    title = html.escape(title or "")
    body = html.escape(body or "")
    return f"<b>{title}</b>\n\n{body}"

def split_long_text(text, max_len=3500):
    parts = []
    while len(text) > max_len:
        cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = max_len
        parts.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        parts.append(text)
    return parts

def ensure_fonts():
    fonts = [FONT_MN, FONT_CHP, FONT_AM, FONT_STORY]
    for font in fonts:
        if not os.path.exists(font):
            logger.warning(f"Шрифт {font} не найден! Карточки могут не работать.")

# =========================
# ПАРСИНГ НОВОСТЕЙ
# =========================
def parse_rss(url, source_name):
    try:
        xml_text = http_get(url)
        root = ET.fromstring(xml_text)
        items = []
        for item in root.findall(".//item")[:15]:
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            image = ""
            enc = item.find("enclosure")
            if enc is not None and enc.get("url"):
                image = enc.get("url")
            items.append({
                "source": source_name,
                "title": title,
                "url": link,
                "summary": BeautifulSoup(desc, "html.parser").get_text()[:300],
                "image": image,
            })
        return items
    except Exception as e:
        logger.error(f"RSS error {source_name}: {e}")
        return []

def parse_html_source(url, source_name):
    try:
        html_text = http_get(url)
        soup = BeautifulSoup(html_text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True)[:30]:
            href = a["href"]
            if not href.startswith("http"):
                href = urljoin(url, href)
            title = a.get_text().strip()
            if len(title) > 30 and not re.search(r"(категория|рубрика|страница)", title.lower()):
                items.append({
                    "source": source_name,
                    "title": title,
                    "url": href,
                    "summary": "",
                    "image": "",
                })
        return items
    except Exception as e:
        logger.error(f"HTML error {source_name}: {e}")
        return []

def fetch_article_text(url):
    try:
        html_text = http_get(url)
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        article = soup.find("article") or soup.find("main") or soup.body
        paragraphs = article.find_all("p") if article else soup.find_all("p")
        text = []
        for p in paragraphs[:20]:
            t = p.get_text().strip()
            if len(t) > 40 and not re.search(r"(подпишись|реклама|источник|telegram)", t.lower()):
                text.append(t)
        return "\n\n".join(text) if text else "Не удалось получить текст статьи"
    except Exception as e:
        logger.error(f"Error fetching article {url}: {e}")
        return ""

def fetch_all_news():
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
    return all_news

# =========================
# ГРАФИЧЕСКИЕ ФУНКЦИИ
# =========================
def crop_to_4x5(img):
    w, h = img.size
    ratio = 4/5
    cur = w/h
    if cur > ratio:
        new_w = int(h * ratio)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / ratio)
        top = (h - new_h) // 2
        return img.crop((0, top, w, top + new_h))

def wrap_text(draw, text, font, max_width):
    if not text:
        return []
    words = text.split()
    lines = []
    current_line = words[0]
    for word in words[1:]:
        test_line = current_line + " " + word
        if draw.textlength(test_line, font) <= max_width:
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines

# =========================
# ШАБЛОН МН (С ВЫБОРОМ ПОЗИЦИИ)
# =========================
def make_card_mn(photo_bytes, title, layout="top"):
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.55)
    draw = ImageDraw.Draw(img)

    font = ImageFont.truetype(FONT_MN, 72)
    text = title.upper()
    max_w = img.width * 0.9
    lines = wrap_text(draw, text, font, max_w)
    line_h = font.getbbox("A")[3]
    block_h = len(lines) * (line_h + 10)

    if layout == "bottom":
        y = img.height - block_h - 120
        footer_y = 50
    else:
        y = 60
        footer_y = img.height - 60

    for line in lines:
        w = draw.textlength(line, font)
        x = (img.width - w) / 2
        draw.text((x, y), line, font=font, fill="white")
        y += line_h + 10

    footer_font = ImageFont.truetype(FONT_MN, 28)
    fw = draw.textlength(FOOTER_TEXT, footer_font)
    draw.text(((img.width - fw) / 2, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, "JPEG", quality=95)
    out.seek(0)
    return out

# =========================
# ШАБЛОН ЧП ВМ
# =========================
def make_card_chp(photo_bytes, title):
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
    img = ImageEnhance.Brightness(img).enhance(0.85)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    grad = Image.new("L", (1, img.height), 0)
    for y in range(img.height):
        a = int(200 * (y / img.height))
        grad.putpixel((0, y), a)
    grad = grad.resize(img.size)
    black = Image.new("RGBA", img.size, (0, 0, 0, 200))
    overlay = Image.composite(black, overlay, grad)
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_CHP, 70)
    text = title.upper()
    lines = wrap_text(draw, text, font, img.width * 0.9)

    y = img.height - 200
    for line in reversed(lines):
        w = draw.textlength(line, font)
        x = (img.width - w) / 2
        draw.text((x, y), line, font=font, fill="white")
        y -= 80

    out = BytesIO()
    img.save(out, "JPEG", quality=95)
    out.seek(0)
    return out

# =========================
# ШАБЛОН АМ
# =========================
def make_card_am(photo_bytes, title):
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)

    blur = img.crop((0, 0, img.width, 200)).filter(ImageFilter.GaussianBlur(15))
    img.paste(blur, (0, 0))

    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_AM, 60)
    lines = wrap_text(draw, title.upper(), font, img.width * 0.9)

    y = 40
    for line in lines:
        w = draw.textlength(line, font)
        x = (img.width - w) / 2
        draw.text((x, y), line, font=font, fill="white")
        y += 70

    out = BytesIO()
    img.save(out, "JPEG", quality=95)
    out.seek(0)
    return out

# =========================
# ШАБЛОН СТОРИС ФДР
# =========================
def make_card_fdr(photo_bytes, title, body):
    canvas = Image.new("RGB", (STORY_W, STORY_H), (0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    photo = Image.open(BytesIO(photo_bytes)).convert("RGB")
    photo = photo.resize((STORY_W, 410), Image.LANCZOS)
    canvas.paste(photo, (0, 0))

    purple = (122, 58, 240)
    header = Image.new("RGB", (STORY_W, 220), purple)
    canvas.paste(header, (0, 410))

    font_title = ImageFont.truetype(FONT_STORY, 50)
    title_lines = wrap_text(draw, title, font_title, STORY_W - 80)
    y = 450
    for line in title_lines:
        w = draw.textlength(line, font_title)
        x = (STORY_W - w) / 2
        draw.text((x, y), line, font=font_title, fill="white")
        y += 60

    font_text = ImageFont.truetype(FONT_STORY, 30)
    body_lines = wrap_text(draw, body, font_text, STORY_W - 80)
    y = 640
    for line in body_lines:
        draw.text((40, y), line, font=font_text, fill="white")
        y += 40

    out = BytesIO()
    canvas.save(out, "JPEG", quality=95)
    out.seek(0)
    return out

# =========================
# ДИСПЕТЧЕР ШАБЛОНОВ
# =========================
def make_card(photo_bytes, title, template, body="", mn_layout="top"):
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

def news_item_kb(key, link):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Оформить", callback_data=f"nfmt:{key}"),
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
# ОТПРАВКА НОВОСТИ (ВАША ФУНКЦИЯ)
# =========================
def send_full_news(chat_id, title, text, photo_url, link):
    try:
        if photo_url:
            try:
                r = SESSION.get(photo_url, timeout=20)
                photo = BytesIO(r.content)
                bot.send_photo(chat_id, photo)
            except:
                pass

        header = f"<b>{html.escape(title)}</b>\n\n"
        message = header + html.escape(text)
        if link:
            message += f"\n\nИсточник: {link}"

        parts = []
        while len(message) > 3500:
            parts.append(message[:3500])
            message = message[3500:]
        parts.append(message)

        for p in parts:
            bot.send_message(chat_id, p, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        bot.send_message(chat_id, f"Ошибка отправки: {e}")

# =========================
# ОБРАБОТЧИКИ КОМАНД
# =========================
@bot.message_handler(commands=["start", "help"])
def start(msg):
    if ADMIN_ID and msg.from_user.id != ADMIN_ID:
        bot.reply_to(msg, "⛔️ Нет доступа.")
        return
    user_state[msg.from_user.id] = {"step": "idle", "template": "MN", "mn_layout": "top"}
    bot.send_message(msg.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())

@bot.message_handler(commands=["post"])
def post_cmd(msg):
    if ADMIN_ID and msg.from_user.id != ADMIN_ID:
        return
    st = user_state.get(msg.from_user.id, {})
    st["step"] = "waiting_template"
    user_state[msg.from_user.id] = st
    bot.send_message(msg.chat.id, "Выбери шаблон оформления:", reply_markup=template_kb())

@bot.message_handler(commands=["news"])
def news_cmd(msg):
    if ADMIN_ID and msg.from_user.id != ADMIN_ID:
        return
    bot.send_message(msg.chat.id, "Собираю новости за 24 часа… 🧲")
    items = fetch_all_news()
    by_key = {}
    for it in items[:20]:
        title = it.get("title", "").strip()
        link = it.get("url", "").strip()
        if not title or not link:
            continue
        key = hashlib.sha256(f"{title}|{link}".encode()).hexdigest()[:16]
        by_key[key] = it
        bot.send_message(
            msg.chat.id,
            f"<b>{html.escape(title)}</b>\n\n{html.escape(it.get('source', ''))}",
            parse_mode="HTML",
            reply_markup=news_item_kb(key, link)
        )
    user_state[msg.from_user.id]["news_cache"] = {"by_key": by_key, "ts": time.time()}

# =========================
# CALLBACK-ОБРАБОТЧИКИ
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("tpl:"))
def tpl_pick(c):
    if ADMIN_ID and c.from_user.id != ADMIN_ID:
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
def mn_layout_pick(c):
    if ADMIN_ID and c.from_user.id != ADMIN_ID:
        return
    uid = c.from_user.id
    layout = c.data.split(":", 1)[1]
    st = user_state.get(uid, {})
    st.update({"template": "MN", "mn_layout": layout, "step": "waiting_photo"})
    user_state[uid] = st
    bot.answer_callback_query(c.id, "Ок ✅")
    bot.send_message(c.message.chat.id, "Пришли фото 📷")

@bot.callback_query_handler(func=lambda c: c.data.startswith(("nfmt:", "nskip:")))
def news_actions(c):
    if ADMIN_ID and c.from_user.id != ADMIN_ID:
        return
    uid = c.from_user.id
    cache = user_state.get(uid, {}).get("news_cache", {}).get("by_key", {})
    action, key = c.data.split(":", 1)
    if action == "nskip":
        bot.answer_callback_query(c.id, "Пропущено")
        try:
            bot.edit_message_text("🗑 Пропущено.", c.message.chat.id, c.message.message_id)
        except:
            pass
        return
    it = cache.get(key)
    if not it:
        bot.answer_callback_query(c.id, "Новость не найдена")
        return
    title = it.get("title", "")
    link = it.get("url", "")
    image = it.get("image", "")
    full_text = fetch_article_text(link) or it.get("summary", "Не удалось получить текст")
    send_full_news(c.message.chat.id, title, full_text, image, link)
    bot.answer_callback_query(c.id, "Готово ✅")

@bot.callback_query_handler(func=lambda c: c.data in ["publish", "edit_body", "edit_title", "cancel"])
def preview_actions(c):
    if ADMIN_ID and c.from_user.id != ADMIN_ID:
        return
    uid = c.from_user.id
    st = user_state.get(uid, {})
    if st.get("step") != "waiting_action":
        bot.answer_callback_query(c.id, "Нет активного превью")
        return
    if c.data == "publish":
        caption = build_caption_html(st.get("title", ""), st.get("body_raw", ""))
        bot.send_photo(CHANNEL, BytesIO(st["card_bytes"]), caption=caption, parse_mode="HTML")
        bot.answer_callback_query(c.id, "Опубликовано ✅")
        user_state[uid] = {"step": "idle", "template": st.get("template", "MN"), "mn_layout": st.get("mn_layout", "top")}
        bot.send_message(c.message.chat.id, "Готово ✅", reply_markup=main_menu_kb())
    elif c.data == "edit_body":
        st["step"] = "waiting_body_fdr" if st.get("template") == "FDR_STORY" else "waiting_body"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок")
        bot.send_message(c.message.chat.id, "Пришли новый текст:")
    elif c.data == "edit_title":
        st["step"] = "waiting_title_fdr" if st.get("template") == "FDR_STORY" else "waiting_title"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок")
        bot.send_message(c.message.chat.id, "Пришли новый заголовок:")
    elif c.data == "cancel":
        bot.answer_callback_query(c.id, "Отменено")
        user_state[uid] = {"step": "idle", "template": st.get("template", "MN"), "mn_layout": st.get("mn_layout", "top")}
        bot.send_message(c.message.chat.id, "Отменил ❌", reply_markup=main_menu_kb())

# =========================
# ОБРАБОТЧИКИ СООБЩЕНИЙ
# =========================
@bot.message_handler(content_types=["photo"])
def on_photo(msg):
    if ADMIN_ID and msg.from_user.id != ADMIN_ID:
        return
    uid = msg.from_user.id
    st = user_state.get(uid)
    if not st or st.get("step") != "waiting_photo":
        return
    st["photo_bytes"] = tg_file_bytes(msg.photo[-1].file_id)
    st["step"] = "waiting_title_fdr" if st.get("template") == "FDR_STORY" else "waiting_title"
    user_state[uid] = st
    bot.reply_to(msg, "Фото получено ✅ Теперь отправь ЗАГОЛОВОК.")

@bot.message_handler(content_types=["document"])
def on_doc(msg):
    if ADMIN_ID and msg.from_user.id != ADMIN_ID:
        return
    uid = msg.from_user.id
    st = user_state.get(uid)
    if not st or st.get("step") != "waiting_photo":
        return
    if not msg.document.mime_type or not msg.document.mime_type.startswith("image/"):
        bot.reply_to(msg, "Пришли картинку JPG/PNG.")
        return
    st["photo_bytes"] = tg_file_bytes(msg.document.file_id)
    st["step"] = "waiting_title_fdr" if st.get("template") == "FDR_STORY" else "waiting_title"
    user_state[uid] = st
    bot.reply_to(msg, "Картинка получена ✅ Теперь отправь ЗАГОЛОВОК.")

@bot.message_handler(func=lambda m: True)
def on_text(msg):
    if ADMIN_ID and msg.from_user.id != ADMIN_ID:
        return
    uid = msg.from_user.id
    text = (msg.text or "").strip()
    if text == BTN_POST:
        return post_cmd(msg)
    if text == BTN_NEWS:
        return news_cmd(msg)
    st = user_state.get(uid, {"step": "idle", "template": "MN", "mn_layout": "top"})
    step = st.get("step")
    if step == "waiting_template":
        bot.send_message(msg.chat.id, "Выбери шаблон кнопками:", reply_markup=template_kb())
    elif step == "waiting_mn_layout":
        bot.send_message(msg.chat.id, "Выбери расположение текста:", reply_markup=mn_layout_kb())
    elif step == "waiting_title_fdr":
        st["title"] = text
        st["step"] = "waiting_body_fdr"
        user_state[uid] = st
        bot.reply_to(msg, "Заголовок сохранен ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ для сторис.")
    elif step == "waiting_body_fdr":
        if not st.get("photo_bytes"):
            bot.reply_to(msg, "❌ Фото потерялось. Начни заново с /post")
            return
        st["body_raw"] = text
        card = make_card(st["photo_bytes"], st["title"], "FDR_STORY", text, st.get("mn_layout", "top"))
        st["card_bytes"] = card.getvalue()
        st["step"] = "waiting_action"
        user_state[uid] = st
        bot.send_photo(
            msg.chat.id,
            BytesIO(st["card_bytes"]),
            caption=build_caption_html(st["title"], text),
            parse_mode="HTML",
            reply_markup=preview_kb()
        )
        bot.reply_to(msg, "Сторис готова ✅")
    elif step == "waiting_title":
        if not st.get("photo_bytes"):
            bot.reply_to(msg, "❌ Фото потерялось. Начни заново с /post")
            return
        st["title"] = text
        card = make_card(st["photo_bytes"], text, st.get("template", "MN"), "", st.get("mn_layout", "top"))
        st["card_bytes"] = card.getvalue()
        st["step"] = "waiting_body"
        user_state[uid] = st
        bot.reply_to(msg, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
    elif step == "waiting_body":
        st["body_raw"] = text
        st["step"] = "waiting_action"
        user_state[uid] = st
        bot.send_photo(
            msg.chat.id,
            BytesIO(st["card_bytes"]),
            caption=build_caption_html(st["title"], text),
            parse_mode="HTML",
            reply_markup=preview_kb()
        )
        bot.reply_to(msg, "Превью готово ✅")
    elif step == "waiting_action":
        bot.reply_to(msg, "Нажми кнопку под превью ✅✏️❌")
    else:
        bot.send_message(msg.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())

# =========================
# ЗАПУСК
# =========================
if __name__ == "__main__":
    ensure_fonts()
    logger.info("Бот запущен!")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
