import logging
import random
import os
import sqlite3
import signal
import sys
import time
import asyncio
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler
)

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"  # ЗАМЕНИТЕ
ADMIN_ID = 123456789  # ЗАМЕНИТЕ на ваш Telegram ID

# Ссылки для кнопок отзывов
VK_REVIEW_LINK = "https://vk.com/ВАША_СТРАНИЦА"
YANDEX_REVIEW_LINK = "https://yandex.ru/ВАША_СТРАНИЦА"
TWOGIS_REVIEW_LINK = "https://2gis.ru/ВАША_СТРАНИЦА"

# Состояния для ConversationHandler
WAITING_FOR_REVIEW, WAITING_FOR_PHONE, WAITING_FOR_BANK = range(3)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Папка для сохранения скриншотов
SCREENSHOTS_FOLDER = "screenshots"
os.makedirs(SCREENSHOTS_FOLDER, exist_ok=True)

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
bot_start_time = datetime.now()
total_requests_this_session = 0
bot_restart_count = 0
application_instance = None  # Глобальная переменная для экземпляра Application

# ==================== ОБРАБОТЧИКИ СИГНАЛОВ ====================
def signal_handler(signum, frame):
    """Graceful shutdown при получении сигналов"""
    logger.info(f"Получен сигнал {signum}. Завершаем работу...")
    
    # Останавливаем бота перед выходом
    if application_instance:
        logger.info("Останавливаем приложение бота...")
        # Используем asyncio для асинхронной остановки
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(application_instance.stop())
                loop.create_task(application_instance.shutdown())
        except:
            pass
    
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==================== ФУНКЦИИ МОНИТОРИНГА ====================
def get_free_space():
    """Получение информации о свободном месте на диске"""
    try:
        import shutil
        total, used, free = shutil.disk_usage(".")
        free_gb = free / (1024**3)
        return round(free_gb, 2)
    except:
        return "N/A"

# ==================== БАЗА ДАННЫХ ====================
def get_db_connection():
    """Создание подключения к базе данных"""
    try:
        conn = sqlite3.connect('requests.db', timeout=10)
        conn.row_factory = sqlite3.Row  # Для доступа к колонкам по имени
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        return None

def init_database():
    """Инициализация базы данных"""
    conn = get_db_connection()
    if not conn:
        logger.error("Не удалось подключиться к БД")
        return False
    
    try:
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS requests
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      username TEXT,
                      full_name TEXT,
                      phone TEXT,
                      bank TEXT,
                      amount INTEGER,
                      screenshot_path TEXT,
                      status TEXT DEFAULT 'pending',
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                      processed_at TIMESTAMP,
                      admin_id INTEGER,
                      admin_username TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS daily_stats
                     (date DATE PRIMARY KEY,
                      total_requests INTEGER DEFAULT 0,
                      approved_requests INTEGER DEFAULT 0,
                      rejected_requests INTEGER DEFAULT 0,
                      total_amount INTEGER DEFAULT 0)''')
        
        conn.commit()
        logger.info("✅ База данных успешно инициализирована")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False
    finally:
        if conn:
            conn.close()

def add_request(user_data):
    """Добавление новой заявки в БД"""
    global total_requests_this_session
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        c = conn.cursor()
        c.execute('''INSERT INTO requests 
                     (user_id, username, full_name, phone, bank, amount, screenshot_path, status, created_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user_data['user_id'], user_data['username'], user_data['full_name'],
                   user_data['phone'], user_data['bank'], user_data['prize_amount'],
                   user_data.get('file_path'), 'pending', datetime.now()))
        
        today = datetime.now().date()
        c.execute('''INSERT OR IGNORE INTO daily_stats (date) VALUES (?)''', (today,))
        c.execute('''UPDATE daily_stats SET total_requests = total_requests + 1 WHERE date = ?''', (today,))
        
        conn.commit()
        request_id = c.lastrowid
        
        total_requests_this_session += 1
        logger.info(f"✅ Заявка #{request_id} добавлена в БД. Всего за сессию: {total_requests_this_session}")
        return request_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления заявки в БД: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ==================== ОТПРАВКА ЗАЯВКИ АДМИНИСТРАТОРУ ====================
