# bot.py
# Two modes:
# 1) /post -> Photo -> Title -> Body -> (optional Source) -> Preview -> Publish
# 2) /news -> Fetch RSS + HTML -> show items -> "✅ Оформить" -> continues as normal post flow

import os
import re
import html
import hashlib
from io import BytesIO
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse

import requests
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from bs4 import BeautifulSoup

from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter


# ---------- ENV ----------
TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()
BOT_USERNAME = (os.getenv("BOT_USERNAME") or "").strip().lstrip("@")
SUGGEST_URL = (os.getenv("SUGGEST_URL") or "").strip()

# Optional admin lock (recommended)
ADMIN_ID_RAW = (os.getenv("ADMIN_ID") or "").strip()
ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

# RSS sources: comma-separated
RSS_SOURCES_RAW = (os.getenv("RSS_SOURCES") or "").strip()
RSS_SOURCES = [s.strip() for s in RSS_SOURCES_RAW.split(",") if s.strip()]

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

# News paging
NEWS_FIRST_BATCH = 20
NEWS_MORE_BATCH = 10

# HTML sources (fallback where RSS is absent/hard)
HTML_SOURCES = [
    {"name": "Onliner",   "url": "https://www.onliner.by/"},
    {"name": "Sputnik",   "url": "https://sputnik.by/"},
    {"name": "Minsknews", "url": "https://minsknews.by/"},
    {"name": "Tochka",    "url": "https://tochka.by/articles"},
    {"name": "Smartpress", "url": "https://smartpress.by/"},  # as html fallback too
    {"name": "Mlyn",      "url": "https://mlyn.by/"},
    {"name": "Brestcity", "url": "https://brestcity.com/"},
    {"name": "Telegraf",  "url": "https://telegraf.news/hashtag/belarus/"},
    {"name": "1prof",     "url": "https://1prof.by/"},
    {"name": "SB",        "url": "https://www.sb.by/"},
    {"name": "NewGrodno", "url": "https://newgrodno.by/"},
    {"name": "ONT",       "url": "https://ont.by/ru/news-ru"},
]

# Requests
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA})

bot = telebot.TeleBot(TOKEN)

# user_state[uid] = {
#   mode: "post" | "news"
#   step: waiting_photo | waiting_title | waiting_body | waiting_source | waiting_action | news_menu
#   photo_bytes: bytes
#   title: str
#   card_bytes: bytes
#   body_raw: str
#   source_url: str
#   news_list: [keys]
#   news_pos: int
# }
user_state = {}

# News cache / dedup
seen_links = set()
seen_titles = []
news_cache = {}  # key -> dict(title, link, source, image_url)

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)


def is_admin(obj) -> bool:
    if ADMIN_ID is None:
        return True
    uid = getattr(obj.from_user, "id", None)
    return uid == ADMIN_ID


# ---------- UI ----------
def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("🖼 Оформить пост"), KeyboardButton("📰 Получить новости"))
    return kb


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
    kb = InlineKeyboardMarkup()
    if SUGGEST_URL:
        kb.row(InlineKeyboardButton("Предложить новость", url=SUGGEST_URL))
    return kb


def news_item_kb(key: str, link: str):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Оформить", callback_data=f"nfmt:{key}"),
        InlineKeyboardButton("🗑 Пропустить", callback_data=f"nskip:{key}"),
    )
    kb.row(InlineKeyboardButton("🔗 Источник", url=link))
    return kb


def news_more_kb():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton(f"➕ Показать ещё {NEWS_MORE_BATCH}", callback_data="nmore"))
    return kb


# ---------- CATEGORY / KEYWORDS ----------
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
    r = SESSION.get(file_url, timeout=30)
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
    words = [w for w in text.split() if w.strip()]
    if not words:
        return [""]

    n = len(words)
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
                rem = (max_width - w)
                cost = rem * rem
                if dp[j + 1][k - 1] == INF:
                    continue
                total = cost + dp[j + 1][k - 1]
                if total < dp[i][k]:
                    dp[i][k] = total
                    nxt[i][k] = j + 1

    best_k = None
    best = INF
    for k in range(1, max_lines + 1):
        if dp[0][k] < best:
            best = dp[0][k]
            best_k = k

    if best_k is None:
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
        if lines:
            lines[-1] = (lines[-1] + " " + " ".join(words[i:])).strip()
        else:
            lines = [" ".join(words[i:])]

    return lines


