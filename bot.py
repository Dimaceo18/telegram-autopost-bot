# bot.py
# Photo -> Title -> Body -> (optional Source) -> Preview with buttons -> Publish to channel
# Card: 4:5, 720x900, darken, Caviar Dreams, title top zone <= 20-25%, smart line breaking

import os
import re
import html
import requests
from io import BytesIO

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter


# ---------- ENV ----------
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")  # e.g. Newsautoposting_bot
SUGGEST_URL = (os.getenv("SUGGEST_URL") or "").strip()

if CHANNEL and not CHANNEL.startswith("@"):
    CHANNEL = "@" + CHANNEL

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set (Render -> Environment -> BOT_TOKEN)")
if " " in TOKEN:
    raise ValueError("BOT_TOKEN must not contain spaces")
if not CHANNEL or CHANNEL == "@":
    raise RuntimeError("CHANNEL_USERNAME is not set (Render -> Environment -> CHANNEL_USERNAME)")

if not SUGGEST_URL and BOT_USERNAME:
    SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"

FONT_PATH = "CaviarDreams.ttf"  # must be in repo next to bot.py
FOOTER_TEXT = "MINSK NEWS"

# Card size (4:5). 1080x1350 / 1.5 = 720x900
TARGET_W, TARGET_H = 720, 900

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

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)


# ---------- CATEGORY / KEYWORDS (optional, can tune) ----------
RU_STOP = {
    "и","в","во","на","но","а","что","это","как","к","по","из","за","для","с","со","у","от","до",
    "при","без","над","под","же","ли","то","не","ни","да","нет","уже","еще","ещё","там","тут",
    "снова","будет","начнут","начал","началась","начался","начали","может","могут","нужно","надо"
}

CATEGORY_RULES = [
    ("🚨", ["дтп", "авар", "пожар", "взрыв", "происшеств", "чп", "полици", "милици", "ранен", "пострад"]),
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


def extract_source_url(text: str) -> str:
    m = URL_RE.search(text or "")
    return m.group(1) if m else ""


def pick_keywords(title: str, body: str, max_words: int = 6):
    txt = (title + " " + body).lower()
    nums = re.findall(r"\b\d+[.,]?\d*\b|[%₽$€]|byn|usd|eur|rub", txt, flags=re.IGNORECASE)
    words = re.findall(r"[а-яёa-z]{4,}", txt, flags=re.IGNORECASE)

    candidates = []
    for w in words:
        wl = w.strip().lower()
        if wl in RU_STOP:
            continue
        if len(wl) >= 7:
            candidates.append(wl)

    seen, out = set(), []
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
    safe = html.escape(text or "")
    for kw in keywords:
        kw_safe = html.escape(kw)
        if not kw_safe.strip():
            continue
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
    return f"<b>{emoji} {title_safe}</b>\n\n{body_high}".strip()


# ---------- Telegram file download ----------
def tg_file_bytes(file_id: str) -> bytes:
    file_info = bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
    r = requests.get(file_url, timeout=30)
    r.raise_for_status()
    return r.content


def warn_if_too_small(chat_id, photo_bytes: bytes):
    try:
        im = Image.open(BytesIO(photo_bytes))
        if im.width < 900 or im.height < 1100:
            bot.send_message(
                chat_id,
                "⚠️ Фото маленького разрешения. Я улучшу качество, но лучше присылать фото побольше (от 1080×1350 и выше)."
            )
    except Exception:
        pass


# ---------- Smart headline line breaking ----------
def text_width(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.FreeTypeFont) -> int:
    bb = draw.textbbox((0, 0), s, font=font)
    return bb[2] - bb[0]


def balanced_wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                  max_width: int, max_lines: int = 5):
    """
    Разбивка на строки с выравниванием "как у медиа":
    минимизируем "рваность" (raggedness) по ширине и ограничиваем кол-во строк.
    DP по словам.
    """
    words = [w for w in text.split() if w.strip()]
    if not words:
        return [""]

    n = len(words)
    # precompute widths for any i..j line
    wcache = [[0] * n for _ in range(n)]
    for i in range(n):
        line = ""
        for j in range(i, n):
            line = (line + " " + words[j]).strip()
            wcache[i][j] = text_width(draw, line, font)

    INF = 10**18
    dp = [[INF] * (max_lines + 1) for _ in range(n + 1)]
    nxt = [[None] * (max_lines + 1) for _ in range(n + 1)]
    dp[n][0] = 0

    for i in range(n - 1, -1, -1):
        for k in range(1, max_lines + 1):
            for j in range(i, n):
                w = wcache[i][j]
                if w > max_width:
                    break
                # cost: square of remaining space (raggedness)
                rem = (max_width - w)
                cost = rem * rem
                if dp[j + 1][k - 1] == INF:
                    continue
                total = cost + dp[j + 1][k - 1]
                if total < dp[i][k]:
                    dp[i][k] = total
                    nxt[i][k] = j + 1

    # choose best k (1..max_lines)
    best_k = None
    best = INF
    for k in range(1, max_lines + 1):
        if dp[0][k] < best:
            best = dp[0][k]
            best_k = k

    if best_k is None:
        # fallback: greedy
        lines = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            if text_width(draw, test, font) <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines[:max_lines]

    # reconstruct
    lines = []
    i, k = 0, best_k
    while i < n and k > 0:
        j = nxt[i][k]
        if j is None:
            break
        lines.append(" ".join(words[i:j]))
        i = j
        k -= 1

    if i < n:
        # append remaining words to last line if any
        if lines:
            lines[-1] = (lines[-1] + " " + " ".join(words[i:])).strip()
        else:
            lines = [" ".join(words[i:])]

    return lines


