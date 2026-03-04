import telebot
import os

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL = os.getenv("CHANNEL_USERNAME")

bot = telebot.TeleBot(TOKEN)

last_photo = None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    global last_photo
    last_photo = message.photo[-1].file_id
    bot.reply_to(message, "Фото получено. Теперь отправьте текст.")

@bot.message_handler(content_types=['text'])
def handle_text(message):
    global last_photo
    
    if last_photo:
        bot.send_photo(CHANNEL, last_photo, caption=message.text)
        bot.reply_to(message, "Новость опубликована.")
        last_photo = None
    else:
        bot.reply_to(message, "Сначала отправьте фото.")

bot.infinity_polling()
