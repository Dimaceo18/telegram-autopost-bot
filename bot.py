import os
import re
import html
import requests
from io import BytesIO

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


# ---------- ENV ----------
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")  # например Newsautoposting_bot

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

SUGGEST_URL = (os.getenv("SUGGEST_URL") or "").strip()
if not SUGGEST_URL and BOT_USERNAME:
    SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"


bot = telebot.TeleBot(TOKEN)

# user_state[uid] = {
#   step: waiting_photo | waiting_title | waiting_body | waiting_source | waiting_action
#   photo_bytes: bytes
#   title: str
#   card_bytes: bytes
#   body_raw: str
#   source_url: str
# }
user_state = {}


# ---------- helpers ----------
URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)


RU_STOP = {
    "и","в","во","на","но","а","что","это","как","к","по","из","за","для","с","со","у","от","до",
    "при","без","над","под","же","ли","то","не","ни","да","нет","уже","еще","ещё","там","тут",
    "снова","будет","начнут","начал","началась","начался","начали","может","могут","нужно","надо"
}

CATEGORY_RULES = [
    ("🚨", ["дтп", "авар", "пожар", "взрыв", "происшеств", "чп", "полици", "милици", "убий", "ранен", "пострад"]),
    ("✈️", ["белавиа", "рейс", "аэропорт", "самолет", "самолёт", "полет", "полёт", "оаэ", "дуба", "ави"]),
    ("🚇", ["метро", "станци", "маршрут", "автобус", "троллейбус", "трамвай", "дорог", "пробк"]),
    ("💳", ["банк", "технобанк", "карта", "налог", "tax free", "global blue", "выплат", "платеж", "платёж"]),
    ("🏷️", ["скидк", "распрод", "акци", "дешев", "бесплат", "купон", "sale", "%"]),
    ("🎫", ["концерт", "афиша", "выставк", "фестиваль", "событи", "матч", "театр", "кино"]),
    ("🌦️", ["погод", "шторм", "ветер", "снег", "дожд", "мороз", "жара"]),
    ("🏥", ["больниц", "врач", "здоров", "вакцин", "грипп", "ковид", "covid"]),
    ("🏛️", ["власт", "закон", "указ", "постанов", "министер", "исполком"]),
]

