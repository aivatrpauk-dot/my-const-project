#PNL Ошибка
import logging
import asyncio
import openpyxl
import pandas as pd
from openpyxl import load_workbook
import io
from datetime import datetime, timedelta, datetime as dt
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from tg_bot.models import sessionmaker, engine
from tg_bot.models import Shop, Advertisement, Penalty
from tg_bot.models import (
    TaxSystemType, TaxSystemSetting,
    ProductCost, RegularExpense, OneTimeExpense
)
from tg_bot.keyboards.pnl_menu import pnl_period_keyboard
from tg_bot.services.wb_api import fetch_full_report, fetch_report_detail_by_period
from tg_bot.states.pnl_states import PNLStates
from dateutil.relativedelta import relativedelta
from tg_bot.models import Order

logger = logging.getLogger(__name__)

# Главное меню P&L
async def pnl_callback(callback: types.CallbackQuery, state: FSMContext):
    # Проверяем выбран ли магазин
    async with state.proxy() as data:
        if 'shop' not in data:
            await callback.answer("❌ Сначала выберите магазин", show_alert=True)
            return
    
    keyboard = pnl_period_keyboard()
    await callback.message.answer(
        "📊 <b>Расчёт прибыли и убытков (P&L)</b>\n\n"
        "Выберите период для расчета:",
        reply_markup=keyboard
    )
    await PNLStates.waiting_for_period.set()

