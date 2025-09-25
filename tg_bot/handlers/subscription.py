# subscription.py
import logging
import os
import hashlib
import random
import aiohttp
from datetime import datetime, timedelta
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from tg_bot.models import sessionmaker, engine, User, Payment
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship
from aiogram.dispatcher.filters import Text
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.dispatcher import FSMContext
# tg_bot/middlewares/activity_middleware.py

from aiogram.dispatcher.middlewares import BaseMiddleware
from tg_bot.models import sessionmaker, engine, User

class ActivityMiddleware(BaseMiddleware):
    async def on_pre_process_message(self, message: types.Message, data: dict):
        session = sessionmaker(bind=engine)()
        try:
            user_id = message.from_user.id
            user = session.query(User).filter(User.telegram_id == user_id).first()
            if user:
                print("ActivityMiddleware: on_pre_process_message")
                user.last_active = datetime.utcnow()
                session.commit()
        except Exception as e:
            print(f"[ActivityMiddleware] Error updating last_active: {e}")
        finally:
            session.close()

    async def on_pre_process_callback_query(self, callback_query: types.CallbackQuery, data: dict):
        session = sessionmaker(bind=engine)()
        try:
            user_id = callback_query.from_user.id
            user = session.query(User).filter(User.telegram_id == user_id).first()
            if user:
                print("ActivityMiddleware: on_pre_process_callback_query")
                user.last_active = datetime.utcnow()
                session.commit()
        except Exception as e:
            print(f"[ActivityMiddleware] Error updating last_active: {e}")
        finally:
            session.close()



logger = logging.getLogger(__name__)

# Настройки Tinkoff Kassa
TINKOFF_API_URL = "https://securepay.tinkoff.ru/v2"

# Функция для получения конфигурации Tinkoff
def get_tinkoff_config():
    from dataclasses import dataclass
    
    @dataclass
    class TinkoffConfig:
        terminal_key: str
        password: str
    
    # Данные Tinkoff API (встроены в код)
    return TinkoffConfig(
        terminal_key="1749885008651",
        password="YBla2Zf$iQYwWuSU"  # Правильный пароль
    )

# Статусы платежей Tinkoff
STATUS_DESCRIPTION = {
    'NEW': 'Создан',
    'FORM_SHOWED': 'Форма оплаты открыта',
    'DEADLINE_EXPIRED': 'Просрочен',
    'CANCELED': 'Отменен',
    'PREAUTHORIZING': 'Проверка',
    'AUTHORIZING': 'Авторизация',
    'AUTHORIZED': 'Авторизован',
    'REJECTED': 'Отклонен',
    'CONFIRMED': 'Подтвержден',
    'REFUNDED': 'Возвращен'
}


# Генерация токена для Tinkoff API
def generate_token(data, password):
    # Создаем копию данных и добавляем пароль
    token_data = data.copy()
    token_data["Password"] = password
    
    # Сортируем параметры по алфавиту
    sorted_params = sorted(token_data.items(), key=lambda x: x[0])
    
    # Объединяем значения в строку
    concatenated = ''.join(str(value) for key, value in sorted_params)
    
    # Создаем SHA256 хеш
    token = hashlib.sha256(concatenated.encode('utf-8')).hexdigest()
    
    logger.info(f"Token generation - concatenated string: {concatenated}")
    logger.info(f"Token generation - final token: {token}")
    
    return token


# Проверка активной подписки
def check_subscription(user):
    if not user:
        return False
    
    # Проверяем основную подписку
    if user.subscription_end and user.subscription_end > datetime.now():
        return True
    
    # Проверяем активные платежи через ЮKassa (Telegram Payments)
    session = sessionmaker(bind=engine)()
    try:
        from tg_bot.models import Payment
        current_time = datetime.utcnow()
        
        # Ищем успешные платежи за последние 30 дней
        active_payment = session.query(Payment).filter(
            Payment.user_id == user.id,
            Payment.payment_method == 'telegram',
            Payment.status == 'SUCCESS',
            Payment.paid_at >= (current_time - timedelta(days=30))
        ).first()
        
        if active_payment:
            return True
            
    except Exception as e:
        print(f"Error checking ЮKassa payments: {e}")
    finally:
        session.close()
    
    return False


