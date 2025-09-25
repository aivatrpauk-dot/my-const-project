#!/usr/bin/env python3
"""
Тестовый скрипт для проверки конфигурации Tinkoff API
"""

import os
import hashlib

def test_tinkoff_config():
    """Проверяет конфигурацию Tinkoff API"""
    
    print("=== Проверка конфигурации Tinkoff API ===\n")
    
    # Проверяем переменные окружения
    terminal_key = os.getenv("TINKOFF_TERMINAL_KEY")
    password = os.getenv("TINKOFF_PASSWORD")
    
    print(f"TINKOFF_TERMINAL_KEY: {'✅ Настроен' if terminal_key else '❌ Не настроен'}")
    print(f"TINKOFF_PASSWORD: {'✅ Настроен' if password else '❌ Не настроен'}")
    
    if not terminal_key or not password:
        print("\n❌ Конфигурация неполная!")
        print("Для настройки создайте файл .env со следующими переменными:")
        print("TINKOFF_TERMINAL_KEY=ваш_терминал_ключ")
        print("TINKOFF_PASSWORD=ваш_пароль")
        return False
    
    # Тестируем генерацию токена
    print("\n=== Тест генерации токена ===")
    
    test_data = {
        "TerminalKey": terminal_key,
        "Amount": 10000,  # 100 рублей в копейках
        "OrderId": "test_order_123",
        "Description": "Тестовый платеж"
    }
    
    # Генерируем токен
    token_data = test_data.copy()
    token_data["Password"] = password
    
    sorted_params = sorted(token_data.items(), key=lambda x: x[0])
    concatenated = ''.join(str(value) for key, value in sorted_params)
    token = hashlib.sha256(concatenated.encode('utf-8')).hexdigest()
    
    print(f"Тестовые данные: {test_data}")
    print(f"Строка для хеширования: {concatenated}")
    print(f"Сгенерированный токен: {token}")
    
    print("\n✅ Конфигурация корректна!")
    return True

if __name__ == "__main__":
    test_tinkoff_config() 