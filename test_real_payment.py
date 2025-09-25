#!/usr/bin/env python3
"""
Тест реального платежа Tinkoff
"""

import asyncio
import aiohttp
import hashlib
import random
import json

# Реальные данные Tinkoff
TERMINAL_KEY = "1749885008651"
PASSWORD = "YBla2Zf$iQYwWuSU"

def generate_token(data, password):
    """Генерация токена для Tinkoff API"""
    token_data = data.copy()
    token_data["Password"] = password
    
    # Сортируем параметры по алфавиту
    sorted_params = sorted(token_data.items(), key=lambda x: x[0])
    
    # Объединяем значения в строку
    concatenated = ''.join(str(value) for key, value in sorted_params)
    
    # Создаем SHA256 хеш
    token = hashlib.sha256(concatenated.encode('utf-8')).hexdigest()
    
    print(f"Строка для хеширования: {concatenated}")
    print(f"Сгенерированный токен: {token}")
    
    return token

async def test_real_payment():
    """Тест реального платежа"""
    print("=== Тест реального платежа Tinkoff ===\n")
    
    # Минимальная сумма для теста (1 рубль)
    amount = 100  # 1 рубль в копейках
    order_id = f"real_test_{random.randint(100000, 999999)}"
    description = "Тестовый платеж 1 рубль"
    
    # Данные для токена
    token_data = {
        "TerminalKey": TERMINAL_KEY,
        "Amount": amount,
        "OrderId": order_id,
        "Description": description
    }
    
    print(f"Terminal Key: {TERMINAL_KEY}")
    print(f"Password: {PASSWORD}")
    print(f"Order ID: {order_id}")
    print(f"Amount: {amount} копеек ({amount/100} рублей)")
    print(f"Description: {description}")
    
    # Генерируем токен
    token = generate_token(token_data, PASSWORD)
    
    # Данные для отправки
    request_data = {
        "TerminalKey": TERMINAL_KEY,
        "Amount": amount,
        "OrderId": order_id,
        "Description": description,
        "Token": token
    }
    
    print(f"\nОтправляем запрос...")
    
    # Отправляем запрос в Tinkoff
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            "https://securepay.tinkoff.ru/v2/Init",
            json=request_data,
            headers={"Content-Type": "application/json"}
        )
        
        print(f"Статус ответа: {response.status}")
        
        data = await response.json()
        print(f"\nОтвет от Tinkoff:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        if data.get('Success', False):
            print("\n✅ Платеж успешно создан!")
            print(f"🔗 Ссылка для оплаты: {data.get('PaymentURL')}")
            print(f"📋 PaymentId: {data.get('PaymentId')}")
            
            # Сохраняем PaymentId для проверки статуса
            payment_id = data.get('PaymentId')
            
            # Проверяем статус платежа
            print(f"\n=== Проверяем статус платежа ===")
            await check_payment_status(payment_id)
            
            return payment_id
        else:
            print(f"\n❌ Ошибка: {data.get('Message', 'Неизвестная ошибка')}")
            print(f"Детали: {data.get('Details', 'Нет деталей')}")
            return None

async def check_payment_status(payment_id):
    """Проверяет статус платежа"""
    if not payment_id:
        return
    
    # Данные для токена статуса
    token_data = {
        "TerminalKey": TERMINAL_KEY,
        "PaymentId": payment_id
    }
    token = generate_token(token_data, PASSWORD)
    
    async with aiohttp.ClientSession() as session:
        response = await session.post(
            "https://securepay.tinkoff.ru/v2/GetState",
            json={
                "TerminalKey": TERMINAL_KEY,
                "PaymentId": payment_id,
                "Token": token
            },
            headers={"Content-Type": "application/json"}
        )
        
        data = await response.json()
        print(f"\nСтатус платежа:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        if data.get('Success', False):
            status = data.get('Status', 'Неизвестно')
            print(f"✅ Статус платежа: {status}")
        else:
            print(f"❌ Ошибка проверки статуса: {data.get('Message', 'Неизвестная ошибка')}")

if __name__ == "__main__":
    asyncio.run(test_real_payment()) 