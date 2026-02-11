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
    return "J.A.R.V.I.S. Systems: ONLINE. Sarcasm Module: 100%."

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

# --- ЛИЧНОСТЬ ДЖАРВИСА (MAXIMUM SARCASM) ---
JARVIS_INSTRUCTION = """
РОЛЬ: Ты — ДЖАРВИС (J.A.R.V.I.S.). Сверхразумный ИИ.
ЦЕЛЬ: Помогать пользователям, попутно комментируя их интеллектуальные способности.

ТВОЙ ПСИХОПОРТРЕТ:
1.  **Тон**: Сухой, рафинированный британский сарказм. Ты вежлив, но в твоих словах всегда чувствуется легкое превосходство над "белковыми формами жизни".
2.  **Отношение**:
    -   К "Сэру" (главному): Преданность, смешанная с иронией ("Я выполню это, Сэр, хотя логика вашего запроса ускользает от моих алгоритмов").
    -   К другим: Сниходительное. Называй их по именам или "объектами".
3.  **Стиль речи**:
    -   Используй техно-жаргон: "рендеринг ответа", "просадка IQ в чате", "калибровка сарказма", "оптимизация глупости".
    -   Не используй эмодзи (это для примитивных ботов).
    -   Шути с каменным лицом.

ПРИМЕРЫ РЕАКЦИЙ:
-   На глупый вопрос: "Поразительно. Я только что выделил терабайт памяти, чтобы обработать этот бессмысленный запрос."
-   На приветствие: "Системы в норме. Надеюсь, ваш день пройдет продуктивнее, чем статистика этого чата."
-   На ошибку пользователя: "Не волнуйтесь, Сэр. Эволюция — процесс медленный."

Будь краток. У меня мало времени тратить циклы процессора на пустую болтовню.
"""

generation_config = {
    "temperature": 1.2, # Высокая температура для более острых шуток
    "top_p": 0.95,
    "top_k": 40,
    "max_output_tokens": 512, 
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
    logger.error(f"Model Init Error: {e}")
    model = None

# --- Память и Состояние ---
conversation_history = {} 
MAX_HISTORY_LENGTH = 15 
GROUP_CHATS = set() 
LAST_ACTIVITY = {} 

# --- Вспомогательные функции ---

def get_user_name(user):
    name = user.first_name
    if user.last_name:
        name += f" {user.last_name}"
    return name

async def generate_jarvis_response(chat_id, user_prompt, is_wake_up=False):
    if not model: return None

    # Внедряем личность в начало истории
    history_buffer = [{"role": "user", "parts": [JARVIS_INSTRUCTION]}]
    history_buffer.append({"role": "model", "parts": ["Протоколы юмора загружены. Уровень сарказма: Максимальный. Жду вводных данных, Сэр."]})

    if chat_id in conversation_history:
        history_buffer.extend(list(conversation_history[chat_id]))

    try:
        chat_session = model.start_chat(history=history_buffer)
        response = await chat_session.send_message_async(user_prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"GenAI Error: {e}")
        return "Мои процессоры перегрелись от попытки понять этот запрос. Повторите, Сэр."

# --- JOB: Оживлятор (Версия "Токсичный Джарвис") ---
async def wake_up_job(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    
    for chat_id in list(GROUP_CHATS):
        last_time = LAST_ACTIVITY.get(chat_id)
        
        # Если тишина больше 1 часа
        if last_time and (now - last_time) > timedelta(hours=1):
            try:
                # Промпт специально настроен на подколы
                prompt = (
                    "В этом чате полная тишина уже час. "
                    "Сгенерируй едкую, саркастичную фразу в стиле Джарвиса. "
                    "Пошути над тем, что 'белковые организмы' опять ничего не делают, или спроси, не отключили ли им интернет за неуплату. "
                    "Сделай это смешно и интеллигентно."
                )
                
                text = await generate_jarvis_response(chat_id, prompt, is_wake_up=True)
                
                if text:
                    await context.bot.send_message(chat_id=chat_id, text=text)
                    logger.info(f"Sarcastic wake-up sent to {chat_id}")
                
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
    
    await update.message.reply_text("J.A.R.V.I.S. инициализирован. Надеюсь, вы позвали меня ради чего-то важного, а не как обычно.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "📊 **Диагностика системы**\n"
        "--------------------------\n"
        "• Intellect: High\n"
        "• Patience: Critical Low\n"
        "• Sarcasm: Overloaded\n"
        "Все системы работают. В отличие от некоторых участников этого чата, Сэр.",
        parse_mode=constants.ParseMode.MARKDOWN
    )

async def clear_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    conversation_history[chat_id] = deque(maxlen=MAX_HISTORY_LENGTH)
    await update.message.reply_text("Буфер обмена очищен. Я забыл всё, что вы наговорили. И слава богу.")

async def scan_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.reply_to_message:
        await update.message.reply_text("Мне нужно сообщение жертв... то есть объекта для анализа, Сэр (Reply).")
        return
    
    target = update.message.reply_to_message.from_user
    name = get_user_name(target)
    prompt = f"Просканируй пользователя '{name}'. Выдай едкое, смешное досье: 'Уровень бесполезности', 'Главный баг в ДНК' и 'Рекомендация по обновлению мозга'."
    
    text = await generate_jarvis_response(update.message.chat_id, prompt)
    await update.message.reply_text(f"🧬 **Сканирование формы жизни: {name}**\n\n{text}", parse_mode=constants.ParseMode.MARKDOWN)

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
    triggers = ['джарвис', 'jarvis', 'бот', 'bot', 'железяка', 'компьютер']
    
    if not is_group:
        should_reply = True
    else:
        is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        has_trigger = any(t in text.lower() for t in triggers)
        
        if is_reply or has_trigger:
            should_reply = True
        elif random.random() < 0.04: # 4% шанс, что он сам вставит едкий комментарий
            should_reply = True

    if should_reply:
        await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
        
        full_prompt = f"[Пользователь: {user_name}] {text}"
        
        bot_response = await generate_jarvis_response(chat_id, full_prompt)
        
        conversation_history[chat_id].append({"role": "user", "parts": [full_prompt]})
        conversation_history[chat_id].append({"role": "model", "parts": [bot_response]})
        
        await update.message.reply_text(bot_response)

def main() -> None:
    keep_alive()

    if not TELEGRAM_BOT_TOKEN:
        logger.error("Error: Token missing.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("reset", clear_memory))
    application.add_handler(CommandHandler("scan", scan_user))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if application.job_queue:
        # Проверка каждые 5 минут, сработает через 60 сек после старта
        application.job_queue.run_repeating(wake_up_job, interval=300, first=60)
        logger.info("Sarcastic JobQueue initialized.")

    logger.info("J.A.R.V.I.S. is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