# ---------- Card generator ----------
def make_card(photo_bytes: bytes, title_text: str) -> BytesIO:
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

    # Resize + sharpen
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=170, threshold=3))

    # Darken
    img = ImageEnhance.Brightness(img).enhance(0.55)

    draw = ImageDraw.Draw(img)

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

    # Title zone <= 23%
    title_max_h = int(img.height * 0.23)

    text = (title_text or "").strip().upper() or " "
    font_size = int(img.height * 0.11)
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
            best_lines = lines
            best_font = font
            best_spacing = spacing
            best_heights = heights
            break

    # Draw title top
    y = margin_top
    for i, ln in enumerate(best_lines):
        draw.text((margin_x, y), ln, font=best_font, fill="white")
        y += best_heights[i] + best_spacing

    # Footer
    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_placeholder_bg() -> bytes:
    img = Image.new("RGB", (1080, 1350), (18, 18, 18))
    draw = ImageDraw.Draw(img)
    for y in range(0, img.height, 7):
        v = 18 + (y % 28) // 4
        draw.line((0, y, img.width, y), fill=(v, v, v))
    out = BytesIO()
    img.save(out, format="JPEG", quality=92)
    return out.getvalue()


# ---------- NEWS helpers ----------
def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def _news_key(title: str, link: str) -> str:
    return hashlib.sha256(f"{title}|{link}".encode("utf-8")).hexdigest()[:16]


def normalize_url(base: str, href: str) -> str:
    if not href:
        return ""
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base, href)


def is_same_domain(base_url: str, candidate: str) -> bool:
    try:
        b = urlparse(base_url)
        c = urlparse(candidate)
        return (b.netloc and c.netloc and b.netloc == c.netloc)
    except Exception:
        return False


