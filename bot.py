import os
import logging
import random
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify
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
BOT_TOKEN = os.environ.get("BOT_TOKEN", "5932864783:AAFbN42qyJBtbuyqo3wD2i2I3OTKEdpq1qI")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 5189651311))  # Ваш Telegram ID

# Ссылки для кнопок отзывов
VK_REVIEW_LINK = "https://clck.ru/3QTvTp"
YANDEX_REVIEW_LINK = "https://clck.ru/3QTRfj"
TWOGIS_REVIEW_LINK = "https://clck.ru/3QsAsL"

# Состояния для ConversationHandler
WAITING_FOR_REVIEW, WAITING_FOR_PHONE, WAITING_FOR_BANK = range(3)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создаем Flask приложение для Bothost
app = Flask(__name__)

# ==================== БАЗА ДАННЫХ ====================
def get_db_connection():
    """Создание подключения к базе данных"""
    try:
        conn = sqlite3.connect('requests.db', timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {e}")
        return None

def init_database():
    """Инициализация базы данных"""
    conn = get_db_connection()
    if not conn:
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
        
        conn.commit()
        logger.info("✅ База данных инициализирована")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        return False
    finally:
        if conn:
            conn.close()

def add_request(user_data):
    """Добавление новой заявки в БД"""
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
        
        conn.commit()
        request_id = c.lastrowid
        logger.info(f"✅ Заявка #{request_id} добавлена в БД")
        return request_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка добавления заявки в БД: {e}")
        return None
    finally:
        if conn:
            conn.close()

# ==================== ОТПРАВКА ЗАЯВКИ АДМИНИСТРАТОРУ ====================
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
    
    try:
        file_id = None
        
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
        elif update.message.document:
            file_id = update.message.document.file_id
        
        if file_id:
            context.user_data['file_id'] = file_id
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
        'file_path': None
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

**Команды администратора:**
/admin - Панель администратора
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

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
            stats_text = f"""
👑 **Панель администратора**

📊 **Статистика:**
├ Всего заявок: {row['total']}
├ Ожидают: {row['pending'] or 0}
├ Выплачены: {row['approved'] or 0}
├ Отклонены: {row['rejected'] or 0}
└ Общая сумма: {row['total_amount'] or 0} руб

💡 **Действия:**
- Все новые заявки приходят сюда автоматически
- Используйте кнопки под сообщениями для обработки
            """
            await update.message.reply_text(stats_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await update.message.reply_text("❌ Ошибка получения статистики.")

# ==================== СОЗДАНИЕ И НАСТРОЙКА БОТА ====================
def setup_application():
    """Создание и настройка приложения бота"""
    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Инициализация БД
    init_database()
    
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
    application.add_handler(CommandHandler("admin", admin_panel))
    
    # Обработчик callback кнопок админа
    application.add_handler(CallbackQueryHandler(handle_admin_callback, pattern="^approve_|^reject_"))
    
    return application

# Создаем приложение один раз при запуске
application = setup_application()

# ==================== FLASK РОУТЫ ДЛЯ BOTHOST ====================

@app.route('/')
def home():
    """Главная страница для проверки работы"""
    return jsonify({
        "status": "online",
        "service": "Telegram Bot Webhook",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Обработчик webhook от Telegram"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = Update.de_json(json_string, application.bot)
        
        try:
            await application.initialize()
            await application.process_update(update)
            return jsonify({"status": "ok"})
        except Exception as e:
            logger.error(f"Ошибка обработки обновления: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    
    return jsonify({"status": "error", "message": "Invalid content type"}), 400

@app.route('/set_webhook', methods=['GET'])
async def set_webhook():
    """Установка webhook (вызовите один раз после деплоя)"""
    try:
        # Получаем URL вашего приложения на Bothost
        webhook_url = f"https://{request.host}/webhook"
        
        # Устанавливаем webhook
        await application.bot.set_webhook(webhook_url)
        
        return jsonify({
            "status": "success",
            "message": f"Webhook установлен: {webhook_url}"
        })
    except Exception as e:
        logger.error(f"Ошибка установки webhook: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health')
def health_check():
    """Проверка здоровья приложения"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "bot_token_set": bool(BOT_TOKEN and BOT_TOKEN != "ВАШ_ТОКЕН_БОТА")
    })

# ==================== ЗАПУСК ПРИЛОЖЕНИЯ ====================
if __name__ == '__main__':
    # Для локального тестирования
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
