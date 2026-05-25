from __future__ import annotations

import os
from unittest.mock import MagicMock, Mock

import pytest
from peewee import SqliteDatabase
from telebot.types import User as TgUser

os.environ["BOT_TOKEN"] = "test"
os.environ["DATABASE_PATH"] = "bot.db"
os.environ["DEFAULT_TIMEZONE"] = "Europe/Moscow"
os.environ["LOG_FILE_PATH"] = "logs/bot.log"

from bot.db.database import db_proxy
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
from bot.services.free_time import FreeTimeService
from bot.services.scheduler import ReminderScheduler
from bot.services.tasks import TaskService
from apscheduler.schedulers.background import BackgroundScheduler

database = SqliteDatabase(":memory:")


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    db_proxy.initialize(database)
    database.create_tables(
        [
            User,
            Category,
            Task,
            Reminder,
            Recurrence,
            TaskWizardState,
            Group,
            GroupMember,
            GroupTask,
            GroupTaskAssignment,
        ]
    )
    yield
    database.drop_tables(
        [
            User,
            Category,
            Task,
            Reminder,
            Recurrence,
            TaskWizardState,
            Group,
            GroupMember,
            GroupTask,
            GroupTaskAssignment,
        ]
    )
    database.close()


@pytest.fixture(autouse=True)
def db_transaction():
    with database.atomic() as txn:
        yield
        txn.rollback()


@pytest.fixture
def tg_user() -> TgUser:
    return TgUser(
        id=12345, is_bot=False, first_name="Test", last_name=None, username="testuser"
    )


@pytest.fixture
def user(tg_user: TgUser) -> User:
    from bot.services.users import ensure_user

    return ensure_user(tg_user)


@pytest.fixture
def another_user() -> User:
    return User.create(telegram_id=99999, timezone="Europe/Moscow")


@pytest.fixture
def mock_bot():
    return MagicMock()


@pytest.fixture
def mock_apscheduler():
    sched = MagicMock(spec=BackgroundScheduler)
    sched.get_jobs.return_value = []
    return sched


@pytest.fixture
def reminder_scheduler(mock_bot, mock_apscheduler):
    return ReminderScheduler(bot=mock_bot, scheduler=mock_apscheduler)


@pytest.fixture
def free_time_service():
    return FreeTimeService()


@pytest.fixture
def task_service(reminder_scheduler, free_time_service):
    return TaskService(scheduler=reminder_scheduler, free_time=free_time_service)


@pytest.fixture
def mock_message(tg_user):
    msg = MagicMock()
    msg.from_user = tg_user
    msg.text = ""
    return msg
