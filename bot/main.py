from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from telebot import ExceptionHandler, TeleBot, types

from bot.config import load_config
from bot.db.database import init_db
from bot.db.models import (
    Category,
    Group,
    GroupMember,
    GroupTask,
    GroupTaskAssignment,
    Recurrence,
    Reminder,
    Task,
    TaskWizardState,
    User,
)
from bot.handlers.group import register_group_handlers
from bot.handlers.start import register_start_handlers
from bot.handlers.sticker import register_sticker_handlers
from bot.handlers.task import register_task_handlers
from bot.logging_config import setup_logging
from bot.services.free_time import FreeTimeService
from bot.services.groups import GroupService
from bot.services.scheduler import ReminderScheduler
from bot.services.tasks import TaskService

log = logging.getLogger(__name__)


class BotExceptionHandler(ExceptionHandler):
    def handle(self, exception: Exception) -> bool:
        log.exception("Unhandled exception in handler: %s", exception)
        return True


def init_models() -> None:
    tables = [
        User,
        Category,
        Task,
        Reminder,
        Recurrence,
        Group,
        GroupMember,
        GroupTask,
        GroupTaskAssignment,
        TaskWizardState,
    ]
    for table in tables:
        table.create_table(safe=True)


def main() -> None:
    config = load_config()
    setup_logging(config.log_file_path)
    init_db(config.database_path)
    init_models()

    bot = TeleBot(config.bot_token, exception_handler=BotExceptionHandler())
    bot.set_my_commands(
        [
            types.BotCommand("start", "Помощь и список команд"),
            types.BotCommand("add", "Новая задача"),
            types.BotCommand("cancel", "Отменить создание задачи"),
            types.BotCommand("list", "Задачи на день / по категориям"),
            types.BotCommand("free", "Свободное время на дату"),
            types.BotCommand("delete", "Удалить задачу"),
            types.BotCommand("unmute", "Вернуть заглушенную повторяющуюся"),
            types.BotCommand("timezone", "Установить таймзону"),
            types.BotCommand("active_start", "Начало активных часов"),
            types.BotCommand("active_end", "Конец активных часов"),
            types.BotCommand("group_create", "Создать группу"),
            types.BotCommand("group_join", "Присоединиться к группе"),
            types.BotCommand("group_add_task", "Добавить задачу в группу"),
            types.BotCommand("group_free", "Свободное время группы"),
            types.BotCommand("group_leave", "Покинуть группу"),
            types.BotCommand("group_fetch", "Задачи группы"),
            types.BotCommand("group_promote", "Повысить участника"),
            types.BotCommand("group_mute", "Выключить уведомления"),
            types.BotCommand("group_unmute", "Включить уведомления"),
        ]
    )
    bot.set_chat_menu_button(menu_button=types.MenuButtonCommands(type="commands"))
    scheduler = ReminderScheduler(bot=bot, scheduler=BackgroundScheduler())
    scheduler.start()

    free_time_service = FreeTimeService()
    task_service = TaskService(scheduler=scheduler, free_time=free_time_service)
    group_service = GroupService(free_time=free_time_service, task_service=task_service)

    register_start_handlers(bot)
    register_sticker_handlers(bot)
    register_task_handlers(bot, task_service)
    register_group_handlers(bot, group_service)

    bot.infinity_polling()


if __name__ == "__main__":
    main()
