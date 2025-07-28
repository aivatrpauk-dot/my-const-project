from aiogram import Dispatcher
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


async def support_main(call: types.CallbackQuery):
    await call.message.delete()
    text = "Это поддержка бота!\nЗдесь Вы можете написать в поддержку или оформить подписку"
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Поддержка", url="https://t.me/Denissssw"))
    kb.add(InlineKeyboardButton("Подписка", callback_data="subscription"))
    kb.add(InlineKeyboardButton("Выйти", callback_data="main_menu"))
    await call.message.answer(text, reply_markup=kb)


async def support_command(message: types.Message):
    text = "Если у вас возникли вопросы, обратитесь в поддержку:\nhttps://t.me/Denissssw"
    await message.answer(text)


def register_support_handlers(dp: Dispatcher):
    # Регистрируем обработчик для callback "support"
    dp.register_callback_query_handler(support_main, text="support", state="*")
    # Регистрируем обработчик для команды /support
    dp.register_message_handler(support_command, commands=["support"])    
