import os
import logging
import random
import json
import asyncio
import threading # <--- Для запуска сервера в фоне
from datetime import datetime, timedelta
from collections import deque
from flask import Flask # <--- Веб-сервер для Render

import google.generativeai as genai
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# --- Загрузка и конфигурация ---
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# Кодовая фраза для принудительного запоминания
MEMORY_TRIGGER = "!запомни" 

# --- БЛОК ОБМАНКИ ДЛЯ RENDER (Keep Alive) ---
app = Flask('')

@app.route('/')
def home():
    return "Nastya is alive. Don't bother her."

def run_http_server():
    # Render передает порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    # Запускаем Flask в отдельном потоке
    t = threading.Thread(target=run_http_server)
    t.start()
# ---------------------------------------------

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    # Для локального запуска оставим warning
    logger.warning("Токены не найдены в .env. Убедитесь, что они есть в Environment Variables!")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- Файл памяти ---
MEMORY_FILE = 'nastya_memory.json'

# --- Класс управления состоянием Насти ---
class NastyaBrain:
    def __init__(self):
        self.memory = self.load_memory()
        self.mood_score = 50 
        self.current_activity = "просто сидит в телефоне"
        self.last_mood_update = datetime.now()
        
    def load_memory(self):
        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_memory(self):
        # Внимание: На Render файловая система временная. 
        # При перезагрузке память сотрется, если не подключить внешний диск или базу данных.
        # Но для теста пойдет.
        try:
            with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Не удалось сохранить память: {e}")

    def get_user_memory(self, user_id):
        return self.memory.get(str(user_id), "Этого человека ты видишь впервые.")

    def update_user_memory(self, user_id, user_name, combined_summary):
        self.memory[str(user_id)] = f"Имя: {user_name}. {combined_summary}"
        self.save_memory()

    def update_mood(self):
        now = datetime.now()
        
        activities = [
            "слушает грустную музыку", "делает домашку и бесится", "лежит на кровати и смотрит в потолок",
            "листает тикток", "пьет энергетик", "пытается уснуть", "играет в телефоне"
        ]
        self.current_activity = random.choice(activities)

        if 2 <= now.hour < 7:
            self.mood_score = max(0, self.mood_score - 15) # Ночью злая
        else:
            change = random.randint(-10, 15)
            self.mood_score = max(0, min(100, self.mood_score + change))
        
        logger.info(f"Настроение: {self.mood_score}, Занятие: {self.current_activity}")

    def get_mood_description(self):
        desc = f"Твое текущее занятие: {self.current_activity}. "
        if self.mood_score < 25:
            return desc + "Настроение ужасное. Ты устала, все бесят. Отвечай односложно, грубо или с агрессией."
        elif self.mood_score < 50:
            return desc + "Настроение так себе. Скучно. Сарказм приветствуется."
        elif self.mood_score < 75:
            return desc + "Настроение норм. Пофигистичное."
        else:
            return desc + "Настроение неплохое. Ты можешь быть чуть более разговорчивой, но не милой."

brain = NastyaBrain()

# --- Конфигурация модели ---
# Добавляем отключение фильтров безопасности, чтобы не ловить ошибки SAFETY
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

try:
    model = genai.GenerativeModel(
        model_name="models/gemma-3-27b-it",
        safety_settings=safety_settings,
        generation_config={"temperature": 1.2, "top_p": 0.95, "max_output_tokens": 1024}
    )
except Exception:
    model = None

conversation_history = {} # Краткосрочная память {chat_id: deque}

# --- Системный промпт ---
def get_system_prompt(mood_desc, user_info, is_group, recent_history_text):
    base_personality = """
    Роль: Ты Настя, 17 лет. Циничная, "живая" девушка-подросток.
    
    СТИЛЬ ОБЩЕНИЯ:
    - Никаких эмодзи (строго).
    - Только строчные буквы (чаще всего).
    - Используй сленг (кринж, пон, жиза, хз, треш), но не перебарщивай.
    - Отвечай КАК ЧЕЛОВЕК: можешь переспросить, огрызнуться, или просто кинуть "мда".
    - Не пиши длинные поэмы. Ты ленивая.
    """
    
    context = f"""
    КОНТЕКСТ:
    - Твое состояние: {mood_desc}
    - Собеседник (что ты о нем помнишь): {user_info}
    - Где ты: {"Групповой чат" if is_group else "Личные сообщения"}
    
    ИСТОРИЯ ДИАЛОГА (последние сообщения):
    {recent_history_text}
    
    Твоя задача: Ответить на ПОСЛЕДНЕЕ сообщение в истории, учитывая контекст выше. 
    Не предлагай помощь. Ты не бот.
    """
    return base_personality + context

# --- Логика обработки ---

