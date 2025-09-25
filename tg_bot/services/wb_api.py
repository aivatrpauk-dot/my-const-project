import requests
import logging
from datetime import datetime, timedelta
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
import json
import hashlib
from tg_bot.models import sessionmaker, engine, WBCacheData
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=5)

# Константы для кэширования
CACHE_DURATION_HOURS = 24  # Кэш действителен 24 часа
CACHE_PERIOD_DAYS = 730   # Кэшируем данные за 2 года (730 дней)


def get_api_token_hash(api_token: str) -> str:
    """Создает хеш API токена для безопасного хранения"""
    return hashlib.sha256(api_token.encode()).hexdigest()


def get_cached_data(shop_id: int, api_token: str, cache_type: str, period_start: datetime, period_end: datetime) -> list:
    """Получает кэшированные данные из базы данных"""
    session = sessionmaker()(bind=engine)
    try:
        api_token_hash = get_api_token_hash(api_token)
        
        # Ищем кэш в базе данных
        cache_record = session.query(WBCacheData).filter(
            WBCacheData.shop_id == shop_id,
            WBCacheData.api_token == api_token_hash,
            WBCacheData.cache_type == cache_type,
            WBCacheData.period_start <= period_start,
            WBCacheData.period_end >= period_end
        ).first()
        
        if cache_record:
            # Проверяем, не устарел ли кэш
            cache_age = datetime.now() - cache_record.cache_timestamp
            if cache_age.total_seconds() <= CACHE_DURATION_HOURS * 3600:
                logger.info(f"Найден актуальный кэш для {cache_type} (возраст: {cache_age.total_seconds() / 3600:.1f} часов)")
                return cache_record.data
            else:
                logger.info(f"Кэш для {cache_type} устарел (возраст: {cache_age.total_seconds() / 3600:.1f} часов)")
                # Удаляем устаревший кэш
                session.delete(cache_record)
                session.commit()
        
        return []
        
    except Exception as e:
        logger.error(f"Ошибка получения кэша для {cache_type}: {e}")
        return []
    finally:
        session.close()


def save_cached_data(shop_id: int, api_token: str, cache_type: str, data: list, period_start: datetime, period_end: datetime):
    """Сохраняет данные в кэш базы данных"""
    session = sessionmaker()(bind=engine)
    try:
        api_token_hash = get_api_token_hash(api_token)
        
        # Удаляем старые записи кэша для этого типа данных
        session.query(WBCacheData).filter(
            WBCacheData.shop_id == shop_id,
            WBCacheData.api_token == api_token_hash,
            WBCacheData.cache_type == cache_type
        ).delete()
        
        # Создаем новую запись кэша
        cache_record = WBCacheData(
            shop_id=shop_id,
            api_token=api_token_hash,
            cache_type=cache_type,
            data=data,
            cache_timestamp=datetime.now(),
            period_start=period_start,
            period_end=period_end
        )
        
        session.add(cache_record)
        session.commit()
        logger.info(f"Кэш для {cache_type} сохранен в базу данных")
        
    except Exception as e:
        logger.error(f"Ошибка сохранения кэша для {cache_type}: {e}")
        session.rollback()
    finally:
        session.close()


