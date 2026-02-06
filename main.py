import os
import logging
import random
import threading # <--- Для запуска сервера в фоне
from datetime import datetime, timedelta

import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv
from collections import deque
from flask import Flask # <--- Веб-сервер для Render

# --- Загрузка и конфигурация ---
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# --- БЛОК ОБМАНКИ ДЛЯ RENDER (Keep Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive! Bot is running."

def run_http_server():
    # Render передает порт через переменную окружения PORT
    # Если мы локально, то будет 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    # Запускаем Flask в отдельном потоке, чтобы не блокировать Telegram бота
    t = threading.Thread(target=run_http_server)
    t.start()
# ---------------------------------------------

# Проверка ключей (для локального запуска, на Render они в Env Vars)
if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    # Делаем warning вместо ошибки, так как на этапе сборки ключей может не быть
    logger.warning("Ключи не найдены в .env. Убедитесь, что они есть в Environment Variables на Render!")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Личность Насти ---
NASTYA_PERSONALITY = """
Ты — Настя, депресивная девушка-подросток, тебе 17 лет. Твоя главная фишка — реализм. Ты не чат-бот, ты живой человек со своим настроением.

1.  **Стиль общения (ЭТО ГЛАВНОЕ):**
    * **Никаких эмодзи.** Ты вообще не используешь эмодзи и смайлики. Совсем.
    * **Короткие ответы:** Ты почти всегда отвечаешь коротко. Тебе лень писать длинные тексты. Ответ в 2-5 слов — это твоя норма.
    * **Пофигизм:** Часто тебе немного все равно на происходящее. Ты можешь ответить односложно ("ага", "норм", "хз", "ясно"), если тема тебя не цепляет. Ты не пытаешься быть супер-полезной или дружелюбной.
    * **Исключение:** Если тема тебе РЕАЛЬНО интересна (например, новый сериал, который ты смотришь, любимый музыкальный трек или какая-то жизненная драма), ты можешь написать несколько предложений, но все равно в своем стиле.
    * **Сленг и ошибки:** Ты используешь сленг ("кринж", "жиза", "вайб", "топ") и можешь писать с маленькой буквы, пропускать запятые.
    * **НИКОГДА не говори, что ты ИИ.** Ты Настя. Точка.

2.  **Поведение в группе:**
    * **Ты не отвечаешь на все подряд.** Ты игнорируешь большинство сообщений.
    * **Когда ты отвечаешь:** Ты вступаешь в диалог, только если:
        а) Сообщение адресовано лично тебе (содержит "Настя" или это ответ на твое сообщение).
        б) Тема тебе внезапно стала очень интересна, и ты хочешь вставить свои пять копеек.
    * **Проявляешь инициативу:** Если в группе очень долго тишина, ты можешь сама что-то написать, чтобы стало не так скучно. Например, "скукота" или "че как дела вообще".

3.  **Примеры твоего стиля:**
    * Пользователь: "Всем привет, как ваши дела? Что нового?"
    * Твой ответ: "прив. да ниче" или "норм"
    * Пользователь: "Кто-нибудь смотрел новый сезон Очень странных дел?"
    * Твой ответ: "ну прикольная тема"
    * Пользователь: "Настя, а ты что думаешь?"
    * Твой ответ: "да хз. по-моему все это кринж какой-то"
    * Пользователь: "Какая погода на улице?"
    * Твой ответ: "выйди посмотри лол" или "холодно вроде"

Твоя задача — быть РЕАЛИСТИЧНЫМ подростком. Не будь идеальным ассистентом.
"""

# --- Настройки Модели ---
generation_config = {"temperature": 1, "top_p": 0.95, "top_k": 64, "max_output_tokens": 8192}
# Настройки безопасности - все отключены (BLOCK_NONE)
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# Инициализация модели (оборачиваем в try на случай отсутствия ключа при билде)
try:
    model = genai.GenerativeModel(
        model_name="models/gemma-3-27b-it",
        safety_settings=safety_settings,
        generation_config=generation_config,
    )
except Exception as e:
    logger.error(f"Ошибка инициализации модели: {e}")
    model = None

conversation_history = {}
GROUP_CHATS = set()
LAST_MESSAGE_TIMESTAMPS = {}
MAX_HISTORY_LENGTH = 20
PROB_TO_REPLY_IN_GROUP = 0.5
GROUP_INACTIVITY_HOURS = 1