# ---------- Card generator ----------
def make_card(photo_bytes: bytes, title_text: str) -> BytesIO:
    """
    Card:
    - 4:5 crop centered
    - resize to 720x900
    - darken
    - title in top zone <= 23% height with auto font sizing
    - smart line breaking
    - footer "MINSK NEWS"
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

    # Resize to target + sharpen
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=170, threshold=3))

    # Darken
    img = ImageEnhance.Brightness(img).enhance(0.55)

    draw = ImageDraw.Draw(img)

    # Safe margins (wide look)
    margin_x = int(img.width * 0.06)
    margin_top = int(img.height * 0.06)
    margin_bottom = int(img.height * 0.10)
    safe_w = img.width - 2 * margin_x

    # Footer
    footer_size = max(24, int(img.height * 0.034))
    footer_font = ImageFont.truetype(FONT_PATH, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    footer_x = (img.width - footer_w) // 2

    # Title zone max height (20–25% of image)
    title_zone_pct = 0.23
    title_max_h = int(img.height * title_zone_pct)

    text = (title_text or "").strip().upper()
    if not text:
        text = " "

    # Auto font sizing to fit zone
    font_size = int(img.height * 0.11)   # start large
    min_font = int(img.height * 0.045)
    line_spacing_ratio = 0.22

    best_lines = None
    best_font = None
    best_spacing = None
    best_heights = None

    while True:
        font = ImageFont.truetype(FONT_PATH, font_size)
        lines = balanced_wrap(draw, text, font, safe_w, max_lines=5)
        spacing = int(font_size * line_spacing_ratio)

        heights = []
        total_h = 0
        max_line_w = 0

        for ln in lines:
            bb = draw.textbbox((0, 0), ln, font=font)
            lw = bb[2] - bb[0]
            lh = bb[3] - bb[1]
            heights.append(lh)
            total_h += lh
            max_line_w = max(max_line_w, lw)

        total_h += spacing * (len(lines) - 1)

        if max_line_w <= safe_w and total_h <= title_max_h:
            best_lines = lines
            best_font = font
            best_spacing = spacing
            best_heights = heights
            break

        font_size -= 3
        if font_size <= min_font:
            # keep last computed even if not perfect, but prevents giant text
            best_lines = lines
            best_font = font
            best_spacing = spacing
            best_heights = heights
            break

    # Draw title always at top
    y = margin_top
    for i, ln in enumerate(best_lines):
        draw.text((margin_x, y), ln, font=best_font, fill="white")
        y += best_heights[i] + best_spacing

    # Draw footer
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


# ---------- Keyboards ----------
def preview_kb(source_url: str):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Опубликовать", callback_data="publish"),
        InlineKeyboardButton("✏️ Изменить текст", callback_data="edit_body"),
    )
    kb.row(
        InlineKeyboardButton("✏️ Изменить заголовок", callback_data="edit_title"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel"),
    )
    if source_url:
        kb.row(InlineKeyboardButton("Источник", url=source_url))
    if SUGGEST_URL:
        kb.row(InlineKeyboardButton("Предложить новость", url=SUGGEST_URL))
    return kb


def channel_kb():
    # Only "Предложить новость" in channel
    kb = InlineKeyboardMarkup()
    if SUGGEST_URL:
        kb.row(InlineKeyboardButton("Предложить новость", url=SUGGEST_URL))
    return kb


# ---------- Handlers ----------
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    user_state[message.from_user.id] = {"step": "waiting_photo"}
    bot.reply_to(
        message,
        "Ок ✅\n"
        "1) Пришли фото\n"
        "2) Пришли заголовок\n"
        "3) Пришли основной текст\n"
        "4) (опционально) Пришли ссылку на источник или '-' чтобы пропустить\n"
        "Потом покажу превью и кнопки."
    )


@bot.message_handler(content_types=["photo"])
def on_photo(message):
    uid = message.from_user.id
    file_id = message.photo[-1].file_id
    photo_bytes = tg_file_bytes(file_id)
    warn_if_too_small(message.chat.id, photo_bytes)
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
    warn_if_too_small(message.chat.id, photo_bytes)
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
        st["source_url"] = extract_source_url(text)
        if st["source_url"]:
            st["step"] = "waiting_action"
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(
                chat_id=message.chat.id,
                photo=BytesIO(st["card_bytes"]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=preview_kb(st["source_url"]),
            )
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
        bot.send_photo(
            chat_id=message.chat.id,
            photo=BytesIO(st["card_bytes"]),
            caption=caption,
            parse_mode="HTML",
            reply_markup=preview_kb(st["source_url"]),
        )
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
                reply_markup=channel_kb()  # only Suggest button in channel
            )
            bot.answer_callback_query(call.id, "Опубликовано ✅")
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
        user_state[uid] = {"step": "waiting_photo"}
        bot.send_message(call.message.chat.id, "Отменил ❌ Пришли новое фото для следующей новости.")


if __name__ == "__main__":
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
