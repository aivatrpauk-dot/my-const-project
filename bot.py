import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from tg_bot.config import load_config
from tg_bot.handlers import register_all_handlers
from tg_bot.handlers.subscription import ActivityMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tg_bot.services.scheduler import ReportScheduler
from tg_bot.models.DBSM import sessionmaker, engine, User, Shop, Order, ProductCost, OneTimeExpense, Advertisement, Penalty
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def cleanup_inactive_users():
    print("Запускаю очистку пользователей с истекшей подпиской...")
    session = sessionmaker(bind=engine)()
    current_time = datetime.utcnow()
    three_days_grace_period = timedelta(days=3)  # 3 дня льготного периода

    # Находим пользователей для удаления
    users_to_delete = []
    
    # 1. Пользователи, которые не оплатили подписку в течение 3 дней после пробного периода
    trial_expired_users = session.query(User).filter(
        User.is_trial_used == True,
        User.subscription_start.is_(None),  # Не начали платную подписку
        User.created_at < (current_time - three_days_grace_period)  # Пробный период закончился более 3 дней назад
    ).all()
    
    # 2. Пользователи, которые не продлили подписку в течение 3 дней после её окончания
    subscription_expired_users = session.query(User).filter(
        User.subscription_end < (current_time - three_days_grace_period)  # Подписка закончилась более 3 дней назад
    ).all()
    
    # 3. Проверяем активные платежи через ЮKassa (Telegram Payments)
    from tg_bot.models import Payment
    active_payments = session.query(Payment).filter(
        Payment.payment_method == 'telegram',
        Payment.status == 'SUCCESS',
        Payment.paid_at >= (current_time - timedelta(days=30))  # Платежи за последние 30 дней
    ).all()
    
    # Создаем список пользователей с активными платежами
    users_with_active_payments = [payment.user_id for payment in active_payments]
    
    # Исключаем пользователей с активными платежами из списка на удаление
    trial_expired_users = [user for user in trial_expired_users if user.id not in users_with_active_payments]
    subscription_expired_users = [user for user in subscription_expired_users if user.id not in users_with_active_payments]
    
    users_to_delete = trial_expired_users + subscription_expired_users
    
    print(f"Найдено пользователей с истекшим пробным периодом: {len(trial_expired_users)}")
    print(f"Найдено пользователей с истекшей подпиской: {len(subscription_expired_users)}")
    print(f"Пользователей с активными платежами ЮKassa: {len(users_with_active_payments)}")

    for user in users_to_delete:
        print(f"Удаляю пользователя {user.telegram_id} (ID: {user.id})")
        user_shops = session.query(Shop).filter(Shop.user_id == user.id).all()
        for shop in user_shops:
            shop_id = shop.id
            session.query(Order).filter(Order.shop_id == shop_id).delete()
            session.query(ProductCost).filter(ProductCost.shop_id == shop_id).delete()
            session.query(OneTimeExpense).filter(OneTimeExpense.shop_id == shop_id).delete()
            session.query(Advertisement).filter(Advertisement.shop_id == shop_id).delete()
            session.query(Penalty).filter(Penalty.shop_id == shop_id).delete()
            session.delete(shop)
        session.delete(user)

    session.commit()
    session.close()
    print(f"Удалено пользователей: {len(users_to_delete)}")

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format=u'%(filename)s:%(lineno)d #%(levelname)-8s [%(asctime)s] - %(name)s - %(message)s'
    )
    config = load_config(".env")
    token = '8240807315:AAGj0vTPsia2vW4baFku7qsuy5My0qLl4Rc'
    bot = Bot(token=token, parse_mode="HTML")
    storage = MemoryStorage()
    dp = Dispatcher(bot, storage=storage)
    bot['config'] = config

    # Регистрируем middleware
    dp.middleware.setup(ActivityMiddleware())

    register_all_handlers(dp)

    # --- Здесь запускаем планировщик ---
    scheduler = AsyncIOScheduler()
    scheduler.add_job(cleanup_inactive_users, 'interval', days=1)
    scheduler.start()
    
    # Запускаем планировщик отчетов
    report_scheduler = ReportScheduler(bot)
    asyncio.create_task(report_scheduler.start_scheduler())
    # ------------------------------------

    try:
        await dp.start_polling()
    finally:
        await dp.storage.close()
        await dp.storage.wait_closed()
        await bot.session.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.error("Bot stopped!")
