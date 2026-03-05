# bot.py
# Photo -> Title -> Body -> (optional Source) -> Preview with buttons -> Publish to channel
# + /news: fetch latest news from sources and send to user in DM (20 + show more 10)

import os
import re
import html
import time
import json
import requests
from io import BytesIO
from typing import List, Dict, Optional, Tuple
from xml.etree import ElementTree as ET

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

# user_state[uid] stores both posting-flow and news-cache
user_state = {}

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

# ============================================================
# NEWS CONFIG (MVP): add RSS/HTML/SITEMAP sources right here ✅
# ============================================================
NEWS_SOURCES = [
    {
        "id": "onliner",
        "name": "Onliner",
        "kind": "rss",
        "url": "https://www.onliner.by/feed",
        "limit": 30,
    },
    {
        "id": "sputnik",
        "name": "Sputnik",
        "kind": "rss",
        "url": "https://sputnik.by/export/rss2/smi/index.xml",
        "limit": 30,
    },
    {
        "id": "sb",
        "name": "SB.by",
        "kind": "html_sb_feed",
        "url": "https://www.sb.by/feed/",
        "limit": 40,
    },
    {
        "id": "tochka",
        "name": "Tochka",
        "kind": "sitemap_og",
        "url": "https://tochka.by/sitemap.xml",
        "limit": 60,
    },
]

NEWS_PAGE_SIZE_FIRST = 20
NEWS_PAGE_SIZE_MORE = 10
NEWS_CACHE_TTL_SEC = 10 * 60  # 10 minutes cache per user

# ---------- Requests session ----------
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
})

def http_get(url: str, timeout: int = 25) -> str:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text

def http_get_bytes(url: str, timeout: int = 25) -> bytes:
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.content

def normalize_url(base: str, href: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        m = re.match(r"^(https?://[^/]+)", base)
        return (m.group(1) if m else base.rstrip("/")) + href
    return base.rstrip("/") + "/" + href.lstrip("/")

def safe_strip(s: str) -> str:
    return (s or "").strip()

# ============================================================
# NEWS PARSERS
# ============================================================

def parse_rss(url: str, source_name: str, limit: int = 30) -> List[Dict]:
    """
    RSS via xml.etree.ElementTree.
    Extract: title, link, description, pubDate (if any), enclosure/media:content (if any).
    """
    xml_text = http_get(url, timeout=25)
    root = ET.fromstring(xml_text)

    # namespaces sometimes appear; we keep flexible checks
    items = []
    for item in root.findall(".//item"):
        title = safe_strip(item.findtext("title"))
        link = safe_strip(item.findtext("link"))
        desc = safe_strip(item.findtext("description"))
        pub = safe_strip(item.findtext("pubDate")) or safe_strip(item.findtext("{http://purl.org/dc/elements/1.1/}date"))

        image = ""
        enc = item.find("enclosure")
        if enc is not None and (enc.get("type", "").startswith("image/") or enc.get("url")):
            image = enc.get("url", "") or ""

        if not image:
            # try media:content
            for child in item:
                tag = child.tag.lower()
                if "content" in tag and child.get("url"):
                    image = child.get("url")
                    break

        items.append({
            "source": source_name,
            "title": title,
            "url": link,
            "summary": html.unescape(re.sub(r"<[^>]+>", " ", desc)).strip(),
            "image": image,
            "published": pub,
        })

        if len(items) >= limit:
            break

    # filter junk
    out = []
    for it in items:
        if it["title"] and it["url"]:
            out.append(it)
    return out

def parse_sb_feed(url: str, limit: int = 40) -> List[Dict]:
    """
    SB.by feed page is HTML. Articles may be blocked (403), so MVP extracts only title+link.
    We pull links that look like /articles/... and take anchor text.
    """
    html_text = http_get(url, timeout=25)

    # anchors to articles
    # Example: href="/articles/....html">TITLE</a>
    pat = re.compile(r'href="(?P<href>/articles/[^"]+)"[^>]*>(?P<title>[^<]{5,200})</a>', re.IGNORECASE)
    seen = set()
    items = []
    for m in pat.finditer(html_text):
        href = m.group("href")
        title = html.unescape(m.group("title")).strip()
        full = normalize_url(url, href)
        key = (title, full)
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "source": "SB.by",
            "title": title,
            "url": full,
            "summary": "",
            "image": "",
            "published": "",
        })
        if len(items) >= limit:
            break
    return items