async def download_file(bot, file_id, user_id):
    """Скачивает файл и сохраняет на компьютер"""
    try:
        file = await bot.get_file(file_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{SCREENSHOTS_FOLDER}/user_{user_id}_{timestamp}.jpg"
        await file.download_to_drive(filename)
        logger.info(f"📸 Файл сохранен: {filename}")
        return filename
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания файла: {e}")
        return None

async def send_to_admin(bot, user_data, request_id):
    """Отправляет заявку администратору в Telegram"""
    try:
        admin_message = f"""
📋 **НОВАЯ ЗАЯВКА #{request_id}**

👤 **Информация о пользователе:**
├ ID: `{user_data['user_id']}`
├ Username: @{user_data['username'] or 'Нет'}
├ Имя: {user_data['full_name']}
├ Дата: {user_data['timestamp'].strftime('%d.%m.%Y %H:%M:%S')}

💰 **Данные для выплаты:**
├ Сумма: {user_data['prize_amount']} рублей
├ Телефон: `{user_data['phone']}`
├ Банк: {user_data['bank']}

📊 **Статус:** ⏳ *Ожидает проверки*
        """
        
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            parse_mode='Markdown'
        )
        
        # Если есть скриншот, отправляем его
        if user_data.get('file_path') and os.path.exists(user_data['file_path']):
            try:
                with open(user_data['file_path'], 'rb') as photo:
                    await bot.send_photo(
                        chat_id=ADMIN_ID,
                        photo=InputFile(photo),
                        caption=f"📸 Скриншот от пользователя ID: {user_data['user_id']}"
                    )
            except Exception as e:
                logger.error(f"❌ Ошибка отправки скриншота админу: {e}")
        
        # Добавляем кнопки действий для админа
        keyboard = [
            [
                InlineKeyboardButton("✅ Выплатить", callback_data=f"approve_{request_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{request_id}")
            ],
            [
                InlineKeyboardButton("💬 Написать", url=f"tg://user?id={user_data['user_id']}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"⚡ **Действия по заявке #{request_id}:**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        logger.info(f"✅ Заявка #{request_id} отправлена админу {ADMIN_ID}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки админу: {e}")
        return False

# ==================== ОБРАБОТКА КНОПОК АДМИНА ====================
async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатий кнопок админом"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    admin_id = query.from_user.id
    admin_username = query.from_user.username
    
    if data.startswith('approve_'):
        request_id = int(data.split('_')[1])
        
        # Обновляем статус в БД
        conn = get_db_connection()
        if conn:
            try:
                c = conn.cursor()
                c.execute('''UPDATE requests SET 
                             status = 'approved', 
                             processed_at = ?,
                             admin_id = ?,
                             admin_username = ?
                             WHERE id = ?''',
                          (datetime.now(), admin_id, admin_username, request_id))
                
                # Получаем данные заявки для уведомления пользователя
                c.execute('SELECT user_id, amount FROM requests WHERE id = ?', (request_id,))
                row = c.fetchone()
                conn.commit()
                
                # Обновляем сообщение у админа
                await query.edit_message_text(
                    text=f"✅ **Заявка #{request_id} - ВЫПЛАЧЕНО**\n\n"
                         f"Время: {datetime.now().strftime('%H:%M:%S')}\n"
                         f"Админ: {admin_username or query.from_user.first_name}",
                    parse_mode='Markdown'
                )
                
                # Уведомляем пользователя
                if row:
                    user_id, amount = row
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"🎉 **Ваша заявка #{request_id} одобрена!**\n\n"
                                 f"💰 Сумма: {amount} рублей\n"
                                 f"⏰ Деньги будут переведены в течение 24 часов."
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления пользователя: {e}")
            except Exception as e:
                logger.error(f"Ошибка обновления статуса заявки: {e}")
            finally:
                conn.close()
                
    elif data.startswith('reject_'):
        request_id = int(data.split('_')[1])
        
        # Обновляем статус в БД
        conn = get_db_connection()
        if conn:
            try:
                c = conn.cursor()
                c.execute('''UPDATE requests SET 
                             status = 'rejected', 
                             processed_at = ?,
                             admin_id = ?,
                             admin_username = ?
                             WHERE id = ?''',
                          (datetime.now(), admin_id, admin_username, request_id))
                
                # Получаем user_id для уведомления
                c.execute('SELECT user_id FROM requests WHERE id = ?', (request_id,))
                row = c.fetchone()
                conn.commit()
                
                # Обновляем сообщение у админа
                await query.edit_message_text(
                    text=f"❌ **Заявка #{request_id} - ОТКЛОНЕНО**\n\n"
                         f"Время: {datetime.now().strftime('%H:%M:%S')}\n"
                         f"Админ: {admin_username or query.from_user.first_name}",
                    parse_mode='Markdown'
                )
                
                # Уведомляем пользователя
                if row:
                    user_id = row[0]
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=f"❌ **Ваша заявка #{request_id} отклонена.**\n\n"
                                 f"ℹ️ Проверьте корректность предоставленных данных.\n"
                                 f"Для новой заявки нажмите /start"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления пользователя: {e}")
            except Exception as e:
                logger.error(f"Ошибка обновления статуса заявки: {e}")
            finally:
                conn.close()

# ==================== ОСНОВНЫЕ КОМАНДЫ БОТА ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    keyboard = [
        [KeyboardButton("🎁 Бонус за отзыв ⭐⭐⭐⭐⭐")],
        [KeyboardButton("📝 Отзыв в VK")],
        [KeyboardButton("🔍 Отзыв в Яндексе")],
        [KeyboardButton("🗺️ Отзыв в 2ГИС")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    welcome_text = f"""Здравствуйте! 😊

Добро пожаловать в бот для получения бонусов!
Размер приза от 150 до 200 рублей! 💰
    """
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    context.user_data.clear()
    context.user_data['user_id'] = user.id
    context.user_data['username'] = user.username
    context.user_data['full_name'] = f"{user.first_name} {user.last_name or ''}".strip()
    return ConversationHandler.END

async def handle_platform_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок отзывов на платформах"""
    text = update.message.text
    if text == "📝 Отзыв в VK":
        await update.message.reply_text(
            f"📝 **Оставить отзыв в VK:**\n\n{VK_REVIEW_LINK}\n\n"
            f"После отзыва нажмите '🎁 Бонус за отзыв ⭐⭐⭐⭐⭐'!",
            parse_mode='Markdown'
        )
    elif text == "🔍 Отзыв в Яндексе":
        await update.message.reply_text(
            f"🔍 **Оставить отзыв в Яндекс:**\n\n{YANDEX_REVIEW_LINK}\n\n"
            f"После отзыва нажмите '🎁 Бонус за отзыв ⭐⭐⭐⭐⭐'!",
            parse_mode='Markdown'
        )
    elif text == "🗺️ Отзыв в 2ГИС":
        await update.message.reply_text(
            f"🗺️ **Оставить отзыв в 2ГИС:**\n\n{TWOGIS_REVIEW_LINK}\n\n"
            f"После отзыва нажмите '🎁 Бонус за отзыв ⭐⭐⭐⭐⭐'!",
            parse_mode='Markdown'
        )
    return ConversationHandler.END

async def bonus_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопки бонуса"""
    instruction_text = """
📱 **Как получить бонус:**

1. Оставьте отзыв на ⭐⭐⭐⭐⭐
2. Сделайте скриншот
3. Отправьте скриншот сюда

Приз: 150-200 рублей!

Отправьте скриншот отзыва:
    """
    await update.message.reply_text(instruction_text, parse_mode='Markdown')
    return WAITING_FOR_REVIEW

async def handle_review_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка скриншота"""
    user = update.effective_user
    bot = context.bot
    
    try:
        file_id = None
        filename = None
        
        if update.message.photo:
            photo = update.message.photo[-1]
            file_id = photo.file_id
            filename = await download_file(bot, file_id, user.id)
        elif update.message.document:
            document = update.message.document
            file_id = document.file_id
            filename = await download_file(bot, file_id, user.id)
        
        if file_id:
            context.user_data['file_id'] = file_id
            context.user_data['file_path'] = filename
            prize_amount = random.randint(150, 200)
            context.user_data['prize_amount'] = prize_amount
            
            prize_text = f"""
✅ **Отличная работа!**

🎉 **Ваш выигрыш: {prize_amount} рублей!**

Отправьте номер телефона:
`+7XXXXXXXXXX` или `8XXXXXXXXXX`

Пример: +79123456789
            """
            await update.message.reply_text(prize_text, parse_mode='Markdown')
            return WAITING_FOR_PHONE
        else:
            await update.message.reply_text("❌ Отправьте скриншот в виде фото или документа.")
            return WAITING_FOR_REVIEW
            
    except Exception as e:
        logger.error(f"Ошибка обработки файла: {e}")
        await update.message.reply_text("❌ Ошибка. Попробуйте еще раз.")
        return WAITING_FOR_REVIEW

async def handle_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка номера телефона"""
    phone = update.message.text.strip()
    
    if (phone.startswith('+7') and len(phone) == 12 and phone[1:].isdigit()) or \
       (phone.startswith('8') and len(phone) == 11 and phone.isdigit()) or \
       (phone.startswith('7') and len(phone) == 11 and phone.isdigit()):
        
        context.user_data['phone'] = phone
        bank_text = """
📋 **Отлично! Укажите ваш банк:**

Например:
- Сбербанк
- Тинькофф
- Альфа-Банк
- ВТБ
- или другой банк

Отправьте название банка:
        """
        await update.message.reply_text(bank_text, parse_mode='Markdown')
        return WAITING_FOR_BANK
    else:
        await update.message.reply_text(
            "❌ Неверный формат номера.\n"
            "Правильный формат: `+7XXXXXXXXXX` или `8XXXXXXXXXX`\n"
            "Пример: +79123456789",
            parse_mode='Markdown'
        )
        return WAITING_FOR_PHONE

async def handle_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка названия банка и завершение заявки"""
    bank = update.message.text.strip()
    context.user_data['bank'] = bank
    
    # Собираем все данные
    user_data = {
        'user_id': context.user_data['user_id'],
        'username': context.user_data.get('username'),
        'full_name': context.user_data.get('full_name'),
        'phone': context.user_data['phone'],
        'bank': bank,
        'prize_amount': context.user_data['prize_amount'],
        'timestamp': datetime.now(),
        'file_path': context.user_data.get('file_path')
    }
    
    # Сохраняем в БД и получаем ID заявки
    request_id = add_request(user_data)
    
    if request_id:
        # Отправляем заявку администратору
        await send_to_admin(context.bot, user_data, request_id)
        
        # Сообщение пользователю
        final_text = f"""
🎊 **Заявка #{request_id} оформлена!**

✅ **Данные:**
- Сумма: {user_data['prize_amount']} рублей
- Телефон: {user_data['phone']}
- Банк: {user_data['bank']}

⏳ **Обработка:**
Заявка отправлена на проверку.
Выплаты в течение 24 часов.

💰 **Деньги будут переведены в течение 1-3 рабочих дней.**

Спасибо! 🎉

**Вы также можете оставить отзывы на других площадках!**
        """
    else:
        final_text = "❌ Ошибка сохранения заявки. Попробуйте позже."
    
    await update.message.reply_text(final_text, parse_mode='Markdown')
    await update.message.reply_text("Для нового бонуса нажмите /start", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога"""
    await update.message.reply_text("Диалог отменен. Для начала нажмите /start", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    help_text = """
🤖 **Помощь по боту:**

/start - Начать работу
/help - Помощь

Для получения бонуса:
1. Нажмите "🎁 Бонус за отзыв ⭐⭐⭐⭐⭐"
2. Отправьте скриншот
3. Укажите телефон и банк
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать мои заявки"""
    user_id = update.effective_user.id
    
    try:
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ Ошибка подключения к БД.")
            return
        
        c = conn.cursor()
        c.execute('''SELECT * FROM requests WHERE user_id = ? ORDER BY created_at DESC LIMIT 5''', (user_id,))
        rows = c.fetchall()
        conn.close()
        
        if not rows:
            await update.message.reply_text("📭 У вас еще нет заявок.")
            return
        
        text = "📋 **Ваши последние заявки:**\n\n"
        for row in rows:
            req_id, _, _, full_name, phone, bank, amount, _, status, created_at, *_ = row
            created = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S') if isinstance(created_at, str) else created_at
            
            status_icons = {'pending': '⏳', 'approved': '✅', 'rejected': '❌'}
            text += f"**Заявка #{req_id}** {status_icons.get(status, '❓')}\n"
            text += f"💰 {amount} руб | 🏦 {bank}\n"
            text += f"📅 {created.strftime('%d.%m.%Y %H:%M')}\n"
            text += f"🔸 Статус: {status}\n"
            text += "─" * 20 + "\n"
        
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка получения заявок: {e}")
        await update.message.reply_text("❌ Ошибка получения данных. Попробуйте позже.")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель администратора"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    try:
        conn = get_db_connection()
        if not conn:
            await update.message.reply_text("❌ Ошибка подключения к БД.")
            return
        
        c = conn.cursor()
        c.execute('''SELECT COUNT(*) as total,
                            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                            SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
                            SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                            SUM(CASE WHEN status = 'approved' THEN amount ELSE 0 END) as total_amount
                     FROM requests''')
        row = c.fetchone()
        conn.close()
        
        if row:
            uptime = datetime.now() - bot_start_time
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            stats_text = f"""
👑 **Панель администратора**

📊 **Статистика:**
├ Всего заявок: {row['total']}
├ Ожидают: {row['pending'] or 0}
├ Выплачены: {row['approved'] or 0}
├ Отклонены: {row['rejected'] or 0}
└ Общая сумма: {row['total_amount'] or 0} руб

📈 **Система:**
├ Аптайм: {uptime.days}д {hours}ч {minutes}м
├ Заявок/сессия: {total_requests_this_session}
└ Свободно: {get_free_space()} ГБ

💡 **Действия:**
- Все новые заявки приходят сюда автоматически
- Используйте кнопки под сообщениями для обработки
            """
            await update.message.reply_text(stats_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await update.message.reply_text("❌ Ошибка получения статистики.")

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================
async def main_async():
    """Асинхронная основная функция"""
    global application_instance, bot_restart_count
    
    max_retries = 100  # Максимальное количество перезапусков
    retry_delay = 30   # Задержка между перезапусками в секундах
    
    while bot_restart_count < max_retries:
        try:
            logger.info(f"🤖 Запуск бота (попытка #{bot_restart_count + 1})")
            
            # Инициализация БД
            if not init_database():
                logger.error("Не удалось инициализировать БД")
                await asyncio.sleep(retry_delay)
                bot_restart_count += 1
                continue
            
            # Создаем приложение
            application_instance = Application.builder().token(BOT_TOKEN).build()
            
            # Обработка кнопок платформ
            application_instance.add_handler(MessageHandler(
                filters.TEXT & filters.Regex('^(📝 Отзыв в VK|🔍 Отзыв в Яндексе|🗺️ Отзыв в 2ГИС)$'), 
                handle_platform_review
            ))
            
            # ConversationHandler для основного диалога
            conv_handler = ConversationHandler(
                entry_points=[
                    MessageHandler(filters.TEXT & filters.Regex('^🎁 Бонус за отзыв ⭐⭐⭐⭐⭐$'), bonus_button),
                    CommandHandler('start', start)
                ],
                states={
                    WAITING_FOR_REVIEW: [
                        MessageHandler(filters.PHOTO | filters.Document.IMAGE, handle_review_screenshot),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, 
                                      lambda u, c: u.message.reply_text("Отправьте скриншот отзыва"))
                    ],
                    WAITING_FOR_PHONE: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_phone)
                    ],
                    WAITING_FOR_BANK: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bank)
                    ],
                },
                fallbacks=[
                    CommandHandler('cancel', cancel),
                    CommandHandler('start', start),
                    CommandHandler('help', help_command)
                ],
            )
            
            # Добавляем обработчики
            application_instance.add_handler(conv_handler)
            application_instance.add_handler(CommandHandler("help", help_command))
            application_instance.add_handler(CommandHandler("start", start))
            application_instance.add_handler(CommandHandler("myrequests", my_requests))
            application_instance.add_handler(CommandHandler("admin", admin_panel))
            
            # Обработчик callback кнопок админа
            application_instance.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^approve_|^reject_"))
            
            # Запускаем бота
            bot_restart_count += 1
            logger.info(f"✅ Бот запущен! Ожидаем сообщений...")
            
            # Отправляем уведомление админу о запуске
            try:
                startup_message = f"""
🚀 **Бот запущен**

✅ Бот успешно запущен
🔄 Перезапуск #{bot_restart_count}
⏰ Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
                """
                await application_instance.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=startup_message,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление о запуске: {e}")
            
            # Основной цикл работы бота
            await application_instance.run_polling()
            
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем (Ctrl+C)")
            break
            
        except Exception as e:
            logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: {e}")
            
            # Отправляем уведомление админу об ошибке
            try:
                error_message = f"""
🔴 **Бот упал с ошибкой**

❌ Ошибка: {str(e)[:100]}
🔄 Перезапуск через {retry_delay} секунд...
📅 Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
                """
                # Используем requests для отправки, если бот не работает
                import requests
                requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": ADMIN_ID,
                        "text": error_message,
                        "parse_mode": "Markdown"
                    },
                    timeout=10
                )
            except:
                pass
            
            # Ждем перед перезапуском
            logger.info(f"Перезапуск через {retry_delay} секунд...")
            await asyncio.sleep(retry_delay)
            
            # Очищаем старый event loop при перезапуске
            try:
                if application_instance:
                    await application_instance.stop()
                    await application_instance.shutdown()
                    application_instance = None
            except:
                pass
    
    logger.error(f"Достигнут максимум перезапусков ({max_retries}). Бот остановлен.")

def main():
    """Точка входа в программу"""
    print("\n" + "="*60)
    print("🤖 TELEGRAM BOT 24/7")
    print("="*60)
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"📁 Лог файл: bot.log")
    print(f"💾 База данных: requests.db")
    print(f"🖼️ Скриншоты: {SCREENSHOTS_FOLDER}")
    print("="*60)
    print("🚀 Запускаем бота с автоперезапуском...")
    print("⚠️  Для остановки нажмите Ctrl+C")
    print("="*60 + "\n")
    
    # Запускаем асинхронную основную функцию
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен")
    except Exception as e:
        logger.critical(f"Фатальная ошибка: {e}")

if __name__ == '__main__':
    main()