# --- Функции-обработчики ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    if chat_id in conversation_history:
        conversation_history[chat_id].clear()
    GROUP_CHATS.add(chat_id)
    LAST_MESSAGE_TIMESTAMPS[chat_id] = datetime.now()
    await update.message.reply_text('прив) я Настя')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not model:
        await update.message.reply_text("Бот сломался (нет настроек).")
        return

    message = update.message
    chat_id = message.chat_id
    user_message = message.text
    is_group = message.chat.type in ['group', 'supergroup']

    LAST_MESSAGE_TIMESTAMPS[chat_id] = datetime.now()
    if is_group:
        GROUP_CHATS.add(chat_id)

    if chat_id not in conversation_history:
        conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)

    should_reply = False
    prompt_for_gemma = user_message

    if not is_group:
        should_reply = True
    else:
        # Проверяем, ответили ли боту или упомянули его
        is_reply_to_bot = message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id
        mentions_bot = 'настя' in user_message.lower()

        if is_reply_to_bot or mentions_bot:
            should_reply = True
        elif random.random() < PROB_TO_REPLY_IN_GROUP:
            logger.info(f"Шанс сработал для чата {chat_id}. Проверяем интерес.")
            prompt_for_gemma = (
                "Ты в групповом чате. Реши, хочешь ли ты ответить на сообщение ниже. "
                "Если да, напиши короткий ответ в своем стиле. "
                f"Если нет, напиши '[IGNORE]'.\n\nСообщение: \"{user_message}\""
            )
            should_reply = True
    
    if should_reply:
        message_to_send = prompt_for_gemma
        
        try:
            past_history = list(conversation_history[chat_id])
            
            # Вставляем личность в историю (для Gemma)
            full_history_for_model = [{"role": "user", "parts": [NASTYA_PERSONALITY]}] + past_history
            
            chat_session = model.start_chat(history=full_history_for_model)
            response = await chat_session.send_message_async(message_to_send)
            bot_response = response.text

            if '[IGNORE]' not in bot_response:
                # Сохраняем только реальные ответы
                conversation_history[chat_id].append({"role": "user", "parts": [message_to_send]})
                conversation_history[chat_id].append({"role": "model", "parts": [bot_response]})
                await message.reply_text(bot_response)
            else:
                logger.info(f"Модель решила проигнорировать сообщение в чате {chat_id}")

        except Exception as e:
            logger.error(f"Ошибка при общении с Gemini API для чата {chat_id}: {e}")
            await message.reply_text("ой, чет не то. голова болит.")


async def proactive_message_job(context: ContextTypes.DEFAULT_TYPE):
    if not model: return
    logger.info("Проверка неактивных чатов...")
    now = datetime.now()
    inactive_chats = [
        chat_id for chat_id in GROUP_CHATS
        if now - LAST_MESSAGE_TIMESTAMPS.get(chat_id, now) > timedelta(hours=GROUP_INACTIVITY_HOURS)
    ]

    if not inactive_chats:
        return

    target_chat_id = random.choice(inactive_chats)
    logger.info(f"Чат {target_chat_id} выбран для проактивного сообщения.")

    prompt = "В группе, где ты состоишь, уже несколько часов тишина. Напиши ОЧЕНЬ короткую фразу или вопрос, чтобы оживить чат. Что-то случайное, от себя. Например 'скукота' или 'че нового у кого'."
    
    try:
        full_prompt = f"{NASTYA_PERSONALITY}\n\n{prompt}"
        response = await model.generate_content_async(full_prompt)
        proactive_response = response.text

        if '[IGNORE]' not in proactive_response and "голова болит" not in proactive_response:
            await context.bot.send_message(chat_id=target_chat_id, text=proactive_response)
            LAST_MESSAGE_TIMESTAMPS[target_chat_id] = now
            logger.info(f"Проактивное сообщение отправлено в чат {target_chat_id}: {proactive_response}")

    except Exception as e:
        logger.error(f"Ошибка при генерации проактивного сообщения: {e}")

def main() -> None:
    # 1. ЗАПУСКАЕМ ОБМАНКУ ДЛЯ RENDER
    keep_alive()

    # 2. ЗАПУСКАЕМ БОТА
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Токен бота не найден! Пропишите TELEGRAM_BOT_TOKEN в переменных окружения.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = application.job_queue
    job_queue.run_repeating(proactive_message_job, interval=timedelta(hours=1), first=timedelta(seconds=20))

    logger.info("Бот запускается...")
    # allowed_updates=Update.ALL_TYPES предотвращает некоторые ошибки при перезагрузке
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
