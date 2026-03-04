# bot.py
# Flow:
# 1) user sends photo
# 2) user sends TITLE (headline) -> bot generates card image
# 3) user sends BODY text -> bot posts card + caption to channel

import os
import requests
from io import BytesIO

import telebot
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()
if not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN must not contain spaces")
if not CHANNEL or CHANNEL == "@":
    raise RuntimeError("CHANNEL_USERNAME is not set")

FONT_PATH = "CaviarDreams.ttf"
FOOTER_TEXT = "MINSK NEWS"

bot = telebot.TeleBot(TOKEN)

# user_id -> state dict
# state:
#   waiting_photo -> expecting photo
#   waiting_title -> photo saved, expecting title
#   waiting_body  -> card ready, expecting body
user_state = {}


def tg_file_bytes(file_id: str) -> bytes:
    file_info = bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
    r = requests.get(file_url, timeout=30)
    r.raise_for_status()
    return r.content


def wrap_text_to_width(draw, text, font, max_width):
    words = text.split()
    if not words:
        return [""]

    lines = []
    line = ""
    for w in words:
        test = (line + " " + w).strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def make_card(photo_bytes: bytes, title_text: str) -> BytesIO:
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")

    # --- Crop to 4:5 (portrait) ---
    w, h = img.size
    target_ratio = 4 / 5
    cur_ratio = w / h

    if cur_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))

    # --- Darken ---
    img = ImageEnhance.Brightness(img).enhance(0.55)

    draw = ImageDraw.Draw(img)

    # --- Safe margins ---
    margin_x = int(img.width * 0.06)
    margin_top = int(img.height * 0.06)
    margin_bottom = int(img.height * 0.10)
    safe_w = img.width - 2 * margin_x

    # --- Footer ---
    footer_size = max(26, int(img.height * 0.035))
    footer_font = ImageFont.truetype(FONT_PATH, footer_size)
    footer_bbox = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = footer_bbox[2] - footer_bbox[0]
    footer_h = footer_bbox[3] - footer_bbox[1]
    footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    footer_x = (img.width - footer_w) // 2

    # --- Title zone (top 20–25%) ---
    title_zone_pct = 0.23
    title_max_h = int(img.height * title_zone_pct)

    text = (title_text or "").strip().upper()
    if not text:
        text = " "

    # Auto-fit font so title stays in the top zone
    font_size = int(img.height * 0.11)
    min_font = int(img.height * 0.045)
    line_spacing_ratio = 0.22

    while True:
        title_font = ImageFont.truetype(FONT_PATH, font_size)
        lines = wrap_text_to_width(draw, text, title_font, safe_w)
        line_spacing = int(font_size * line_spacing_ratio)

        total_h = 0
        max_line_w = 0
        line_heights = []

        for ln in lines:
            bbox = draw.textbbox((0, 0), ln, font=title_font)
            lw = bbox[2] - bbox[0]
            lh = bbox[3] - bbox[1]
            max_line_w = max(max_line_w, lw)
            line_heights.append(lh)
            total_h += lh

        total_h += line_spacing * (len(lines) - 1)

        if (max_line_w <= safe_w) and (total_h <= title_max_h):
            break
        if font_size <= min_font:
            break
        font_size -= 3

    # Draw title (left-aligned for "edge-to-edge" feel)
    y = margin_top
    for i, ln in enumerate(lines):
        draw.text((margin_x, y), ln, font=title_font, fill="white")
        y += line_heights[i] + int(font_size * line_spacing_ratio)

    # Draw footer
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    user_state[message.from_user.id] = {"step": "waiting_photo"}
    bot.reply_to(
        message,
        "Ок ✅\n"
        "1) Пришли фото\n"
        "2) Пришли заголовок\n"
        "3) Пришли основной текст\n"
        "Я опубликую в канал."
    )


@bot.message_handler(content_types=["photo"])
def on_photo(message):
    uid = message.from_user.id
    file_id = message.photo[-1].file_id
    user_state[uid] = {"step": "waiting_title", "photo_file_id": file_id}
    bot.reply_to(message, "Фото получено ✅ Теперь отправь ЗАГОЛОВОК.")


@bot.message_handler(content_types=["document"])
def on_document(message):
    # allow image sent as file
    uid = message.from_user.id
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        bot.reply_to(message, "Пришли картинку (JPG/PNG).")
        return

    user_state[uid] = {"step": "waiting_title", "doc_file_id": doc.file_id}
    bot.reply_to(message, "Картинка получена ✅ Теперь отправь ЗАГОЛОВОК.")


@bot.message_handler(content_types=["text"])
def on_text(message):
    uid = message.from_user.id
    text = (message.text or "").strip()

    st = user_state.get(uid)
    if not st:
        user_state[uid] = {"step": "waiting_photo"}
        bot.reply_to(message, "Сначала пришли фото 📷")
        return

    step = st.get("step")

    if step == "waiting_title":
        # Build card from saved image + headline
        try:
            if "photo_file_id" in st:
                photo_bytes = tg_file_bytes(st["photo_file_id"])
            else:
                photo_bytes = tg_file_bytes(st["doc_file_id"])

            card = make_card(photo_bytes, text)
            st["step"] = "waiting_body"
            st["card_bytes"] = card.getvalue()

            bot.reply_to(message, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
        except Exception as e:
            bot.reply_to(message, f"Ошибка при создании карточки: {e}")
            st["step"] = "waiting_photo"

    elif step == "waiting_body":
        # Publish to channel: image + caption
        try:
            card_bytes = st.get("card_bytes")
            if not card_bytes:
                bot.reply_to(message, "Не нашёл карточку. Начни заново: пришли фото.")
                st["step"] = "waiting_photo"
                return

            caption = text
            bot.send_photo(CHANNEL, BytesIO(card_bytes), caption=caption)

            bot.reply_to(message, "Опубликовано ✅ Можешь присылать следующую новость (фото).")
            user_state[uid] = {"step": "waiting_photo"}
        except Exception as e:
            bot.reply_to(message, f"Ошибка публикации: {e}")

    else:
        # waiting_photo or unknown
        user_state[uid] = {"step": "waiting_photo"}
        bot.reply_to(message, "Пришли фото 📷")


if __name__ == "__main__":
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
