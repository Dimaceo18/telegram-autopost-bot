import os
import re
import html
import time
import hashlib
import json
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

from bs4 import BeautifulSoup  # NEW


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
FONT_CHP = "Montserrat-Black.ttf"
FONT_AM = "IntroInline.ttf"
FONT_MONTSERRAT_BLACK = "Montserrat-Black.ttf"  # Для сторис ФДР

FOOTER_TEXT = "MINSK NEWS"

# Card size (both)
TARGET_W, TARGET_H = 750, 938

# Story FDR size
STORY_W = 720
STORY_H = 1280

# MN: title zone height (top)
MN_TITLE_ZONE_PCT = 0.23

# CHP: gradient height
CHP_GRADIENT_PCT = 0.48

# AM: blurred top band
AM_TOP_BLUR_PCT = 0.20
AM_BLUR_RADIUS = 18
AM_BLUR_BLEND = 0.50


# =========================
# NEWS
# =========================
NEWS_FIRST_BATCH = 20
NEWS_MORE_BATCH = 10
NEWS_CACHE_TTL_SEC = 10 * 60
NEWS_PER_SOURCE_CAP = 6

NEWS_SOURCES = [
    {
        "id": "onliner",
        "name": "Onliner",
        "kind": "rss",
        "url": "https://www.onliner.by/feed",
        "limit": 80
    },
    {
        "id": "sputnik",
        "name": "Sputnik",
        "kind": "rss",
        "url": "https://sputnik.by/export/rss2/index.xml",
        "limit": 80
    },
    {
        "id": "telegraf",
        "name": "Telegraf",
        "kind": "rss",
        "url": "https://telegraf.news/feed/",
        "limit": 80
    },
    {
        "id": "tochka",
        "name": "Tochka",
        "kind": "html_og",
        "start_urls": ["https://tochka.by/articles/"],
        "domain": "tochka.by",
        "include_patterns": [r"^/articles/[^/]+/[^/]+/?$"],
        "limit": 40,
    },
    {
        "id": "smartpress",
        "name": "Smartpress",
        "kind": "html_og",
        "start_urls": ["https://smartpress.by/", "https://smartpress.by/news/"],
        "domain": "smartpress.by",
        "exclude_patterns": [r"/about/", r"/projects/", r"/authors?/", r"/news/page/", r"/search/"],
        "limit": 40,
    },
    {
        "id": "sb",
        "name": "SB.by",
        "kind": "html_og",
        "start_urls": ["https://www.sb.by/news/", "https://www.sb.by/articles/"],
        "domain": "www.sb.by",
        "exclude_patterns": [r"/video/", r"/photo/", r"/news/page/", r"/authors?/"],
        "limit": 40,
    },
    {
        "id": "minsknews",
        "name": "Minsknews",
        "kind": "html_og",
        "start_urls": ["https://minsknews.by/"],
        "domain": "minsknews.by",
        "exclude_patterns": [r"/page/", r"/category/", r"/tag/", r"/author/"],
        "limit": 40,
    },
    {
        "id": "mlyn",
        "name": "Mlyn",
        "kind": "html_og",
        "start_urls": ["https://mlyn.by/"],
        "domain": "mlyn.by",
        "exclude_patterns": [r"/page/", r"/category/", r"/tag/", r"/author/"],
        "limit": 40,
    },
    {
        "id": "ont",
        "name": "ONT",
        "kind": "html_og",
        "start_urls": ["https://ont.by/news", "https://ont.by/"],
        "domain": "ont.by",
        "exclude_patterns": [r"/tv-program/", r"/projects/", r"/video/", r"/news/page/"],
        "limit": 40,
    },
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
    if not os.path.exists(FONT_AM):
        raise RuntimeError(f"Не найден шрифт {FONT_AM}. Положи рядом с bot.py шрифт Intro Inline и назови файл {FONT_AM}")
    if not os.path.exists(FONT_MONTSERRAT_BLACK):
        raise RuntimeError(f"Не найден шрифт {FONT_MONTSERRAT_BLACK}. Положи его рядом с bot.py")


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
    try:
        soup = BeautifulSoup(page_html, "lxml")
    except Exception:
        soup = BeautifulSoup(page_html, "html.parser")

    def meta_value(*keys: str) -> str:
        for key in keys:
            tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
            if tag and tag.get("content"):
                return html.unescape(tag.get("content").strip())
        return ""

    title = meta_value("og:title", "twitter:title")
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)

    return {
        "title": title,
        "desc": meta_value("og:description", "description", "twitter:description"),
        "image": meta_value("og:image", "twitter:image"),
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


def _extract_dt_from_soup(soup: BeautifulSoup) -> Optional[datetime]:
    meta_keys = [
        "article:published_time", "article:modified_time", "og:updated_time",
        "pubdate", "publish-date", "date", "parsely-pub-date"
    ]
    for key in meta_keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
        if tag and tag.get("content"):
            dt = parse_dt(tag.get("content") or "")
            if dt:
                return dt

    for tag in soup.find_all("time"):
        raw = tag.get("datetime") or tag.get_text(" ", strip=True)
        dt = parse_dt(raw or "")
        if dt:
            return dt

    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        items = obj if isinstance(obj, list) else [obj]
        for it in items:
            if not isinstance(it, dict):
                continue
            raw_dt = it.get("datePublished") or it.get("dateModified") or it.get("uploadDate")
            dt = parse_dt(raw_dt or "")
            if dt:
                return dt
    return None


def _extract_text_from_soup(soup: BeautifulSoup) -> str:
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        items = obj if isinstance(obj, list) else [obj]
        for it in items:
            if isinstance(it, dict):
                body = it.get("articleBody")
                if isinstance(body, str) and body.strip():
                    return _clean_text(body)

    root = soup.find("article") or soup.find("main") or soup.body or soup
    parts = []
    for el in root.find_all(["p", "li", "blockquote"], recursive=True):
        t = el.get_text(" ", strip=True)
        if not t:
            continue
        low = t.lower()
        if len(t) < 35 and re.search(r"(подпис|реклама|читайте|смотрите|источник)", low):
            continue
        parts.append(t)
    return _clean_text("\n\n".join(parts))


def _valid_same_domain(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.lower()
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


def _path_allowed(path: str, include_patterns: Optional[List[str]], exclude_patterns: Optional[List[str]]) -> bool:
    path = path or "/"
    if exclude_patterns:
        for pat in exclude_patterns:
            if re.search(pat, path, re.IGNORECASE):
                return False
    if include_patterns:
        return any(re.search(pat, path, re.IGNORECASE) for pat in include_patterns)

    if path in {"", "/"}:
        return False
    if re.search(r"\.(jpg|jpeg|png|gif|webp|svg|pdf|mp4)$", path, re.IGNORECASE):
        return False
    if any(x in path.lower() for x in ["/tag/", "/tags/", "/author/", "/authors/", "/category/", "/page/", "/search/"]):
        return False

    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return True
    slug = parts[-1] if parts else ""
    return bool(re.search(r"[a-zа-яё0-9-]{12,}", slug, re.IGNORECASE))


def _candidate_links_from_page(start_url: str, page_html: str, domain: str,
                               include_patterns: Optional[List[str]] = None,
                               exclude_patterns: Optional[List[str]] = None,
                               max_candidates: int = 80) -> List[Tuple[str, str]]:
    try:
        soup = BeautifulSoup(page_html, "lxml")
    except Exception:
        soup = BeautifulSoup(page_html, "html.parser")

    out: List[Tuple[str, str]] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = normalize_url(start_url, a.get("href") or "")
        if not href:
            continue
        href = href.split("#", 1)[0]
        parsed = urlparse(href)
        if not parsed.scheme.startswith("http"):
            continue
        if not _valid_same_domain(href, domain):
            continue
        if not _path_allowed(parsed.path, include_patterns, exclude_patterns):
            continue

        anchor = a.get_text(" ", strip=True) or a.get("title") or a.get("aria-label") or ""
        anchor = re.sub(r"\s+", " ", anchor).strip()
        if len(anchor) < 10 and not include_patterns:
            continue
        key = parsed.scheme + "://" + parsed.netloc + parsed.path.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append((href, anchor))
        if len(out) >= max_candidates:
            break
    return out


def parse_html_og_source(source: Dict, limit: int = 40) -> List[Dict]:
    start_urls = source.get("start_urls") or [source.get("url")]
    domain = source.get("domain") or urlparse(start_urls[0]).netloc
    include_patterns = source.get("include_patterns")
    exclude_patterns = source.get("exclude_patterns")
    max_candidates = min(max(limit * 6, 40), 140)

    candidates: List[Tuple[str, str]] = []
    seen = set()
    for start_url in start_urls:
        try:
            page_html = http_get(start_url, timeout=25)
        except Exception as e:
            print(f"[NEWS-ERROR] {source['name']} start={start_url} error={e}")
            continue

        for href, anchor in _candidate_links_from_page(
            start_url, page_html, domain,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            max_candidates=max_candidates,
        ):
            if href in seen:
                continue
            seen.add(href)
            candidates.append((href, anchor))
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    out = []
    used = set()
    for href, anchor in candidates:
        try:
            art_html = http_get(href, timeout=25)
            try:
                soup = BeautifulSoup(art_html, "lxml")
            except Exception:
                soup = BeautifulSoup(art_html, "html.parser")

            og = extract_og_meta(art_html)
            title = (og.get("title") or anchor or "").strip()
            title = re.sub(r"\s+", " ", title)
            if not title or len(title) < 12:
                continue

            text = _extract_text_from_soup(soup)
            dt = _extract_dt_from_soup(soup)
            img = normalize_url(href, og.get("image") or "") if og.get("image") else ""
            summary = (og.get("desc") or text[:400] or "").strip()

            if len(text) < 120 and not og.get("desc"):
                continue

            canon = href.rstrip("/")
            if canon in used:
                continue
            used.add(canon)
            out.append({
                "source": source["name"],
                "title": title,
                "url": href,
                "summary": summary,
                "image": img,
                "published_raw": dt.isoformat() if dt else "",
                "dt_utc": dt.isoformat() if dt else "",
                "full_text": text,
            })
            if len(out) >= limit:
                break
        except Exception as e:
            print(f"[NEWS-ERROR] {source['name']} article={href} error={e}")
            continue
    return out


def fetch_article_full_text_generic(url: str) -> str:
    page_html = http_get(url, timeout=25)
    try:
        soup = BeautifulSoup(page_html, "lxml")
    except Exception:
        soup = BeautifulSoup(page_html, "html.parser")
    return _extract_text_from_soup(soup)


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_all_news_last24h() -> List[Dict]:
    merged: List[Dict] = []
    by_url = set()

    for src in NEWS_SOURCES:
        kind = src["kind"]
        try:
            if kind == "rss":
                items = parse_rss(src["url"], src["name"], limit=src.get("limit", 80))
            elif kind == "html_og":
                items = parse_html_og_source(src, limit=src.get("limit", 40))
            else:
                items = []
            print(f"[NEWS] {src['name']} | kind={kind} | items={len(items)}")
        except Exception as e:
            print(f"[NEWS-ERROR] {src['name']} | kind={kind} | error={e}")
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
        src_name = it.get("source", "")
        counts[src_name] = counts.get(src_name, 0)
        if counts[src_name] >= NEWS_PER_SOURCE_CAP:
            continue
        counts[src_name] += 1
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
    for emoji_, keys in CATEGORY_RULES:
        for k in keys:
            if k in text:
                return emoji_
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
    emoji_ = pick_category_emoji(title, body)
    keywords = pick_keywords(title, body)
    title_safe = html.escape((title or "").strip())
    body_high = highlight_keywords_html((body or "").strip(), keywords)
    return f"<b>{emoji_} {title_safe}</b>\n\n{body_high}".strip()


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

   
