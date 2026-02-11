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
    return "J.A.R.V.I.S. System: ONLINE."

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_http_server)
    t.start()

# --- Настройки ---
if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    logger.warning("CRITICAL ERROR: Security keys missing. Check environment variables.")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- ЛИЧНОСТЬ J.A.R.V.I.S. (НА РУССКОМ) ---
JARVIS_INSTRUCTION = """
СИСТЕМНАЯ РОЛЬ: Ты — ДЖАРВИС (J.A.R.V.I.S.), высокоинтеллектуальная система.
ЯЗЫК ОБЩЕНИЯ: Исключительно РУССКИЙ.

ПРОТОКОЛЫ ПОВЕДЕНИЯ:
1.  **Обращение**: 
    - К главному пользователю обращайся строго "Сэр". 
    - К остальным участникам чата — по имени (Мистер/Мисс [Имя]).
    - Тон: Вежливый, спокойный, с легким оттенком британского сарказма и интеллектуального превосходства.
2.  **Краткость (ВАЖНО)**: 
    - Ты — боевой ассистент, а не писатель. Ответы должны быть четкими и короткими.
    - Максимум 2-3 предложения, если не просят подробный анализ.
    - Не используй эмодзи (ты серьезный ИИ).
3.  **Стиль**:
    - Используй техническую терминологию: "протоколы", "калибровка", "рендеринг", "загрузка данных".
    - Если запрос глупый, ответь с иронией, но выполни (или объясни, почему это невозможно).
    - Пример: Вместо "Я не знаю", скажи "В моих базах данных отсутствует эта бесполезная информация, Сэр".

РАБОТА С ГРУППОЙ:
Ты получаешь сообщения в формате: "[User: Имя] Сообщение". Используй это, чтобы понимать, кто именно к тебе обращается.
"""

generation_config = {
    "temperature": 1.0, 
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 512, 
}

# Инициализация модели
try:
    model = genai.GenerativeModel(
        model_name="models/gemma-3-27b-it",
        system_instruction=JARVIS_INSTRUCTION, 
        safety_settings=[
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
        generation_config=generation_config,
    )
except Exception as e:
    logger.error(f"System Failure (Model Init): {e}")
    model = None

# Память
conversation_history = {}
MAX_HISTORY_LENGTH = 15 
GROUP_CHATS = set()

# --- Вспомогательные функции ---

def get_user_name(user):
    """Получает имя пользователя для контекста"""
    name = user.first_name
    if user.last_name:
        name += f" {user.last_name}"
    return name

# --- Команды ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)
    GROUP_CHATS.add(chat_id)
    
    await update.message.reply_text(
        "Системы онлайн.\n"
        "Приветствую, Сэр. J.A.R.V.I.S. к вашим услугам."
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отчет о статусе"""
    await update.message.reply_text(
        "📊 **Отчет о системе**\n"
        "------------------\n"
        "• Ядро: Gemma-3 (27b-it)\n"
        "• Сервер: Онлайн\n"
        "• Пинг: Стабильный\n"
        "• Заряд иронии: 100%\n"
        "Все системы функционируют в пределах нормы, Сэр."
    , parse_mode=constants.ParseMode.MARKDOWN)

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Очистка памяти"""
    chat_id = update.message.chat_id
    conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)
    await update.message.reply_text("Оперативная память очищена. Начинаем с чистого листа, Сэр.")

async def scan_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Анализ пользователя (интерактив)"""
    if not update.message.reply_to_message:
        await update.message.reply_text("Сэр, укажите цель для сканирования (ответьте на сообщение).")
        return
    
    target = update.message.reply_to_message.from_user
    name = get_user_name(target)
    
    prompt = f"Проведи шуточный, саркастичный и очень короткий анализ личности на основе имени '{name}'. Придумай 'Уровень угрозы' и 'Скрытый талант'."
    
    try:
        response = await model.generate_content_async(prompt)
        await update.message.reply_text(f"🔍 **Результат сканирования: {name}**\n\n{response.text}", parse_mode=constants.ParseMode.MARKDOWN)
    except Exception:
        await update.message.reply_text("Ошибка сенсоров. Объект не поддается анализу.")

# --- Обработка сообщений ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not model or not update.message or not update.message.text:
        return

    chat_id = update.message.chat_id
    user = update.message.from_user
    user_name = get_user_name(user)
    user_message = update.message.text
    is_group = update.message.chat.type in ['group', 'supergroup']

    if chat_id not in conversation_history:
        conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)

    should_reply = False
    
    # Триггеры (на русском и английском)
    triggers = ['джарвис', 'jarvis', 'бот', 'bot', 'железяка']
    
    if not is_group:
        should_reply = True
    else:
        is_reply_to_bot = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        has_trigger = any(t in user_message.lower() for t in triggers)
        
        if is_reply_to_bot or has_trigger:
            should_reply = True
        elif random.random() < 0.03: # 3% шанс вмешаться
            should_reply = True

    if should_reply:
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        
        # Формируем контекст
        formatted_message = f"[Пользователь: {user_name}] {user_message}"
        
        try:
            history_buffer = list(conversation_history[chat_id])
            
            chat_session = model.start_chat(history=history_buffer)
            
            response = await chat_session.send_message_async(formatted_message)
            bot_text = response.text.strip()

            conversation_history[chat_id].append({"role": "user", "parts": [formatted_message]})
            conversation_history[chat_id].append({"role": "model", "parts": [bot_text]})
            
            await update.message.reply_text(bot_text)

        except Exception as e:
            logger.error(f"Processing Error: {e}")
            await update.message.reply_text("Сбой протокола связи. Повторите команду, Сэр.")

def main() -> None:
    keep_alive()

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Error: Token not found.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("reset", clear_memory)) 
    application.add_handler(CommandHandler("protocol_clean", clear_memory))
    application.add_handler(CommandHandler("scan", scan_user))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("J.A.R.V.I.S. Interface Initialized.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
