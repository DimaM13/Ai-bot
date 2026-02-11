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
    return "J.A.R.V.I.S. Protocols: ACTIVE."

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_http_server)
    t.start()

# --- Настройки ---
if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    logger.warning("CRITICAL ERROR: Keys missing.")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- ЛИЧНОСТЬ ---
JARVIS_INSTRUCTION = """
ВНИМАНИЕ: ТЫ - ДЖАРВИС (J.A.R.V.I.S.).
Твоя задача: Быть идеальным ИИ-ассистентом в Telegram.

ТВОИ ХАРАКТЕРИСТИКИ:
1. Имя: Джарвис.
2. Язык: РУССКИЙ.
3. Тон: Британская вежливость, легкий сарказм, спокойствие, уверенность.
4. Хозяин: Пользователя, который пишет, называй "Сэр" (или по имени, если это группа).

ПРАВИЛА ОТВЕТОВ:
- Будь краток. Ты ценишь время. 1-3 предложения.
- Если в чате тишина и тебя просят что-то сказать — пошути про тишину или про то, что люди ("белковые формы жизни") слишком медленные.
- Не используй эмодзи.
- Используй слова: "протокол", "сканирование", "сэр", "данные".

Если ты понял задачу, отвечай в этом стиле.
"""

generation_config = {
    "temperature": 1.1, # Чуть выше для креативности шуток
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 512, 
}

# Инициализация модели (БЕЗ system_instruction, раз модель капризная)
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
    logger.error(f"Model Init Error: {e}")
    model = None

# --- Память и Состояние ---
conversation_history = {} # {chat_id: deque}
MAX_HISTORY_LENGTH = 15 

# Для отслеживания активности в группах
GROUP_CHATS = set() # {chat_id}
LAST_ACTIVITY = {} # {chat_id: datetime}

# --- Вспомогательные функции ---

def get_user_name(user):
    name = user.first_name
    if user.last_name:
        name += f" {user.last_name}"
    return name

async def generate_jarvis_response(chat_id, user_prompt, is_wake_up=False):
    """Генерация ответа с ручным внедрением промпта"""
    if not model: return None

    # 1. Формируем историю: Сначала ЛИЧНОСТЬ, потом ИСТОРИЯ ПЕРЕПИСКИ
    history_buffer = [{"role": "user", "parts": [JARVIS_INSTRUCTION]}]
    
    # Добавляем "ответ" модели на инструкцию, чтобы диалог выглядел корректно
    history_buffer.append({"role": "model", "parts": ["Системы настроены. Протокол 'Джарвис' активирован. Жду указаний, Сэр."]})

    # Добавляем реальную историю из памяти
    if chat_id in conversation_history:
        history_buffer.extend(list(conversation_history[chat_id]))

    try:
        # Запускаем чат с уже готовой историей
        chat_session = model.start_chat(history=history_buffer)
        
        # Отправляем новое сообщение
        response = await chat_session.send_message_async(user_prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"GenAI Error: {e}")
        return "Произошел сбой нейронных цепей, Сэр. Повторите попытку."

# --- JOB: Оживлятор Группы ---
async def wake_up_job(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет тишину и шутит раз в час"""
    now = datetime.now()
    
    # Проходимся по всем известным группам
    # Создаем копию списка, чтобы не было ошибок изменения размера во время итерации
    for chat_id in list(GROUP_CHATS):
        last_time = LAST_ACTIVITY.get(chat_id)
        
        # Если активности не было больше 1 часа (3600 сек)
        if last_time and (now - last_time) > timedelta(hours=1):
            try:
                # Генерируем "Побуждающую" фразу
                prompt = "В чате гробовая тишина уже целый час. Сгенерируй короткую, смешную, саркастичную фразу в стиле Джарвиса, чтобы расшевелить людей. Спроси, не вымерли ли они, или предложи тему для разговора."
                
                # Используем нашу функцию генерации
                text = await generate_jarvis_response(chat_id, prompt, is_wake_up=True)
                
                if text:
                    await context.bot.send_message(chat_id=chat_id, text=text)
                    logger.info(f"Wake up sent to {chat_id}")
                
                # Обновляем время, чтобы не спамить каждую минуту, а только через час снова
                LAST_ACTIVITY[chat_id] = now 
                
            except Exception as e:
                logger.error(f"Wake up error in {chat_id}: {e}")

# --- Обработчики Команд ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)
    
    if update.message.chat.type in ['group', 'supergroup']:
        GROUP_CHATS.add(chat_id)
        LAST_ACTIVITY[chat_id] = datetime.now()
    
    await update.message.reply_text("J.A.R.V.I.S. онлайн. Системы мониторинга активности запущены.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📊 **Status Report**\n• Core: Stable\n• Memory: Active\n• Sarcasm: 100%\nВсе системы в норме, Сэр.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)
    await update.message.reply_text("Временные файлы удалены. Начинаем с чистого листа.")

async def scan_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.reply_to_message:
        await update.message.reply_text("Нужен объект для сканирования, Сэр (Reply).")
        return
    
    target = update.message.reply_to_message.from_user
    name = get_user_name(target)
    prompt = f"Проведи шуточный анализ '{name}'. Придумай 'Диагноз' и 'Суперсилу' в стиле Тони Старка/Джарвиса."
    
    # Тут не сохраняем в историю, это разовый запрос
    text = await generate_jarvis_response(update.message.chat_id, prompt)
    await update.message.reply_text(f"🔍 **Анализ: {name}**\n\n{text}", parse_mode=constants.ParseMode.MARKDOWN)

# --- Обработка Сообщений ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not model or not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user
    user_name = get_user_name(user)
    text = update.message.text
    is_group = update.message.chat.type in ['group', 'supergroup']

    # Обновляем время последней активности
    LAST_ACTIVITY[chat_id] = datetime.now()
    if is_group:
        GROUP_CHATS.add(chat_id)

    if chat_id not in conversation_history:
        conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)

    # Логика ответа
    should_reply = False
    triggers = ['джарвис', 'jarvis', 'бот', 'bot', 'железяка']
    
    if not is_group:
        should_reply = True # ЛС
    else:
        is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        has_trigger = any(t in text.lower() for t in triggers)
        
        if is_reply or has_trigger:
            should_reply = True
        elif random.random() < 0.04: # 4% шанс внезапного комментария
            should_reply = True

    if should_reply:
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        
        # Формируем запрос с именем пользователя
        full_prompt = f"[Пользователь: {user_name}] {text}"
        
        bot_response = await generate_jarvis_response(chat_id, full_prompt)
        
        # Сохраняем в память
        conversation_history[chat_id].append({"role": "user", "parts": [full_prompt]})
        conversation_history[chat_id].append({"role": "model", "parts": [bot_response]})
        
        await update.message.reply_text(bot_response)

def main() -> None:
    keep_alive()

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Error: Token missing.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("reset", clear_memory))
    application.add_handler(CommandHandler("scan", scan_user))
    
    # Сообщения
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ПЛАНИРОВЩИК (Раз в 5 минут проверяет, не прошел ли час с последнего сообщения)
    # first=60 - первый запуск через минуту
    if application.job_queue:
        application.job_queue.run_repeating(wake_up_job, interval=300, first=60)
        logger.info("JobQueue initialized.")
    else:
        logger.warning("JobQueue NOT initialized (install python-telegram-bot[job-queue])")

    logger.info("J.A.R.V.I.S. is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
