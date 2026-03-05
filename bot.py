import os
import re
import html
import time
import hashlib
from io import BytesIO
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import requests
import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from PIL import Image, ImageDraw, ImageFont, ImageEnhance


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
    raise ValueError("BOT_TOKEN must not contain spaces")
if not CHANNEL or CHANNEL == "@":
    raise RuntimeError("CHANNEL_USERNAME is not set (Render -> Environment -> CHANNEL_USERNAME)")

if not SUGGEST_URL and BOT_USERNAME:
    SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"



def extract_og_meta(html_text):
    og = {}
    m = re.search(r'<meta property="og:image" content="(.*?)"', html_text)
    if m:
        og["image"] = m.group(1)
    m = re.search(r'<meta property="og:description" content="(.*?)"', html_text)
    if m:
        og["desc"] = m.group(1)
    return og

# =========================
# UI BUTTONS
# =========================
BTN_POST = "📝 Оформить пост"
BTN_NEWS = "📰 Получить новости"


def main_menu_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton(BTN_POST), KeyboardButton(BTN_NEWS))
    return kb


# =========================
# FONTS / CARD
# =========================
FONT_MN = "CaviarDreams.ttf"
FONT_CHP = "Inter-ExtraBold.ttf"

FOOTER_TEXT = "MINSK NEWS"

# Card size (both)
TARGET_W, TARGET_H = 750, 938

# MN: title zone height (top)
MN_TITLE_ZONE_PCT = 0.23

# CHP: gradient height
CHP_GRADIENT_PCT = 0.48


# =========================
# NEWS
# =========================
NEWS_FIRST_BATCH = 20
NEWS_MORE_BATCH = 10
NEWS_CACHE_TTL_SEC = 10 * 60
NEWS_PER_SOURCE_CAP = 6

NEWS_SOURCES = [
    {"id": "onliner", "name": "Onliner", "kind": "rss", "url": "https://www.onliner.by/feed", "limit": 80},
    {"id": "sputnik", "name": "Sputnik", "kind": "rss", "url": "https://sputnik.by/export/rss2/smi/index.xml", "limit": 80},
    {"id": "sb", "name": "SB.by", "kind": "sb_feed_html", "url": "https://www.sb.by/feed/", "limit": 120},
    {"id": "tochka", "name": "Tochka", "kind": "tochka_sitemap_og", "url": "https://tochka.by/sitemap.xml", "limit": 160},
]


# =========================
# BOT + SESSION
# =========================
bot = telebot.TeleBot(TOKEN)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
})

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)

user_state: Dict[int, Dict] = {}


# =========================
# Helpers
# =========================
def is_admin(msg_or_call) -> bool:
    if ADMIN_ID is None:
        return True
    uid = getattr(msg_or_call.from_user, "id", None)
    return uid == ADMIN_ID


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
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return urljoin(base, href)


def extract_source_url(text: str) -> str:
    m = URL_RE.search(text or "")
    return m.group(1) if m else ""


def ensure_fonts():
    if not os.path.exists(FONT_MN):
        raise RuntimeError(f"Не найден шрифт {FONT_MN}. Положи его рядом с bot.py")
    if not os.path.exists(FONT_CHP):
        raise RuntimeError(f"Не найден шрифт {FONT_CHP}. Положи его рядом с bot.py")


def warn_if_too_small(chat_id, photo_bytes: bytes):
    try:
        im = Image.open(BytesIO(photo_bytes))
        if im.width < 900 or im.height < 1100:
            bot.send_message(
                chat_id,
                "⚠️ Фото маленького разрешения. Лучше присылать больше (от 1080×1350 и выше), "
                "чтобы текст был максимально чёткий."
            )
    except Exception:
        pass


# =========================
# Date parsing + last 24h
# =========================
def parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    s = s.strip()

    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def is_last_24h(dt_utc: Optional[datetime]) -> bool:
    if not dt_utc:
        return False
    now = datetime.now(timezone.utc)
    return dt_utc >= now - timedelta(hours=24)


# =========================
# News parsers
# =========================
def extract_og_meta(page_html: str) -> Dict[str, str]:
    def find_meta(prop: str) -> str:
        m = re.search(
            rf'<meta[^>]+property=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)["\']',
            page_html, re.IGNORECASE
        )
        return html.unescape(m.group(1)).strip() if m else ""
    return {
        "title": find_meta("og:title"),
        "desc": find_meta("og:description"),
        "image": find_meta("og:image"),
    }


