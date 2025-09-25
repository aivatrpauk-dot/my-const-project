#!/usr/bin/env python3
"""
Скрипт для создания таблицы кэширования WB API данных
"""

from tg_bot.models import engine, WBCacheData, Base

def create_wb_cache_table():
    """Создает таблицу для кэширования WB API данных"""
    try:
        # Создаем таблицу
        WBCacheData.__table__.create(bind=engine, checkfirst=True)
        print("✅ Таблица wb_cache_data успешно создана")
        
        # Проверяем, что таблица создана
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        
        if 'wb_cache_data' in tables:
            print("✅ Таблица wb_cache_data найдена в базе данных")
            
            # Показываем структуру таблицы
            columns = inspector.get_columns('wb_cache_data')
            print("📋 Структура таблицы wb_cache_data:")
            for column in columns:
                print(f"  - {column['name']}: {column['type']}")
        else:
            print("❌ Таблица wb_cache_data не найдена в базе данных")
            
    except Exception as e:
        print(f"❌ Ошибка создания таблицы: {e}")

if __name__ == "__main__":
    create_wb_cache_table()
