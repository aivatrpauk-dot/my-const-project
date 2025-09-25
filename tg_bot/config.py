from dataclasses import dataclass
import os
from dotenv import load_dotenv

@dataclass
class TgBot:
    token: str

@dataclass
class TinkoffConfig:
    terminal_key: str
    password: str

@dataclass
class TelegramPayConfig:
    provider_token: str
    currency: str = "RUB"

@dataclass
class Config:
    tg_bot: TgBot
    tinkoff: TinkoffConfig
    telegram_pay: TelegramPayConfig

def load_config(path: str = None):
    # Загружаем переменные окружения из .env файла (если есть)
    if path:
        load_dotenv(path)
    else:
        load_dotenv()

    return Config(
        tg_bot=TgBot(
            token=os.getenv("BOT_TOKEN"),
        ),
        tinkoff=TinkoffConfig(
            terminal_key=os.getenv("TINKOFF_TERMINAL_KEY") or "1749885008651",
            password=os.getenv("TINKOFF_PASSWORD") or "YBla2Zf$iQYwWuSU",
        ),
        telegram_pay=TelegramPayConfig(
            provider_token=os.getenv("TELEGRAM_PAYMENT_PROVIDER_TOKEN") or "",
            currency=os.getenv("TELEGRAM_PAYMENT_CURRENCY", "RUB")
        )
    )