def parse_rss(url: str, source_name: str, limit: int = 80) -> List[Dict]:
    xml_text = http_get(url, timeout=25)
    root = ET.fromstring(xml_text)

    out = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = (item.findtext("pubDate") or "").strip() or (item.findtext("{http://purl.org/dc/elements/1.1/}date") or "").strip()

        image = ""
        enc = item.find("enclosure")
        if enc is not None and enc.get("url"):
            image = enc.get("url") or ""
        if not image:
            for child in item:
                tag = (child.tag or "").lower()
                if "content" in tag and child.get("url"):
                    image = child.get("url")
                    break

        dt = parse_dt(pub)

        if title and link:
            out.append({
                "source": source_name,
                "title": title,
                "url": link,
                "summary": html.unescape(re.sub(r"<[^>]+>", " ", desc)).strip(),
                "image": image,
                "published_raw": pub,
                "dt_utc": dt.isoformat() if dt else "",
            })
        if len(out) >= limit:
            break
    return out


def parse_sb_feed_html(url: str, limit: int = 120) -> List[Dict]:
    page = http_get(url, timeout=25)

    pat = re.compile(
        r'href="(?P<href>/articles/[^"]+)"[^>]*>(?P<title>[^<]{5,220})</a>',
        re.IGNORECASE
    )

    seen = set()
    out = []
    now_dt = datetime.now(timezone.utc) - timedelta(hours=1)

    for m in pat.finditer(page):
        href = m.group("href")
        title = html.unescape(m.group("title")).strip()
        full = normalize_url(url, href)
        key = (title, full)
        if key in seen:
            continue
        seen.add(key)
        if not title or not full:
            continue
        out.append({
            "source": "SB.by",
            "title": title,
            "url": full,
            "summary": "",
            "image": "",
            "published_raw": "",
            "dt_utc": now_dt.isoformat(),
        })
        if len(out) >= limit:
            break
    return out


def parse_tochka_sitemap_og(url: str, limit: int = 160) -> List[Dict]:
    xml_text = http_get(url, timeout=35)

    locs: List[Tuple[str, str]] = []
    for loc, lastmod in re.findall(
        r"<loc>(.*?)</loc>\s*(?:<lastmod>(.*?)</lastmod>)?",
        xml_text, flags=re.DOTALL | re.IGNORECASE
    ):
        loc = (loc or "").strip()
        lastmod = (lastmod or "").strip()
        if "/articles/" not in loc:
            continue
        locs.append((loc, lastmod))

    locs.sort(key=lambda x: x[1], reverse=True)
    locs = locs[:limit]

    out = []
    for (loc, lastmod) in locs:
        dt = parse_dt(lastmod)
        if dt and not is_last_24h(dt):
            continue

        try:
            page = http_get(loc, timeout=25)
            og = extract_og_meta(page)
            title = (og.get("title") or "").strip()
            desc = (og.get("desc") or "").strip()
            img = (og.get("image") or "").strip()
            if img:
                img = normalize_url(loc, img)

            if title and loc:
                out.append({
                    "source": "Tochka",
                    "title": title,
                    "url": loc,
                    "summary": desc,
                    "image": img,
                    "published_raw": lastmod,
                    "dt_utc": dt.isoformat() if dt else "",
                })
        except Exception:
            continue

    return out


