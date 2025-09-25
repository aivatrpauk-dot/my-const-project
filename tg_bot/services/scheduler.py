import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import sessionmaker
from tg_bot.models.DBSM import engine, User, Shop
from tg_bot.handlers.pnl import generate_pnl_excel_report
from tg_bot.services.wb_api import fetch_report_detail_by_period
from aiogram import Bot
import os

logger = logging.getLogger(__name__)

class ReportScheduler:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.session = sessionmaker(bind=engine)
        
    async def send_weekly_report(self):
        """Отправляет еженедельные отчеты каждую среду в 12:00"""
        try:
            logger.info("Запуск отправки еженедельных отчетов")
            
            # Вычисляем период за прошедшую неделю
            today = datetime.now()
            # Находим прошлую среду
            days_since_wednesday = (today.weekday() - 2) % 7
            if days_since_wednesday == 0:
                days_since_wednesday = 7
            last_wednesday = today - timedelta(days=days_since_wednesday)
            week_start = last_wednesday - timedelta(days=6)  # Начало недели (понедельник)
            week_end = last_wednesday  # Конец недели (воскресенье)
            
            await self._send_reports_to_users(week_start, week_end, "еженедельный")
            
        except Exception as e:
            logger.error(f"Ошибка при отправке еженедельных отчетов: {e}")
    
    async def send_monthly_report(self):
        """Отправляет ежемесячные отчеты каждое 3 число в 12:00"""
        try:
            logger.info("Запуск отправки ежемесячных отчетов")
            
            # Вычисляем период за прошедший месяц
            today = datetime.now()
            if today.day >= 3:
                # Если сегодня 3 число или позже, берем прошлый месяц
                if today.month == 1:
                    last_month = today.replace(year=today.year-1, month=12)
                else:
                    last_month = today.replace(month=today.month-1)
            else:
                # Если сегодня 1-2 число, берем месяц до прошлого
                if today.month <= 2:
                    if today.month == 1:
                        last_month = today.replace(year=today.year-1, month=11)
                    else:
                        last_month = today.replace(year=today.year-1, month=12)
                else:
                    last_month = today.replace(month=today.month-2)
            
            month_start = last_month.replace(day=1)
            # Конец месяца - первый день следующего месяца минус 1 день
            if last_month.month == 12:
                next_month = last_month.replace(year=last_month.year+1, month=1)
            else:
                next_month = last_month.replace(month=last_month.month+1)
            month_end = next_month.replace(day=1) - timedelta(days=1)
            
            await self._send_reports_to_users(month_start, month_end, "ежемесячный")
            
        except Exception as e:
            logger.error(f"Ошибка при отправке ежемесячных отчетов: {e}")
    
    async def _send_reports_to_users(self, start_date: datetime, end_date: datetime, report_type: str):
        """Отправляет отчеты всем пользователям с включенными ежедневными отчетами"""
        session = self.session()
        try:
            # Получаем всех пользователей с включенными ежедневными отчетами
            users = session.query(User).filter(User.daily_reports_enabled == True).all()
            
            for user in users:
                try:
                    # Получаем магазин пользователя
                    shop = session.query(Shop).filter(Shop.user_id == user.id).first()
                    if not shop:
                        logger.warning(f"Магазин не найден для пользователя {user.telegram_id}")
                        continue
                    
                    # Получаем данные напрямую из API
                    loop = asyncio.get_event_loop()
                    full_data = await loop.run_in_executor(
                        None,
                        fetch_report_detail_by_period,
                        shop.api_token,
                        start_date,
                        end_date
                    )
                    
                    # Генерируем отчет
                    wb = await generate_pnl_excel_report(
                        shop.id,
                        shop.api_token,
                        start_date,
                        end_date,
                        shop.name,
                        full_data
                    )
                    
                    if wb:
                        # Сохраняем файл
                        filename = f"pnl_{report_type}_{shop.id}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}.xlsx"
                        wb.save(filename)
                        
                        # Отправляем файл пользователю
                        with open(filename, 'rb') as file:
                            await self.bot.send_document(
                                chat_id=user.telegram_id,
                                document=file,
                                caption=f"📊 {report_type.capitalize()} отчет за период {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}"
                            )
                        
                        # Удаляем временный файл
                        os.remove(filename)
                        logger.info(f"Отправлен {report_type} отчет пользователю {user.telegram_id}")
                    else:
                        logger.warning(f"Не удалось сгенерировать {report_type} отчет для пользователя {user.telegram_id}")
                        
                except Exception as e:
                    logger.error(f"Ошибка при отправке {report_type} отчета пользователю {user.telegram_id}: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка при получении пользователей: {e}")
        finally:
            session.close()
    
    async def start_scheduler(self):
        """Запускает планировщик задач"""
        logger.info("Запуск планировщика автоматических отчетов")
        
        # ТЕСТОВЫЙ РЕЖИМ - каждые 5 минут
        TEST_MODE = True  # Изменить на False для возврата к нормальному режиму
        
        while True:
            try:
                now = datetime.now()
                
                if False:
                    # ТЕСТОВЫЙ РЕЖИМ - каждые 5 минут
                    print("Тестовый отчёт пошёл", now.minute)
                    if now.minute % 5 == 0:  # Срабатывает каждые 5 минут в первые 10 секунд
                        logger.info("🧪 ТЕСТОВЫЙ РЕЖИМ: Отправка еженедельного отчета")
                        await self.send_weekly_report()
                        logger.info("🧪 ТЕСТОВЫЙ РЕЖИМ: Отправка ежемесячного отчета")
                        await self.send_monthly_report()
                else:
                    # НОРМАЛЬНЫЙ РЕЖИМ
                    # Проверяем, нужно ли отправить еженедельный отчет (среда в 12:00)
                    if now.weekday() == 2 and now.hour == 12 and now.minute == 0:
                        await self.send_weekly_report()
                    
                    # Проверяем, нужно ли отправить ежемесячный отчет (3 число в 12:00)
                    if now.day == 3 and now.hour == 12 and now.minute == 0:
                        await self.send_monthly_report()
                
                # Ждем 1 минуту перед следующей проверкой
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Ошибка в планировщике: {e}")
                await asyncio.sleep(60) 