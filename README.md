# golden-fish-planner
Простой адаптивный планер с фронтендом в виде Телеграм-бота, выполненный в рамках курса по ЯП Python.

## Список участников

- Ая Леко
- Мария Юр
- Варвара Лозовых
- Дарья Поварницына


## Описание проекта

Проект представляет собой телеграм-бота для планирования задач и напоминания о них. Бот позволяет пользователю ставить задачи, просматривать их, удалять задачи, также есть функционал группировки задач по категориям. Реализованы группы пользователей, в них есть администратор, который проставляет задачи и назначает их участникам.

Существует специальный вид задачи --- дедлайн. Он отличается тем, что пользователю достаточно ввести время, требуемое чтобы выполнить задачу, и бот самостоятельно раздробит потенциально большую работу в множество мелких сессий, о которых заботливо напомнит.

## Структура репозитория

```
├── bot
│   ├── config.py
│   ├── db
│   │   ├── database.py
│   │   ├── __init__.py
│   │   └── models.py
│   ├── handlers
│   │   ├── group.py
│   │   ├── __init__.py
│   │   ├── start.py
│   │   ├── sticker.py
│   │   └── task.py
│   ├── __init__.py
│   ├── logging_config.py
│   ├── main.py
│   ├── services
│   │   ├── free_time.py
│   │   ├── groups.py
│   │   ├── __init__.py
│   │   ├── scheduler.py
│   │   ├── tasks.py
│   │   └── users.py
│   └── utils
│       ├── __init__.py
│       ├── time_parse.py
│       └── timezone.py
├── LICENSE
├── README.md
└── requirements.txt
```

В корне проекта на сервере лежит файл с БД и файл `.env`. В папке `bot` лежит всё связанное с реализацией бота. В папке `handlers` лежат все обработчики сообщений, в папке `services` --- бизнес-логика, в папке `db` --- всё, что связано с БД, в папке `utils` --- вспомогательные функции. Если нужна новая схема, базу можно удалить и создать заново; отдельные миграции не используются.

## Развёртывание проекта

### На Unix-like
```
cp .env.example .env # заполните токен бота в файле .env
source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

### На Windows
Скопируйте файл `.env.example` в `.env` и заполните токен бота в файле `.env`. Затем выполните следующие команды:
```
venv\Scripts\activate
pip install -r requirements.txt
python -m bot.main
```


## Откуда скопировали код
Код проекта опирается на примеры и документацию следующих источников:

- [PyTelegramBotAPI](https://github.com/eternnoir/pyTelegramBotAPI) — обработчики команд, `TeleBot`, inline-кнопки и callback-хендлеры.
- [Peewee](https://docs.peewee-orm.com/) — модели, связи и запросы к БД.
- [APScheduler](https://apscheduler.readthedocs.io/) — фоновые задачи и напоминания по времени.
- [python-dotenv](https://github.com/theskumar/python-dotenv) — загрузка конфигурации из `.env`.
- [telegram_bot_calendar](https://github.com/Youtlaw/telegram_bot_calendar) — inline-календарь для выбора даты.
- [Stack Overflow](https://stackoverflow.com/questions) — отдельные решения по Telegram inline-клавиатурам, callback query и напоминаниям.
