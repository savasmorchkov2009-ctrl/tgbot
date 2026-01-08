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
BOT_TOKEN = "5932864783:AAFbN42qyJBtbuyqo3wD2i2I3OTKEdpq1qI"  # ЗАМЕНИТЕ
ADMIN_ID = 1996778406  # ЗАМЕНИТЕ на ваш Telegram ID

# Ссылки для кнопок отзывов
VK_REVIEW_LINK = "https://clck.ru/3QTvTp"
YANDEX_REVIEW_LINK = "https://clck.ru/3QTRfj"
TWOGIS_REVIEW_LINK = "https://clck.ru/3QsAsL"

# Состояния для ConversationHandler
WAITING_FOR_REVIEW, WAITING_FOR_PHONE, WAITING_FOR_BANK = range(3)

# Настройка расширенного логирования для 24/7
log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)

# Создаем логгер
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Файловый обработчик с ротацией
file_handler = logging.FileHandler('bot_24_7.log', encoding='utf-8')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

# Консольный обработчик
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# Отключаем логирование от библиотек (опционально)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.INFO)

# Папка для сохранения скриншотов
SCREENSHOTS_FOLDER = "screenshots"
os.makedirs(SCREENSHOTS_FOLDER, exist_ok=True)

# ==================== ПЕРЕМЕННЫЕ ДЛЯ МОНИТОРИНГА ====================
bot_start_time = datetime.now()
total_requests = 0
bot_restart_count = 0

# ==================== ОБРАБОТЧИКИ СИГНАЛОВ ====================
def signal_handler(signum, frame):
    """Обработка сигналов для graceful shutdown"""
    logger.info(f"Получен сигнал {signum}. Завершаем работу...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==================== ФУНКЦИИ МОНИТОРИНГА ====================
async def send_health_check(context: ContextTypes.DEFAULT_TYPE):
    """Регулярная отправка статуса бота админу"""
    try:
        # Текущая статистика
        uptime = datetime.now() - bot_start_time
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        status_text = f"""
🏥 **Статус бота (Health Check)**

✅ Бот работает нормально
⏱ Аптайм: {uptime.days}д {hours}ч {minutes}м
🔄 Перезапусков: {bot_restart_count}
📊 Заявок за сессию: {total_requests}
📅 Серверное время: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
💾 Свободное место: {get_free_space()} ГБ
        """
        
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=status_text,
            parse_mode='Markdown'
        )
        logger.info("Health check отправлен администратору")
    except Exception as e:
        logger.error(f"Ошибка отправки health check: {e}")

def get_free_space():
    """Получение информации о свободном месте на диске"""
    try:
        stat = os.statvfs('.')
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        return round(free_gb, 2)
    except:
        return "N/A"

