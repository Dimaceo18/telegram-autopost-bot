# tochka_source.py
from __future__ import annotations

import time
from typing import List

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from tochka_parser import parse_list, fetch_article_full, ArticlePreview

router = Router()

# Простой кэш, чтобы не дергать сайт каждую секунду
_CACHE_TTL = 120  # секунд
_cache_ts = 0
_cache_items: List[ArticlePreview] = []


def _get_cached_list(limit: int = 10) -> List[ArticlePreview]:
    global _cache_ts, _cache_items
    now = time.time()
    if now - _cache_ts > _CACHE_TTL or not _cache_items:
        _cache_items = parse_list(max_items=max(20, limit))
        _cache_ts = now
    return _cache_items[:limit]


def _split_telegram(text: str, chunk: int = 3900) -> List[str]:
    text = text.strip()
    if len(text) <= chunk:
        return [text]
    parts = []
    while text:
        parts.append(text[:chunk])
        text = text[chunk:]
    return parts


@router.message(F.text.in_({"/tochka", "🟦 Tochka"}))
async def tochka_list(message: Message):
    items = _get_cached_list(limit=8)

    if not items:
        await message.answer("Не удалось получить новости с Tochka.by сейчас 😕 Попробуй чуть позже.")
        return

    for it in items:
        kb = InlineKeyboardBuilder()
        kb.button(text="📰 Оформить", callback_data=f"tochka_full|{it.url}")
        kb.button(text="🔗 Источник", url=it.url)
        kb.adjust(2)

        caption = f"<b>{it.title}</b>\n\n{it.url}"
        if it.image:
            await message.answer_photo(photo=it.image, caption=caption, parse_mode="HTML", reply_markup=kb.as_markup())
        else:
            await message.answer(caption, parse_mode="HTML", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("tochka_full|"))
async def tochka_full(cb: CallbackQuery):
    url = cb.data.split("|", 1)[1]

    try:
        art = fetch_article_full(url)
    except Exception:
        await cb.answer("Не получилось открыть статью 😕", show_alert=True)
        return

    header = f"<b>{art.title}</b>\n"
    body = art.text.strip()
    footer = f"\n\n🔗 Источник: {art.url}"

    full_text = (header + "\n" + body + footer).strip()

    # Телега режет длинные сообщения: отправим частями, но первая часть может быть с картинкой
    chunks = _split_telegram(full_text)

    if art.image:
        await cb.message.answer_photo(photo=art.image, caption=chunks[0], parse_mode="HTML")
        for part in chunks[1:]:
            await cb.message.answer(part, parse_mode="HTML")
    else:
        for part in chunks:
            await cb.message.answer(part, parse_mode="HTML")

    await cb.answer("Готово ✅")
