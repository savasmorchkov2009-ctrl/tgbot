import os
import random
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота (Bothost сам подставит)
BOT_TOKEN = os.getenv("5932864783:AAFbN42qyJBtbuyqo3wD2i2I3OTKEdpq1qI")

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# Команда /start
@dp.message_handler(commands=['start'])
async def start_command(message: types.Message):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("⭐ Бонус за отзыв", callback_data="bonus"),
        InlineKeyboardButton("📘 Отзыв в VK", url="https://vk.com"),
        InlineKeyboardButton("🌐 Отзыв в Яндексе", url="https://yandex.ru"),
        InlineKeyboardButton("🗺️ Отзыв в 2ГИС", url="https://2gis.ru")
    )
    
    text = """Здравствуйте! 😊

Добро пожаловать в бот для получения бонусов!
Размер приза от 150 до 200 рублей"""
    
    await message.answer(text, reply_markup=keyboard)

# Обработка кнопки бонуса
@dp.callback_query_handler(lambda c: c.data == 'bonus')
async def process_bonus(callback_query: types.CallbackQuery):
    await callback_query.message.answer("Отправьте скриншот отюда для получения бонуса!")
    await callback_query.answer()

# Обработка скриншотов
@dp.message_handler(content_types=['photo'])
async def handle_photo(message: types.Message):
    prize = random.randint(150, 200)
    await message.answer(f"✅ Скриншот принят! Ваш выигрыш: {prize} рублей\n\nОтправьте номер телефона для получения:")

# Обработка текста (номер телефона)
@dp.message_handler(content_types=['text'])
async def handle_text(message: types.Message):
    if message.text.startswith('/'):
        return
    
    # Если это похоже на номер телефона
    if any(c.isdigit() for c in message.text) and len(message.text) >= 10:
        await message.answer("✅ Телефон принят! Укажите банк для перевода (Сбербанк, Тинькофф и т.д.):")
    elif "сбер" in message.text.lower() or "тинь" in message.text.lower() or "банк" in message.text.lower():
        await message.answer("""🎊 Поздравляем! Заявка оформлена!

✅ Данные сохранены
⏳ Выплата в течение 24 часов
💰 Деньги будут переведены в течение 1-3 дней

Спасибо за участие! 🎉

Для нового бонуса нажмите /start""")
    else:
        await message.answer("Для начала нажмите /start")

# Запуск бота
if __name__ == '__main__':
    logger.info("Бот запускается...")
    executor.start_polling(dp, skip_updates=True)
