from __future__ import annotations

from telebot import TeleBot
from telebot.types import Message

from bot.services.users import (
    ensure_user,
    set_active_end,
    set_active_start,
    set_user_timezone,
)

TIMEZONE_EXAMPLES = [
    ("UTC−11", "Паго-Паго", "Pacific/Pago_Pago"),
    ("UTC−10", "Гонолулу", "Pacific/Honolulu"),
    ("UTC−9", "Анкоридж", "America/Anchorage"),
    ("UTC−8", "Лос-Анджелес", "America/Los_Angeles"),
    ("UTC−7", "Денвер", "America/Denver"),
    ("UTC−6", "Чикаго", "America/Chicago"),
    ("UTC−5", "Нью-Йорк", "America/New_York"),
    ("UTC−4", "Сантьяго", "America/Santiago"),
    ("UTC−3", "Бразилиа", "America/Sao_Paulo"),
    ("UTC−2", "Южная Георгия", "Atlantic/South_Georgia"),
    ("UTC−1", "Азорские о-ва", "Atlantic/Azores"),
    ("UTC+0", "Лондон", "Europe/London"),
    ("UTC+1", "Париж", "Europe/Paris"),
    ("UTC+2", "Киев", "Europe/Kyiv"),
    ("UTC+3", "Москва", "Europe/Moscow"),
    ("UTC+4", "Дубай", "Asia/Dubai"),
    ("UTC+5", "Карачи", "Asia/Karachi"),
    ("UTC+6", "Дакка", "Asia/Dhaka"),
    ("UTC+7", "Бангкок", "Asia/Bangkok"),
    ("UTC+8", "Сингапур", "Asia/Singapore"),
    ("UTC+9", "Токио", "Asia/Tokyo"),
    ("UTC+10", "Сидней", "Australia/Sydney"),
    ("UTC+11", "Нумеа", "Pacific/Noumea"),
    ("UTC+12", "Окленд", "Pacific/Auckland"),
    ("UTC+13", "Апиа", "Pacific/Apia"),
    ("UTC+14", "Киритимати", "Pacific/Kiritimati"),
]


def _timezone_help_text() -> str:
    lines = ["🌍 <b>Часовые пояса</b>\n" "Выберите ближайший и отправьте:\n"]
    for offset, city, tz in TIMEZONE_EXAMPLES:
        if not tz:
            lines.append(f"\n{offset}: {city}")
        else:
            lines.append(f"\n{offset}: {city}\n  <code>/timezone {tz}</code>")
    return "\n".join(lines)


def register_start_handlers(bot: TeleBot) -> None:
    @bot.message_handler(commands=["start", "help"])
    def handle_start(message: Message) -> None:
        ensure_user(message.from_user)
        bot.reply_to(
            message,
            "Привет! Я помогу держать дела под контролем. Вот быстрые команды:\n"
            "➕ /add — новая задача\n"
            "📅 /list day — задачи на день\n"
            "🏷️ /list category — задачи по категориям\n"
            "⏳ /free — свободное время на дату\n"
            "🧹 /delete 1 или /delete 2,3 или /delete 1-5 — удалить\n"
            "🔕 /unmute 1 — вернуть заглушенную повторяющуюся\n"
            "👥 /group_create, /group_join, /group_add_task, /group_free, /group_fetch, /group_leave, "
            "/group_promote, /group_mute, /group_unmute — группы\n"
            "🌍 /timezone Europe/Moscow — таймзона\n"
            "🕘 /active_start 9 и /active_end 22 — часы активности",
        )

    @bot.message_handler(commands=["timezone"])
    def handle_timezone(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, _timezone_help_text(), parse_mode="HTML")
            return
        response = set_user_timezone(message.from_user.id, parts[1].strip())
        bot.reply_to(message, response)

    @bot.message_handler(commands=["active_start"])
    def handle_active_start(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "🕘 Укажите час начала. Пример: /active_start 9")
            return
        try:
            hour = int(parts[1].strip())
        except ValueError:
            bot.reply_to(message, "Неверный формат. Пример: /active_start 9")
            return
        response = set_active_start(message.from_user.id, hour)
        bot.reply_to(message, response)

    @bot.message_handler(commands=["active_end"])
    def handle_active_end(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "🕙 Укажите час конца. Пример: /active_end 22")
            return
        try:
            hour = int(parts[1].strip())
        except ValueError:
            bot.reply_to(message, "Неверный формат. Пример: /active_end 22")
            return
        response = set_active_end(message.from_user.id, hour)
        bot.reply_to(message, response)