def extract_og_fields(page_url: str):
    """
    Returns: (title, image_url)
    """
    try:
        r = SESSION.get(page_url, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        og_title = ""
        og_img = ""

        t = soup.find("meta", property="og:title")
        if t and t.get("content"):
            og_title = t["content"].strip()

        img = soup.find("meta", property="og:image")
        if img and img.get("content"):
            og_img = img["content"].strip()

        if not og_title:
            if soup.title and soup.title.text:
                og_title = soup.title.text.strip()

        if og_img:
            og_img = normalize_url(page_url, og_img)

        return og_title, og_img
    except Exception:
        return "", ""


def download_bytes(url: str) -> bytes:
    if not url:
        return b""
    try:
        r = SESSION.get(url, timeout=25)
        r.raise_for_status()
        return r.content
    except Exception:
        return b""


def rss_fetch_items(max_items: int):
    """
    Minimal RSS parser (no extra libs).
    Accepts RSS/Atom in common forms.
    """
    out_keys = []
    for feed_url in RSS_SOURCES:
        if len(out_keys) >= max_items:
            break
        try:
            r = SESSION.get(feed_url, timeout=25)
            r.raise_for_status()
            xml = r.text
        except Exception:
            continue

        # naive but robust enough parsing for title/link/enclosure
        # Try both <item> (RSS) and <entry> (Atom)
        items = re.findall(r"<item\b[\s\S]*?</item>", xml, flags=re.IGNORECASE)
        is_atom = False
        if not items:
            items = re.findall(r"<entry\b[\s\S]*?</entry>", xml, flags=re.IGNORECASE)
            is_atom = True

        for raw in items[:40]:
            if len(out_keys) >= max_items:
                break

            title = ""
            link = ""
            img = ""

            mt = re.search(r"<title[^>]*>([\s\S]*?)</title>", raw, flags=re.IGNORECASE)
            if mt:
                title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", mt.group(1))).strip()

            if is_atom:
                ml = re.search(r'<link[^>]+href="([^"]+)"', raw, flags=re.IGNORECASE)
                if ml:
                    link = ml.group(1).strip()
            else:
                ml = re.search(r"<link[^>]*>([\s\S]*?)</link>", raw, flags=re.IGNORECASE)
                if ml:
                    link = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", ml.group(1))).strip()

            me = re.search(r'<enclosure[^>]+url="([^"]+)"', raw, flags=re.IGNORECASE)
            if me:
                img = me.group(1).strip()

            if not title or not link:
                continue

            if link in seen_links:
                continue
            dup = any(_similar(title, t) >= 0.94 for t in seen_titles[-200:])
            if dup:
                continue

            key = _news_key(title, link)
            news_cache[key] = {"title": title, "link": link, "source": feed_url, "image_url": img}
            seen_links.add(link)
            seen_titles.append(title)
            out_keys.append(key)

    return out_keys


def html_fetch_items(max_items: int):
    out_keys = []
    for src in HTML_SOURCES:
        if len(out_keys) >= max_items:
            break
        base = src["url"]
        name = src["name"]

        try:
            r = SESSION.get(base, timeout=25)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
        except Exception:
            continue

        # Collect candidate links (article-like)
        links = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            u = normalize_url(base, href)
            if not u:
                continue
            # Keep mostly same-domain to avoid external junk
            if not is_same_domain(base, u):
                continue
            # Heuristic: keep URLs that look like articles
            path = urlparse(u).path.lower()
            if len(path) < 6:
                continue
            if any(x in path for x in ["/news", "/articles", "/article", "/belarus", "/world", "/society", "/incidents", "/event", "/ru/"]):
                links.append(u)

        # Deduplicate in-page
        uniq = []
        seen = set()
        for u in links:
            if u in seen:
                continue
            seen.add(u)
            uniq.append(u)

        # Take first N and resolve title/image via og tags
        for u in uniq[:30]:
            if len(out_keys) >= max_items:
                break
            if u in seen_links:
                continue

            t, og_img = extract_og_fields(u)
            if not t:
                continue

            dup = any(_similar(t, tt) >= 0.94 for tt in seen_titles[-200:])
            if dup:
                continue

            key = _news_key(t, u)
            news_cache[key] = {"title": t, "link": u, "source": name, "image_url": og_img}
            seen_links.add(u)
            seen_titles.append(t)
            out_keys.append(key)

    return out_keys


def news_collect(max_items: int):
    keys = []
    # Mix: RSS first (stable), then HTML
    if RSS_SOURCES:
        keys.extend(rss_fetch_items(max_items=max_items))
    if len(keys) < max_items:
        keys.extend(html_fetch_items(max_items=max_items - len(keys)))
    return keys


# ---------- Flows ----------
def start_post_flow(uid: int, chat_id: int):
    user_state[uid] = {"mode": "post", "step": "waiting_photo"}
    bot.send_message(
        chat_id,
        "🖼 Режим: Оформить пост\n"
        "1) Пришли фото\n"
        "2) Пришли заголовок\n"
        "3) Пришли основной текст\n"
        "4) (опционально) Пришли ссылку на источник или '-' чтобы пропустить\n"
        "Потом покажу превью и кнопки.",
        reply_markup=main_menu_kb()
    )


def start_news_flow(uid: int, chat_id: int):
    user_state[uid] = {"mode": "news", "step": "news_menu", "news_list": [], "news_pos": 0}
    if not RSS_SOURCES and not HTML_SOURCES:
        bot.send_message(chat_id, "Источники не настроены.", reply_markup=main_menu_kb())
        return

    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("▶️ Собрать сейчас", callback_data="news_fetch"))
    kb.row(InlineKeyboardButton("📌 Показать RSS", callback_data="news_sources"))
    bot.send_message(
        chat_id,
        "📰 Режим: Получить новости\n"
        f"Нажми «Собрать сейчас» и я пришлю {NEWS_FIRST_BATCH} новостей.\n"
        f"Потом можно «Показать ещё {NEWS_MORE_BATCH}».",
        reply_markup=kb
    )