def pick_category_emoji(title: str, body: str) -> str:
    text = (title + " " + body).lower()
    for emoji, keys in CATEGORY_RULES:
        for k in keys:
            if k in text:
                return emoji
    return "📰"


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

    lines, line = [], ""
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
    """
    4:5, заголовок всегда сверху, <= ~23% высоты, широкий по краям, затемнение, Caviar Dreams, footer.
    """
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")

    # Crop to 4:5
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

    # Darken
    img = ImageEnhance.Brightness(img).enhance(0.55)
    draw = ImageDraw.Draw(img)

    margin_x = int(img.width * 0.06)
    margin_top = int(img.height * 0.06)
    margin_bottom = int(img.height * 0.10)
    safe_w = img.width - 2 * margin_x

    # Footer
    footer_size = max(26, int(img.height * 0.035))
    footer_font = ImageFont.truetype(FONT_PATH, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    footer_x = (img.width - footer_w) // 2

    # Title zone (20–25%)
    title_zone_pct = 0.23
    title_max_h = int(img.height * title_zone_pct)

    text = (title_text or "").strip().upper() or " "

    font_size = int(img.height * 0.11)
    min_font = int(img.height * 0.045)
    line_spacing_ratio = 0.22

    while True:
        title_font = ImageFont.truetype(FONT_PATH, font_size)
        lines = wrap_text_to_width(draw, text, title_font, safe_w)
        spacing = int(font_size * line_spacing_ratio)

        total_h = 0
        max_line_w = 0
        heights = []
        for ln in lines:
            bb = draw.textbbox((0, 0), ln, font=title_font)
            lw = bb[2] - bb[0]
            lh = bb[3] - bb[1]
            max_line_w = max(max_line_w, lw)
            heights.append(lh)
            total_h += lh
        total_h += spacing * (len(lines) - 1)

        if max_line_w <= safe_w and total_h <= title_max_h:
            break
        if font_size <= min_font:
            break
        font_size -= 3

    # Draw title (top, left-aligned for "wide" look)
    y = margin_top
    spacing = int(font_size * line_spacing_ratio)
    for i, ln in enumerate(lines):
        draw.text((margin_x, y), ln, font=title_font, fill="white")
        y += heights[i] + spacing

    # Draw footer
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out


def extract_source_url(text: str) -> str:
    m = URL_RE.search(text or "")
    return m.group(1) if m else ""


def pick_keywords(title: str, body: str, max_words: int = 6):
    """
    Простая эвристика:
    - числа/проценты/валюта
    - “длинные” слова (>=7) не стоп-слова
    """
    txt = (title + " " + body).lower()

    # числа, проценты, BYN/USD/EUR/₽ etc.
    nums = re.findall(r"\b\d+[.,]?\d*\b|[%₽$€]|bYn|byn|usd|eur|rub", txt, flags=re.IGNORECASE)

    words = re.findall(r"[а-яёa-z]{4,}", txt, flags=re.IGNORECASE)
    candidates = []
    for w in words:
        wl = w.strip().lower()
        if wl in RU_STOP:
            continue
        if len(wl) >= 7:
            candidates.append(wl)

    # уникальные, сначала числа/символы, потом слова
    seen = set()
    out = []
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
    """
    Безопасно: сначала экранируем HTML, потом подсвечиваем по экранированной строке.
    """
    safe = html.escape(text or "")
    for kw in keywords:
        kw_safe = html.escape(kw)
        if not kw_safe.strip():
            continue
        # Подсветка целых слов (если это слово), или просто вхождение (если символ/валюта/%)
        if re.match(r"^[а-яёa-z0-9]+$", kw, flags=re.IGNORECASE):
            pattern = re.compile(rf"(?<![а-яёa-z0-9])({re.escape(kw_safe)})(?![а-яёa-z0-9])", re.IGNORECASE)
        else:
            pattern = re.compile(rf"({re.escape(kw_safe)})", re.IGNORECASE)
        safe = pattern.sub(r"<b>\1</b>", safe)
    return safe


def build_caption_html(title: str, body: str) -> str:
    emoji = pick_category_emoji(title, body)
    keywords = pick_keywords(title, body)

    title_safe = html.escape((title or "").strip())
    body_high = highlight_keywords_html((body or "").strip(), keywords)

    # Заголовок жирный, основной текст обычный (но с подсветкой ключевых слов)
    return f"<b>{emoji} {title_safe}</b>\n\n{body_high}".strip()


def action_kb(source_url: str):
    kb = InlineKeyboardMarkup()

    kb.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("✏️ Изменить текст", callback_data="edit_body"),
    )
    kb.row(
        InlineKeyboardButton("✏️ Изменить заголовок", callback_data="edit_title"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel"),
    )

    # Источник (если есть ссылка)
    if source_url:
        kb.row(InlineKeyboardButton("Источник", url=source_url))

    # Предложить новость (если есть)
    if SUGGEST_URL:
        kb.row(InlineKeyboardButton("Предложить новость", url=SUGGEST_URL))

    return kb


# ---------- handlers ----------
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    user_state[message.from_user.id] = {"step": "waiting_photo"}
    bot.reply_to(
        message,
        "Ок ✅\n"
        "1) Пришли фото\n"
        "2) Пришли заголовок\n"
        "3) Пришли основной текст\n"
        "4) (опционально) Пришли ссылку на источник\n"
        "Потом покажу превью и кнопки."
    )


@bot.message_handler(content_types=["photo"])
def on_photo(message):
    uid = message.from_user.id
    file_id = message.photo[-1].file_id
    photo_bytes = tg_file_bytes(file_id)
    user_state[uid] = {"step": "waiting_title", "photo_bytes": photo_bytes}
    bot.reply_to(message, "Фото получено ✅ Теперь отправь ЗАГОЛОВОК.")


@bot.message_handler(content_types=["document"])
def on_document(message):
    uid = message.from_user.id
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        bot.reply_to(message, "Пришли картинку (JPG/PNG).")
        return

    photo_bytes = tg_file_bytes(doc.file_id)
    user_state[uid] = {"step": "waiting_title", "photo_bytes": photo_bytes}
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
        st["title"] = text
        try:
            card = make_card(st["photo_bytes"], st["title"])
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_body"
            bot.reply_to(message, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
        except Exception as e:
            st["step"] = "waiting_photo"
            bot.reply_to(message, f"Ошибка при создании карточки: {e}")

    elif step == "waiting_body":
        st["body_raw"] = text
        # Если ссылка уже есть в тексте, источник можно не спрашивать
        st["source_url"] = extract_source_url(text)
        if st["source_url"]:
            st["step"] = "waiting_action"
            caption = build_caption_html(st["title"], st["body_raw"])
            preview = bot.send_photo(
                chat_id=message.chat.id,
                photo=BytesIO(st["card_bytes"]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=action_kb(st["source_url"]),
            )
            st["preview_msg_id"] = preview.message_id
            bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")
        else:
            st["step"] = "waiting_source"
            bot.reply_to(message, "Если есть источник, пришли ссылку (или напиши: - чтобы пропустить).")

    elif step == "waiting_source":
        if text == "-" or text.lower() in {"нет", "не", "пропустить"}:
            st["source_url"] = ""
        else:
            st["source_url"] = extract_source_url(text)

        st["step"] = "waiting_action"
        caption = build_caption_html(st["title"], st["body_raw"])
        preview = bot.send_photo(
            chat_id=message.chat.id,
            photo=BytesIO(st["card_bytes"]),
            caption=caption,
            parse_mode="HTML",
            reply_markup=action_kb(st["source_url"]),
        )
        st["preview_msg_id"] = preview.message_id
        bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")

    elif step == "waiting_action":
        bot.reply_to(message, "Сейчас ждём кнопку под превью: ✅✏️❌")

    else:
        user_state[uid] = {"step": "waiting_photo"}
        bot.reply_to(message, "Пришли фото 📷")


@bot.callback_query_handler(func=lambda call: call.data in ["publish", "edit_body", "edit_title", "cancel"])
def on_action(call):
    uid = call.from_user.id
    st = user_state.get(uid)

    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(call.id, "Нет активного превью. Начни с фото.")
        return

    if call.data == "publish":
        try:
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(
                CHANNEL,
                BytesIO(st["card_bytes"]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=action_kb(st.get("source_url", ""))  # кнопки пойдут и в канал
            )
            bot.answer_callback_query(call.id, "Опубликовано ✅")
            try:
                bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(call.message.chat.id, "Готово ✅ Можешь присылать следующую новость (фото).")
            user_state[uid] = {"step": "waiting_photo"}
        except Exception as e:
            bot.answer_callback_query(call.id, "Ошибка публикации")
            bot.send_message(call.message.chat.id, f"Не смог опубликовать: {e}")

    elif call.data == "edit_body":
        st["step"] = "waiting_body"
        bot.answer_callback_query(call.id, "Ок")
        bot.send_message(call.message.chat.id, "Пришли новый ОСНОВНОЙ ТЕКСТ (заголовок на картинке не меняем).")

    elif call.data == "edit_title":
        st["step"] = "waiting_title"
        bot.answer_callback_query(call.id, "Ок")
        bot.send_message(call.message.chat.id, "Пришли новый ЗАГОЛОВОК (перерисую карточку).")

    elif call.data == "cancel":
        bot.answer_callback_query(call.id, "Отменено")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        user_state[uid] = {"step": "waiting_photo"}
        bot.send_message(call.message.chat.id, "Отменил ❌ Пришли новое фото для следующей новости.")


if __name__ == "__main__":
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
