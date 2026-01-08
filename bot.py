import os
import random
import logging
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.utils.callback_data import CallbackData

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получение токена из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")
ADMIN_ID = int(os.getenv("ADMIN_ID", "ВАШ_ТЕЛЕГРАМ_ID"))

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Ссылки для кнопок (замените на свои)
VK_REVIEW_LINK = "https://clck.ru/3QTvTp"
YANDEX_REVIEW_LINK = "https://clck.ru/3QTRfj"
TWOGIS_REVIEW_LINK = "https://clck.ru/3QsAsL"

# Инициализация базы данных SQLite
def init_db():
    conn = sqlite3.connect('bonus_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        full_name TEXT,
        screenshot_id TEXT,
        prize_amount INTEGER,
        phone TEXT,
        bank TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'pending'
    )
    ''')
    conn.commit()
    conn.close()

# Класс состояний
class Form(StatesGroup):
    screenshot = State()
    phone = State()
    bank = State()

# Создаем callback data
bonus_cb = CallbackData("bonus", "action")

# Функция создания основной клавиатуры
def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("⭐ Бонус за отзыв 5", callback_data=bonus_cb.new(action="get_bonus")),
        InlineKeyboardButton("📘 Отзыв в VK", url=VK_REVIEW_LINK),
        InlineKeyboardButton("🌐 Отзыв в Яндексе", url=YANDEX_REVIEW_LINK),
        InlineKeyboardButton("🗺️ Отзыв в 2ГИС", url=TWOGIS_REVIEW_LINK)
    )
    return keyboard

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    welcome_text = """Здравствуйте! 😊

Добро пожаловать в бот для получения бонусов!
Размер приза от 150 до 200 рублей

Вы также можете оставить отзывы на других площадках и получить бонус!"""
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

# Обработка callback запросов
@dp.callback_query_handler(bonus_cb.filter(action="get_bonus"))
async def process_bonus(callback_query: types.CallbackQuery):
    instructions = """⭐ Как получить бонус:

1. Оставьте отзыв на ⭐️⭐️⭐️⭐️⭐️ о нашем сервисе (Авито, Суточно, Островок, Озон, ВК, Яндекс)
2. Сделайте скриншот вашего отзыва
3. Отправьте скриншот сюда

После проверки вы получите случайный денежный приз от 150 до 200 рублей!

Отправьте скриншот отзыва:"""
    
    await callback_query.message.edit_text(instructions)
    await Form.screenshot.set()
    await callback_query.answer()

# Обработка скриншота
@dp.message_handler(state=Form.screenshot, content_types=['photo'])
async def process_screenshot(message: types.Message, state: FSMContext):
    # Генерируем случайную сумму
    prize_amount = random.randint(150, 200)
    
    # Сохраняем в состояние
    async with state.proxy() as data:
        data['user_id'] = message.from_user.id
        data['username'] = message.from_user.username
        data['full_name'] = message.from_user.full_name
        data['screenshot_id'] = message.photo[-1].file_id
        data['prize_amount'] = prize_amount
    
    success_text = f"""✅ Отличная работа!

Скриншот принят и сохранен! 
Спасибо за ваш отзыв! 🙏

🎉 Ваш выигрыш: {prize_amount} рублей!

Для получения денежного приза отправьте ваш номер телефона:
+7XXXXXXXXXX или 8XXXXXXXXXX

Пример: +79123456789"""
    
    await message.answer(success_text)
    await Form.next()

# Обработка номера телефона
@dp.message_handler(state=Form.phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.text.strip()
    
    # Валидация номера
    if not (phone.startswith('+7') or phone.startswith('8')) or len(phone.replace('+', '')) != 11:
        await message.answer("❌ Пожалуйста, введите номер телефона в правильном формате:\n+7XXXXXXXXXX или 8XXXXXXXXXX\n\nПример: +79123456789")
        return
    
    async with state.proxy() as data:
        data['phone'] = phone
    
    bank_request = """📋 Отлично! Теперь укажите ваш банк для перевода:

Например:
- Сбербанк
- Тинькофф
- Альфа-Банк
- ВТБ
- или другой банк

Отправьте название банка:"""
    
    await message.answer(bank_request)
    await Form.next()

# Обработка банка
@dp.message_handler(state=Form.bank)
async def process_bank(message: types.Message, state: FSMContext):
    bank = message.text.strip()
    
    async with state.proxy() as data:
        data['bank'] = bank
        
        # Сохраняем в базу данных
        conn = sqlite3.connect('bonus_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO applications (user_id, username, full_name, screenshot_id, prize_amount, phone, bank)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['user_id'],
            data['username'],
            data['full_name'],
            data['screenshot_id'],
            data['prize_amount'],
            data['phone'],
            data['bank']
        ))
        conn.commit()
        conn.close()
        
        # Отправляем финальное сообщение
        final_message = f"""🎊 Поздравляем! Заявка оформлена!

✅ Данные для выплаты:
- Сумма: {data['prize_amount']} рублей
- Телефон: {data['phone']}
- Банк: {bank}

⏳ Обработка выплаты:
Ваша заявка принята. 
Выплаты происходят в течение 24 часов.

💰 Деньги будут переведены в течение 1-3 рабочих дней.

Спасибо за участие! 🎉

Для нового бонуса нажмите /start"""
        
        await message.answer(final_message)
        
        # Отправляем администратору
        await send_to_admin(data)
    
    await state.finish()

# Функция отправки заявки администратору
async def send_to_admin(data):
    admin_message = f"""📨 Новая заявка на бонус!

👤 Пользователь:
ID: {data['user_id']}
Имя: {data['full_name']}
Username: @{data['username'] if data['username'] else 'Не указан'}

💰 Сумма: {data['prize_amount']} руб.
📱 Телефон: {data['phone']}
🏦 Банк: {data['bank']}

Скриншот отправлен."""
    
    try:
        # Отправляем текстовое сообщение
        await bot.send_message(ADMIN_ID, admin_message)
        
        # Отправляем скриншот
        await bot.send_photo(ADMIN_ID, data['screenshot_id'], 
                           caption=f"Скриншот отзыва от {data['full_name']}")
        
        logger.info(f"Заявка отправлена администратору от пользователя {data['user_id']}")
    except Exception as e:
        logger.error(f"Ошибка отправки админу: {e}")

# Обработка текстовых сообщений
@dp.message_handler(content_types=['text'])
async def handle_text(message: types.Message):
    if message.text and not message.text.startswith('/'):
        await message.answer("Для получения бонуса нажмите на кнопку ниже или введите /start", 
                           reply_markup=get_main_keyboard())

# Главная функция
if __name__ == '__main__':
    # Инициализация базы данных
    init_db()
    
    logger.info("Бот запущен...")
    executor.start_polling(dp, skip_updates=True)
