import os
import re
import html
import requests
from io import BytesIO

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter


TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = os.getenv("CHANNEL_USERNAME")
BOT_USERNAME = os.getenv("BOT_USERNAME")

FONT_PATH = "CaviarDreams.ttf"
FOOTER_TEXT = "MINSK NEWS"

SUGGEST_URL = f"https://t.me/{BOT_USERNAME}?start=suggest"

bot = telebot.TeleBot(TOKEN)

user_state = {}

URL_RE = re.compile(r"(https?://[^\s]+)", re.IGNORECASE)


# ---------- KEYWORDS ----------
STOP_WORDS = {
"и","в","на","но","а","что","это","как","к","по","из","за","для","с","у","от","до"
}


# ---------- CATEGORY ----------
CATEGORY_RULES = [
("🚨",["дтп","авар","чп","пожар"]),
("✈️",["белавиа","рейс","самолет","самолёт"]),
("💳",["банк","tax","global","карта"]),
("🎫",["концерт","афиша","выставк"]),
]


def pick_category_emoji(title,body):
    text=(title+" "+body).lower()

    for emoji,keys in CATEGORY_RULES:
        for k in keys:
            if k in text:
                return emoji

    return "📰"


# ---------- DOWNLOAD PHOTO ----------
def tg_file_bytes(file_id):

    file_info=bot.get_file(file_id)

    url=f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"

    r=requests.get(url)

    return r.content


# ---------- WRAP TEXT ----------
def wrap_text(draw,text,font,max_width):

    words=text.split()

    lines=[]

    line=""

    for w in words:

        test=(line+" "+w).strip()

        box=draw.textbbox((0,0),test,font=font)

        if box[2]<=max_width:

            line=test

        else:

            lines.append(line)

            line=w

    if line:

        lines.append(line)

    return lines


# ---------- CARD GENERATOR ----------
def make_card(photo_bytes,title):

    img=Image.open(BytesIO(photo_bytes)).convert("RGB")

    w,h=img.size

    ratio=4/5

    cur=w/h

    if cur>ratio:

        new_w=int(h*ratio)

        left=(w-new_w)//2

        img=img.crop((left,0,left+new_w,h))

    else:

        new_h=int(w/ratio)

        top=(h-new_h)//2

        img=img.crop((0,top,w,top+new_h))


    # уменьшенная карточка
    TARGET_W=720
    TARGET_H=900

    img=img.resize((TARGET_W,TARGET_H),Image.Resampling.LANCZOS)

    img=img.filter(ImageFilter.UnsharpMask(radius=2,percent=180,threshold=2))

    img=ImageEnhance.Brightness(img).enhance(0.55)

    draw=ImageDraw.Draw(img)

    margin_x=int(img.width*0.06)

    margin_top=int(img.height*0.06)

    margin_bottom=int(img.height*0.10)

    safe_w=img.width-2*margin_x

    title_zone=int(img.height*0.23)

    font_size=int(img.height*0.11)

    font=ImageFont.truetype(FONT_PATH,font_size)

    text=title.upper()

    lines=wrap_text(draw,text,font,safe_w)

    spacing=int(font_size*0.22)

    y=margin_top

    for line in lines:

        draw.text((margin_x,y),line,font=font,fill="white")

        y+=font_size+spacing


    footer_font=ImageFont.truetype(FONT_PATH,28)

    box=draw.textbbox((0,0),FOOTER_TEXT,font=footer_font)

    fw=box[2]

    fy=img.height-margin_bottom

    draw.text(((img.width-fw)//2,fy),FOOTER_TEXT,font=footer_font,fill="white")

    out=BytesIO()

    img.save(out,"JPEG",quality=95,subsampling=0)

    out.seek(0)

    return out


# ---------- CAPTION ----------
def build_caption(title,body):

    emoji=pick_category_emoji(title,body)

    title_html=html.escape(title)

    body_html=html.escape(body)

    return f"<b>{emoji} {title_html}</b>\n\n{body_html}"


# ---------- KEYBOARD ----------
def preview_kb():

    kb=InlineKeyboardMarkup()

    kb.row(

        InlineKeyboardButton("✅ Опубликовать",callback_data="publish"),

        InlineKeyboardButton("✏️ Изменить текст",callback_data="edit")

    )

    kb.row(

        InlineKeyboardButton("❌ Отмена",callback_data="cancel")

    )

    return kb


def channel_kb():

    kb=InlineKeyboardMarkup()

    kb.row(

        InlineKeyboardButton("Предложить новость",url=SUGGEST_URL)

    )

    return kb


# ---------- START ----------
@bot.message_handler(commands=["start"])

def start(msg):

    user_state[msg.from_user.id]={"step":"photo"}

    bot.send_message(msg.chat.id,"Пришли фото")


# ---------- PHOTO ----------
@bot.message_handler(content_types=["photo"])

def photo(msg):

    uid=msg.from_user.id

    file_id=msg.photo[-1].file_id

    photo_bytes=tg_file_bytes(file_id)

    user_state[uid]={

        "step":"title",

        "photo":photo_bytes

    }

    bot.send_message(msg.chat.id,"Теперь пришли заголовок")


# ---------- TEXT ----------
@bot.message_handler(content_types=["text"])

def text(msg):

    uid=msg.from_user.id

    state=user_state.get(uid)

    if not state:

        bot.send_message(msg.chat.id,"Сначала фото")

        return

    step=state["step"]

    if step=="title":

        state["title"]=msg.text

        card=make_card(state["photo"],msg.text)

        state["card"]=card.getvalue()

        state["step"]="body"

        bot.send_message(msg.chat.id,"Теперь пришли основной текст")

    elif step=="body":

        state["body"]=msg.text

        caption=build_caption(state["title"],state["body"])

        state["step"]="preview"

        bot.send_photo(

            msg.chat.id,

            BytesIO(state["card"]),

            caption=caption,

            parse_mode="HTML",

            reply_markup=preview_kb()

        )


# ---------- CALLBACK ----------
@bot.callback_query_handler(func=lambda call:True)

def callback(call):

    uid=call.from_user.id

    state=user_state.get(uid)

    if not state:

        return

    if call.data=="publish":

        caption=build_caption(state["title"],state["body"])

        bot.send_photo(

            CHANNEL,

            BytesIO(state["card"]),

            caption=caption,

            parse_mode="HTML",

            reply_markup=channel_kb()

        )

        bot.send_message(call.message.chat.id,"Опубликовано")

        user_state[uid]={"step":"photo"}

    elif call.data=="cancel":

        bot.send_message(call.message.chat.id,"Отменено")

        user_state[uid]={"step":"photo"}

    elif call.data=="edit":

        state["step"]="body"

        bot.send_message(call.message.chat.id,"Пришли новый текст")


bot.infinity_polling()
