# Аналитика страницы регистрации / Network

Streamlit-приложение для анализа эффективности страницы регистрации Битрикс24 через Yandex Metrika Reports API (`/stat/v1/data`).

Приложение анализирует только страницу:

```text
https://auth2.bitrix24.net/create/
```

Все запросы к API автоматически фильтруются по визитам, где URL содержит `auth2.bitrix24.net/create`, поэтому URL с query-параметрами не теряются.

## Что входит в MVP

- KPI по визитам, пользователям, отказам, глубине просмотра и длительности визита.
- Если задан Goal ID успешной регистрации — показываются регистрации и CR.
- Динамика по дням.
- Разрезы по устройствам, браузерам и ОС.
- Разрезы по источникам и UTM с расчетом потенциальных потерь.
- Мини-воронка по необязательным промежуточным целям.
- Автоматический список проблемных сегментов.

Logs API и ClickHouse в MVP не используются. Данные загружаются напрямую из Reports API при запуске или обновлении. Для кэширования используется `st.cache_data`.

## Установка и запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Настройка доступа

Создайте файл `.streamlit/secrets.toml` на основе примера:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Заполните обязательные значения:

```toml
YANDEX_METRIKA_TOKEN = "your_token_here"
YANDEX_METRIKA_COUNTER_ID = "your_counter_id_here"
YANDEX_METRIKA_REG_GOAL_ID = "your_registration_goal_id_here"
```

Также можно использовать переменные окружения с теми же именами:

```bash
export YANDEX_METRIKA_TOKEN="your_token_here"
export YANDEX_METRIKA_COUNTER_ID="your_counter_id_here"
export YANDEX_METRIKA_REG_GOAL_ID="your_registration_goal_id_here"
```

Counter ID и Goal ID успешной регистрации можно переопределить в сайдбаре приложения.

## Необязательные промежуточные цели

Для вкладки с воронкой можно заполнить дополнительные цели:

```toml
YANDEX_METRIKA_START_GOAL_ID = ""
YANDEX_METRIKA_FORM_GOAL_ID = ""
YANDEX_METRIKA_ERROR_GOAL_ID = ""
YANDEX_METRIKA_NEXT_STEP_GOAL_ID = ""
```

Если промежуточные цели не заданы, приложение покажет сообщение, что считает только визиты и успешные регистрации.

## Безопасность

- Токен не хранится в коде и не выводится в интерфейс.
- `.streamlit/secrets.toml` должен оставаться локальным файлом и не попадать в git.
- В репозитории хранится только `.streamlit/secrets.toml.example`.
