import os
import random
import logging
import sqlite3
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === НАСТРОЙКИ ===
# ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ НА СВОИ!
BOT_TOKEN = "5932864783:AAFbN42qyJBtbuyqo3wD2i2I3OTKEdpq1qI"  # Пример: "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz-123456789"
ADMIN_ID = 1996778406  # Пример: 987654321 (только цифры, ваш Telegram ID)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('applications.db')
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
        status TEXT DEFAULT 'new'
    )
    ''')
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# Хранилище состояний пользователей
user_states = {}

# ========== ФУНКЦИИ ДЛЯ АДМИНА ==========

async def send_admin_notification(text):
    """Отправляет уведомление администратору"""
    try:
        await bot.send_message(ADMIN_ID, text)
        logger.info(f"✅ Уведомление отправлено админу: {text[:50]}...")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка отправки админу: {e}")
        return False

async def notify_admin_new_app(user_id, state, bank, user):
    """Уведомление о новой заявке"""
    admin_message = f"""📨 НОВАЯ ЗАЯВКА #{random.randint(1000, 9999)}

👤 Пользователь:
ID: {user_id}
Имя: {user.full_name}
Username: @{user.username if user.username else 'нет'}

💰 Сумма: {state['prize_amount']} руб.
📱 Телефон: {state['phone']}
🏦 Банк: {bank}

📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}

⚠️ Проверьте скриншот ниже 👇"""
    
    await send_admin_notification(admin_message)
    
    # Отправляем скриншот
    try:
        await bot.send_photo(
            ADMIN_ID, 
            state['screenshot_id'], 
            caption=f"📸 Скриншот от {user.full_name}"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки скриншота админу: {e}")

def save_application(user_id, username, full_name, screenshot_id, prize_amount, phone, bank):
    """Сохраняет заявку в базу данных"""
    conn = sqlite3.connect('applications.db')
    cursor = conn.cursor()
    cursor.execute('''
    INSERT INTO applications (user_id, username, full_name, screenshot_id, prize_amount, phone, bank)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, username, full_name, screenshot_id, prize_amount, phone, bank))
    conn.commit()
    conn.close()
    return cursor.lastrowid