async def generate_pnl_excel_report(shop_id: int, shop_api_token: str, start_date: datetime, end_date: datetime, shop_name: str):
    """Генерация Excel-отчета PNL"""

    session = sessionmaker()(bind=engine)
    try:
    # Получаем свежие данные из WB API
        loop = asyncio.get_event_loop()
        full_data = await loop.run_in_executor(
            None,
            fetch_report_detail_by_period,
            shop_api_token,
            start_date,
            end_date
        )    
    
        report_data = full_data['finance']
        orders = full_data['orders']
        sales = full_data['sales']
        
        # Определяем период
        DATE_FROM = start_date.strftime("%Y-%m-%d")
        DATE_TO = end_date.strftime("%Y-%m-%d")

        df_orders = pd.DataFrame(orders)
        df_sales = pd.DataFrame(sales)
        df_fin = pd.DataFrame(report_data)

        def determine_period_type(date_from, date_to):
            """Определяет тип периода и возвращает расширенный период для загрузки."""
            start_dt = dt.strptime(date_from, "%Y-%m-%d")
            end_dt = dt.strptime(date_to, "%Y-%m-%d")
            
            days_diff = (end_dt - start_dt).days
            
            if days_diff == 0:
                # День - загружаем неделю
                period_start = start_dt - timedelta(days=6)
                period_end = start_dt + timedelta(days=6)
                period_type = "день"
            elif days_diff <= 7:
                # Неделя - загружаем месяц
                period_start = start_dt - timedelta(days=30)
                period_end = end_dt + timedelta(days=30)
                period_type = "неделя"
            elif days_diff <= 31:
                # Месяц - загружаем квартал
                period_start = start_dt - timedelta(days=90)
                period_end = end_dt + timedelta(days=90)
                period_type = "месяц"
            else:
                # Год - загружаем год
                period_start = start_dt - timedelta(days=365)
                period_end = end_dt + timedelta(days=365)
                period_type = "год"
            
            return period_start.strftime("%Y-%m-%d"), period_end.strftime("%Y-%m-%d"), period_type

        # Определяем расширенный период
        extended_date_from, extended_date_to, period_type = determine_period_type(DATE_FROM, DATE_TO)

        # day‑столбец
        if not df_orders.empty:
            df_orders["day"] = pd.to_datetime(df_orders["date"]).dt.date
        else:
            df_orders["day"] = pd.to_datetime("2025-01-01").date()
            
        if not df_sales.empty:
            df_sales["day"] = pd.to_datetime(df_sales["date"]).dt.date
        else:
            df_sales["day"] = pd.to_datetime("2025-01-01").date()
        
        # Проверяем наличие поля rr_dt в финансовых данных
        if not df_fin.empty:
            if "rr_dt" in df_fin.columns:
                df_fin["day"] = pd.to_datetime(df_fin["rr_dt"]).dt.date
            elif "date" in df_fin.columns:
                df_fin["day"] = pd.to_datetime(df_fin["date"]).dt.date
            else:
                # Если нет поля даты, создаем пустой столбец day
                df_fin["day"] = pd.to_datetime("2025-01-01").date()
        else:
            df_fin["day"] = pd.to_datetime("2025-01-01").date()

        # 4.1 Orders
        if not df_orders.empty:
            grp_orders = (
                df_orders.groupby("day")
                        .agg(
                            order_sum = ("priceWithDisc", "sum"),
                            ordered_qty = ("srid", "size"),
                            orders_cnt = ("srid", "nunique")
                        )
            )
        else:
            # Создаем пустой DataFrame с нужными столбцами
            grp_orders = pd.DataFrame(columns=['order_sum', 'ordered_qty', 'orders_cnt'])

        # 4.2 Sales (только продажи, не возвраты)
        if not df_sales.empty:
            sales_mask = df_sales["saleID"].str.startswith("S", na=False)
            grp_sales = (
                df_sales[sales_mask]
                .groupby("day")
                .agg(
                    sales_sum = ("priceWithDisc", "sum"),
                    sold_qty = ("saleID", "size"),
                    for_pay = ("forPay", "sum")
                )
            )
        else:
            # Создаем пустой DataFrame с нужными столбцами
            grp_sales = pd.DataFrame(columns=['sales_sum', 'sold_qty', 'for_pay'])

        # 4.3 Finance — logistica = только delivery_rub
        if not df_fin.empty:
            grp_fin = (
                df_fin.groupby("day")
                    .agg(
                        delivery_cost = ("delivery_rub", "sum"),
                        storage = ("storage_fee", "sum"),
                        penalty = ("penalty", "sum"),
                        acceptance = ("acceptance", "sum"),
                        pay_for_goods = ("ppvz_for_pay", "sum")
                    )
                    .apply(pd.to_numeric, errors="coerce")
            )
        else:
            # Создаем пустой DataFrame с нужными столбцами
            grp_fin = pd.DataFrame(columns=['delivery_cost', 'storage', 'penalty', 'acceptance', 'pay_for_goods'])

        # ────────────────────────────────────────────────────────────────────
        # 5. Объединяем и рассчитываем
        # ────────────────────────────────────────────────────────────────────
        all_daily = (
            grp_orders
            .join(grp_sales, how="outer")
            .join(grp_fin, how="outer")
            .fillna(0)
            .infer_objects(copy=False)
        )

        all_daily["buyout_pct"] = (
            all_daily["sold_qty"] / all_daily["ordered_qty"]
        ).fillna(0)

        all_daily["total_to_pay"] = (
            all_daily["pay_for_goods"]
            - all_daily[["delivery_cost", "storage", "penalty", "acceptance"]].sum(axis=1)
        )

        # Фильтруем данные для текущего периода
        current_start = start_date.date()
        current_end = end_date.date()
        daily = all_daily[(all_daily.index >= current_start) & (all_daily.index <= current_end)]
        
        # Отладочная информация
        logger.info(f"Период: {current_start} - {current_end}")
        logger.info(f"Всего записей в all_daily: {len(all_daily)}")
        logger.info(f"Записей в daily после фильтрации: {len(daily)}")
        if not daily.empty:
            logger.info(f"Индексы daily: {daily.index.tolist()}")

        # Получаем рекламу и штрафы из базы данных
        advert = sum(
            i.amount for i in session.query(Advertisement)
            .filter(Advertisement.shop_id == shop_id)
            .filter(Advertisement.date >= start_date)
            .filter(Advertisement.date <= end_date)
        )

        stops = sum(
            i.amount for i in session.query(Penalty)
            .filter(Penalty.shop_id == shop_id)
            .filter(Penalty.date >= start_date)
            .filter(Penalty.date <= end_date)
        )

        # Получаем настройки налоговой системы
        tax_setting = session.query(TaxSystemSetting).filter(TaxSystemSetting.shop_id == shop_id).first()
        
        # Рассчитываем налог
        revenue = daily["sales_sum"].sum()
        if tax_setting:
            if tax_setting.tax_system == TaxSystemType.USN_6:
                tax_rate = 0.06
                print("tax_rate = ", tax_rate)
            elif tax_setting.tax_system == TaxSystemType.NO_TAX:
                tax_rate = 0.0
                print("tax_rate = ", tax_rate)
            elif tax_setting.tax_system == TaxSystemType.CUSTOM:
                tax_rate = tax_setting.custom_percent / 100
                print("tax_rate = ", tax_rate)
            else:
                tax_rate = 0.0
                print("пошло в else")
        else:
            tax_rate = 0.0
            
        tax = revenue * tax_rate
        
        # Себестоимость (как в analytics.py)
        cost_of_goods = 0
        articles = {}
        
        # Собираем артикулы для расчета себестоимости
        for item in report_data:
            if not isinstance(item, dict):
                continue
            article = item.get("nm_id")
            quantity = item.get("quantity", 0)
            if article and quantity:
                if article not in articles:
                    articles[article] = 0
                articles[article] += quantity

        # Рассчитываем себестоимость
        for article, quantity in articles.items():
            try:
                supp_article = session.query(Order).filter(Order.nmId == int(article)).first().supplierArticle
                product_cost = (
                    session.query(ProductCost)
                    .filter(ProductCost.shop_id == shop_id, ProductCost.article == supp_article)
                    .first()
                )
                if product_cost:
                    cost_of_goods += product_cost.cost * quantity
            except:
                pass
        
        # Формируем метрики как в Test.py
        monthly_data = {
            "Заказы": daily["order_sum"].sum(),
            "Выкупы": daily["sales_sum"].sum(),
            "Комиссия": daily["pay_for_goods"].sum(),
            "Себестоймость": cost_of_goods,  # Теперь с правильным расчетом
            "Налог": tax,
            "Логистика": daily["delivery_cost"].sum(),
            "Хранение": daily["storage"].sum(),
            "Штрафы и корректировки": daily["penalty"].sum() + stops,
            "Реклама": advert,
            "К перечислению": daily["sales_sum"].sum() - daily["pay_for_goods"].sum() - daily["delivery_cost"].sum() - daily["storage"].sum() - (daily["penalty"].sum() + stops) - advert - cost_of_goods,
            "Чистая прибыль": daily["sales_sum"].sum() - daily["pay_for_goods"].sum() - daily[["delivery_cost", "storage", "penalty"]].sum().sum() - advert - tax - cost_of_goods
        }

        # Получаем данные для сравнения (предыдущий период)
        if period_type == "день":
            # Для дня - предыдущий день
            prev_start = current_start - timedelta(days=1)
            prev_end = prev_start
            period_days = 1
        elif period_type == "неделя":
            # Для недели - предыдущая неделя
            prev_start = current_start - timedelta(days=7)
            prev_end = current_start - timedelta(days=1)
            period_days = 7
        elif period_type == "месяц":
            # Для месяца - предыдущий месяц
            prev_start = current_start - timedelta(days=30)
            prev_end = current_start - timedelta(days=1)
            period_days = 30
        else:  # год
            # Для года - предыдущий год
            prev_start = current_start - timedelta(days=365)
            prev_end = current_start - timedelta(days=1)
            period_days = 365

        # Получаем данные за предыдущий период
        prev_daily = all_daily[(all_daily.index >= prev_start) & (all_daily.index <= prev_end)]

        # Рассчитываем налог для предыдущего периода
        prev_revenue = prev_daily["sales_sum"].sum()
        prev_tax = prev_revenue * tax_rate

        # Получаем рекламу за предыдущий период
        prev_advert = sum(
            i.amount for i in session.query(Advertisement)
            .filter(Advertisement.shop_id == shop_id)
            .filter(Advertisement.date >= start_date - timedelta(days=period_days))
            .filter(Advertisement.date < start_date)
            .all()
        )

        # Себестоимость для предыдущего периода (как в analytics.py)
        prev_cost_of_goods = 0
        prev_articles = {}
        
        # Собираем артикулы для расчета себестоимости за предыдущий период
        for item in report_data:
            if not isinstance(item, dict):
                continue
            article = item.get("nm_id")
            quantity = item.get("quantity", 0)
            # Проверяем, что товар был продан в предыдущем периоде
            item_date = datetime.strptime(item.get("sale_dt", "2025-01-01")[:10], "%Y-%m-%d").date()
            if prev_start <= item_date <= prev_end and article and quantity:
                if article not in prev_articles:
                    prev_articles[article] = 0
                prev_articles[article] += quantity

        # Рассчитываем себестоимость для предыдущего периода
        for article, quantity in prev_articles.items():
            try:
                supp_article = session.query(Order).filter(Order.nmId == int(article)).first().supplierArticle
                product_cost = (
                    session.query(ProductCost)
                    .filter(ProductCost.shop_id == shop_id, ProductCost.article == supp_article)
                    .first()
                )
                if product_cost:
                    prev_cost_of_goods += product_cost.cost * quantity
            except:
                pass

        # Формируем метрики за предыдущий период
        prev_monthly_data = {
            "Заказы": prev_daily["order_sum"].sum(),
            "Выкупы": prev_daily["sales_sum"].sum(),
            "Комиссия": prev_daily["pay_for_goods"].sum(),
            "Себестоймость": prev_cost_of_goods,  # Теперь с правильным расчетом
            "Налог": prev_tax,
            "Логистика": prev_daily["delivery_cost"].sum(),
            "Хранение": prev_daily["storage"].sum(),
            "Штрафы и корректировки": prev_daily["penalty"].sum(),
            "Реклама": prev_advert,
            "К перечислению": prev_daily["sales_sum"].sum() - prev_daily["pay_for_goods"].sum() - prev_daily["delivery_cost"].sum() - prev_daily["storage"].sum() - prev_daily["penalty"].sum() - prev_advert - prev_cost_of_goods,
            "Чистая прибыль": prev_daily["sales_sum"].sum() - prev_daily["pay_for_goods"].sum() - prev_daily[["delivery_cost", "storage", "penalty"]].sum().sum() - prev_tax - prev_advert - prev_cost_of_goods
        }

        # Рассчитываем относительные изменения
        def calculate_relative_change(current, previous):
            if previous == 0:
                return 0
            return (current - previous) / previous

        relative_changes = {}
        for metric in monthly_data.keys():
            relative_changes[metric] = calculate_relative_change(
                monthly_data[metric], 
                prev_monthly_data[metric]
            )

        # Проверяем наличие данных только для логирования
        if not report_data:
            logger.warning("Нет данных из API, но продолжаем обработку")

        # Определяем путь к шаблону
        def determine_template_path(period_type):
            """Определяет путь к шаблону в зависимости от типа периода."""
            if period_type == "год":
                return "pnl_template_year.xlsx"
            else:
                return "pnl_template.xlsx"

        template_path = determine_template_path(period_type)

        # Загружаем шаблон
        try:
            wb = load_workbook(template_path)
        except FileNotFoundError:
            logger.error(f"Файл шаблона {template_path} не найден")
            return None

        ws = wb.active

        # Функция для расчета себестоимости за конкретный день
        def calculate_cost_for_day(day_date, report_data):
            day_cost = 0
            day_articles = {}
            
            for item in report_data:
                if not isinstance(item, dict):
                    continue
                article = item.get("nm_id")
                quantity = item.get("quantity", 0)
                item_date = datetime.strptime(item.get("sale_dt", "2025-01-01")[:10], "%Y-%m-%d").date()
                
                # Убеждаемся, что day_date тоже является date объектом
                if isinstance(day_date, datetime):
                    day_date = day_date.date()
                
                if item_date == day_date and article and quantity:
                    if article not in day_articles:
                        day_articles[article] = 0
                    day_articles[article] += quantity
            
            for article, quantity in day_articles.items():
                try:
                    supp_article = session.query(Order).filter(Order.nmId == int(article)).first().supplierArticle
                    product_cost = (
                        session.query(ProductCost)
                        .filter(ProductCost.shop_id == shop_id, ProductCost.article == supp_article)
                        .first()
                    )
                    if product_cost:
                        day_cost += product_cost.cost * quantity
                except:
                    pass
            
            return day_cost

        # Функция для расчета себестоимости за конкретный месяц
        def calculate_cost_for_month(month_num, year, report_data):
            month_cost = 0
            month_articles = {}
            
            month_start = datetime(year, month_num, 1)
            if month_num == 12:
                month_end = datetime(year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = datetime(year, month_num + 1, 1) - timedelta(days=1)
            
            for item in report_data:
                if not isinstance(item, dict):
                    continue
                article = item.get("nm_id")
                quantity = item.get("quantity", 0)
                item_date = datetime.strptime(item.get("sale_dt", "2025-01-01")[:10], "%Y-%m-%d")
                
                if month_start <= item_date <= month_end and article and quantity:
                    if article not in month_articles:
                        month_articles[article] = 0
                    month_articles[article] += quantity
            
            for article, quantity in month_articles.items():
                try:
                    supp_article = session.query(Order).filter(Order.nmId == int(article)).first().supplierArticle
                    product_cost = (
                        session.query(ProductCost)
                        .filter(ProductCost.shop_id == shop_id, ProductCost.article == supp_article)
                        .first()
                    )
                    if product_cost:
                        month_cost += product_cost.cost * quantity
                except:
                    pass
            
            return month_cost

        # Заполняем столбец C (текущие метрики)
        row_mapping = {
            "Заказы": 3,
            "Выкупы": 4,
            "Комиссия": 5,
            "Себестоймость": 6,
            "Налог": 7,
            "Логистика": 8,
            "Хранение": 9,
            "Штрафы и корректировки": 10,
            "Реклама": 11,
            "К перечислению": 12,
            "Чистая прибыль": 13
        }

        for metric, value in monthly_data.items():
            row = row_mapping.get(metric)
            if row:
                ws[f"C{row}"] = value

        # Заполняем столбец E (относительные изменения)
        for metric, change in relative_changes.items():
            row = row_mapping.get(metric)
            if row:
                ws[f"E{row}"] = change

        # Заполняем столбцы F-AJ в зависимости от типа периода
        if period_type == "день":
            # Для дня - не заполняем столбцы F-AJ
            pass
        elif period_type == "неделя":
            # Для недели - заполняем F-L по дням недели
            weekdays = ['F', 'G', 'H', 'I', 'J', 'K', 'L']
            for i, col in enumerate(weekdays):
                if i < len(daily):
                    day_data = daily.iloc[i] if i < len(daily) else pd.Series(0, index=daily.columns)
                    day_date = start_date + timedelta(days=i)
                    day_cost = calculate_cost_for_day(day_date, report_data)
                    
                    ws[f"{col}3"] = day_data.get("order_sum", 0)  # Заказы
                    ws[f"{col}4"] = day_data.get("sales_sum", 0)  # Выкупы
                    ws[f"{col}5"] = day_data.get("pay_for_goods", 0)  # Комиссия
                    ws[f"{col}6"] = day_cost  # Себестоймость
                    ws[f"{col}7"] = day_data.get("sales_sum", 0) * tax_rate  # Налог
                    ws[f"{col}8"] = day_data.get("delivery_cost", 0)  # Логистика
                    ws[f"{col}9"] = day_data.get("storage", 0)  # Хранение
                    ws[f"{col}10"] = day_data.get("penalty", 0)  # Штрафы и корректировки
                    # Получаем рекламу для конкретного дня
                    day_advert = sum(
                        i.amount for i in session.query(Advertisement)
                        .filter(Advertisement.shop_id == shop_id)
                        .filter(Advertisement.date == day_date)
                        .all()
                    )
                    ws[f"{col}11"] = day_advert  # Реклама
                    ws[f"{col}12"] = day_data.get("sales_sum", 0) - day_data.get("pay_for_goods", 0) - day_data.get("delivery_cost", 0) - day_data.get("storage", 0) - day_data.get("penalty", 0) - day_advert - day_cost  # К перечислению
                    ws[f"{col}13"] = day_data.get("sales_sum", 0) - day_data.get("pay_for_goods", 0) - day_data.get("delivery_cost", 0) - day_data.get("storage", 0) - day_data.get("penalty", 0) - (day_data.get("sales_sum", 0) * tax_rate) - day_advert - day_cost  # Чистая прибыль
        elif period_type == "месяц":
            # Для месяца - заполняем F-AJ по дням месяца
            columns = ['F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z',
                       'AA', 'AB', 'AC', 'AD', 'AE', 'AF', 'AG', 'AH', 'AI', 'AJ']
            
            for day_num in range(1, 32):
                if day_num <= len(columns):
                    col_letter = columns[day_num - 1]
                    day_date = current_start.replace(day=day_num)
                    if day_date in daily.index:
                        day_data = daily.loc[day_date]
                    else:
                        day_data = pd.Series(0, index=daily.columns)
                    
                    day_cost = calculate_cost_for_day(day_date, report_data)
                    
                    ws[f"{col_letter}3"] = day_data.get("order_sum", 0)  # Заказы
                    ws[f"{col_letter}4"] = day_data.get("sales_sum", 0)  # Выкупы
                    ws[f"{col_letter}5"] = day_data.get("pay_for_goods", 0)  # Комиссия
                    ws[f"{col_letter}6"] = day_cost  # Себестоймость
                    ws[f"{col_letter}7"] = day_data.get("sales_sum", 0) * tax_rate  # Налог
                    ws[f"{col_letter}8"] = day_data.get("delivery_cost", 0)  # Логистика
                    ws[f"{col_letter}9"] = day_data.get("storage", 0)  # Хранение
                    ws[f"{col_letter}10"] = day_data.get("penalty", 0)  # Штрафы и корректировки
                    # Получаем рекламу для конкретного дня месяца
                    day_advert = sum(
                        i.amount for i in session.query(Advertisement)
                        .filter(Advertisement.shop_id == shop_id)
                        .filter(Advertisement.date == day_date)
                        .all()
                    )
                    ws[f"{col_letter}11"] = day_advert  # Реклама
                    ws[f"{col_letter}12"] = day_data.get("sales_sum", 0) - day_data.get("pay_for_goods", 0) - day_data.get("delivery_cost", 0) - day_data.get("storage", 0) - day_data.get("penalty", 0) - day_advert - day_cost  # К перечислению
                    ws[f"{col_letter}13"] = day_data.get("sales_sum", 0) - day_data.get("pay_for_goods", 0) - day_data.get("delivery_cost", 0) - day_data.get("storage", 0) - day_data.get("penalty", 0) - (day_data.get("sales_sum", 0) * tax_rate) - day_advert - day_cost  # Чистая прибыль
        elif period_type == "год":
            # Для года - заполняем F-Q по месяцам
            months = ['F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q']
            
            # Группируем данные по месяцам
            daily_copy = daily.copy()
            daily_copy.index = pd.to_datetime(daily_copy.index)
            
            # Определяем текущий месяц
            current_month = dt.now().month
            current_year = dt.now().year
            
            for month_num in range(1, 13):
                if month_num <= current_month:  # Заполняем только до текущего месяца
                    col_letter = months[month_num - 1]
                    month_data = daily_copy[daily_copy.index.month == month_num]
                    
                    if not month_data.empty:
                        month_sum = month_data.sum()
                        month_cost = calculate_cost_for_month(month_num, current_year, report_data)
                        
                        ws[f"{col_letter}3"] = month_sum.get("order_sum", 0)  # Заказы
                        ws[f"{col_letter}4"] = month_sum.get("sales_sum", 0)  # Выкупы
                        ws[f"{col_letter}5"] = month_sum.get("pay_for_goods", 0)  # Комиссия
                        ws[f"{col_letter}6"] = month_cost  # Себестоймость
                        ws[f"{col_letter}7"] = month_sum.get("sales_sum", 0) * tax_rate  # Налог
                        ws[f"{col_letter}8"] = month_sum.get("delivery_cost", 0)  # Логистика
                        ws[f"{col_letter}9"] = month_sum.get("storage", 0)  # Хранение
                        ws[f"{col_letter}10"] = month_sum.get("penalty", 0)  # Штрафы и корректировки
                        # Получаем рекламу для конкретного месяца
                        month_start = datetime(current_year, month_num, 1)
                        month_end = datetime(current_year, month_num, 1) + relativedelta(months=1) - timedelta(days=1)
                        month_advert = sum(
                            i.amount for i in session.query(Advertisement)
                            .filter(Advertisement.shop_id == shop_id)
                            .filter(Advertisement.date >= month_start)
                            .filter(Advertisement.date <= month_end)
                            .all()
                        )
                        ws[f"{col_letter}11"] = month_advert  # Реклама
                        ws[f"{col_letter}12"] = month_sum.get("sales_sum", 0) - month_sum.get("pay_for_goods", 0) - month_sum.get("delivery_cost", 0) - month_sum.get("storage", 0) - month_sum.get("penalty", 0) - month_advert - month_cost  # К перечислению
                        ws[f"{col_letter}13"] = month_sum.get("sales_sum", 0) - month_sum.get("pay_for_goods", 0) - month_sum.get("delivery_cost", 0) - month_sum.get("storage", 0) - month_sum.get("penalty", 0) - (month_sum.get("sales_sum", 0) * tax_rate) - month_advert - month_cost  # Чистая прибыль

        return wb
        
    except Exception as e:
        logger.error(f"Ошибка генерации PNL отчета: {e}")
        return None
    finally:
        session.close()

# Обработка выбора периода
async def select_pnl_period_callback(callback: types.CallbackQuery, state: FSMContext):
    period_type = callback.data.split('_')[1]  # day, week, month, year
    await callback.message.edit_text(text="Подождите около 10 секунд, пока произведем подсчёт данных... (иногда дольше, но не более 2х минут)")
    
    # Определяем периоды
    now = datetime.utcnow()
    if period_type == "week":
        # Находим последний понедельник
        start_week = now - timedelta(days=now.isoweekday() - 1)
        start_date = datetime(start_week.year, start_week.month, start_week.day)
        end_date = now
        period_name = "неделю"
    elif period_type == "month":
        start_date = datetime(now.year, now.month, 1)
        end_date = now
        period_name = "месяц"
    elif period_type == "year":
        start_date = datetime(now.year, 1, 1)
        end_date = now
        period_name = "год"
    else:  # day
        start_date = now - timedelta(days=1)
        end_date = now
        period_name = "день"
    
    async with state.proxy() as data:
        shop_id = data['shop']['id']
        shop_name = data['shop']['name'] or f"Магазин {shop_id}"
        shop_api_token = data['shop']['api_token']
    
    # Показываем сообщение о загрузке
    await callback.message.edit_text(
        f"📊 <b>Генерация PNL отчета</b>\n\n"
        f"Магазин: {shop_name}\n"
        f"Период: за {period_name}\n\n"
        "Подождите, идет сбор и обработка данных..."
    )
    
    # Генерируем Excel отчет
    wb = await generate_pnl_excel_report(shop_id, shop_api_token, start_date, end_date, shop_name)
    
    if not wb:
        await callback.message.edit_text(
            "❌ <b>Не удалось сгенерировать отчет</b>\n\n"
            "Возможные причины:\n"
            "1. Нет данных за выбранный период\n"
            "2. Проблемы с подключением к базе данных\n"
            "3. Файл шаблона pnl_template.xlsx не найден"
        )
        return
    
    # Сохраняем в буфер
    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)
    
    # Формируем имя файла
    safe_shop_name = "".join(c for c in shop_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    filename = f"pnl_{safe_shop_name}_{datetime.now().strftime('%Y%m%d%H%M')}.xlsx"
    
    # Отправляем файл
    file = InputFile(file_stream, filename=filename)
    await callback.message.answer_document(
        file,
        caption=f"📊 PNL отчет за {period_name}\nМагазин: {shop_name}"
    )
    
    # Возвращаемся к меню PNL
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔙 Назад", callback_data="pnl"))
    await callback.message.answer("✅ Отчет готов!", reply_markup=keyboard)

def register_pnl_handlers(dp):
    dp.register_callback_query_handler(pnl_callback, text="pnl", state="*")
    dp.register_callback_query_handler(
        select_pnl_period_callback, 
        lambda c: c.data.startswith("pnlperiod_"), 
        state=PNLStates.waiting_for_period
    )