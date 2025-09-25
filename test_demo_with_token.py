#!/usr/bin/env python3
"""
Тест с демо-ключом Tinkoff с токеном
"""

import requests
import random
import json
import hashlib

# Демо данные Tinkoff
TERMINAL_KEY = "1749885008622DEMO"
PASSWORD = "#pV72D&&Gph7Ydqx"  # Демо пароль

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

def generate_payment_link(amount, order_id, description):
    """Генерирует ссылку для оплаты"""
    url = "https://securepay.tinkoff.ru/v2/Init"
    
    # Данные для токена
    token_data = {
        "TerminalKey": TERMINAL_KEY,
        "Amount": amount * 100,  # в копейках
        "OrderId": order_id,
        "Description": description
    }
    
    # Генерируем токен
    token = generate_token(token_data, PASSWORD)
    
    payload = {
        "TerminalKey": TERMINAL_KEY,
        "Amount": amount * 100,  # в копейках
        "OrderId": order_id,
        "Description": description,
        "Token": token,
        "SuccessURL": "https://t.me/your_bot",  # или ваш сайт
        "FailURL": "https://t.me/your_bot",
        # "NotificationURL": "https://ваш-сервер.ру/webhook",  # для уведомлений
    }
    
    print(f"Отправляем запрос:")
    print(f"URL: {url}")
    print(f"Payload: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload)
    
    print(f"\nСтатус ответа: {response.status_code}")
    print(f"Ответ: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    
    if response.status_code == 200:
        data = response.json()
        if data.get("Success", False):
            payment_url = data.get("PaymentURL")
            print(f"\n✅ Платеж создан!")
            print(f"🔗 Ссылка для оплаты: {payment_url}")
            return payment_url
        else:
            print(f"\n❌ Ошибка: {data.get('Message', 'Неизвестная ошибка')}")
            print(f"Детали: {data.get('Details', 'Нет деталей')}")
            return None
    else:
        print(f"\n❌ HTTP ошибка: {response.status_code}")
        return None

def test_demo_payment():
    """Тест демо-платежа"""
    print("=== Тест демо-платежа Tinkoff с токеном ===\n")
    
    # Тестовые данные
    amount = 1  # 1 рубль
    order_id = f"demo_test_{random.randint(100000, 999999)}"
    description = "Тестовый демо-платеж 1 рубль"
    
    print(f"Terminal Key: {TERMINAL_KEY}")
    print(f"Password: {PASSWORD}")
    print(f"Amount: {amount} рубль")
    print(f"Order ID: {order_id}")
    print(f"Description: {description}")
    
    # Генерируем ссылку для оплаты
    payment_url = generate_payment_link(amount, order_id, description)
    
    if payment_url:
        print(f"\n🎉 Демо-платеж создан успешно!")
        print(f"🔗 Перейдите по ссылке для оплаты: {payment_url}")
        print(f"\n💡 Это демо-режим, реальные деньги не спишутся!")
    else:
        print(f"\n❌ Не удалось создать демо-платеж")

if __name__ == "__main__":
    test_demo_payment() 