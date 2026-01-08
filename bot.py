import os
import random
import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    BOT_TOKEN = "5932864783:AAFbN42qyJBtbuyqo3wD2i2I3OTKEdpq1qI"

# Инициализация
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Команда /start
@dp.message(Command("start"))
async def start_command(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Бонус за отзыв", callback_data="bonus")],
        [InlineKeyboardButton(text="📘 Отзыв в VK", url="https://clck.ru/3QTvTp")],
        [InlineKeyboardButton(text="🌐 Отзыв в Яндексе", url="https://clck.ru/3QTRfj")],
        [InlineKeyboardButton(text="🗺️ Отзыв в 2ГИС", url="https://clck.ru/3QsAsL")]
    ])
    
    text = """Здравствуйте! 😊

Добро пожаловать в бот для получения бонусов!
Размер приза от 150 до 200 рублей

Вы также можете оставить отзывы на других площадках и получить бонус!"""
    
    await message.answer(text, reply_markup=keyboard)

# Обработка кнопки бонуса
@dp.callback_query(F.data == "bonus")
async def process_bonus(callback_query: types.CallbackQuery):
    instructions = """⭐ Как получить бонус:

1. Оставьте отзыв на ⭐️⭐️⭐️⭐️⭐️ о нашем сервисе (Авито, Суточно, Островок, Озон, ВК, Яндекс)
2. Сделайте скриншот вашего отзыва
3. Отправьте скриншот сюда

После проверки вы получите случайный денежный приз от 150 до 200 рублей!

Отправьте скриншот отзыва:"""
    
    await callback_query.message.answer(instructions)
    await callback_query.answer()

# Обработка скриншотов
@dp.message(F.photo)
async def handle_photo(message: types.Message):
    prize = random.randint(150, 200)
    response = f"""✅ Отличная работа!

Скриншот принят и сохранен! 
Спасибо за ваш отзыв! 🙏

🎉 Ваш выигрыш: {prize} рублей!

Для получения денежного приза отправьте ваш номер телефона:
+7XXXXXXXXXX или 8XXXXXXXXXX

Пример: +79123456789"""
    
    await message.answer(response)

# Обработка текста (номер телефона)
@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: types.Message):
    text = message.text.strip()
    
    # Если это похоже на номер телефона
    if any(c.isdigit() for c in text) and (text.startswith('+7') or text.startswith('8')) and len(text.replace('+', '')) >= 11:
        bank_request = """📋 Отлично! Теперь укажите ваш банк для перевода:

Например:
- Сбербанк
- Тинькофф
- Альфа-Банк
- ВТБ
- или другой банк

Отправьте название банка:"""
        await message.answer(bank_request)
    
    # Если это банк
    elif any(word in text.lower() for word in ['сбер', 'тиньк', 'альфа', 'втб', 'банк', 'тинькофф']):
        final_message = """🎊 Поздравляем! Заявка оформлена!

✅ Данные для выплаты сохранены

⏳ Обработка выплаты:
Ваша заявка принята. 
Выплаты происходят в течение 24 часов.

💰 Деньги будут переведены в течение 1-3 рабочих дней.

Спасибо за участие! 🎉

Для нового бонуса нажмите /start"""
        await message.answer(final_message)
    
    else:
        await message.answer("Для начала работы нажмите /start")

# Главная функция
async def main():
    logger.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