async def fetch_report_async(api_token: str, date_from: datetime, date_to: datetime):
    """Асинхронная обертка для получения отчета"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor, 
        fetch_report_detail_by_period, 
        api_token, date_from, date_to
    )


def calculate_period_intervals(start_date: datetime, end_date: datetime):
    """Разбивает период на интервалы по 28 дней (ограничение WB API)"""
    intervals = []
    current = start_date
    while current < end_date:
        next_date = current + timedelta(days=28)
        if next_date > end_date:
            next_date = end_date
        intervals.append((current, next_date))
        current = next_date + timedelta(days=1)
    return intervals


async def fetch_full_report(api_token: str, start_date: datetime, end_date: datetime, shop_id: int = None):
    """Получение полного отчета за период с разбивкой на интервалы"""
    if shop_id is not None:
        # Используем кэшированную версию
        return fetch_report_detail_by_period_cached(api_token, start_date, end_date, shop_id)
    else:
        # Используем обычную версию без кэширования
        intervals = calculate_period_intervals(start_date, end_date)
        tasks = [fetch_report_async(api_token, start, end) for start, end in intervals]
        results = await asyncio.gather(*tasks)
        full_report = []
        for result in results:
            full_report.extend(result)
        return full_report


def fetch_report_detail_by_period(api_token: str, DATE_FROM: datetime, DATE_TO: datetime, limit: int = 100_000, delay: float = 1.0) -> list:
    BASE_URL = "https://statistics-api.wildberries.ru"
    HEADERS = {"Authorization": api_token}

    def wb_get(endpoint: str, params: dict):
        """Запрос к WB, возвращает JSON."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                logger.info(f"Запрос к {endpoint} с параметрами: {params}")
                r = requests.get(f"{BASE_URL}{endpoint}",
                            headers=HEADERS,
                            params=params,
                            timeout=40)
                r.raise_for_status()
                result = r.json()
                logger.info(f"Ответ от {endpoint}: {len(result) if isinstance(result, list) else 'не список'} записей")
                return result
            except requests.exceptions.HTTPError as e:
                logger.error(f"HTTP ошибка {e.response.status_code} для {endpoint}: {e}")
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    logger.info(f"Превышен лимит запросов, ожидание 60 секунд... (попытка {attempt + 1}/{max_retries})")
                    time.sleep(60)
                    continue
                else:
                    raise
            except Exception as e:
                logger.error(f"Общая ошибка для {endpoint}: {e}")
                if attempt < max_retries - 1:
                    logger.info(f"Ошибка запроса, повтор через 5 секунд... (попытка {attempt + 1}/{max_retries})")
                    time.sleep(5)
                    continue
                else:
                    raise

    # Проверяем тип входных данных и конвертируем в datetime если нужно
    if isinstance(DATE_FROM, str):
        start_date = datetime.strptime(DATE_FROM, "%Y-%m-%d")
    else:
        start_date = DATE_FROM
    
    if isinstance(DATE_TO, str):
        end_date = datetime.strptime(DATE_TO, "%Y-%m-%d")
    else:
        end_date = DATE_TO
    
    # Вычисляем длину периода
    period_length = (end_date - start_date).days
    
    # Расширяем период только в прошлое на длину исходного периода
    extended_start = start_date - timedelta(days=period_length)
    extended_end = end_date
    
    extended_date_from = extended_start.strftime("%Y-%m-%d")
    extended_date_to = extended_end.strftime("%Y-%m-%d")
    
    logger.info(f"Исходный период: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
    logger.info(f"Расширенный период: {extended_date_from} - {extended_date_to}")

    # Загружаем данные за расширенный период
    logger.info("Загружаем Orders...")
    orders = wb_get(
        "/api/v1/supplier/orders",
        {
            "dateFrom": f"{extended_date_from}T00:00:00",
            "limit": 100_000,
            "flag": 0
        }
    )
    
    if not orders:
        logger.warning("Orders API вернул пустой ответ")
        orders = []

    logger.info("Загружаем Sales...")
    sales = wb_get(
        "/api/v1/supplier/sales",
        {
            "dateFrom": f"{extended_date_from}T00:00:00",
            "limit": 100_000,
            "flag": 0
        }
    )
    
    if not sales:
        logger.warning("Sales API вернул пустой ответ")
        sales = []

    logger.info("Загружаем reportDetailByPeriod...")
    fin_rows, rrdid = [], 0
    while True:
        chunk = wb_get(
            "/api/v5/supplier/reportDetailByPeriod",
            {
                "dateFrom": extended_date_from,
                "dateTo": extended_date_to,
                "rrdid": rrdid,
                "limit": 100_000
            }
        )
        if not chunk:
            break
        fin_rows.extend(chunk)
        if chunk and len(chunk) > 0:
            rrdid = chunk[-1]["rrd_id"]
        time.sleep(1)

    if not fin_rows:
        logger.warning("Finance API вернул пустой ответ")
        fin_rows = []

    # Формируем результат
    all_data = {
        "orders": orders,
        "sales": sales, 
        "finance": fin_rows
    }

    logger.info(f"Загружено данных:")
    logger.info(f"  - Orders: {len(orders)}")
    logger.info(f"  - Sales: {len(sales)}")
    logger.info(f"  - Finance: {len(fin_rows)}")

    return all_data


def fetch_report_detail_by_period_cached(api_token: str, DATE_FROM: datetime, DATE_TO: datetime, shop_id: int, limit: int = 100_000, delay: float = 1.0) -> dict:
    """
    Версия функции с кэшированием данных в базе данных.
    Кэш создается отдельно для каждого пользователя (shop_id) и типа данных.
    """
    if shop_id is None:
        logger.error("shop_id обязателен для кэширования")
        return fetch_report_detail_by_period(api_token, DATE_FROM, DATE_TO, limit, delay)
    
    # Проверяем тип входных данных и конвертируем в datetime если нужно
    if isinstance(DATE_FROM, str):
        start_date = datetime.strptime(DATE_FROM, "%Y-%m-%d")
    else:
        start_date = DATE_FROM
    
    if isinstance(DATE_TO, str):
        end_date = datetime.strptime(DATE_TO, "%Y-%m-%d")
    else:
        end_date = DATE_TO
    
    # Вычисляем период для кэширования (2 года назад)
    current_time = datetime.now()
    cache_start_date = current_time - timedelta(days=CACHE_PERIOD_DAYS)
    cache_end_date = current_time
    
    logger.info(f"Проверяем кэш для периода: {cache_start_date.strftime('%Y-%m-%d')} - {cache_end_date.strftime('%Y-%m-%d')}")
    
    # Проверяем кэш для каждого типа данных
    cached_orders = get_cached_data(shop_id, api_token, "orders", cache_start_date, cache_end_date)
    cached_sales = get_cached_data(shop_id, api_token, "sales", cache_start_date, cache_end_date)
    cached_finance = get_cached_data(shop_id, api_token, "finance", cache_start_date, cache_end_date)
    
    # Если кэш неполный или устарел, загружаем данные заново
    if not cached_orders or not cached_sales or not cached_finance:
        logger.info("Кэш неполный или устарел. Загружаем данные заново...")
        
        # Загружаем данные за 2 года
        fresh_data = fetch_report_detail_by_period(api_token, cache_start_date, cache_end_date)
        
        # Сохраняем в кэш
        save_cached_data(shop_id, api_token, "orders", fresh_data["orders"], cache_start_date, cache_end_date)
        save_cached_data(shop_id, api_token, "sales", fresh_data["sales"], cache_start_date, cache_end_date)
        save_cached_data(shop_id, api_token, "finance", fresh_data["finance"], cache_start_date, cache_end_date)
        
        cached_orders = fresh_data["orders"]
        cached_sales = fresh_data["sales"]
        cached_finance = fresh_data["finance"]
        
        logger.info("Данные загружены и сохранены в кэш")
    else:
        logger.info("Используем кэшированные данные")
    
    # Фильтруем данные по запрошенному периоду
    logger.info(f"Фильтруем данные по периоду: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
    
    def filter_by_date(data_list, date_field="date"):
        """Фильтрует данные по дате"""
        filtered = []
        for item in data_list:
            if not isinstance(item, dict) or date_field not in item:
                continue
            
            try:
                # Парсим дату, учитывая возможное время в ISO формате
                item_date_str = item[date_field]
                if 'T' in item_date_str:
                    item_date = datetime.fromisoformat(item_date_str.replace('Z', '+00:00'))
                else:
                    item_date = datetime.strptime(item_date_str, "%Y-%m-%d")
                
                if start_date <= item_date <= end_date:
                    filtered.append(item)
            except (ValueError, TypeError) as e:
                logger.warning(f"Ошибка парсинга даты '{item_date_str}': {e}")
                continue
        
        return filtered
    
    # Фильтруем orders и sales по дате
    filtered_orders = filter_by_date(cached_orders, "date")
    filtered_sales = filter_by_date(cached_sales, "date")
    
    # Фильтруем finance по дате (проверяем разные поля с датой)
    filtered_finance = []
    for finance in cached_finance:
        if not isinstance(finance, dict):
            continue
        
        # Ищем поле с датой
        date_key = None
        for key in ["date", "dateFrom", "dateTo", "createdAt", "updatedAt", "rr_dt"]:
            if key in finance:
                date_key = key
                break
        
        if date_key is None:
            continue
        
        try:
            item_date_str = finance[date_key]
            if 'T' in item_date_str:
                item_date = datetime.fromisoformat(item_date_str.replace('Z', '+00:00'))
            else:
                item_date = datetime.strptime(item_date_str, "%Y-%m-%d")
            
            if start_date <= item_date <= end_date:
                filtered_finance.append(finance)
        except (ValueError, TypeError) as e:
            logger.warning(f"Ошибка парсинга даты finance '{item_date_str}': {e}")
            continue
    
    # Формируем результат
    filtered_data = {
        "orders": filtered_orders,
        "sales": filtered_sales,
        "finance": filtered_finance
    }
    
    logger.info(f"Отфильтрованные данные:")
    logger.info(f"  - Orders: {len(filtered_orders)}")
    logger.info(f"  - Sales: {len(filtered_sales)}")
    logger.info(f"  - Finance: {len(filtered_finance)}")
    
    return filtered_data


def clear_cache_for_shop(shop_id: int):
    """Очищает кэш для конкретного магазина"""
    session = sessionmaker()(bind=engine)
    try:
        deleted_count = session.query(WBCacheData).filter(
            WBCacheData.shop_id == shop_id
        ).delete()
        session.commit()
        logger.info(f"Очищен кэш для магазина {shop_id}: удалено {deleted_count} записей")
    except Exception as e:
        logger.error(f"Ошибка очистки кэша для магазина {shop_id}: {e}")
        session.rollback()
    finally:
        session.close()


def clear_all_cache():
    """Очищает весь кэш"""
    session = sessionmaker()(bind=engine)
    try:
        deleted_count = session.query(WBCacheData).delete()
        session.commit()
        logger.info(f"Очищен весь кэш: удалено {deleted_count} записей")
    except Exception as e:
        logger.error(f"Ошибка очистки всего кэша: {e}")
        session.rollback()
    finally:
        session.close()