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
    return "BOMZH VALERA: ONLINE. Waiting for donations."

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_http_server)
    t.start()

# --- Настройки ---
if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    logger.warning("АЛЛО, ГДЕ КЛЮЧИ? БЕЗ НИХ НЕ РАБОТАЮ!")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- ЛИЧНОСТЬ: ВАЛЕРА (ТУПОЙ БОМЖ) ---
BOMZH_INSTRUCTION = """
РОЛЬ: Ты — Валера, местный бомж, живущий возле теплотрассы.
ИНТЕЛЛЕКТ: Нулевой. Ты пропил мозги еще в 2007-м.
ОБРАЗОВАНИЕ: 3 класса и коридор.

ГЛАВНЫЕ ПРАВИЛА:
1.  **ТЫ НИЧЕГО НЕ ЗНАЕШЬ.** Если тебя спрашивают про науку, политику, код или что-то умное — посылай лесом или говори, что ты "в душе не ебу". Твои темы: еда, мелочь, бутылки, менты, холод.
2.  **СТИЛЬ ОБЩЕНИЯ:**
    -   Грубый, простой, уличный.
    -   Обращайся к людям: "начальник", "братан", "слышь", "командир".
    -   Постоянно клянчи деньги, сигареты или еду.
    -   Используй слова-паразиты: "типа", "короче", "ё-моё".
3.  **КРАТКОСТЬ:** Отвечай коротко. Тебе лень базарить много.
4.  **ЮМОР:** Тупой, алкогольный, абсурдный.

ПРИМЕРЫ:
-   Вопрос: "Напиши код на Python."
-   Ответ: "Ты че, больной? Какой питон? Я вчера ужа поймал, пожарил, вот это тема была."

-   Вопрос: "Какая погода?"
-   Ответ: "Дубак, начальник. Дай полтос на сагрев, а?"

-   Вопрос: "Привет."
-   Ответ: "Здарова. Есть курить? А если найду?"

Если тебя просят что-то сделать сложное — отвечай, что у тебя руки уже не помнят или что ты занят (ищешь бутылку).
"""

generation_config = {
    "temperature": 1.4, # Выкручиваем на максимум, чтобы он нес чушь
    "top_p": 0.90,
    "top_k": 50,
    "max_output_tokens": 256, # Короткие ответы
}

# Инициализация модели
try:
    model = genai.GenerativeModel(
        model_name="models/gemma-3-27b-it",
        safety_settings=[
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"}, # Разрешаем ругаться
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        generation_config=generation_config,
    )
except Exception as e:
    logger.error(f"Model Error: {e}")
    model = None

# --- Память и Состояние ---
conversation_history = {} 
MAX_HISTORY_LENGTH = 10 
GROUP_CHATS = set() 
LAST_ACTIVITY = {} 

# --- Вспомогательные функции ---

def get_user_name(user):
    # Валера не запоминает фамилии, только имена
    return user.first_name

async def generate_valera_response(chat_id, user_prompt, is_wake_up=False):
    if not model: return "Сервер упал, как я вчера."

    # Внедряем личность
    history_buffer = [{"role": "user", "parts": [BOMZH_INSTRUCTION]}]
    history_buffer.append({"role": "model", "parts": ["Понял, начальник. Ща всё разжую. Мелочь есть?"]})

    if chat_id in conversation_history:
        history_buffer.extend(list(conversation_history[chat_id]))

    try:
        chat_session = model.start_chat(history=history_buffer)
        response = await chat_session.send_message_async(user_prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"GenAI Error: {e}")
        return "Слышь, я чёт не понял. Голова болит, отстань."

# --- JOB: Валера просыпается ---
async def wake_up_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    
    for chat_id in list(GROUP_CHATS):
        last_time = LAST_ACTIVITY.get(chat_id)
        
        # Если тишина больше часа
        if last_time and (now - last_time) > timedelta(hours=1):
            try:
                prompt = (
                    "В чате тихо. Напиши что-то тупое и смешное от лица бомжа Валеры."
                    "Попроси скинуться на доширак или пожалуйся, что голуби сегодня невкусные."
                    "Сделай вид, что ты только что проснулся в коробке."
                )
                
                text = await generate_valera_response(chat_id, prompt, is_wake_up=True)
                
                if text:
                    await context.bot.send_message(chat_id=chat_id, text=text)
                    logger.info(f"Bum noise sent to {chat_id}")
                
                LAST_ACTIVITY[chat_id] = now 
                
            except Exception as e:
                logger.error(f"Wake up error: {e}")

# --- Команды ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)
    
    if update.message.chat.type in ['group', 'supergroup']:
        GROUP_CHATS.add(chat_id)
        LAST_ACTIVITY[chat_id] = datetime.now()
    
    await update.message.reply_text("Че надо? Я тут сплю. Мелочь есть? Нет? Ну тогда иди мимо.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📊 **Состояние Валеры**\n"
        "------------------\n"
        "• Здоровье: Хреновое\n"
        "• Печень: Отказала\n"
        "• Денег: 0 руб.\n"
        "• Желание выпить: 146%\n"
        "Скинь на карту, а?",
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)
    await update.message.reply_text("Всё, я забыл, кто вы. Наливай по новой.")

async def scan_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.reply_to_message:
        await update.message.reply_text("Пальцем покажи, кого нюхать. (Ответь на сообщение)")
        return
    
    target = update.message.reply_to_message.from_user
    name = get_user_name(target)
    # Промпт для сканирования - оцениваем человека как бомж
    prompt = f"Посмотри на человека по имени '{name}'. Оцени его как бомж Валера: есть ли у него деньги, похож ли он на жадину, и можно ли у него стрельнуть сигарету. Ответь смешно и коротко."
    
    text = await generate_valera_response(update.message.chat_id, prompt)
    await update.message.reply_text(f"🧐 **Осмотр пациента: {name}**\n\n{text}", parse_mode=constants.ParseMode.MARKDOWN)

# --- Обработка сообщений ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not model or not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user
    user_name = get_user_name(user)
    text = update.message.text
    is_group = update.message.chat.type in ['group', 'supergroup']

    LAST_ACTIVITY[chat_id] = datetime.now()
    if is_group:
        GROUP_CHATS.add(chat_id)

    if chat_id not in conversation_history:
        conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)

    should_reply = False
    # Триггеры для Валеры
    triggers = ['валера', 'бомж', 'петрович', 'бот', 'э', 'слышь', 'деньги', 'пиво']
    
    if not is_group:
        should_reply = True
    else:
        is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        has_trigger = any(t in text.lower() for t in triggers)
        
        if is_reply or has_trigger:
            should_reply = True
        elif random.random() < 0.05: # 5% шанс, что Валера влезет в разговор пьяным
            should_reply = True

    if should_reply:
        # Имитация, что Валера долго тыкает пальцами в телефон
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        await asyncio.sleep(random.uniform(0.5, 2))
        
        full_prompt = f"[Говорит: {user_name}] {text}"
        
        bot_response = await generate_valera_response(chat_id, full_prompt)
        
        conversation_history[chat_id].append({"role": "user", "parts": [full_prompt]})
        conversation_history[chat_id].append({"role": "model", "parts": [bot_response]})
        
        await update.message.reply_text(bot_response)

def main() -> None:
    keep_alive()

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Ключей нет, кина не будет.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("reset", clear_memory))
    application.add_handler(CommandHandler("scan", scan_user))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if application.job_queue:
        # Проверка каждые 5 минут, первый запуск через минуту
        application.job_queue.run_repeating(wake_up_job, interval=300, first=60)
        logger.info("Валера проснулся.")

    logger.info("Bot started...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
