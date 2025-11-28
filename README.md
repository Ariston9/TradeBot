# TradeBot (Telegram + TradingView + PocketOption + WebAPI)

Модульная версия твоего Trade Assistant:
- Анализ M1/M5/M15 через TradingView (tvDatafeed)
- Сложная система индикаторов (EMA/RSI/MACD/SMC/уровни)
- Интеграция с PocketOption (реальные OTC котировки)
- Telegram-бот на aiogram 3.x
- Автосканер пар и логирование сигналов в CSV
- FastAPI WebAPI для WebApp / GitHub Pages

## Установка

```bash
pip install -r requirements.txt
```

Создай файл `.env` в корне (рядом с `requirements.txt`) по шаблону `.env.example`.

## Запуск Telegram-бота

```bash
python -m bot.bot_main
```

## Запуск API (для WebApp)

```bash
uvicorn api.server:app --host 0.0.0.0 --port 8000
```