def fetch_all_news_last24h() -> List[Dict]:
    merged: List[Dict] = []
    by_url = set()

    for src in NEWS_SOURCES:
        kind = src["kind"]
        try:
            if kind == "rss":
                items = parse_rss(src["url"], src["name"], limit=src.get("limit", 80))
            elif kind == "sb_feed_html":
                items = parse_sb_feed_html(src["url"], limit=src.get("limit", 120))
            elif kind == "tochka_sitemap_og":
                items = parse_tochka_sitemap_og(src["url"], limit=src.get("limit", 160))
            else:
                items = []
        except Exception:
            items = []

        for it in items:
            u = it.get("url", "")
            if not u or u in by_url:
                continue
            by_url.add(u)
            dt = parse_dt(it.get("dt_utc") or "") or parse_dt(it.get("published_raw") or "")
            it["_dt"] = dt
            merged.append(it)

    last24 = [it for it in merged if is_last_24h(it.get("_dt"))]
    nodt = [it for it in merged if it.get("_dt") is None]
    base = last24 if len(last24) >= 10 else (last24 + nodt)

    base.sort(
        key=lambda x: (x.get("_dt") is not None, x.get("_dt") or datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True
    )

    counts = {}
    diversified = []
    for it in base:
        src = it.get("source", "")
        counts[src] = counts.get(src, 0)
        if counts[src] >= NEWS_PER_SOURCE_CAP:
            continue
        counts[src] += 1
        diversified.append(it)

    if len(diversified) < 80:
        for it in base:
            if it in diversified:
                continue
            diversified.append(it)

    return diversified


# =========================
# Caption formatting
# =========================
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


# =========================
# Telegram download
# =========================
def tg_file_bytes(file_id: str) -> bytes:
    file_info = bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
    r = SESSION.get(file_url, timeout=30)
    r.raise_for_status()
    return r.content


# =========================
# Wrapping + drawing
# =========================
def text_width(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.FreeTypeFont) -> int:
    bb = draw.textbbox((0, 0), s, font=font)
    return bb[2] - bb[0]


def wrap_no_truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
                     max_width: int, max_lines: int = 6) -> Tuple[List[str], bool]:
    words = [w for w in (text or "").split() if w.strip()]
    if not words:
        return [""], True

    lines: List[str] = []
    cur = ""
    i = 0

    while i < len(words):
        w = words[i]
        test = (cur + " " + w).strip()
        if text_width(draw, test, font) <= max_width:
            cur = test
            i += 1
        else:
            if not cur:
                return [words[i]], False
            lines.append(cur)
            cur = ""
            if len(lines) >= max_lines:
                return lines, False

    if cur:
        lines.append(cur)

    if len(lines) > max_lines:
        return lines[:max_lines], False

    return lines, True


def crop_to_4x5(img: Image.Image) -> Image.Image:
    w, h = img.size
    target_ratio = 4 / 5
    cur_ratio = w / h
    if cur_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        return img.crop((0, top, w, top + new_h))


def apply_bottom_gradient(img: Image.Image, height_pct: float, max_alpha: int = 220) -> Image.Image:
    w, h = img.size
    gh = int(h * height_pct)
    if gh <= 0:
        return img

    overlay_alpha = Image.new("L", (w, h), 0)
    grad = Image.new("L", (1, gh), 0)
    for y in range(gh):
        a = int(max_alpha * (y / max(1, gh - 1)))
        grad.putpixel((0, y), a)
    grad = grad.resize((w, gh))
    overlay_alpha.paste(grad, (0, h - gh))

    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    base = img.convert("RGBA")
    overlay = Image.composite(black, Image.new("RGBA", (w, h), (0, 0, 0, 0)), overlay_alpha)
    out = Image.alpha_composite(base, overlay)
    return out.convert("RGB")


def fit_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    safe_w: int,
    max_block_h: int,
    max_lines: int = 6,
    start_size: int = 90,
    min_size: int = 16,
    line_spacing_ratio: float = 0.22,
) -> Tuple[ImageFont.FreeTypeFont, List[str], List[int], int, int]:
    text = (text or "").strip()
    if not text:
        text = " "

    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines, ok = wrap_no_truncate(draw, text, font, safe_w, max_lines=max_lines)
        spacing = int(size * line_spacing_ratio)

        heights = []
        total_h = 0
        max_w = 0
        for ln in lines:
            bb = draw.textbbox((0, 0), ln, font=font)
            lw = bb[2] - bb[0]
            lh = bb[3] - bb[1]
            heights.append(lh)
            total_h += lh
            max_w = max(max_w, lw)
        total_h += spacing * (len(lines) - 1)

        if ok and max_w <= safe_w and total_h <= max_block_h:
            return font, lines, heights, spacing, total_h

        size -= 2

    font = ImageFont.truetype(font_path, min_size)
    lines, _ = wrap_no_truncate(draw, text, font, safe_w, max_lines=max_lines)
    spacing = int(min_size * line_spacing_ratio)
    heights = []
    total_h = 0
    for ln in lines:
        bb = draw.textbbox((0, 0), ln, font=font)
        lh = bb[3] - bb[1]
        heights.append(lh)
        total_h += lh
    total_h += spacing * (len(lines) - 1)
    return font, lines, heights, spacing, total_h