def send_news_batch(chat_id: int, uid: int, batch: int):
    st = user_state.get(uid) or {}
    keys = st.get("news_list", [])
    pos = int(st.get("news_pos", 0))

    if pos >= len(keys):
        bot.send_message(chat_id, "Больше новостей нет (пока).")
        return

    end = min(pos + batch, len(keys))
    for key in keys[pos:end]:
        item = news_cache.get(key, {})
        title = item.get("title", "")
        link = item.get("link", "")
        source = item.get("source", "")
        msg = f"<b>{html.escape(title)}</b>\n\n{html.escape(str(source))}"
        bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=news_item_kb(key, link))

    st["news_pos"] = end
    user_state[uid] = st

    if st["news_pos"] < len(keys):
        bot.send_message(chat_id, "Хочешь ещё?", reply_markup=news_more_kb())
    else:
        bot.send_message(chat_id, "Это всё на сейчас ✅", reply_markup=main_menu_kb())


# ---------- Handlers ----------
@bot.message_handler(commands=["start", "help", "menu"])
def cmd_start(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return
    bot.send_message(
        message.chat.id,
        "Меню:\n"
        "🖼 /post — оформить пост\n"
        "📰 /news — получить новости\n\n"
        "Можно кнопками снизу 👇",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(commands=["post"])
def cmd_post(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return
    start_post_flow(message.from_user.id, message.chat.id)


@bot.message_handler(commands=["news"])
def cmd_news(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return
    start_news_flow(message.from_user.id, message.chat.id)


@bot.message_handler(func=lambda m: (m.text or "").strip() in ["🖼 Оформить пост", "📰 Получить новости"])
def on_menu_buttons(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return
    txt = (message.text or "").strip()
    if txt == "🖼 Оформить пост":
        start_post_flow(message.from_user.id, message.chat.id)
    else:
        start_news_flow(message.from_user.id, message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data in ["news_fetch", "news_sources", "nmore"])
def on_news_menu(call):
    if not is_admin(call):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return

    uid = call.from_user.id
    chat_id = call.message.chat.id

    if call.data == "news_sources":
        if not RSS_SOURCES:
            bot.answer_callback_query(call.id, "RSS не задан", show_alert=True)
            return
        txt = "📌 RSS источники:\n" + "\n".join(f"• {s}" for s in RSS_SOURCES)
        bot.send_message(chat_id, txt)
        bot.answer_callback_query(call.id, "Ок")
        return

    if call.data == "news_fetch":
        bot.answer_callback_query(call.id, "Собираю…")
        keys = news_collect(max_items=60)  # collect more, show in pages
        if not keys:
            bot.send_message(chat_id, "Ничего нового не нашёл.")
            return
        user_state[uid] = {"mode": "news", "step": "news_menu", "news_list": keys, "news_pos": 0}
        bot.send_message(chat_id, f"Нашёл: {len(keys)}. Отправляю первые {NEWS_FIRST_BATCH}…", reply_markup=main_menu_kb())
        send_news_batch(chat_id, uid, NEWS_FIRST_BATCH)
        return

    if call.data == "nmore":
        bot.answer_callback_query(call.id, "Ок")
        send_news_batch(chat_id, uid, NEWS_MORE_BATCH)
        return


@bot.callback_query_handler(func=lambda call: call.data.startswith("nskip:") or call.data.startswith("nfmt:"))
def on_news_item_action(call):
    if not is_admin(call):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return

    uid = call.from_user.id
    chat_id = call.message.chat.id

    action, key = call.data.split(":", 1)
    item = news_cache.get(key)

    if not item:
        bot.answer_callback_query(call.id, "Эта новость уже недоступна", show_alert=True)
        return

    if action == "nskip":
        news_cache.pop(key, None)
        try:
            bot.edit_message_text("🗑 Пропущено.", chat_id, call.message.message_id)
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Ок")
        return

    # nfmt: start formatting flow from item
    title = (item.get("title") or "").strip()
    link = (item.get("link") or "").strip()
    image_url = (item.get("image_url") or "").strip()

    # download image or placeholder
    photo_bytes = download_bytes(image_url)
    if not photo_bytes:
        photo_bytes = make_placeholder_bg()

    warn_if_too_small(chat_id, photo_bytes)

    # make card now, then ask for body
    try:
        card = make_card(photo_bytes, title)
        card_bytes = card.getvalue()
    except Exception as e:
        bot.answer_callback_query(call.id, "Не смог сделать карточку", show_alert=True)
        bot.send_message(chat_id, f"Ошибка при создании карточки: {e}")
        return

    user_state[uid] = {
        "mode": "post",
        "step": "waiting_body",
        "photo_bytes": photo_bytes,
        "title": title,
        "card_bytes": card_bytes,
        "body_raw": "",
        "source_url": link  # default source
    }

    try:
        bot.edit_message_text("✅ Ок, оформляем. Жду основной текст поста.", chat_id, call.message.message_id)
    except Exception:
        pass

    bot.send_message(
        chat_id,
        "🖼 Карточка уже готова (заголовок нанесён).\n"
        "Теперь пришли ОСНОВНОЙ ТЕКСТ поста.\n\n"
        "Источник уже подставлен из новости (можешь заменить позже).",
        reply_markup=main_menu_kb()
    )
    bot.answer_callback_query(call.id, "Ок")


# ---- Post mode handlers (your original flow) ----
@bot.message_handler(content_types=["photo"])
def on_photo(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return

    uid = message.from_user.id
    file_id = message.photo[-1].file_id
    photo_bytes = tg_file_bytes(file_id)
    warn_if_too_small(message.chat.id, photo_bytes)
    user_state[uid] = {"mode": "post", "step": "waiting_title", "photo_bytes": photo_bytes}
    bot.reply_to(message, "Фото получено ✅ Теперь отправь ЗАГОЛОВОК.")


@bot.message_handler(content_types=["document"])
def on_document(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return

    uid = message.from_user.id
    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        bot.reply_to(message, "Пришли картинку (JPG/PNG).")
        return
    photo_bytes = tg_file_bytes(doc.file_id)
    warn_if_too_small(message.chat.id, photo_bytes)
    user_state[uid] = {"mode": "post", "step": "waiting_title", "photo_bytes": photo_bytes}
    bot.reply_to(message, "Картинка получена ✅ Теперь отправь ЗАГОЛОВОК.")


@bot.message_handler(content_types=["text"])
def on_text(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return

    uid = message.from_user.id
    text = (message.text or "").strip()

    # quick menu triggers
    if text in ["🖼 Оформить пост"]:
        start_post_flow(uid, message.chat.id)
        return
    if text in ["📰 Получить новости"]:
        start_news_flow(uid, message.chat.id)
        return

    st = user_state.get(uid)
    if not st:
        user_state[uid] = {"mode": "post", "step": "waiting_photo"}
        bot.reply_to(message, "Сначала пришли фото 📷 (или нажми 🖼).", reply_markup=main_menu_kb())
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

        body_src = extract_source_url(text)
        if body_src:
            st["source_url"] = body_src

        if st.get("source_url"):
            st["step"] = "waiting_action"
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(
                chat_id=message.chat.id,
                photo=BytesIO(st["card_bytes"]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=preview_kb(st.get("source_url", "")),
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
            reply_markup=preview_kb(st.get("source_url", "")),
        )
        bot.reply_to(message, "Превью готово ✅ Нажми кнопку.")

    elif step == "waiting_action":
        bot.reply_to(message, "Сейчас ждём кнопку под превью: ✅✏️❌")

    else:
        user_state[uid] = {"mode": "post", "step": "waiting_photo"}
        bot.reply_to(message, "Пришли фото 📷", reply_markup=main_menu_kb())


@bot.callback_query_handler(func=lambda call: call.data in ["publish", "edit_body", "edit_title", "cancel"])
def on_action(call):
    if not is_admin(call):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return

    uid = call.from_user.id
    st = user_state.get(uid)

    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(call.id, "Нет активного превью. Начни с /post и фото.")
        return

    if call.data == "publish":
        try:
            caption = build_caption_html(st["title"], st["body_raw"])
            bot.send_photo(
                CHANNEL,
                BytesIO(st["card_bytes"]),
                caption=caption,
                parse_mode="HTML",
                reply_markup=channel_kb()
            )
            bot.answer_callback_query(call.id, "Опубликовано ✅")
            bot.send_message(call.message.chat.id, "Готово ✅ Дальше: фото (/post) или новости (/news).", reply_markup=main_menu_kb())
            user_state[uid] = {"mode": "post", "step": "waiting_photo"}
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
        user_state[uid] = {"mode": "post", "step": "waiting_photo"}
        bot.send_message(call.message.chat.id, "Отменил ❌ Пришли новое фото.", reply_markup=main_menu_kb())


if __name__ == "__main__":
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
