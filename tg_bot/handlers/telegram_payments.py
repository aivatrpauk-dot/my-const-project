import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice
from aiogram.dispatcher import FSMContext
from tg_bot.models import sessionmaker, engine, User, Payment

logger = logging.getLogger(__name__)

# Конфигурация Telegram Payments - вписываем данные прямо в код
TELEGRAM_PAYMENT_CONFIG = {
    'provider_token': 'YOUR_TELEGRAM_PAYMENT_PROVIDER_TOKEN_HERE',  # Замените на ваш токен
    'currency': 'RUB'
}

# Статусы платежей
PAYMENT_STATUS = {
    'PENDING': 'Ожидает оплаты',
    'SUCCESS': 'Оплачен',
    'FAILED': 'Ошибка оплаты',
    'CANCELLED': 'Отменен'
}

class TelegramPaymentHandler:
    def __init__(self):
        self.provider_token = TELEGRAM_PAYMENT_CONFIG['provider_token']
        self.currency = TELEGRAM_PAYMENT_CONFIG['currency']
    
    async def create_invoice(self, user_id: int, amount: int, title: str, description: str, payload: str = None):
        """Создает инвойс для оплаты через Telegram"""
        try:
            # Создаем платеж в базе данных
            session = sessionmaker()(bind=engine)
            try:
                payment = Payment(
                    user_id=user_id,
                    amount=amount,
                    currency=self.currency,
                    status='PENDING',
                    payment_method='telegram',
                    created_at=datetime.utcnow()
                )
                session.add(payment)
                session.commit()
                payment_id = payment.id
            finally:
                session.close()
            
            # Создаем инвойс для Telegram
            prices = [LabeledPrice(label=title, amount=amount * 100)]  # amount в копейках
            
            invoice_data = {
                'title': title,
                'description': description,
                'payload': payload or f"payment_{payment_id}",
                'provider_token': self.provider_token,
                'currency': self.currency,
                'prices': prices,
                'start_parameter': f"payment_{payment_id}",
                'need_name': False,
                'need_phone_number': False,
                'need_email': False,
                'need_shipping_address': False,
                'send_phone_number_to_provider': False,
                'send_email_to_provider': False,
                'is_flexible': False
            }
            
            return invoice_data, payment_id
            
        except Exception as e:
            logger.error(f"Error creating invoice: {e}")
            return None, None
    
    async def process_successful_payment(self, payment_id: int, telegram_payment_id: str):
        """Обрабатывает успешный платеж"""
        session = sessionmaker()(bind=engine)
        try:
            payment = session.query(Payment).filter(Payment.id == payment_id).first()
            if payment:
                payment.status = 'SUCCESS'
                payment.telegram_payment_id = telegram_payment_id
                payment.paid_at = datetime.utcnow()
                
                # Активируем подписку пользователя
                user = session.query(User).filter(User.id == payment.user_id).first()
                if user:
                    # Определяем срок подписки на основе суммы
                    if payment.amount >= 299:  # 299 рублей = 1 месяц
                        subscription_days = 30
                    else:
                        subscription_days = 7  # Демо период
                    
                    user.subscription_end = datetime.utcnow() + timedelta(days=subscription_days)
                    user.is_subscribed = True
                
                session.commit()
                return True
        except Exception as e:
            logger.error(f"Error processing successful payment: {e}")
            session.rollback()
        finally:
            session.close()
        return False

# Создаем экземпляр обработчика
payment_handler = TelegramPaymentHandler()

async def show_telegram_payment_menu(callback: types.CallbackQuery):
    """Показывает меню выбора тарифа для оплаты через Telegram"""
    keyboard = InlineKeyboardMarkup(row_width=1)
    
    keyboard.add(
        InlineKeyboardButton("💳 1 месяц - 299₽", callback_data="telegram_pay_month"),
        InlineKeyboardButton("🔙 Назад", callback_data="subscription_menu")
    )
    
    await callback.message.edit_text(
        "💳 <b>Оплата через Telegram</b>\n\n"
        "Тариф: 299₽ в месяц\n\n"
        "Оплата производится через Telegram Payments",
        reply_markup=keyboard
    )

async def handle_telegram_payment_month(callback: types.CallbackQuery):
    """Обрабатывает оплату за месяц"""
    await create_telegram_payment(callback, 299, "Подписка на 1 месяц", "Доступ к аналитике на 30 дней")

async def create_telegram_payment(callback: types.CallbackQuery, amount: int, title: str, description: str):
    """Создает платеж через Telegram"""
    if not payment_handler.provider_token:
        await callback.answer("❌ Платежная система не настроена", show_alert=True)
        return
    
    user_id = callback.from_user.id
    
    # Получаем пользователя из БД
    session = sessionmaker()(bind=engine)
    try:
        user = session.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            await callback.answer("❌ Пользователь не найден", show_alert=True)
            return
    finally:
        session.close()
    
    # Создаем инвойс
    invoice_data, payment_id = await payment_handler.create_invoice(user_id, amount, title, description)
    
    if not invoice_data:
        await callback.answer("❌ Ошибка создания платежа", show_alert=True)
        return
    
    try:
        # Отправляем инвойс пользователю
        await callback.message.bot.send_invoice(
            chat_id=user_id,
            **invoice_data
        )
        await callback.answer("✅ Платежная форма отправлена")
    except Exception as e:
        logger.error(f"Error sending invoice: {e}")
        await callback.answer("❌ Ошибка отправки платежной формы", show_alert=True)

async def handle_pre_checkout(pre_checkout_query: types.PreCheckoutQuery):
    """Обрабатывает предварительную проверку платежа"""
    await pre_checkout_query.answer(ok=True)

async def handle_successful_payment(message: types.Message):
    """Обрабатывает успешный платеж"""
    try:
        payment_info = message.successful_payment
        payment_id = int(payment_info.invoice_payload.split('_')[1])
        
        success = await payment_handler.process_successful_payment(
            payment_id, 
            payment_info.telegram_payment_charge_id
        )
        
        if success:
            await message.answer(
                "✅ <b>Оплата прошла успешно!</b>\n\n"
                "Ваша подписка активирована. Теперь вы можете использовать все функции бота.",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                "❌ <b>Ошибка обработки платежа</b>\n\n"
                "Пожалуйста, обратитесь в поддержку.",
                parse_mode="HTML"
            )
            
    except Exception as e:
        logger.error(f"Error handling successful payment: {e}")
        await message.answer(
            "❌ <b>Ошибка обработки платежа</b>\n\n"
            "Пожалуйста, обратитесь в поддержку.",
            parse_mode="HTML"
        )

def register_telegram_payment_handlers(dp):
    """Регистрирует обработчики для Telegram платежей"""
    dp.register_callback_query_handler(show_telegram_payment_menu, lambda c: c.data == "telegram_payment_menu")
    dp.register_callback_query_handler(handle_telegram_payment_month, lambda c: c.data == "telegram_pay_month")
    dp.register_pre_checkout_query_handler(handle_pre_checkout)
    dp.register_message_handler(handle_successful_payment, content_types=types.ContentTypes.SUCCESSFUL_PAYMENT) 