# =========================
# Cards
# =========================
def make_card_mn(photo_bytes: bytes, title_text: str) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)

    img = ImageEnhance.Brightness(img).enhance(0.55)
    draw = ImageDraw.Draw(img)

    margin_x = int(img.width * 0.06)
    margin_top = int(img.height * 0.06)
    # Футер ниже
    margin_bottom = int(img.height * 0.07)

    safe_w = img.width - 2 * margin_x

    footer_size = max(24, int(img.height * 0.034))
    footer_font = ImageFont.truetype(FONT_MN, footer_size)
    fb = draw.textbbox((0, 0), FOOTER_TEXT, font=footer_font)
    footer_w = fb[2] - fb[0]
    footer_h = fb[3] - fb[1]
    footer_y = img.height - margin_bottom + (margin_bottom - footer_h) // 2
    footer_x = (img.width - footer_w) // 2

    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    text = (title_text or "").strip().upper()

    font, lines, heights, spacing, _total_h = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_MN,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(img.height * 0.11),
        min_size=16,
        line_spacing_ratio=0.22
    )

    # Блок по центру, текст внутри блока по левому краю
    block_w = 0
    for ln in lines:
        block_w = max(block_w, text_width(draw, ln, font))
    block_x = (img.width - block_w) // 2
    block_x = max(margin_x, block_x)  # защита, чтобы блок не уехал в поля

    y = margin_top
    for i, ln in enumerate(lines):
        draw.text((block_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing

    draw.text((footer_x, footer_y), FOOTER_TEXT, font=footer_font, fill="white")

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card_chp(photo_bytes: bytes, title_text: str) -> BytesIO:
    ensure_fonts()

    img = Image.open(BytesIO(photo_bytes)).convert("RGB")
    img = crop_to_4x5(img)
    img = img.resize((TARGET_W, TARGET_H), resample=Image.Resampling.LANCZOS)

    img = ImageEnhance.Brightness(img).enhance(0.85)
    img = apply_bottom_gradient(img, height_pct=CHP_GRADIENT_PCT, max_alpha=220)
    draw = ImageDraw.Draw(img)

    margin_x = int(img.width * 0.06)
    margin_bottom = int(img.height * 0.08)
    safe_w = img.width - 2 * margin_x

    title_max_h = int(img.height * MN_TITLE_ZONE_PCT)
    text = (title_text or "").strip().upper()

    font, lines, heights, spacing, total_h = fit_text_block(
        draw=draw,
        text=text,
        font_path=FONT_CHP,
        safe_w=safe_w,
        max_block_h=title_max_h,
        max_lines=6,
        start_size=int(img.height * 0.11),
        min_size=16,
        line_spacing_ratio=0.22
    )

    y = img.height - margin_bottom - total_h
    for i, ln in enumerate(lines):
        draw.text((margin_x, y), ln, font=font, fill="white")
        y += heights[i] + spacing

    out = BytesIO()
    img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    out.seek(0)
    return out


def make_card(photo_bytes: bytes, title_text: str, template: str) -> BytesIO:
    if template == "CHP":
        return make_card_chp(photo_bytes, title_text)
    return make_card_mn(photo_bytes, title_text)


# =========================
# Keyboards
# =========================
def template_kb():
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📰 МН", callback_data="tpl:MN"),
        InlineKeyboardButton("🚨 ЧП ВМ", callback_data="tpl:CHP"),
    )
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
        InlineKeyboardButton("🗑 Пропустить", callback_data=f"nskip:{key}")
    )
    kb.row(InlineKeyboardButton("🔗 Источник", url=link))
    return kb


def news_more_kb():
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton(f"➕ Показать ещё {NEWS_MORE_BATCH}", callback_data="nmore"))
    kb.row(InlineKeyboardButton("🔄 Обновить", callback_data="nrefresh"))
    return kb


# =========================
# NEWS cache per user
# =========================
def get_news_cache(uid: int) -> Optional[Dict]:
    st = user_state.get(uid) or {}
    cache = st.get("news_cache")
    if not cache:
        return None
    if time.time() - cache.get("ts", 0) > NEWS_CACHE_TTL_SEC:
        return None
    return cache