def extract_og_meta(page_html: str) -> Dict[str, str]:
    """
    Minimal OG parser: og:title, og:description, og:image
    """
    def find_meta(prop: str) -> str:
        # meta property="og:title" content="..."
        m = re.search(rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']', page_html, re.IGNORECASE)
        if m:
            return html.unescape(m.group(1)).strip()
        return ""

    return {
        "title": find_meta("og:title"),
        "desc": find_meta("og:description"),
        "image": find_meta("og:image"),
    }

def parse_tochka_sitemap(url: str, limit: int = 60) -> List[Dict]:
    """
    Tochka: sitemap.xml -> take latest /articles/ URLs.
    Then fetch each article and extract og:title/og:description/og:image.
    """
    xml_text = http_get(url, timeout=35)

    # Collect (loc, lastmod)
    locs: List[Tuple[str, str]] = []
    # Fast regex parsing is OK for sitemap MVP
    for loc, lastmod in re.findall(r"<loc>(.*?)</loc>\s*(?:<lastmod>(.*?)</lastmod>)?", xml_text, flags=re.DOTALL | re.IGNORECASE):
        loc = loc.strip()
        lastmod = (lastmod or "").strip()
        if "/articles/" not in loc:
            continue
        locs.append((loc, lastmod))

    # Sort newest first by lastmod string (ISO usually sorts lexicographically)
    locs.sort(key=lambda x: x[1], reverse=True)
    locs = locs[:limit]

    items = []
    for (loc, lastmod) in locs:
        try:
            page = http_get(loc, timeout=25)
            og = extract_og_meta(page)
            title = og["title"] or ""
            desc = og["desc"] or ""
            image = og["image"] or ""
            if title and loc:
                items.append({
                    "source": "Tochka",
                    "title": title,
                    "url": loc,
                    "summary": desc,
                    "image": image,
                    "published": lastmod,
                })
        except Exception:
            continue

    return items

def fetch_all_news() -> List[Dict]:
    """
    Pull from all configured sources, merge, de-dup by URL, keep best effort ordering.
    MVP ordering: keep source order but de-dup; later можно сортировать по времени.
    """
    merged: List[Dict] = []
    by_url = set()

    for src in NEWS_SOURCES:
        try:
            if src["kind"] == "rss":
                items = parse_rss(src["url"], src["name"], limit=src.get("limit", 30))
            elif src["kind"] == "html_sb_feed":
                items = parse_sb_feed(src["url"], limit=src.get("limit", 40))
            elif src["kind"] == "sitemap_og":
                items = parse_tochka_sitemap(src["url"], limit=src.get("limit", 60))
            else:
                items = []
        except Exception:
            items = []

        for it in items:
            u = it.get("url", "")
            if not u or u in by_url:
                continue
            by_url.add(u)
            merged.append(it)

    return merged

def format_news_message(items: List[Dict], offset: int, count: int) -> str:
    chunk = items[offset:offset + count]
    lines = []
    for i, it in enumerate(chunk, start=offset + 1):
        title = it.get("title", "").strip()
        src = it.get("source", "").strip()
        url = it.get("url", "").strip()
        # Telegram HTML parse mode supports <a href="">
        lines.append(f"{i}. <b>[{html.escape(src)}]</b> {html.escape(title)}\n<a href=\"{html.escape(url)}\">ссылка</a>")
    if not lines:
        return "Пока пусто 🤷‍♂️ Попробуй /news позже."
    return "\n\n".join(lines)