def get_admin_stats():
    """Получает статистику для админа"""
    conn = sqlite3.connect('applications.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM applications")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM applications WHERE status = 'new'")
    new = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM applications WHERE status = 'paid'")
    paid = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(prize_amount) FROM applications")
    total_sum = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT SUM(prize_amount) FROM applications WHERE status = 'paid'")
    paid_sum = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return {
        'total': total,
        'new': new,
        'paid': paid,
        'total_sum': total_sum,
        'paid_sum': paid_sum
    }

# ========== КОМАНДЫ ПОЛЬЗОВАТЕЛЕЙ ==========

@dp.message(Command("start"))
async def start_command(message: types.Message):
    """Команда /start для пользователей"""
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

@dp.callback_query(F.data == "bonus")
async def process_bonus(callback_query: types.CallbackQuery):
    """Обработка кнопки получения бонуса"""
    instructions = """⭐ Как получить бонус:

1. Оставьте отзыв на ⭐️⭐️⭐️⭐️⭐️ о нашем сервисе (Авито, Суточно, Островок, Озон, ВК, Яндекс)
2. Сделайте скриншот вашего отзыва
3. Отправьте скриншот сюда

После проверки вы получите случайный денежный приз от 150 до 200 рублей!

Отправьте скриншот отзыва:"""
    
    await callback_query.message.answer(instructions)
    await callback_query.answer("Инструкции отправлены! 📝")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    """Обработка скриншотов"""
    prize = random.randint(150, 200)
    
    # Сохраняем состояние пользователя
    user_states[message.from_user.id] = {
        'screenshot_id': message.photo[-1].file_id,
        'prize_amount': prize,
        'step': 'phone',
        'user_info': {
            'username': message.from_user.username,
            'full_name': message.from_user.full_name
        }
    }
    
    response = f"""✅ Отличная работа!

Скриншот принят и сохранен! 
Спасибо за ваш отзыв! 🙏

🎉 Ваш выигрыш: {prize} рублей!

Для получения денежного приза отправьте ваш номер телефона:
+7XXXXXXXXXX или 8XXXXXXXXXX

Пример: +79123456789"""
    
    await message.answer(response)

@dp.message(F.text & ~F.text.startswith('/'))
async def handle_text(message: types.Message):
    """Обработка текстовых сообщений"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Проверяем состояние пользователя
    if user_id in user_states:
        state = user_states[user_id]
        
        if state['step'] == 'phone':
            # Проверка номера телефона
            if (text.startswith('+7') or text.startswith('8')) and len(text.replace('+', '')) == 11 and text.replace('+', '').isdigit():
                state['phone'] = text
                state['step'] = 'bank'
                
                bank_request = """📋 Отлично! Теперь укажите ваш банк для перевода:

Например:
- Сбербанк
- Тинькофф
- Альфа-Банк
- ВТБ
- или другой банк

Отправьте название банка:"""
                await message.answer(bank_request)
            else:
                await message.answer("❌ Неверный формат номера. Пример: +79123456789")
        
        elif state['step'] == 'bank':
            # Сохраняем заявку в БД
            app_id = save_application(
                user_id,
                state['user_info']['username'],
                state['user_info']['full_name'],
                state['screenshot_id'],
                state['prize_amount'],
                state['phone'],
                text
            )
            
            # Отправляем уведомление админу
            await notify_admin_new_app(
                user_id, 
                state, 
                text, 
                message.from_user
            )
            
            final_message = f"""🎊 Поздравляем! Заявка #{app_id} оформлена!

✅ Данные для выплаты:
- Сумма: {state['prize_amount']} рублей
- Телефон: {state['phone']}
- Банк: {text}

⏳ Обработка выплаты:
Ваша заявка принята. 
Выплаты происходят в течение 24 часов.

💰 Деньги будут переведены в течение 1-3 рабочих дней.

Спасибо за участие! 🎉

Для нового бонуса нажмите /start"""
            
            await message.answer(final_message)
            
            # Удаляем состояние пользователя
            del user_states[user_id]
    
    else:
        await message.answer("Для начала работы нажмите /start")

# ========== АДМИН ПАНЕЛЬ ==========

@dp.message(Command("admin"))
async def admin_command(message: types.Message):
    """Команда /admin для админа"""
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещен!")
        return
    
    stats = get_admin_stats()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton(text="📋 Новые заявки", callback_data="admin_new")],
        [InlineKeyboardButton(text="💰 Финансы", callback_data="admin_finance"),
         InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_refresh"),
         InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_close")]
    ])
    
    text = f"""🔐 ПАНЕЛЬ АДМИНИСТРАТОРА

📊 Статистика:
├ Всего заявок: {stats['total']}
├ Новых: {stats['new']}
└ Оплачено: {stats['paid']}

💰 Финансы:
├ Общая сумма: {stats['total_sum']} руб.
└ Выплачено: {stats['paid_sum']} руб.

🕒 Серверное время: {datetime.now().strftime('%H:%M:%S')}"""
    
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data.startswith("admin_"))
async def admin_panel_handler(callback_query: types.CallbackQuery):
    """Обработка админ-панели"""
    if callback_query.from_user.id != ADMIN_ID:
        await callback_query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    action = callback_query.data
    
    if action == "admin_close":
        await callback_query.message.delete()
        await callback_query.answer("Панель закрыта")
        return
    
    if action == "admin_refresh":
        await callback_query.message.delete()
        await admin_command(callback_query.message)
        await callback_query.answer("✅ Данные обновлены!")
        return
    
    stats = get_admin_stats()
    conn = sqlite3.connect('applications.db')
    cursor = conn.cursor()
    
    if action == "admin_stats":
        cursor.execute("SELECT * FROM applications ORDER BY created_at DESC LIMIT 5")
        recent_apps = cursor.fetchall()
        
        text = f"""📊 ДЕТАЛЬНАЯ СТАТИСТИКА

📈 Основные показатели:
├ Всего заявок: {stats['total']}
├ Новых: {stats['new']}
├ Оплачено: {stats['paid']}
└ Ожидают: {stats['total'] - stats['new'] - stats['paid']}

🔄 Последние 5 заявок:
"""
        if recent_apps:
            for app in recent_apps:
                text += f"\n├ #{app[0]} | {app[3]} | {app[5]} руб."
        else:
            text += "\n└ Нет заявок"
    
    elif action == "admin_new":
        cursor.execute("SELECT * FROM applications WHERE status = 'new' ORDER BY created_at DESC LIMIT 10")
        new_apps = cursor.fetchall()
        
        text = "🆕 ПОСЛЕДНИЕ НОВЫЕ ЗАЯВКИ:\n\n"
        if new_apps:
            for app in new_apps:
                text += f"🔸 #{app[0]}\n"
                text += f"👤 {app[3]} (@{app[2] if app[2] else 'нет'})\n"
                text += f"💰 {app[5]} руб. | 📱 {app[6]}\n"
                text += f"🏦 {app[7]} | 📅 {app[8][:16]}\n"
                text += "─" * 30 + "\n"
        else:
            text = "✅ Новых заявок нет"
    
    elif action == "admin_finance":
        cursor.execute("SELECT SUM(prize_amount) FROM applications WHERE status = 'new'")
        pending_sum = cursor.fetchone()[0] or 0
        
        text = f"""💰 ФИНАНСОВАЯ ОТЧЕТНОСТЬ

💵 Общая сумма всех заявок: {stats['total_sum']} руб.
✅ Выплачено: {stats['paid_sum']} руб.
⏳ Ожидают выплаты: {pending_sum} руб.
📊 В обработке: {stats['total_sum'] - stats['paid_sum'] - pending_sum} руб.

📅 Средний чек: {round(stats['total_sum']/stats['total'] if stats['total'] > 0 else 0, 2)} руб."""
    
    elif action == "admin_users":
        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM applications")
        unique_users = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT user_id, full_name, COUNT(*) as app_count, SUM(prize_amount) as total_sum
            FROM applications 
            GROUP BY user_id 
            ORDER BY app_count DESC 
            LIMIT 5
        """)
        top_users = cursor.fetchall()
        
        text = f"""👥 АКТИВНЫЕ ПОЛЬЗОВАТЕЛИ

👤 Уникальных пользователей: {unique_users}
📊 Среднее заявок на пользователя: {round(stats['total']/unique_users if unique_users > 0 else 0, 2)}

🏆 Топ-5 пользователей:
"""
        if top_users:
            for i, user in enumerate(top_users, 1):
                text += f"\n{i}. {user[1]}"
                text += f"\n   📊 {user[2]} заявок | 💰 {user[3]} руб."
        else:
            text += "\nНет данных о пользователях"
    
    conn.close()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton(text="📋 Новые заявки", callback_data="admin_new")],
        [InlineKeyboardButton(text="💰 Финансы", callback_data="admin_finance"),
         InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_refresh"),
         InlineKeyboardButton(text="❌ Закрыть", callback_data="admin_close")]
    ])
    
    await callback_query.message.edit_text(text, reply_markup=keyboard)
    await callback_query.answer()