async def generate_nastya_response(chat_id, user_message, user_info, is_group):
    if not model: return "мозг не подключен..."
    
    mood_desc = brain.get_mood_description()
    
    raw_history = conversation_history.get(chat_id, deque(maxlen=10))
    history_text = "\n".join(list(raw_history))
    
    full_context_history = f"{history_text}\nUser: {user_message}"
    
    system_instruction = get_system_prompt(mood_desc, user_info, is_group, full_context_history)
    
    # Gemma не поддерживает system_instruction в конфиге, поэтому шлем как user message
    messages = [{"role": "user", "parts": [system_instruction]}]

    try:
        response = await model.generate_content_async(messages)
        text = response.text.strip()
        if text.lower().startswith("nastya:"):
            text = text[7:].strip()
        return text
    except Exception as e:
        logger.error(f"Ошибка Gemini: {e}")
        return "чет голова болит.. позже"

async def summarize_user(user_id, user_name, new_message, is_forced=False):
    if not model: return
    try:
        current_memory = brain.get_user_memory(user_id)
        
        prompt = f"""
        Ты ведешь личный дневник памяти о людях.
        
        СТАРАЯ ЗАПИСЬ О ЧЕЛОВЕКЕ: "{current_memory}"
        НОВОЕ СООБЩЕНИЕ ОТ НЕГО: "{new_message}"
        
        ЗАДАЧА:
        Объедини старую запись и новую информацию в ОДИН короткий текст.
        Сохрани важные факты (имя, увлечения, кто он). 
        Если новая информация противоречит старой — замени старую.
        Если новой информации нет (просто "привет") — оставь старую запись.
        Пиши сухо, как факты.
        """
        
        response = await model.generate_content_async(prompt)
        new_memory = response.text.strip()
        
        brain.update_user_memory(user_id, user_name, new_memory)
        logger.info(f"Память о {user_name} обновлена (Forced: {is_forced}).")
        
    except Exception as e:
        logger.error(f"Ошибка памяти: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    chat_id = message.chat_id
    user = message.from_user
    user_message = message.text
    is_group = message.chat.type in ['group', 'supergroup']
    
    forced_memory_update = False
    if MEMORY_TRIGGER in user_message.lower():
        forced_memory_update = True
    
    # 1. Логика "Отвечать или нет"
    should_reply = False
    if not is_group:
        should_reply = True
    else:
        is_reply = message.reply_to_message and message.reply_to_message.from_user.id == context.bot.id
        mentions = 'настя' in user_message.lower()
        
        if is_reply or mentions or forced_memory_update:
            should_reply = True
        elif random.randint(0, 100) < (brain.mood_score / 2): 
             should_reply = True

    # Если не отвечаем, но была команда запомнить
    if not should_reply and forced_memory_update:
        asyncio.create_task(summarize_user(user.id, user.first_name, user_message, is_forced=True))
        return 

    if not should_reply:
        if chat_id not in conversation_history:
            conversation_history[chat_id] = deque(maxlen=6)
        conversation_history[chat_id].append(f"User ({user.first_name}): {user_message}")
        return

    # 2. Имитация набора текста
    await context.bot.send_chat_action(chat_id=chat_id, action=constants.ChatAction.TYPING)
    # Немного уменьшил задержку для отзывчивости
    typing_delay = random.uniform(1.0, 3.0) 
    await asyncio.sleep(typing_delay) 

    # 3. Ответ
    user_info = brain.get_user_memory(user.id)
    response_text = await generate_nastya_response(chat_id, user_message, user_info, is_group)
    
    if "[IGNORE]" in response_text:
        return

    await message.reply_text(response_text)

    # 4. Обновление истории
    if chat_id not in conversation_history:
        conversation_history[chat_id] = deque(maxlen=6)
    
    conversation_history[chat_id].append(f"User ({user.first_name}): {user_message}")
    conversation_history[chat_id].append(f"Nastya: {response_text}")

    # 5. Обновление долговременной памяти
    if forced_memory_update or random.random() < 0.3:
        asyncio.create_task(summarize_user(user.id, user.first_name, user_message, is_forced=forced_memory_update))

async def mood_update_job(context: ContextTypes.DEFAULT_TYPE):
    brain.update_mood()

def main() -> None:
    # 1. ЗАПУСКАЕМ ОБМАНКУ ПЕРЕД БОТОМ
    keep_alive()

    # 2. ЗАПУСКАЕМ БОТА
    if not TELEGRAM_BOT_TOKEN:
        logger.error("Нет токена бота!")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("ну привет")))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = application.job_queue
    job_queue.run_repeating(mood_update_job, interval=timedelta(minutes=45), first=10)

    logger.info("Настя проснулась...")
    application.run_polling()

if __name__ == '__main__':
    main()