async def subscription_callback(callback: types.CallbackQuery):
    session = sessionmaker(bind=engine)()
    try:
        user = session.query(User).filter(User.telegram_id == callback.from_user.id).first()

        if not user:
            await callback.message.answer("❌ Пользователь не найден!")
            return

        if check_subscription(user):
            text = (
                f"🌟 <b>Ваша подписка активна!</b>\n\n"
                f"✅ Окончание подписки: {user.subscription_end.strftime('%d.%m.%Y')}\n"
                f"💎 Доступ ко всем функциям открыт"
            )
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="main_menu"))
        else:
            text = (
                "🔒 <b>Подписка ProfitBee Premium</b>\n\n"
                "💡 Получите полный доступ к возможностям бота:\n"
                "💰 Стоимость: 299 руб./месяц\n"
                "🛒 Первые 3 дня - бесплатно!"
            )
            keyboard = InlineKeyboardMarkup(row_width=1)
            if not user.is_trial_used:
                keyboard.add(InlineKeyboardButton("🎁 Активировать пробный период", callback_data="activate_trial"))
            keyboard.add(
                InlineKeyboardButton("💳 Купить подписку", callback_data="buy_subscription"),
                InlineKeyboardButton("🔙 Назад", callback_data="main_menu")
            )

        await callback.message.answer(text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Subscription error: {e}")
        await callback.message.answer("⚠️ Ошибка загрузки данных. Попробуйте позже.")
    finally:
        session.close()


async def activate_trial_callback(callback: types.CallbackQuery):
    session = sessionmaker(bind=engine)()
    try:
        user = session.query(User).filter(User.telegram_id == callback.from_user.id).first()

        if not user:
            await callback.answer("❌ Пользователь не найден!", show_alert=True)
            return

        if user.is_trial_used:
            await callback.answer("❌ Вы уже использовали пробный период", show_alert=True)
            return


        user.subscription_start = datetime.now()
        user.subscription_end = datetime.now() + timedelta(days=3)
        user.is_trial_used = True
        session.commit()

        text = (
            "🎉 <b>Пробный период активирован!</b>\n\n"
            f"Теперь у вас есть 3 дня бесплатного доступа ко всем функциям бота.\n"
            f"Окончание подписки: {user.subscription_end.strftime('%d.%m.%Y')}"
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🚀 Начать использовать", callback_data="main_menu"))
        await callback.message.edit_text(text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Trial activation error: {e}")
        await callback.answer("⚠️ Ошибка активации пробного периода", show_alert=True)
    finally:
        session.close()


async def buy_subscription_callback(callback: types.CallbackQuery):
    session = sessionmaker(bind=engine)()
    try:
        user = session.query(User).filter(User.telegram_id == callback.from_user.id).first()
        if not user:
            await callback.answer("❌ Пользователь не найден!", show_alert=True)
            return

        text = (
            '💳 <b>Выберите способ оплаты</b>\n\n'
            'Доступные способы оплаты:\n'
            '• Telegram Payments (рекомендуется)\n'
            '• Тинькофф Касса\n\n'
            '💰 Стоимость: 299₽/месяц'
        )
        
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("💳 Telegram Payments", callback_data="telegram_payment_menu"),
            InlineKeyboardButton("🏦 Тинькофф Касса", callback_data="tinkoff_payment_menu"),
            InlineKeyboardButton("🎁 Демо-подписка", callback_data="activate_demo_subscription"),
            InlineKeyboardButton("🔙 Назад", callback_data="subscription")
        )
        
        await callback.message.edit_text(text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Payment creation error: {e}")
        await callback.answer("⚠️ Ошибка создания платежа", show_alert=True)
    finally:
        session.close()


# Добавляем функцию для демо-подписки
async def activate_demo_subscription_callback(callback: types.CallbackQuery):
    session = sessionmaker(bind=engine)()
    try:
        user = session.query(User).filter(User.telegram_id == callback.from_user.id).first()
        if not user:
            await callback.answer("❌ Пользователь не найден!", show_alert=True)
            return

        # Активируем демо-подписку на 30 дней
        if user.subscription_end and user.subscription_end > datetime.now():
            user.subscription_end += timedelta(days=30)
        else:
            user.subscription_end = datetime.now() + timedelta(days=30)
        
        session.commit()

        text = (
            "🎉 <b>Демо-подписка активирована!</b>\n\n"
            f"Теперь у вас есть полный доступ ко всем функциям бота на 30 дней.\n"
            f"Окончание подписки: {user.subscription_end.strftime('%d.%m.%Y')}\n\n"
            "🛠️ Это демо-режим для тестирования."
        )
        keyboard = InlineKeyboardMarkup()
        keyboard.add(InlineKeyboardButton("🚀 Начать использовать", callback_data="main_menu"))
        await callback.message.edit_text(text, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Demo subscription activation error: {e}")
        await callback.answer("⚠️ Ошибка активации демо-подписки", show_alert=True)
    finally:
        session.close()


async def check_payment_callback(callback: types.CallbackQuery):
    payment_id = int(callback.data.split(':')[1])
    session = sessionmaker(bind=engine)()
    try:
        payment = session.query(Payment).get(payment_id)
        if not payment:
            await callback.answer("❌ Платеж не найден", show_alert=True)
            return

        # Проверяем тип платежа
        if payment.payment_method == 'telegram':
            # Для платежей через ЮKassa (Telegram Payments)
            await check_yukassa_payment(callback, payment, session)
        else:
            # Для платежей через Тинькофф
            await check_tinkoff_payment(callback, payment, session)

    except Exception as e:
        logger.error(f"Payment check error: {e}")
        await callback.answer("❌ Ошибка проверки платежа", show_alert=True)
    finally:
        session.close()

async def check_yukassa_payment(callback: types.CallbackQuery, payment: Payment, session):
    """Проверяет статус платежа через ЮKassa (Telegram Payments)"""
    try:
        # Для Telegram Payments статус уже должен быть SUCCESS
        if payment.status == 'SUCCESS':
            user = session.query(User).filter(User.id == payment.user_id).first()
            if user:
                # Обновляем подписку пользователя
                if user.subscription_end and user.subscription_end > datetime.now():
                    user.subscription_end += timedelta(days=30)
                else:
                    user.subscription_end = datetime.now() + timedelta(days=30)
                session.commit()

                text = (
                    "🎉 <b>Подписка активирована!</b>\n\n"
                    f"Теперь у вас есть полный доступ ко всем функциям бота.\n"
                    f"Окончание подписки: {user.subscription_end.strftime('%d.%m.%Y')}"
                )
                keyboard = InlineKeyboardMarkup()
                keyboard.add(InlineKeyboardButton("🚀 Начать использовать", callback_data="main_menu"))
                await callback.message.edit_text(text, reply_markup=keyboard)
            else:
                await callback.answer("❌ Пользователь не найден", show_alert=True)
        else:
            await callback.answer(f"⌛ Статус платежа: {payment.status}", show_alert=True)
    except Exception as e:
        logger.error(f"ЮKassa payment check error: {e}")
        await callback.answer("❌ Ошибка проверки платежа ЮKassa", show_alert=True)

async def check_tinkoff_payment(callback: types.CallbackQuery, payment: Payment, session):
    """Проверяет статус платежа через Тинькофф Кассу"""
    try:
        # Получаем конфигурацию Tinkoff
        tinkoff_config = get_tinkoff_config()
        if not tinkoff_config.terminal_key or not tinkoff_config.password:
            await callback.answer("❌ Tinkoff API не настроен!", show_alert=True)
            return

        # Проверяем статус в Tinkoff
        token_data = {
            "TerminalKey": tinkoff_config.terminal_key,
            "PaymentId": payment.payment_id
        }
        token = generate_token(token_data, tinkoff_config.password)

        async with aiohttp.ClientSession() as http_session:
            response = await http_session.post(
                f"{TINKOFF_API_URL}/GetState",
                json={
                    "TerminalKey": tinkoff_config.terminal_key,
                    "PaymentId": payment.payment_id,
                    "Token": token
                },
                headers={"Content-Type": "application/json"}
            )
            data = await response.json()

        if not data.get('Success', False):
            await callback.answer("❌ Ошибка проверки статуса", show_alert=True)
            return

        new_status = data['Status']
        payment.status = new_status
        session.commit()

        if new_status == 'CONFIRMED':
            user = session.query(User).filter(User.id == payment.user_id).first()
            # Обновляем подписку пользователя
            if user.subscription_end and user.subscription_end > datetime.now():
                user.subscription_end += timedelta(days=30)
            else:
                user.subscription_end = datetime.now() + timedelta(days=30)
            session.commit()

            text = (
                "🎉 <b>Подписка активирована!</b>\n\n"
                f"Теперь у вас есть полный доступ ко всем функциям бота.\n"
                f"Окончание подписки: {user.subscription_end.strftime('%d.%m.%Y')}"
            )
            keyboard = InlineKeyboardMarkup()
            keyboard.add(InlineKeyboardButton("🚀 Начать использовать", callback_data="main_menu"))
            await callback.message.edit_text(text, reply_markup=keyboard)
        else:
            status_text = STATUS_DESCRIPTION.get(new_status, new_status)
            await callback.answer(f"⌛ Статус платежа: {status_text}", show_alert=True)
    except Exception as e:
        logger.error(f"Tinkoff payment check error: {e}")
        await callback.answer("❌ Ошибка проверки платежа Тинькофф", show_alert=True)



async def donate_project_callback(callback: types.CallbackQuery):
    await callback.message.answer(
        "Бот бесплатный, но если хотите помочь с развитием — Спасибо! ❤️\n\n"
        "+7 123 456 78 90 - Сбербанк (СБП)"
    )



# Альтернативная функция для DonatePay (быстрое решение)
async def tinkoff_payment_menu_callback(callback: types.CallbackQuery):
    """Показывает меню выбора тарифа для оплаты через Тинькофф"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    keyboard.add(
        InlineKeyboardButton("💳 1 месяц - 299₽", callback_data="tinkoff_pay_month"),
        InlineKeyboardButton("🔙 Назад", callback_data="buy_subscription")
    )
    
    await callback.message.edit_text(
        "🏦 <b>Оплата через Тинькофф Кассу</b>\n\n"
        "Тариф: 299₽ в месяц\n\n"
        "Оплата производится через Тинькофф Кассу",
        reply_markup=keyboard
    )

async def tinkoff_pay_month_callback(callback: types.CallbackQuery):
    """Обрабатывает оплату за месяц через Тинькофф"""
    await callback.answer("🏦 Оплата через Тинькофф Кассу - 299₽/месяц", show_alert=True)
    # Здесь можно добавить логику создания платежа через Тинькофф API

async def donate_project_donatepay_callback(callback: types.CallbackQuery):
    """Быстрое решение с DonatePay"""
    await callback.message.answer(
        "💝 <b>Поддержать проект</b>\n\n"
        "Спасибо за желание поддержать развитие бота!\n\n"
        "🔗 <a href='https://donatepay.ru/don/ваш_логин'>Перейти к донату</a>\n\n"
        "Или отправьте любую сумму на:\n"
        "💳 СБП: +7XXXXXXXXXX\n"
        "💳 Карта: 2202 XXXX XXXX XXXX",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


def register_subscription_handlers(dp):
    dp.register_callback_query_handler(subscription_callback, text="subscription")
    dp.register_callback_query_handler(subscription_callback, text="subscription", state="*")
    dp.register_callback_query_handler(activate_trial_callback, text="activate_trial")
    dp.register_callback_query_handler(activate_trial_callback, text="activate_trial", state="*")
    dp.register_callback_query_handler(buy_subscription_callback, text="buy_subscription")
    dp.register_callback_query_handler(buy_subscription_callback, text="buy_subscription", state="*")
    dp.register_callback_query_handler(tinkoff_payment_menu_callback, text="tinkoff_payment_menu")
    dp.register_callback_query_handler(tinkoff_payment_menu_callback, text="tinkoff_payment_menu", state="*")
    dp.register_callback_query_handler(tinkoff_pay_month_callback, text="tinkoff_pay_month")
    dp.register_callback_query_handler(tinkoff_pay_month_callback, text="tinkoff_pay_month", state="*")
    dp.register_callback_query_handler(activate_demo_subscription_callback, text="activate_demo_subscription")
    dp.register_callback_query_handler(activate_demo_subscription_callback, text="activate_demo_subscription", state="*")
    dp.register_callback_query_handler(check_payment_callback, text="check_payment")
    dp.register_callback_query_handler(check_payment_callback, text="check_payment", state="*")
    dp.register_callback_query_handler(check_payment_callback, lambda c: c.data.startswith('check_payment:'))
    dp.register_callback_query_handler(donate_project_callback, text="donate_project")