async def auto_backup(context: ContextTypes.DEFAULT_TYPE):
    """Автоматическое резервное копирование базы данных"""
    try:
        backup_dir = "backups"
        os.makedirs(backup_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{backup_dir}/requests_backup_{timestamp}.db"
        
        # Копируем базу данных
        import shutil
        shutil.copy2('requests.db', backup_file)
        
        # Удаляем старые бэкапы (оставляем последние 7)
        backups = sorted([f for f in os.listdir(backup_dir) if f.startswith('requests_backup_')])
        if len(backups) > 7:
            for old_backup in backups[:-7]:
                os.remove(os.path.join(backup_dir, old_backup))
        
        logger.info(f"Создан бэкап базы данных: {backup_file}")
    except Exception as e:
        logger.error(f"Ошибка создания бэкапа: {e}")

# ==================== БАЗА ДАННЫХ ====================
def init_database():
    """Инициализация базы данных с улучшенной обработкой ошибок"""
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            conn = sqlite3.connect('requests.db', timeout=10)
            c = conn.cursor()
            
            # Включаем WAL mode для лучшей производительности
            c.execute('PRAGMA journal_mode=WAL')
            c.execute('PRAGMA synchronous=NORMAL')
            
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
            
            # Индексы для ускорения поиска
            c.execute('CREATE INDEX IF NOT EXISTS idx_user_id ON requests(user_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_status ON requests(status)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON requests(created_at)')
            
            conn.commit()
            conn.close()
            logger.info("База данных успешно инициализирована")
            return True
            
        except sqlite3.Error as e:
            logger.error(f"Ошибка инициализации БД (попытка {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                logger.critical("Не удалось инициализировать базу данных после всех попыток")
                return False

def add_request(user_data):
    """Добавление новой заявки в БД"""
    global total_requests
    try:
        conn = sqlite3.connect('requests.db', timeout=5)
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
        conn.close()
        
        total_requests += 1
        logger.info(f"Заявка #{request_id} добавлена в БД. Всего за сессию: {total_requests}")
        return request_id
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка добавления заявки в БД: {e}")
        # Пробуем переподключиться
        init_database()
        return None

# ==================== ОТПРАВКА ЗАЯВКИ АДМИНИСТРАТОРУ ====================
async def download_file(bot, file_id, user_id):
    """Скачивает файл и сохраняет на компьютер"""
    try:
        file = await bot.get_file(file_id)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{SCREENSHOTS_FOLDER}/user_{user_id}_{timestamp}.jpg"
        await file.download_to_drive(filename)
        logger.info(f"Файл сохранен: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Ошибка скачивания файла: {e}")
        return None

async def send_to_admin(bot, user_data, request_id):
    """Отправляет заявку администратору в Telegram"""
    try:
        # Формируем сообщение для админа
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
        
        # Отправляем текстовое сообщение
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            parse_mode='Markdown'
        )
        
        # Если есть скриншот, скачиваем и отправляем его
        if user_data.get('file_path') and os.path.exists(user_data['file_path']):
            try:
                with open(user_data['file_path'], 'rb') as photo:
                    await bot.send_photo(
                        chat_id=ADMIN_ID,
                        photo=InputFile(photo),
                        caption=f"📸 Скриншот от пользователя ID: {user_data['user_id']}"
                    )
            except Exception as e:
                logger.error(f"Ошибка отправки скриншота админу: {e}")
        
        # Добавляем кнопки действий для админа
        keyboard = [
            [
                InlineKeyboardButton("✅ Выплатить", callback_data=f"approve_{request_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{request_id}")
            ],
            [
                InlineKeyboardButton("💬 Написать пользователю", 
                                   url=f"tg://user?id={user_data['user_id']}")
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
        
        try:
            conn = sqlite3.connect('requests.db', timeout=5)
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
            conn.close()
            
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
                    
        except sqlite3.Error as e:
            logger.error(f"Ошибка обновления статуса заявки: {e}")
            await query.message.reply_text(f"❌ Ошибка обновления статуса: {e}")
            
    elif data.startswith('reject_'):
        request_id = int(data.split('_')[1])
        
        try:
            conn = sqlite3.connect('requests.db', timeout=5)
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
            conn.close()
            
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
                    
        except sqlite3.Error as e:
            logger.error(f"Ошибка обновления статуса заявки: {e}")
            await query.message.reply_text(f"❌ Ошибка обновления статуса: {e}")

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
/myrequests - Мои заявки
/status - Статус бота
/help - Помощь

Для получения бонуса:
1. Нажмите "🎁 Бонус за отзыв ⭐⭐⭐⭐⭐"
2. Отправьте скриншот
3. Укажите телефон и банк

**Команды администратора:**
/admin - Панель администратора
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать мои заявки"""
    user_id = update.effective_user.id
    
    try:
        conn = sqlite3.connect('requests.db', timeout=5)
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
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения заявок: {e}")
        await update.message.reply_text("❌ Ошибка получения данных. Попробуйте позже.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда статуса бота"""
    uptime = datetime.now() - bot_start_time
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    status_text = f"""
🤖 **Статус бота**

✅ Бот работает
⏱ Аптайм: {uptime.days}д {hours}ч {minutes}м
🔄 Перезапусков: {bot_restart_count}
📊 Заявок за сессию: {total_requests}
📅 Время сервера: {datetime.now().strftime("%d.%m.%Y %H:%M:%S")}
💾 Свободное место: {get_free_space()} ГБ
    """
    await update.message.reply_text(status_text, parse_mode='Markdown')

# ==================== АДМИН ПАНЕЛЬ ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Панель администратора"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа.")
        return
    
    try:
        conn = sqlite3.connect('requests.db', timeout=5)
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
├ Всего заявок: {row[0]}
├ Ожидают: {row[1] or 0}
├ Выплачены: {row[2] or 0}
├ Отклонены: {row[3] or 0}
└ Общая сумма: {row[4] or 0} руб

📈 **Система:**
├ Аптайм: {uptime.days}д {hours}ч {minutes}м
├ Перезапусков: {bot_restart_count}
├ Заявок/сессия: {total_requests}
└ Свободно: {get_free_space()} ГБ

💡 **Действия:**
- Заявки приходят автоматически
- Используйте кнопки для обработки
            """
            await update.message.reply_text(stats_text, parse_mode='Markdown')
    except sqlite3.Error as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await update.message.reply_text("❌ Ошибка получения статистики.")

# ==================== ГЛАВНАЯ ФУНКЦИЯ С АВТОПЕРЕЗАПУСКОМ ====================
async def run_bot_forever():
    """Основная функция с автоперезапуском"""
    global bot_restart_count
    
    while True:
        try:
            logger.info(f"Запуск бота (попытка #{bot_restart_count + 1})")
            
            # Инициализация БД
            if not init_database():
                logger.error("Не удалось инициализировать БД. Повтор через 30 секунд...")
                await asyncio.sleep(30)
                continue
            
            # Создаем приложение
            application = Application.builder().token(BOT_TOKEN).build()
            
            # Настраиваем планировщик задач для админа
            job_queue = application.job_queue
            if job_queue:
                # Health check каждые 6 часов
                job_queue.run_repeating(send_health_check, interval=21600, first=10)
                # Автобэкап каждые 24 часа
                job_queue.run_repeating(auto_backup, interval=86400, first=60)
            
            # Обработка кнопок платформ
            application.add_handler(MessageHandler(
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
            application.add_handler(conv_handler)
            application.add_handler(CommandHandler("help", help_command))
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("myrequests", my_requests))
            application.add_handler(CommandHandler("status", status_command))
            application.add_handler(CommandHandler("admin", admin_panel))
            
            # Обработчик callback кнопок админа
            application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^approve_|^reject_"))
            
            # Запускаем бота
            bot_restart_count += 1
            logger.info(f"🤖 Бот запускается... (Перезапуск #{bot_restart_count})")
            
            # Отправляем уведомление админу о запуске
            try:
                startup_message = f"""
🚀 **Бот запущен**

✅ Бот успешно запущен
🔄 Перезапуск #{bot_restart_count}
⏰ Время запуска: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
💻 Сервер: Oracle Cloud Free Tier
                """
                await application.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=startup_message,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление о запуске: {e}")
            
            # Основной цикл работы бота
            await application.run_polling()
            
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
            sys.exit(0)
            
        except Exception as e:
            logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: {e}", exc_info=True)
            
            # Отправляем уведомление админу об ошибке
            try:
                error_message = f"""
🔴 **Бот упал с ошибкой**

❌ Ошибка: {str(e)[:200]}
🔄 Перезапуск через 30 секунд...
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
            logger.info("Перезапуск через 30 секунд...")
            await asyncio.sleep(30)

def main():
    """Точка входа в программу"""
    print("\n" + "="*60)
    print("🤖 TELEGRAM BOT 24/7 - ORACLE CLOUD FREE TIER")
    print("="*60)
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"📁 Лог файл: bot_24_7.log")
    print(f"💾 База данных: requests.db")
    print(f"🖼️ Скриншоты: {SCREENSHOTS_FOLDER}")
    print("="*60)
    print("🚀 Запускаем бота с автоперезапуском...")
    print("⚠️  Для остановки нажмите Ctrl+C")
    print("="*60 + "\n")
    
    # Запускаем бесконечный цикл
    asyncio.run(run_bot_forever())

if __name__ == '__main__':
    main()
