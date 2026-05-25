from __future__ import annotations

from peewee import (
    BooleanField,
    DateTimeField,
    ForeignKeyField,
    IntegerField,
    Model,
    TextField,
)

from bot.db.database import get_db


class BaseModel(Model):
    class Meta:
        database = get_db()


class User(BaseModel):
    telegram_id = IntegerField(unique=True)
    username = TextField(null=True)
    timezone = TextField()
    day_start_hour = IntegerField(default=8)
    day_end_hour = IntegerField(default=23)


class Category(BaseModel):
    user = ForeignKeyField(User, backref="categories")
    name = TextField()


class Task(BaseModel):
    user = ForeignKeyField(User, backref="tasks")
    category = ForeignKeyField(Category, backref="tasks", null=True)
    task_type = TextField()  # one_time | recurring | deadline
    name = TextField(default="")
    start_dt = DateTimeField()
    end_dt = DateTimeField(null=True)
    is_group = BooleanField(default=False)
    expected_work_hours = IntegerField(null=True)
    is_muted = BooleanField(default=False)
    mute_reminders = BooleanField(default=False)


class Reminder(BaseModel):
    task = ForeignKeyField(Task, backref="reminders")
    offset_minutes = IntegerField()


class Recurrence(BaseModel):
    task = ForeignKeyField(Task, backref="recurrence", unique=True)
    rule = TextField()  # daily | weekly | monthly | every_n_days
    interval = IntegerField(null=True)


class TaskWizardState(BaseModel):
    user = ForeignKeyField(User, backref="wizard_state", unique=True)
    step = TextField()
    payload = TextField()  # JSON string


class Group(BaseModel):
    name = TextField()
    join_code = TextField(unique=True)


class GroupMember(BaseModel):
    group = ForeignKeyField(Group, backref="members")
    user = ForeignKeyField(User, backref="groups")
    is_admin = BooleanField(default=False)
    mute_notifications = BooleanField(default=False)


class GroupTask(BaseModel):
    group = ForeignKeyField(Group, backref="tasks")
    task = ForeignKeyField(Task, backref="group_task")


class GroupTaskAssignment(BaseModel):
    group_task = ForeignKeyField(GroupTask, backref="assignments")
    user = ForeignKeyField(User, backref="group_task_assignments")

    class Meta:
        indexes = ((("group_task", "user"), True),)