def set_news_cache(uid: int, items: List[Dict]):
    st = user_state.get(uid) or {}
    st["news_cache"] = {"ts": time.time(), "items": items, "pos": 0, "by_key": {}}
    user_state[uid] = st


def item_key(title: str, url: str) -> str:
    return hashlib.sha256(f"{title}|{url}".encode("utf-8")).hexdigest()[:16]


# =========================
# Template selection handler
# =========================
@bot.callback_query_handler(func=lambda c: c.data.startswith("tpl:"))
def on_tpl(c):
    if not is_admin(c):
        bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
        return
    uid = c.from_user.id
    tpl = c.data.split(":", 1)[1]
    st = user_state.get(uid) or {}
    st["template"] = tpl
    if st.get("step") in {"waiting_template", None}:
        st["step"] = "waiting_photo"
    user_state[uid] = st
    bot.answer_callback_query(c.id, "Ок ✅")
    bot.send_message(c.message.chat.id, f"Шаблон выбран: {'МН' if tpl=='MN' else 'ЧП ВМ'}. Пришли фото 📷")


# =========================
# Commands
# =========================
@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")
    st["step"] = "idle"
    user_state[uid] = st

    bot.send_message(message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())
    bot.send_message(
        message.chat.id,
        "Команды:\n"
        "• /post — оформить пост\n"
        "• /news — получить новости за 24 часа\n"
        "• /template — выбрать шаблон (МН / ЧП ВМ)\n",
        reply_markup=main_menu_kb()
    )


