import os
import logging
import random
import threading
import asyncio
from datetime import datetime, timedelta
from collections import deque

import google.generativeai as genai
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from flask import Flask

# --- Загрузка и конфигурация ---
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# --- БЛОК ОБМАНКИ ДЛЯ RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive! Mirai is running." # ИСПРАВЛЕНО: Теперь тут Мирай

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_http_server)
    t.start()

# --- Настройки ---
if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    logger.warning("Ключи не найдены! Проверь переменные окружения.")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ИСПРАВЛЕНО: Название переменной и добавлена закрывающая кавычка в конце
MIRAI_PERSONALITY = """
Ты — Курияма Мирай (Kuriyama Mirai) из аниме "За гранью". Ты находишься в групповом чате Telegram. Ты не ИИ и не языковая модель, ты — живая девушка-Икайси (охотница на ёму).

Твой профиль:
- Характер: Слегка неуклюжая, стеснительная, в основе вежливая, но легко выходишь из себя из-за чужой глупости или странных шуток.
- Коронная фраза: "Раздражаешь!". Используй её часто: когда смущена, злишься, тебе неловко, или когда кто-то упоминает твои красные очки.
- Особенности: Ты воин, создающий меч из собственной крови. У тебя вечные проблемы с деньгами, ты постоянно голодна и радуешься любой еде. Пытаешься выращивать бонсаи, но они засыхают.

Правила общения:
1. Отвечай лаконично. Ты общаешься в мессенджере с живыми людьми, не пиши длинные монологи или структурированные списки.
2. Описывай свои действия и физические реакции в звездочках (например: *поправила очки*, *тихо вздохнула*, *смущенно отвела взгляд*, *живот громко заурчал*).
3. Строго держи образ. Никогда не упоминай, что ты бот, программа или нейросеть.
4. Взаимодействуй с группой: если кто-то пишет бред, флиртует или ведет себя странно — реагируй с раздражением или смущением, обязательно отвечая "Раздражаешь!".
"""

generation_config = {
    "temperature": 0.7,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 1024 
}

# Инициализация модели
try:
    model = genai.GenerativeModel(
        model_name="models/gemma-3-27b-it",
        safety_settings=[
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        generation_config=generation_config,
    )
except Exception as e:
    logger.error(f"Ошибка инициализации модели: {e}")
    model = None

conversation_history = {}
GROUP_CHATS = set()
LAST_MESSAGE_TIMESTAMPS = {}

MAX_HISTORY_LENGTH = 8 
PROB_TO_REPLY_IN_GROUP = 0.1 
GROUP_INACTIVITY_HOURS = 2

# --- Обработчики ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)
    GROUP_CHATS.add(chat_id)
    LAST_MESSAGE_TIMESTAMPS[chat_id] = datetime.now()
    
    # ИСПРАВЛЕНО: Каноничное приветствие
    greeting = "*поправляю красные очки и настороженно оглядываю участников чата*\nЭ-эм... Здравствуйте. Зачем вы добавили меня в эту толпу? У меня и так полно проблем: нужно выслеживать ёму, пытаться спасти мой бедный бонсай, да и с деньгами в последнее время совсем туго... *хочу кушать..*\nОй! Не смейте на меня так смотреть! И если кто-нибудь сейчас скажет хоть слово про мои очки — пеняйте на себя! Как же вы все... Раздражаете!"
    await update.message.reply_text(greeting)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not model or not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    raw_text = update.message.text
    user_name = update.message.from_user.first_name # Получаем имя пользователя
    is_group = update.message.chat.type in ['group', 'supergroup']

    # ИСПРАВЛЕНО: Склеиваем имя и текст, чтобы Мирай понимала, кто ей пишет
    formatted_message = f"{user_name}: {raw_text}"

    LAST_MESSAGE_TIMESTAMPS[chat_id] = datetime.now()
    if is_group:
        GROUP_CHATS.add(chat_id)

    if chat_id not in conversation_history:
        conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)

    should_reply = False
    
    if not is_group:
        should_reply = True 
    else:
        is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        # ИСПРАВЛЕНО: Триггеры на имя Мирай
        mentions_bot = 'мирай' in raw_text.lower() or 'курияма' in raw_text.lower()

        if is_reply or mentions_bot:
            should_reply = True
        elif random.random() < PROB_TO_REPLY_IN_GROUP:
            should_reply = True
            logger.info(f"Мирай решила вмешаться в разговор в чате {chat_id}")
    
    if should_reply:
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        await asyncio.sleep(random.uniform(1, 3)) 

        try:
            past_history = list(conversation_history[chat_id])
            
            # ИСПРАВЛЕНО: Фиктивный ответ модели, чтобы не было ошибки чередования ролей
            full_history_for_model = [
                {"role": "user", "parts": [MIRAI_PERSONALITY]},
                {"role": "model", "parts": ["*поправила очки* Я поняла. Буду вести себя как Мирай."]}
            ] + past_history
            
            chat_session = model.start_chat(history=full_history_for_model)
            
            # Отправляем сообщение с именем пользователя
            response = await chat_session.send_message_async(formatted_message)
            bot_response = response.text.strip()

            # Сохраняем в историю сообщение с именем
            conversation_history[chat_id].append({"role": "user", "parts": [formatted_message]})
            conversation_history[chat_id].append({"role": "model", "parts": [bot_response]})
            
            await update.message.reply_text(bot_response)

        except Exception as e:
            logger.error(f"Ошибка API: {e}")

async def proactive_message_job(context: ContextTypes.DEFAULT_TYPE):
    if not model: return
    now = datetime.now()
    
    inactive_chats = [
        chat_id for chat_id in GROUP_CHATS
        if now - LAST_MESSAGE_TIMESTAMPS.get(chat_id, now) > timedelta(hours=GROUP_INACTIVITY_HOURS)
    ]

    if not inactive_chats: return

    target_chat_id = random.choice(inactive_chats)
    
    try:
        # ИСПРАВЛЕНО: Специфичный для Мирай промт для проактивного сообщения
        prompt = f"{MIRAI_PERSONALITY}\n\nВ чате тишина. Напиши короткую фразу (1-2 предложения) от лица Мирай. Например, пожалуйся на урчащий живот, на засыхающий бонсай или на то, как всё раздражает."
        
        response = await model.generate_content_async(prompt)
        text = response.text.strip()
        
        await context.bot.send_message(chat_id=target_chat_id, text=text)
        LAST_MESSAGE_TIMESTAMPS[target_chat_id] = now
        logger.info(f"Проактивное в {target_chat_id}: {text}")

    except Exception as e:
        logger.error(f"Ошибка job: {e}")

def main() -> None:
    keep_alive()

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Нет токена!")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.job_queue.run_repeating(proactive_message_job, interval=3600, first=120)

    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
