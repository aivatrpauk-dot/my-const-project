import requests
import logging
from datetime import datetime, timedelta
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=5)


async def fetch_report_async(api_token: str, date_from: datetime, date_to: datetime):
    """Асинхронная обертка для получения отчета"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor, 
        fetch_report_detail_by_period, 
        api_token, date_from, date_to
    )

def calculate_period_intervals(start_date: datetime, end_date: datetime):
    """Разбивает период на интервалы по 7 дней (ограничение WB API)"""
    intervals = []
    current = start_date
    while current < end_date:
        next_date = current + timedelta(days=28)
        if next_date > end_date:
            next_date = end_date
        intervals.append((current, next_date))
        current = next_date + timedelta(days=1)
    return intervals

async def fetch_full_report(api_token: str, start_date: datetime, end_date: datetime):
    """Получение полного отчета за период с разбивкой на интервалы"""
    intervals = calculate_period_intervals(start_date, end_date)
    tasks = [fetch_report_async(api_token, start, end) for start, end in intervals]
    results = await asyncio.gather(*tasks)
    full_report = []
    for result in results:
        full_report.extend(result)
    return full_report


def fetch_report_detail_by_period(api_token: str,  DATE_FROM: datetime, DATE_TO: datetime, limit: int = 100_000, delay: float = 1.0) -> list:
    BASE_URL = "https://statistics-api.wildberries.ru"
    HEADERS  = {"Authorization": api_token}

    def wb_get(endpoint: str, params: dict):
        """Запрос к WB, возвращает JSON."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                r = requests.get(f"{BASE_URL}{endpoint}",
                            headers=HEADERS,
                            params=params,
                            timeout=40)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and attempt < max_retries - 1:
                    print(f"Превышен лимит запросов, ожидание 60 секунд... (попытка {attempt + 1}/{max_retries})")
                    time.sleep(60)
                    continue
                else:
                    raise
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"Ошибка запроса, повтор через 5 секунд... (попытка {attempt + 1}/{max_retries})")
                    time.sleep(5)
                    continue
                else:
                    raise

    # ────────────────────────────────────────────────────────────────────
    # 3. ОПРЕДЕЛЕНИЕ ПЕРИОДА И ЗАГРУЗКА ДАННЫХ
    # ────────────────────────────────────────────────────────────────────
    def determine_period_type(date_from, date_to):
        """Определяет тип периода и возвращает расширенный период для загрузки."""
        # Проверяем тип входных данных и конвертируем в datetime если нужно
        if isinstance(date_from, str):
            start_date = datetime.strptime(date_from, "%Y-%m-%d")
        else:
            start_date = date_from
        
        if isinstance(date_to, str):
            end_date = datetime.strptime(date_to, "%Y-%m-%d")
        else:
            end_date = date_to
        
        days_diff = (end_date - start_date).days
        
        if days_diff == 0:
            # День - загружаем неделю
            period_start = start_date - timedelta(days=6)
            period_end = start_date + timedelta(days=6)
            period_type = "день"
        elif days_diff <= 7:
            # Неделя - загружаем месяц
            period_start = start_date - timedelta(days=30)
            period_end = end_date + timedelta(days=30)
            period_type = "неделя"
        elif days_diff <= 31:
            # Месяц - загружаем квартал
            period_start = start_date - timedelta(days=90)
            period_end = end_date + timedelta(days=90)
            period_type = "месяц"
        else:
            # Год - загружаем год
            period_start = start_date - timedelta(days=365)
            period_end = end_date + timedelta(days=365)
            period_type = "год"
        
        return period_start.strftime("%Y-%m-%d"), period_end.strftime("%Y-%m-%d"), period_type

    # Определяем расширенный период
    extended_date_from, extended_date_to, period_type = determine_period_type(DATE_FROM, DATE_TO)
    print(f"→ Определен период: {period_type}")
    print(f"→ Загружаем данные за расширенный период: {extended_date_from} - {extended_date_to}")

    # Загружаем данные за расширенный период
    print("→ Orders …")
    orders = wb_get(
        "/api/v1/supplier/orders",
        {
            "dateFrom": f"{extended_date_from}T00:00:00",
            "limit":    100_000,
            "flag":     0
        }
    )

    print("→ Sales …")
    sales = wb_get(
        "/api/v1/supplier/sales",
        {
            "dateFrom": f"{extended_date_from}T00:00:00",
            "limit":    100_000,
            "flag":     0
        }
    )

    print("→ reportDetailByPeriod …")
    fin_rows, rrdid = [], 0
    while True:
        chunk = wb_get(
            "/api/v5/supplier/reportDetailByPeriod",
            {
                "dateFrom": extended_date_from,
                "dateTo":   extended_date_to,
                "rrdid":    rrdid,
                "limit":    100_000
            }
        )
        if not chunk:
            break
        fin_rows.extend(chunk)
        rrdid = chunk[-1]["rrd_id"]
        time.sleep(1)

    # Использование:
    # После загрузки всех данных
    all_data = {
        "orders": orders,
        "sales": sales, 
        "finance": fin_rows
    }



    return all_data