# ========== ЗАПУСК И ОСТАНОВКА БОТА ==========

async def on_startup():
    """Действия при запуске бота"""
    logger.info("=" * 50)
    logger.info("🤖 БОТ ЗАПУСКАЕТСЯ...")
    logger.info(f"📊 Токен: {BOT_TOKEN[:15]}...")
    logger.info(f"👑 Админ ID: {ADMIN_ID}")
    logger.info("=" * 50)
    
    # Отправляем уведомление админу
    startup_msg = f"""🚀 БОТ ЗАПУЩЕН!

⏰ Время запуска: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
🤖 Статус: Активен ✅
📊 Версия: 2.0
👑 Администратор: ID {ADMIN_ID}

Бот готов к работе!"""
    
    await send_admin_notification(startup_msg)

async def on_shutdown():
    """Действия при остановке бота"""
    logger.info("=" * 50)
    logger.info("🛑 БОТ ОСТАНАВЛИВАЕТСЯ...")
    logger.info("=" * 50)
    
    # Отправляем уведомление админу
    shutdown_msg = f"""⚠️ БОТ ОСТАНОВЛЕН!

⏰ Время остановки: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
🤖 Статус: Неактивен ❌
📊 Причина: Перезапуск/Остановка

Бот будет перезапущен автоматически."""
    
    await send_admin_notification(shutdown_msg)

# Главная функция
async def main():
    """Основная функция запуска бота"""
    try:
        await on_startup()
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        
        # Отправляем уведомление об ошибке
        error_msg = f"""🚨 КРИТИЧЕСКАЯ ОШИБКА БОТА!

⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
❌ Ошибка: {str(e)[:200]}
🤖 Статус: Упал 💥

Бот будет перезапущен автоматически."""
        
        try:
            await send_admin_notification(error_msg)
        except:
            pass  # Если не удалось отправить уведомление
        
        raise e
    finally:
        await on_shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную")
    except Exception as e:
        logger.error(f"Необработанная ошибка: {e}")


