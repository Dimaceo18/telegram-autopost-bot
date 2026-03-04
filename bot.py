# bot.py
# Telegram autopost bot: photo + text -> generates 5:4 news card (darken, Caviar Dreams, margins, centered text) -> posts to channel

import os
import requests
from io import BytesIO

import telebot
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


# ---------- ENV ----------
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set (Render -> Environment -> BOT_TOKEN)")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN must not contain spaces")
if not CHANNEL:
    raise RuntimeError("CHANNEL_USERNAME is not set (Render -> Environment -> CHANNEL_USERNAME)")
if not CHANNEL.startswith("@"):
    # allow user to pass username without @
    CHANNEL = "@" + CHANNEL

# Font file must be in the same repo folder as bot.py
FONT_PATH = "CaviarDreams.ttf"

# ---------- BOT ----------
bot = telebot.TeleBot(TOKEN)

# user_id -> either ("file_id", file_id) or ("bytes", image_bytes)
pending_image = {}


def tg_file_bytes(file_id: str) -> bytes:
    """Download a Telegram file (photo/document) into bytes."""
    file_info = bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
    r = requests.get(file_url, timeout=30)
    r.raise_for_status()
    return r.content


def wrap_text_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int):
    """Greedy wrap by words so each line fits max_width."""
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
    """Generate 5:4 card with darkening, centered title, safe margins, and footer 'MINSK NEWS'."""
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")

    # --- Crop to 5:4, centered ---
    w, h = img.size
    target_ratio = 5 / 4
    cur_ratio = w / h

    if cur_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))

    # --- Darken background for readability ---
    img = ImageEnhance.Brightness(img).enhance(0.55)

    draw = ImageDraw.Draw(img)

    # --- Safe margins (padding) ---
    margin_x = int(img.width * 0.08)     # ~8% side padding
    margin_top = int(img.height * 0.08)  # ~8% top padding
    margin_bottom = int(img.height * 0.10)  # ~10% bottom safe zone

    safe_w = img.width - 2 * margin_x

    # --- Footer ---
    footer_text = "MINSK NEWS"
    footer_size = max(26, int(img.height * 0.035))
    footer_font = ImageFont.truetype(FONT_PATH, footer_size)

    footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
    footer_w = footer_bbox[2] - footer_bbox[0]
    footer_h = footer_bbox[3] - footer_bbox[1]

    footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    footer_x = (img.width - footer_w) // 2

    # --- Title: auto-wrap + auto-shrink so it never clips ---
    text = (title_text or "").strip().upper()
    if not text:
        text = " "

    # Start big, shrink until fits
    font_size = int(img.height * 0.10)
    min_font = int(img.height * 0.045)

    while True:
        title_font = ImageFont.truetype(FONT_PATH, font_size)
        lines = wrap_text_to_width(draw, text, title_font, safe_w)

        line_spacing = int(font_size * 0.25)

        total_h = 0
        max_line_w = 0
        for ln in lines:
            bbox = draw.textbbox((0, 0), ln, font=title_font)
            lw = bbox[2] - bbox[0]
            lh = bbox[3] - bbox[1]
            max_line_w = max(max_line_w, lw)
            total_h += lh
        total_h += line_spacing * (len(lines) - 1)

        # Available height above footer (leave a little breathing room)
        available_h = (footer_y - margin_top) - int(img.height * 0.04)

        fits = (max_line_w <= safe_w) and (total_h <= available_h)

        if fits or font_size <= min_font:
            break
        font_size -= 4

    # --- Draw title centered line-by-line ---
    y = margin_top
    for ln in lines:
        bbox = draw.textbbox((0, 0), ln, font=title_font)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        x = margin_x + (safe_w - lw) // 2
        draw.text((x, y), ln, font=title_font, fill="white")
        y += lh + line_spacing

    # --- Draw footer centered ---
    draw.text((footer_x, footer_y), footer_text, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out


@bot.message_handler(commands=["start", "help"])
def on_start(message):
    bot.reply_to(
        message,
        "Отправь фото (или картинку как файл), затем текст новости.\n"
        "Я сделаю карточку 5:4 (затемнение + Caviar Dreams) и опубликую в канал."
    )


@bot.message_handler(content_types=["photo"])
def on_photo(message):
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id
    pending_image[user_id] = ("file_id", file_id)
    bot.reply_to(message, "Фото получено ✅ Теперь отправь текст новости.")


@bot.message_handler(content_types=["document"])
def on_document(message):
    # If user sent image as a file (document), accept only images
    user_id = message.from_user.id
    doc = message.document

    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        bot.reply_to(message, "Это не картинка. Пришли JPG/PNG, пожалуйста.")
        return

    try:
        img_bytes = tg_file_bytes(doc.file_id)
    except Exception as e:
        bot.reply_to(message, f"Не смог скачать файл: {e}")
        return

    pending_image[user_id] = ("bytes", img_bytes)
    bot.reply_to(message, "Картинка-файл получена ✅ Теперь отправь текст новости.")


@bot.message_handler(content_types=["text"])
def on_text(message):
    user_id = message.from_user.id

    if user_id not in pending_image:
        bot.reply_to(message, "Сначала отправь фото 📷")
        return

    kind, payload = pending_image.pop(user_id)

    try:
        if kind == "bytes":
            photo_bytes = payload
        else:
            photo_bytes = tg_file_bytes(payload)

        card = make_card(photo_bytes, message.text)

        # Publish to channel
        bot.send_photo(CHANNEL, card)

        bot.reply_to(message, "Готово ✅ Опубликовано в канал.")
    except Exception as e:
        bot.reply_to(message, f"Ошибка при создании/публикации: {e}")


if __name__ == "__main__":
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
