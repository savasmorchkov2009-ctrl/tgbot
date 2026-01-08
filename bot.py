import os
import random
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получение токена из переменных окружения
BOT_TOKEN = os.getenv("5932864783:AAFbN42qyJBtbuyqo3wD2i2I3OTKEdpq1qI")
ADMIN_ID = int(os.getenv("5189651311"))  # ID администратора для получения заявок

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Ссылки для кнопок (замените на свои)
VK_REVIEW_LINK = "https://clck.ru/3QTvTp"
YANDEX_REVIEW_LINK = "https://clck.ru/3QTRfj"
TWOGIS_REVIEW_LINK = "https://clck.ru/3QsAsL"

# Состояния FSM
class UserState(StatesGroup):
    waiting_for_screenshot = State()
    waiting_for_phone = State()
    waiting_for_bank = State()

# Хранение данных пользователя (в продакшене лучше использовать БД)
user_data = {}

# Клавиатура с основными кнопками
def get_main_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(
        InlineKeyboardButton(text="⭐ Бонус за отзыв 5", callback_data="get_bonus"),
        InlineKeyboardButton(text="📘 Отзыв в VK", url=VK_REVIEW_LINK),
        InlineKeyboardButton(text="🌐 Отзыв в Яндексе", url=YANDEX_REVIEW_LINK),
        InlineKeyboardButton(text="🗺️ Отзыв в 2ГИС", url=TWOGIS_REVIEW_LINK)
    )
    keyboard.adjust(1)
    return keyboard.as_markup()

# Приветственное сообщение
@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = """Здравствуйте! 😊

Добро пожаловать в бот для получения бонусов!
Размер приза от 150 до 200 рублей

Вы также можете оставить отзывы на других площадках и получить бонус!"""
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard())

# Обработка нажатия кнопки "Бонус за отзыв"
@dp.callback_query(F.data == "get_bonus")
async def process_bonus(callback: types.CallbackQuery, state: FSMContext):
    instructions = """⭐ Как получить бонус:

1. Оставьте отзыв на ⭐️⭐️⭐️⭐️⭐️ о нашем сервисе (Авито, Суточно, Островок, Озон, ВК, Яндекс)
2. Сделайте скриншот вашего отзыва
3. Отправьте скриншот сюда

После проверки вы получите случайный денежный приз от 150 до 200 рублей!

Отправьте скриншот отзыва:"""
    
    await callback.message.edit_text(instructions)
    await state.set_state(UserState.waiting_for_screenshot)
    await callback.answer()

# Обработка скриншота
@dp.message(UserState.waiting_for_screenshot, F.photo)
async def process_screenshot(message: Message, state: FSMContext):
    # Генерируем случайную сумму от 150 до 200
    prize_amount = random.randint(150, 200)
    
    # Сохраняем данные пользователя
    user_data[message.from_user.id] = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "full_name": message.from_user.full_name,
        "screenshot_id": message.photo[-1].file_id,
        "prize_amount": prize_amount,
        "phone": None,
        "bank": None
    }
    
    # Сообщение о принятии скриншота
    success_text = f"""✅ Отличная работа!

Скриншот принят и сохранен! 
Спасибо за ваш отзыв! 🙏

🎉 Ваш выигрыш: {prize_amount} рублей!

Для получения денежного приза отправьте ваш номер телефона:
+7XXXXXXXXXX или 8XXXXXXXXXX

Пример: +79123456789"""
    
    await message.answer(success_text)
    await state.set_state(UserState.waiting_for_phone)

# Обработка номера телефона
@dp.message(UserState.waiting_for_phone, F.text)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    
    # Простая валидация номера телефона
    if not (phone.startswith('+7') or phone.startswith('8')) or len(phone.replace('+', '')) != 11:
        await message.answer("❌ Пожалуйста, введите номер телефона в правильном формате:\n+7XXXXXXXXXX или 8XXXXXXXXXX\n\nПример: +79123456789")
        return
    
    # Сохраняем номер телефона
    if message.from_user.id in user_data:
        user_data[message.from_user.id]["phone"] = phone
    
    bank_request = """📋 Отлично! Теперь укажите ваш банк для перевода:

Например:
- Сбербанк
- Тинькофф
- Альфа-Банк
- ВТБ
- или другой банк

Отправьте название банка:"""
    
    await message.answer(bank_request)
    await state.set_state(UserState.waiting_for_bank)

# Обработка названия банка
@dp.message(UserState.waiting_for_bank, F.text)
async def process_bank(message: Message, state: FSMContext):
    bank = message.text.strip()
    
    # Сохраняем банк
    if message.from_user.id in user_data:
        user_data[message.from_user.id]["bank"] = bank
        
        # Получаем данные пользователя
        user_info = user_data[message.from_user.id]
        
        # Отправляем сообщение об успешном оформлении
        final_message = f"""🎊 Поздравляем! Заявка оформлена!

✅ Данные для выплаты:
- Сумма: {user_info['prize_amount']} рублей
- Телефон: {user_info['phone']}
- Банк: {bank}

⏳ Обработка выплаты:
Ваша заявка принята. 
Выплаты происходят в течение 24 часов.

💰 Деньги будут переведены в течение 1-3 рабочих дней.

Спасибо за участие! 🎉

Для нового бонуса нажмите /start"""
        
        await message.answer(final_message)
        
        # Отправляем заявку администратору
        await send_to_admin(user_info)
    
    await state.clear()

# Функция отправки заявки администратору
async def send_to_admin(user_info):
    admin_message = f"""📨 Новая заявка на бонус!

👤 Пользователь:
ID: {user_info['user_id']}
Имя: {user_info['full_name']}
Username: @{user_info['username'] if user_info['username'] else 'Не указан'}

💰 Сумма: {user_info['prize_amount']} руб.
📱 Телефон: {user_info['phone']}
🏦 Банк: {user_info['bank']}

Скриншот отправлен."""
    
    try:
        # Отправляем текстовое сообщение
        await bot.send_message(ADMIN_ID, admin_message)
        
        # Отправляем скриншот (если есть)
        if user_info.get('screenshot_id'):
            await bot.send_photo(ADMIN_ID, user_info['screenshot_id'], 
                                 caption="Скриншот отзыва")
        
        logger.info(f"Заявка отправлена администратору для пользователя {user_info['user_id']}")
    except Exception as e:
        logger.error(f"Ошибка при отправке заявки администратору: {e}")

# Обработка текстовых сообщений не в состояниях
@dp.message()
async def handle_other_messages(message: Message):
    if message.text and not message.text.startswith('/'):
        await message.answer("Для получения бонуса нажмите на кнопку ниже или введите /start", 
                           reply_markup=get_main_keyboard())

# Основная функция запуска бота
async def main():
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