@bot.message_handler(commands=["template"])
def cmd_template(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st["step"] = "waiting_template"
    user_state[uid] = st
    bot.send_message(message.chat.id, "Выбери шаблон оформления:", reply_markup=template_kb())


@bot.message_handler(commands=["post"])
def cmd_post(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return
    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")
    st["step"] = "waiting_template"
    user_state[uid] = st
    bot.send_message(message.chat.id, "Выбери шаблон оформления:", reply_markup=template_kb())


@bot.message_handler(commands=["news"])
def cmd_news(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return
    uid = message.from_user.id
    bot.send_message(message.chat.id, "Собираю новости за 24 часа… 🧲", reply_markup=main_menu_kb())
    items = fetch_all_news_last24h()
    set_news_cache(uid, items)
    send_news_batch(message.chat.id, uid, NEWS_FIRST_BATCH)


def send_news_batch(chat_id: int, uid: int, batch: int):
    cache = get_news_cache(uid)
    if not cache:
        bot.send_message(chat_id, "Кэш пуст. Нажми «Получить новости» или /news.", reply_markup=main_menu_kb())
        return

    items = cache["items"]
    pos = int(cache.get("pos", 0))
    if pos >= len(items):
        bot.send_message(chat_id, "Больше новостей нет ✅", reply_markup=main_menu_kb())
        return

    end = min(pos + batch, len(items))
    by_key = cache.get("by_key") or {}

    for it in items[pos:end]:
        title = (it.get("title") or "").strip()
        link = (it.get("url") or "").strip()
        src = (it.get("source") or "").strip()
        if not title or not link:
            continue

        key = item_key(title, link)
        by_key[key] = it

        msg = f"<b>{html.escape(title)}</b>\n\n{html.escape(src)}"
        
        image = it.get("image")
        if not image:
            try:
                page = http_get(link)
                og = extract_og_meta(page)
                image = og.get("image")
            except:
                image = None

        caption = f"<b>{html.escape(title)}</b>

🔗 {link}"

        if image:
            bot.send_photo(chat_id, image, caption=caption, parse_mode="HTML", reply_markup=news_item_kb(key, link))
        else:
            bot.send_message(chat_id, caption, parse_mode="HTML", reply_markup=news_item_kb(key, link))


    cache["pos"] = end
    cache["by_key"] = by_key
    user_state[uid]["news_cache"] = cache

    if end < len(items):
        bot.send_message(chat_id, "Хочешь ещё?", reply_markup=news_more_kb())
    else:
        bot.send_message(chat_id, "Это всё на сейчас ✅", reply_markup=main_menu_kb())


@bot.callback_query_handler(func=lambda c: c.data in {"nmore", "nrefresh"})
def on_news_nav(c):
    if not is_admin(c):
        bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
        return
    uid = c.from_user.id

    if c.data == "nrefresh":
        bot.answer_callback_query(c.id, "Обновляю…")
        items = fetch_all_news_last24h()
        set_news_cache(uid, items)
        send_news_batch(c.message.chat.id, uid, NEWS_FIRST_BATCH)
        return

    bot.answer_callback_query(c.id, "Ок")
    send_news_batch(c.message.chat.id, uid, NEWS_MORE_BATCH)


@bot.callback_query_handler(func=lambda c: c.data.startswith("nfmt:") or c.data.startswith("nskip:"))
def on_news_item_action(c):
    if not is_admin(c):
        bot.answer_callback_query(c.id, "Нет доступа", show_alert=True)
        return

    uid = c.from_user.id
    cache = get_news_cache(uid)
    if not cache:
        bot.answer_callback_query(c.id, "Сначала /news", show_alert=True)
        return

    action, key = c.data.split(":", 1)

    if action == "nskip":
        try:
            bot.edit_message_text("🗑 Пропущено.", c.message.chat.id, c.message.message_id)
        except Exception:
            pass
        bot.answer_callback_query(c.id, "Ок")
        return

    it = (cache.get("by_key") or {}).get(key)
    if not it:
        bot.answer_callback_query(c.id, "Не нашёл новость. Нажми /news ещё раз.", show_alert=True)
        return

    title = (it.get("title") or "").strip()
    link = (it.get("url") or "").strip()
    image_url = (it.get("image") or "").strip()

    photo_bytes = b""
    if image_url:
        try:
            photo_bytes = http_get_bytes(image_url, timeout=25)
        except Exception:
            photo_bytes = b""

    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")
    st["title"] = title
    st["source_url"] = link

    if not photo_bytes:
        st["step"] = "waiting_photo"
        st["prefill_title"] = title
        st["prefill_source"] = link
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Нужно фото")
        bot.send_message(
            c.message.chat.id,
            "Для этой новости не смог взять картинку.\nПришли фото 📷, а заголовок я уже подставлю.",
            reply_markup=main_menu_kb()
        )
        return

    warn_if_too_small(c.message.chat.id, photo_bytes)
    st["photo_bytes"] = photo_bytes

    try:
        card = make_card(photo_bytes, title, st["template"])
        st["card_bytes"] = card.getvalue()
        st["step"] = "waiting_body"
        user_state[uid] = st
        bot.answer_callback_query(c.id, "Ок ✅")
        bot.send_message(c.message.chat.id, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.", reply_markup=main_menu_kb())
    except Exception as e:
        bot.answer_callback_query(c.id, "Ошибка карточки", show_alert=True)
        bot.send_message(c.message.chat.id, f"Ошибка при создании карточки: {e}", reply_markup=main_menu_kb())


# =========================
# Post flow
# =========================
@bot.message_handler(content_types=["photo"])
def on_photo(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return

    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")

    if st.get("step") == "waiting_template":
        bot.send_message(message.chat.id, "Сначала выбери шаблон:", reply_markup=template_kb())
        return

    file_id = message.photo[-1].file_id
    photo_bytes = tg_file_bytes(file_id)
    warn_if_too_small(message.chat.id, photo_bytes)

    st["photo_bytes"] = photo_bytes

    if st.get("prefill_title"):
        st["title"] = st["prefill_title"]
        st["source_url"] = st.get("prefill_source", "") or ""
        try:
            card = make_card(st["photo_bytes"], st["title"], st["template"])
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_body"
            st.pop("prefill_title", None)
            st.pop("prefill_source", None)
            user_state[uid] = st
            bot.reply_to(message, "Фото получено ✅ Заголовок уже есть. Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
        except Exception as e:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            bot.reply_to(message, f"Ошибка при создании карточки: {e}")
        return

    st["step"] = "waiting_title"
    user_state[uid] = st
    bot.reply_to(message, "Фото получено ✅ Теперь отправь ЗАГОЛОВОК.")


@bot.message_handler(content_types=["document"])
def on_document(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return

    uid = message.from_user.id
    st = user_state.get(uid) or {}
    st.setdefault("template", "MN")

    doc = message.document
    if not doc.mime_type or not doc.mime_type.startswith("image/"):
        bot.reply_to(message, "Пришли картинку (JPG/PNG).")
        return

    photo_bytes = tg_file_bytes(doc.file_id)
    warn_if_too_small(message.chat.id, photo_bytes)

    st["photo_bytes"] = photo_bytes
    st["step"] = "waiting_title"
    user_state[uid] = st
    bot.reply_to(message, "Картинка получена ✅ Теперь отправь ЗАГОЛОВОК.")


@bot.message_handler(content_types=["text"])
def on_text(message):
    if not is_admin(message):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return

    uid = message.from_user.id
    text = (message.text or "").strip()
    st = user_state.get(uid) or {"template": "MN", "step": "idle"}

    # GLOBAL MENU HANDLING
    if text == BTN_POST or text.lower() in {"оформить пост", "оформление поста"}:
        cmd_post(message)
        return

    if text == BTN_NEWS or text.lower() in {"получить новости", "новости", "дай новости"}:
        cmd_news(message)
        return

    step = st.get("step")

    if step == "waiting_title":
        st["title"] = text
        try:
            card = make_card(st["photo_bytes"], st["title"], st.get("template", "MN"))
            st["card_bytes"] = card.getvalue()
            st["step"] = "waiting_body"
            user_state[uid] = st
            bot.reply_to(message, "Карточка готова ✅ Теперь пришли ОСНОВНОЙ ТЕКСТ поста.")
        except Exception as e:
            st["step"] = "waiting_photo"
            user_state[uid] = st
            bot.reply_to(message, f"Ошибка при создании карточки: {e}")

    elif step == "waiting_body":
        st["body_raw"] = text
        body_src = extract_source_url(text)
        if body_src:
            st["source_url"] = body_src

        if st.get("source_url"):
            st["step"] = "waiting_action"
            user_state[uid] = st
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
            user_state[uid] = st
            bot.reply_to(message, "Если есть источник, пришли ссылку (или напиши: - чтобы пропустить).")

    elif step == "waiting_source":
        if text == "-" or text.lower() in {"нет", "не", "пропустить"}:
            st["source_url"] = ""
        else:
            st["source_url"] = extract_source_url(text)

        st["step"] = "waiting_action"
        user_state[uid] = st

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
        bot.reply_to(message, "Нажми кнопку под превью ✅✏️❌ (или выбери действие в меню снизу).", reply_markup=main_menu_kb())

    elif step == "waiting_template":
        bot.send_message(message.chat.id, "Выбери шаблон кнопками:", reply_markup=template_kb())

    else:
        user_state[uid] = st
        bot.send_message(message.chat.id, "Выбери действие 👇", reply_markup=main_menu_kb())


@bot.callback_query_handler(func=lambda call: call.data in ["publish", "edit_body", "edit_title", "cancel"])
def on_action(call):
    if not is_admin(call):
        bot.answer_callback_query(call.id, "Нет доступа", show_alert=True)
        return

    uid = call.from_user.id
    st = user_state.get(uid)

    if not st or st.get("step") != "waiting_action":
        bot.answer_callback_query(call.id, "Нет активного превью. Начни с «Оформить пост».")
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
            bot.send_message(call.message.chat.id, "Готово ✅", reply_markup=main_menu_kb())
            tpl = st.get("template", "MN")
            user_state[uid] = {"step": "idle", "template": tpl}
        except Exception as e:
            bot.answer_callback_query(call.id, "Ошибка публикации")
            bot.send_message(call.message.chat.id, f"Не смог опубликовать: {e}", reply_markup=main_menu_kb())

    elif call.data == "edit_body":
        st["step"] = "waiting_body"
        user_state[uid] = st
        bot.answer_callback_query(call.id, "Ок")
        bot.send_message(call.message.chat.id, "Пришли новый ОСНОВНОЙ ТЕКСТ (заголовок на картинке не меняем).", reply_markup=main_menu_kb())

    elif call.data == "edit_title":
        st["step"] = "waiting_title"
        user_state[uid] = st
        bot.answer_callback_query(call.id, "Ок")
        bot.send_message(call.message.chat.id, "Пришли новый ЗАГОЛОВОК (перерисую карточку).", reply_markup=main_menu_kb())

    elif call.data == "cancel":
        bot.answer_callback_query(call.id, "Отменено")
        tpl = st.get("template", "MN")
        user_state[uid] = {"step": "idle", "template": tpl}
        bot.send_message(call.message.chat.id, "Отменил ❌", reply_markup=main_menu_kb())


if __name__ == "__main__":
    ensure_fonts()
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