def news_kb(offset: int, total: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    next_offset = offset + NEWS_PAGE_SIZE_MORE
    buttons = []

    if next_offset < total:
        buttons.append(InlineKeyboardButton("➕ Показать ещё 10", callback_data=f"news_more:{next_offset}"))
    buttons.append(InlineKeyboardButton("🔄 Обновить", callback_data="news_refresh"))
    kb.row(*buttons)
    return kb

def get_user_news_cache(uid: int) -> Optional[Dict]:
    st = user_state.get(uid) or {}
    cache = st.get("news_cache")
    if not cache:
        return None
    if time.time() - cache.get("ts", 0) > NEWS_CACHE_TTL_SEC:
        return None
    return cache

def set_user_news_cache(uid: int, items: List[Dict]):
    st = user_state.get(uid) or {}
    st["news_cache"] = {"ts": time.time(), "items": items}
    user_state[uid] = st

def send_news_page(chat_id: int, uid: int, offset: int, first: bool = False):
    cache = get_user_news_cache(uid)
    if not cache:
        bot.send_message(chat_id, "Собираю новости… 🧲")
        items = fetch_all_news()
        set_user_news_cache(uid, items)
        cache = get_user_news_cache(uid)

    items = cache["items"]
    total = len(items)

    page_size = NEWS_PAGE_SIZE_FIRST if first else NEWS_PAGE_SIZE_MORE
    text = format_news_message(items, offset, page_size)

    kb = news_kb(offset if first else offset, total)
    bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)

# ============================================================
# CATEGORY / KEYWORDS (your existing logic)
# ============================================================

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
    for emoji_, keys in CATEGORY_RULES:
        for k in keys:
            if k in text:
                return emoji_
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
    emoji_ = pick_category_emoji(title, body)
    keywords = pick_keywords(title, body)
    title_safe = html.escape((title or "").strip())
    body_high = highlight_keywords_html((body or "").strip(), keywords)
    return f"<b>{emoji_} {title_safe}</b>\n\n{body_high}".strip()

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

    # Resize to target + sharpen
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=170, threshold=3))

    # Darken
    img = ImageEnhance.Brightness(img).enhance(0.55)

    draw = ImageDraw.Draw(img)

    # Safe margins
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

    # Title zone max height
    title_zone_pct = 0.23
    title_max_h = int(img.height * title_zone_pct)

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

    y = margin_top
    for i, ln in enumerate(best_lines):
        draw.text((margin_x, y), ln, font=best_font, fill="white")
        y += best_heights[i] + best_spacing

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
    kb = InlineKeyboardMarkup()
    if SUGGEST_URL:
        kb.row(InlineKeyboardButton("Предложить новость", url=SUGGEST_URL))
    return kb

# ============================================================
# COMMANDS
# ============================================================

@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    user_state[message.from_user.id] = {"step": "waiting_photo"}
    bot.reply_to(
        message,
        "Привет! Я умею:\n"
        "• /post — оформить пост (фото → заголовок → текст → превью)\n"
        "• /news — прислать главные новости (20 + показать ещё)\n\n"
        "Режим /post:\n"
        "1) Пришли фото\n"
        "2) Пришли заголовок\n"
        "3) Пришли основной текст\n"
        "4) (опционально) Пришли ссылку на источник или '-' чтобы пропустить\n"
    )

@bot.message_handler(commands=["post"])
def cmd_post(message):
    user_state[message.from_user.id] = {"step": "waiting_photo"}
    bot.reply_to(message, "Ок ✅ Режим оформления поста. Пришли фото 📷")

@bot.message_handler(commands=["news"])
def cmd_news(message):
    uid = message.from_user.id
    # first page offset=0
    send_news_page(message.chat.id, uid, offset=0, first=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("news_more:") or call.data in {"news_refresh"})
def on_news_callback(call):
    uid = call.from_user.id
    if call.data == "news_refresh":
        # drop cache and send first page
        st = user_state.get(uid) or {}
        st["news_cache"] = None
        user_state[uid] = st
        bot.answer_callback_query(call.id, "Обновляю…")
        send_news_page(call.message.chat.id, uid, offset=0, first=True)
        return

    m = re.match(r"news_more:(\d+)", call.data)
    if not m:
        bot.answer_callback_query(call.id, "Ошибка")
        return
    offset = int(m.group(1))
    bot.answer_callback_query(call.id, "Ещё новости ✅")
    send_news_page(call.message.chat.id, uid, offset=offset, first=False)

# ============================================================
# POSTING FLOW HANDLERS (your existing)
# ============================================================

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

    # allow user to type /post or /news as text without triggering flow
    if text.startswith("/"):
        return

    st = user_state.get(uid)
    if not st:
        user_state[uid] = {"step": "waiting_photo"}
        bot.reply_to(message, "Сначала пришли фото 📷 или нажми /post")
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
        bot.reply_to(message, "Пришли фото 📷 или нажми /post")

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
                reply_markup=channel_kb()
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
