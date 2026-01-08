import os
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor

bot = Bot(token=os.getenv("5932864783:AAFbN42qyJBtbuyqo3wD2i2I3OTKEdpq1qI"))
dp = Dispatcher(bot)

@dp.message_handler(commands=['start'])
async def start_cmd(message: types.Message):
    await message.answer("Bot is alive!")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
