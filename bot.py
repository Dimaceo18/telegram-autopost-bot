# bot.py
# Flow:
# 1) photo
# 2) title -> generate card (4:5, darken, Caviar Dreams)
# 3) body text
# 4) preview + inline buttons: Publish / Edit / Cancel

import os
import requests
from io import BytesIO

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


# ---------- ENV ----------
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()
if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set (Render -> Environment -> BOT_TOKEN)")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN must not contain spaces")
if not CHANNEL or CHANNEL == "@":
    raise RuntimeError("CHANNEL_USERNAME is not set (Render -> Environment -> CHANNEL_USERNAME)")

FONT_PATH = "CaviarDreams.ttf"
FOOTER_TEXT = "MINSK NEWS"

bot = telebot.TeleBot(TOKEN)

# user_state[uid] = {
#   step: waiting_photo | waiting_title | waiting_body | waiting_action
#   photo_file_id / doc_file_id
#   card_bytes: bytes
#   body_text: str
#   preview_msg_id: int
# }
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

    # --- Crop to 4:5 (portrait), centered ---
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
    margin_x = int(img.width * 0.06)       # "широко" по краям
    margin_top = int(img.height * 0.06)
    margin_bottom = int(img.height * 0.10)
    safe_w = img.width - 2 * margin_x

    # --- Footer ---
    footer_size = max(26, int(img.height * 0.035))
    footer_font = ImageFont.truetype(FONT_PATH, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    footer_x = (img.width - footer_w) // 2

    # --- Title zone (top 20–25%) ---
    title_zone_pct = 0.23
    title_max_h = int(img.height * title_zone_pct)

    text = (title_text or "").strip().upper()
    if not text:
        text = " "

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
            bb = draw.textbbox((0, 0), ln, font=title_font)
            lw = bb[2] - bb[0]
            lh = bb[3] - bb[1]
            max_line_w = max(max_line_w, lw)
            line_heights.append(lh)
            total_h += lh

        total_h += line_spacing * (len(lines) - 1)

        if (max_line_w <= safe_w) and (total_h <= title_max_h):
            break
        if font_size <= min_font:
            break
        font_size -= 3

    # --- Draw title: always top, left-aligned for "edge-to-edge" feel ---
    y = margin_top
    spacing = int(font_size * line_spacing_ratio)
    for i, ln in enumerate(lines):
        draw.text((margin_x, y), ln, font=title_font, fill="white")
        y += line_heights[i] + spacing

    # --- Draw footer ---
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out


def action_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("✏️ Изменить текст", callback_data="edit"),
    )
    kb.row(
        InlineKeyboardButton("❌ Отмена", callback_data="cancel")
    )
    return kb


@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    user_state[message.from_user.id] = {"step": "waiting_photo"}
    bot.reply_to(
        message,
        "Ок ✅\n"
        "1) Пришли фото\n"
        "2) Пришли заголовок\n"
        "3) Пришли основной текст\n"
        "Потом покажу превью и кнопки: Опубликовать / Изменить / Отмена."
    )


@bot.message_handler(content_types=["photo"])
def on_photo(message):
    uid = message.from_user.id
    file_id = message.photo[-1].file_id
    user_state[uid] = {"step": "waiting_title", "photo_file_id": file_id}
    bot.reply_to(message, "Фото получено ✅ Теперь отправь ЗАГОЛОВОК.")


@bot.message_handler(content_types=["document"])
def on_document(message):
    uid = message.from_user.id
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        bot.reply_to(message, "Пришли картинку (JPG/PNG) как файл, пожалуйста.")
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
        try:
            if "photo_file_id" in st:
                photo_bytes = tg_file_bytes(st["photo_file_id"])
            else:
                photo_bytes = tg_file_bytes(st["doc_file_id"])

            card = make_card(photo_bytes, text)
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_body"
            bot.reply_to(message, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
        except Exception as e:
            st["step"] = "waiting_photo"
            bot.reply_to(message, f"Ошибка при создании карточки: {e}")

    elif step == "waiting_body":
        # Save body text and show preview with buttons
        st["body_text"] = text
        st["step"] = "waiting_action"

        card_bytes = st.get("card_bytes")
        if not card_bytes:
            st["step"] = "waiting_photo"
            bot.reply_to(message, "Карточка потерялась. Начни заново: пришли фото.")
            return

        try:
            preview = bot.send_photo(
                chat_id=message.chat.id,
                photo=BytesIO(card_bytes),
                caption=text,
                reply_markup=action_kb()
            )
            st["preview_msg_id"] = preview.message_id
            bot.reply_to(message, "Проверь превью и нажми кнопку ✅✏️❌")
        except Exception as e:
            st["step"] = "waiting_body"
            bot.reply_to(message, f"Не смог отправить превью: {e}")

    elif step == "waiting_action":
        bot.reply_to(message, "Сейчас ждём кнопку под превью: ✅ Опубликовать / ✏️ Изменить / ❌ Отмена.")

    else:
        user_state[uid] = {"step": "waiting_photo"}
        bot.reply_to(message, "Пришли фото 📷")


@bot.callback_query_handler(func=lambda call: call.data in ["publish", "edit", "cancel"])
def on_action(call):
    uid = call.from_user.id
    st = user_state.get(uid)

    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(call.id, "Нет активного превью. Начни с фото.")
        return

    if call.data == "publish":
        try:
            card_bytes = st.get("card_bytes")
            body = st.get("body_text", "")
            bot.send_photo(CHANNEL, BytesIO(card_bytes), caption=body)
            bot.answer_callback_query(call.id, "Опубликовано ✅")

            # optionally remove buttons on preview
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception:
                pass

            bot.send_message(call.message.chat.id, "Готово ✅ Можешь присылать следующую новость (фото).")
            user_state[uid] = {"step": "waiting_photo"}

        except Exception as e:
            bot.answer_callback_query(call.id, "Ошибка публикации")
            bot.send_message(call.message.chat.id, f"Не смог опубликовать: {e}")

    elif call.data == "edit":
        st["step"] = "waiting_body"
        bot.answer_callback_query(call.id, "Ок, редактируем")
        bot.send_message(call.message.chat.id, "Пришли новый ОСНОВНОЙ ТЕКСТ поста (заголовок на картинке останется прежним).")

    elif call.data == "cancel":
        bot.answer_callback_query(call.id, "Отменено")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        user_state[uid] = {"step": "waiting_photo"}
        bot.send_message(call.message.chat.id, "Отменил ❌ Можешь прислать новое фото для следующей новости.")


if __name__ == "__main__":
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
