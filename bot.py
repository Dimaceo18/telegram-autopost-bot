import os
import telebot
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import requests
from io import BytesIO
import textwrap

TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
CHANNEL = (os.getenv("CHANNEL_USERNAME") or "").strip()

bot = telebot.TeleBot(TOKEN)

pending_photo = {}

FONT_PATH = "CaviarDreams.ttf"

def make_card(photo_bytes, text):
    img = Image.open(BytesIO(photo_bytes)).convert("RGB")

    # формат 5:4
    w, h = img.size
    target_ratio = 5/4
    current_ratio = w / h

    if current_ratio > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        img = img.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))

    # затемнение
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.55)

    draw = ImageDraw.Draw(img)

    font_big = ImageFont.truetype(FONT_PATH, 90)
    font_small = ImageFont.truetype(FONT_PATH, 40)

    margin = 80

    wrapped = textwrap.fill(text.upper(), width=22)

    draw.multiline_text(
        (margin, margin),
        wrapped,
        font=font_big,
        fill="white",
        spacing=20
    )

    draw.text(
        (img.width/2 - 120, img.height - 80),
        "MINSK NEWS",
        font=font_small,
        fill="white"
    )

    output = BytesIO()
    img.save(output, format="JPEG", quality=95)
    output.seek(0)
    return output


@bot.message_handler(content_types=["photo"])
def photo(message):
    file_id = message.photo[-1].file_id
    pending_photo[message.from_user.id] = file_id
    bot.reply_to(message, "Фото получено. Теперь отправь текст.")


@bot.message_handler(content_types=["text"])
def text(message):
    user = message.from_user.id

    if user not in pending_photo:
        bot.reply_to(message, "Сначала отправь фото.")
        return

    file_id = pending_photo.pop(user)

    file_info = bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

    photo_bytes = requests.get(file_url).content

    card = make_card(photo_bytes, message.text)

    bot.send_photo(CHANNEL, card)
    bot.reply_to(message, "Карточка опубликована ✅")


bot.infinity_polling()
