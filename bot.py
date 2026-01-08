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
ADMIN_ID = 5189651311  # ЗАМЕНИТЕ на ваш Telegram ID

# Ссылки для кнопок отзывов
VK_REVIEW_LINK = "https://clck.ru/3QTvTp"
YANDEX_REVIEW_LINK = "https://clck.ru/3QTRfj"
TWOGIS_REVIEW_LINK = "https://clck.ru/3QsAsL"

# Состояния для ConversationHandler
WAITING_FOR_REVIEW, WAITING_FOR_PHONE, WAITING_FOR_BANK = range(3)

# Настройка логирования для 24/7
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot_24_7.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Уменьшаем логи от библиотек
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('telegram').setLevel(logging.INFO)

# Папка для сохранения скриншотов
SCREENSHOTS_FOLDER = "screenshots"
os.makedirs(SCREENSHOTS_FOLDER, exist_ok=True)

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
bot_start_time = datetime.now()
total_requests_this_session = 0
bot_restart_count = 0

# ==================== ОБРАБОТЧИКИ СИГНАЛОВ ====================
def signal_handler(signum, frame):
    """Graceful shutdown при получении сигналов"""
    logger.info(f"Получен сигнал {signum}. Завершаем работу...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==================== ФУНКЦИИ МОНИТОРИНГА ====================
async def send_health_check(context: ContextTypes.DEFAULT_TYPE):
    """Регулярная отправка статуса бота админу"""
    try:
        uptime = datetime.now() - bot_start_time
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        # Получаем свободное место на диске
        free_space = get_free_space()
        
        status_text = f"""
🏥 **HEALTH CHECK - Бот работает**

✅ Статус: Нормальный
⏱ Аптайм: {uptime.days}д {hours}ч {minutes}м
🔄 Перезапусков: {bot_restart_count}
📊 Заявок за сессию: {total_requests_this_session}
💾 Свободное место: {free_space} ГБ
📅 Время сервера: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
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
        import shutil
        total, used, free = shutil.disk_usage(".")
        free_gb = free / (1024**3)
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
        if os.path.exists('requests.db'):
            shutil.copy2('requests.db', backup_file)
            logger.info(f"Создан бэкап базы данных: {backup_file}")
            
            # Удаляем старые бэкапы (оставляем последние 7)
            backups = sorted([f for f in os.listdir(backup_dir) if f.startswith('requests_backup_')])
            if len(backups) > 7:
                for old_backup in backups[:-7]:
                    os.remove(os.path.join(backup_dir, old_backup))
                    logger.info(f"Удален старый бэкап: {old_backup}")
    except Exception as e:
        logger.error(f"Ошибка создания бэкапа: {e}")

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
                InlineKeyboardButton("✅ Выплатить", callback_data=f"admin_approve_{request_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_{request_id}")
            ],
            [
                InlineKeyboardButton("💬 Написать пользователю", 
                                   url=f"tg://user?id={user_data['user_id']}"),
                InlineKeyboardButton("📋 Подробнее", callback_data=f"admin_details_{request_id}")
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

# ==================== ПАНЕЛЬ АДМИНИСТРАТОРА (ИСПРАВЛЕННАЯ) ====================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню панели администратора"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton("📋 Все заявки", callback_data="admin_all")],
        [InlineKeyboardButton("⏳ Ожидают решения", callback_data="admin_pending")],
        [InlineKeyboardButton("✅ Одобренные", callback_data="admin_approved")],
        [InlineKeyboardButton("❌ Отклоненные", callback_data="admin_rejected")],
        [InlineKeyboardButton("🔍 Поиск по ID", callback_data="admin_search_id")],
        [InlineKeyboardButton("📞 Поиск по телефону", callback_data="admin_search_phone")],
        [InlineKeyboardButton("📅 Статистика по дням", callback_data="admin_daily_stats")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👑 **ПАНЕЛЬ АДМИНИСТРАТОРА**\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общая статистика"""
    query = update.callback_query
    await query.answer()
    
    conn = get_db_connection()
    if not conn:
        await query.edit_message_text("❌ Ошибка подключения к базе данных.")
        return
    
    try:
        c = conn.cursor()
        
        # Общая статистика
        c.execute('''SELECT 
                     COUNT(*) as total,
                     SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                     SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
                     SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                     SUM(CASE WHEN status = 'approved' THEN amount ELSE 0 END) as total_amount
                     FROM requests''')
        
        row = c.fetchone()
        
        # Статистика за сегодня
        today = datetime.now().date()
        c.execute('''SELECT 
                     total_requests, approved_requests, rejected_requests, total_amount
                     FROM daily_stats WHERE date = ?''', (today,))
        today_stats = c.fetchone()
        
        # Статистика бота
        uptime = datetime.now() - bot_start_time
        hours, remainder = divmod(uptime.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        stats_text = f"""
📊 **ОБЩАЯ СТАТИСТИКА**

📈 Всего заявок: *{row['total']}*
⏳ Ожидают решения: *{row['pending'] or 0}*
✅ Одобрено: *{row['approved'] or 0}*
❌ Отклонено: *{row['rejected'] or 0}*
💰 Общая сумма выплат: *{row['total_amount'] or 0} руб*

📅 **ЗА СЕГОДНЯ ({today.strftime('%d.%m.%Y')}):**
├ Заявок: *{today_stats['total_requests'] if today_stats else 0}*
├ Одобрено: *{today_stats['approved_requests'] if today_stats else 0}*
├ Отклонено: *{today_stats['rejected_requests'] if today_stats else 0}*
└ Сумма: *{today_stats['total_amount'] if today_stats else 0} руб*

🤖 **СТАТУС БОТА:**
├ Аптайм: {uptime.days}д {hours}ч {minutes}м
├ Перезапусков: {bot_restart_count}
├ Заявок/сессия: {total_requests_this_session}
└ Свободно: {get_free_space()} ГБ
        """
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(stats_text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")
    finally:
        if conn:
            conn.close()

async def show_requests(update: Update, context: ContextTypes.DEFAULT_TYPE, status=None, limit=15):
    """Показать заявки"""
    query = update.callback_query
    if query:
        await query.answer()
        chat_id = query.message.chat_id
    else:
        chat_id = update.message.chat_id
    
    conn = get_db_connection()
    if not conn:
        if query:
            await query.edit_message_text("❌ Ошибка подключения к БД.")
        else:
            await update.message.reply_text("❌ Ошибка подключения к БД.")
        return
    
    try:
        c = conn.cursor()
        
        if status:
            c.execute('''SELECT * FROM requests WHERE status = ? ORDER BY created_at DESC LIMIT ?''', 
                     (status, limit))
            status_text = {
                'pending': "⏳ Ожидающие",
                'approved': "✅ Одобренные", 
                'rejected': "❌ Отклоненные"
            }.get(status, "Заявки")
        else:
            c.execute('''SELECT * FROM requests ORDER BY created_at DESC LIMIT ?''', (limit,))
            status_text = "📋 Все заявки"
        
        requests = c.fetchall()
        
        if not requests:
            text = f"📭 *{status_text}*\n\nЗаявок не найдено."
        else:
            text = f"{status_text} (последние {len(requests)}):\n\n"
            
            for req in requests:
                created = datetime.strptime(req['created_at'], '%Y-%m-%d %H:%M:%S') if isinstance(req['created_at'], str) else req['created_at']
                
                text += f"*#{req['id']}* - {req['full_name']}\n"
                text += f"💰 {req['amount']} руб | 📞 {req['phone']}\n"
                text += f"🏦 {req['bank']} | 📅 {created.strftime('%d.%m %H:%M')}\n"
                text += f"🔸 Статус: {req['status']}\n"
                if req['username']:
                    text += f"👤 @{req['username']}\n"
                text += "─" * 25 + "\n"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if query:
            await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')
            
    except Exception as e:
        logger.error(f"Ошибка показа заявок: {e}")
        if query:
            await query.edit_message_text(f"❌ Ошибка: {str(e)}")
        else:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        if conn:
            conn.close()

async def admin_daily_stats_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика по дням"""
    query = update.callback_query
    await query.answer()
    
    conn = get_db_connection()
    if not conn:
        await query.edit_message_text("❌ Ошибка подключения к БД.")
        return
    
    try:
        c = conn.cursor()
        
        # Получаем статистику за последние 7 дней
        dates = [(datetime.now() - timedelta(days=i)).date() for i in range(7)]
        
        text = "📅 **Статистика за последние 7 дней:**\n\n"
        total_week = {'requests': 0, 'approved': 0, 'rejected': 0, 'amount': 0}
        
        for date in reversed(dates):
            c.execute('''SELECT * FROM daily_stats WHERE date = ?''', (date,))
            stats = c.fetchone()
            
            if stats:
                text += f"**{date.strftime('%d.%m.%Y')}:**\n"
                text += f"├ Заявок: {stats['total_requests']}\n"
                text += f"├ Одобрено: {stats['approved_requests']}\n"
                text += f"├ Отклонено: {stats['rejected_requests']}\n"
                text += f"└ Сумма: {stats['total_amount']} руб\n\n"
                
                total_week['requests'] += stats['total_requests']
                total_week['approved'] += stats['approved_requests']
                total_week['rejected'] += stats['rejected_requests']
                total_week['amount'] += stats['total_amount']
            else:
                text += f"**{date.strftime('%d.%m.%Y')}:**\n"
                text += f"├ Заявок: 0\n├ Одобрено: 0\n├ Отклонено: 0\n└ Сумма: 0 руб\n\n"
        
        text += f"**Итого за неделю:**\n"
        text += f"📈 Всего заявок: {total_week['requests']}\n"
        text += f"✅ Одобрено: {total_week['approved']}\n"
        text += f"❌ Отклонено: {total_week['rejected']}\n"
        text += f"💰 Общая сумма: {total_week['amount']} руб\n"
        
        keyboard = [[InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики по дням: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")
    finally:
        if conn:
            conn.close()

async def admin_search_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск заявки по ID"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔍 **Поиск заявки по ID**\n\n"
        "Введите ID заявки (число):"
    )
    context.user_data['admin_action'] = 'search_by_id'

async def admin_search_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Поиск заявки по телефону"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "📞 **Поиск заявки по телефону**\n\n"
        "Введите номер телефона (частично или полностью):"
    )
    context.user_data['admin_action'] = 'search_by_phone'

async def handle_admin_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка поискового запроса от админа"""
    if not context.user_data.get('admin_action'):
        return
    
    search_query = update.message.text.strip()
    action = context.user_data['admin_action']
    
    conn = get_db_connection()
    if not conn:
        await update.message.reply_text("❌ Ошибка подключения к БД.")
        return
    
    try:
        c = conn.cursor()
        
        if action == 'search_by_id' and search_query.isdigit():
            c.execute('''SELECT * FROM requests WHERE id = ?''', (int(search_query),))
        elif action == 'search_by_phone':
            c.execute('''SELECT * FROM requests WHERE phone LIKE ? ORDER BY created_at DESC LIMIT 10''', 
                      (f'%{search_query}%',))
        else:
            await update.message.reply_text("❌ Неверный формат запроса.")
            return
        
        results = c.fetchall()
        
        if not results:
            await update.message.reply_text("🔍 Заявок не найдено.")
        else:
            text = f"🔍 *Результаты поиска* ({len(results)}):\n\n"
            
            for req in results:
                created = datetime.strptime(req['created_at'], '%Y-%m-%d %H:%M:%S') if isinstance(req['created_at'], str) else req['created_at']
                
                text += f"*#{req['id']}* - {req['full_name']}\n"
                text += f"💰 {req['amount']} руб | 📞 {req['phone']}\n"
                text += f"🏦 {req['bank']} | 📅 {created.strftime('%d.%m.%Y %H:%M')}\n"
                text += f"🔸 Статус: {req['status']}\n"
                text += "─" * 25 + "\n"
            
            await update.message.reply_text(text, parse_mode='Markdown')
            
            # Добавляем кнопки действий для каждой найденной заявки
            for req in results[:3]:  # Ограничиваем 3 заявками
                if req['status'] == 'pending':
                    keyboard = [
                        [
                            InlineKeyboardButton(f"✅ Одобрить #{req['id']}", callback_data=f"admin_approve_{req['id']}"),
                            InlineKeyboardButton(f"❌ Отклонить #{req['id']}", callback_data=f"admin_reject_{req['id']}")
                        ],
                        [
                            InlineKeyboardButton(f"📋 Подробнее #{req['id']}", callback_data=f"admin_details_{req['id']}")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        f"Действия для заявки #{req['id']}:",
                        reply_markup=reply_markup
                    )
    
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        await update.message.reply_text(f"❌ Ошибка поиска: {str(e)}")
    finally:
        if conn:
            conn.close()
        context.user_data.pop('admin_action', None)

async def show_request_details_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать детали заявки для админа"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not data.startswith('admin_details_'):
        return
    
    request_id = int(data.split('_')[2])
    
    conn = get_db_connection()
    if not conn:
        await query.edit_message_text("❌ Ошибка подключения к БД.")
        return
    
    try:
        c = conn.cursor()
        c.execute('''SELECT * FROM requests WHERE id = ?''', (request_id,))
        req = c.fetchone()
        
        if not req:
            await query.edit_message_text(f"❌ Заявка #{request_id} не найдена.")
            return
        
        created = datetime.strptime(req['created_at'], '%Y-%m-%d %H:%M:%S') if isinstance(req['created_at'], str) else req['created_at']
        processed = datetime.strptime(req['processed_at'], '%Y-%m-%d %H:%M:%S') if req['processed_at'] and isinstance(req['processed_at'], str) else req['processed_at']
        
        details = f"""
📄 *ДЕТАЛИ ЗАЯВКИ #{req['id']}*

👤 *ПОЛЬЗОВАТЕЛЬ:*
├ ID: `{req['user_id']}`
├ Username: @{req['username'] or 'не указан'}
├ Имя: {req['full_name']}

📞 *КОНТАКТЫ:*
├ Телефон: `{req['phone']}`
├ Банк: {req['bank']}

💰 *ФИНАНСЫ:*
├ Сумма: {req['amount']} руб
└ Статус: {req['status']}

📅 *ВРЕМЯ:*
├ Создана: {created.strftime('%d.%m.%Y %H:%M:%S')}
"""
        
        if processed:
            details += f"├ Обработана: {processed.strftime('%d.%m.%Y %H:%M:%S')}\n"
        
        if req['admin_username']:
            details += f"└ Админ: @{req['admin_username']}"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Одобрить", callback_data=f"admin_approve_{req['id']}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"admin_reject_{req['id']}")
            ] if req['status'] == 'pending' else [],
            [InlineKeyboardButton("◀️ Назад", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(details, reply_markup=reply_markup, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка показа деталей: {e}")
        await query.edit_message_text(f"❌ Ошибка: {str(e)}")
    finally:
        if conn:
            conn.close()

async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка решения админа по заявке"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if not (data.startswith('admin_approve_') or data.startswith('admin_reject_')):
        return
    
    request_id = int(data.split('_')[2])
    action = 'approved' if data.startswith('admin_approve_') else 'rejected'
    admin_id = query.from_user.id
    admin_username = query.from_user.username
    
    conn = get_db_connection()
    if not conn:
        await query.edit_message_text("❌ Ошибка подключения к БД.")
        return
    
    try:
        c = conn.cursor()
        
        # Обновляем статус заявки
        c.execute('''UPDATE requests SET 
                     status = ?, 
                     processed_at = ?,
                     admin_id = ?,
                     admin_username = ?
                     WHERE id = ?''',
                  (action, datetime.now(), admin_id, admin_username, request_id))
        
        # Обновляем дневную статистику
        today = datetime.now().date()
        if action == 'approved':
            c.execute('''SELECT amount FROM requests WHERE id = ?''', (request_id,))
            amount_result = c.fetchone()
            amount = amount_result['amount'] if amount_result else 0
            
            c.execute('''UPDATE daily_stats SET 
                         approved_requests = approved_requests + 1,
                         total_amount = total_amount + ?
                         WHERE date = ?''', (amount, today))
        elif action == 'rejected':
            c.execute('''UPDATE daily_stats SET rejected_requests = rejected_requests + 1 WHERE date = ?''', (today,))
        
        # Получаем данные пользователя для уведомления
        c.execute('SELECT user_id, amount FROM requests WHERE id = ?', (request_id,))
        req_data = c.fetchone()
        
        conn.commit()
        
        # Уведомляем администратора
        action_text = "ОДОБРЕНА ✅" if action == 'approved' else "ОТКЛОНЕНА ❌"
        await query.edit_message_text(
            text=f"**Заявка #{request_id} {action_text}**\n\n"
                 f"👨‍💼 Админ: @{admin_username or query.from_user.first_name}\n"
                 f"⏰ Время: {datetime.now().strftime('%H:%M:%S')}",
            parse_mode='Markdown'
        )
        
        # Отправляем уведомление пользователю
        if req_data:
            user_id = req_data['user_id']
            amount = req_data['amount']
            
            try:
                if action == 'approved':
                    user_message = f"""
🎉 *Ваша заявка #{request_id} одобрена!*

💰 Сумма: {amount} рублей
⏰ Деньги будут переведены в течение 24 часов.

Спасибо за участие! 🎉
                    """
                else:
                    user_message = f"""
❌ *Ваша заявка #{request_id} отклонена.*

ℹ️ Проверьте корректность предоставленных данных.
Для новой заявки нажмите /start
                    """
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=user_message,
                    parse_mode='Markdown'
                )
                logger.info(f"Уведомление отправлено пользователю {user_id}")
                
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю: {e}")
        
        logger.info(f"Заявка #{request_id} {action} администратором {admin_username}")
        
    except Exception as e:
        logger.error(f"Ошибка обновления статуса заявки: {e}")
        await query.message.reply_text(f"❌ Ошибка обновления статуса: {str(e)}")
    finally:
        if conn:
            conn.close()

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback кнопок админки"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "admin_stats":
        await admin_stats_command(update, context)
    elif data == "admin_all":
        await show_requests(update, context, status=None, limit=15)
    elif data == "admin_pending":
        await show_requests(update, context, status='pending', limit=15)
    elif data == "admin_approved":
        await show_requests(update, context, status='approved', limit=15)
    elif data == "admin_rejected":
        await show_requests(update, context, status='rejected', limit=15)
    elif data == "admin_daily_stats":
        await admin_daily_stats_panel(update, context)
    elif data == "admin_search_id":
        await admin_search_id(update, context)
    elif data == "admin_search_phone":
        await admin_search_phone(update, context)
    elif data == "admin_back":
        await admin_panel(update, context)
    elif data.startswith('admin_details_'):


