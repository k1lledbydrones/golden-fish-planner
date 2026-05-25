from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import logging
import secrets

log = logging.getLogger(__name__)

from telebot.types import Message, User as TgUser

import json

from bot.db.models import (
    Group,
    GroupMember,
    GroupTask,
    GroupTaskAssignment,
    Task,
    TaskWizardState,
    User,
)
from bot.services.free_time import FreeTimeService
from bot.services.tasks import TaskService
from bot.services.users import ensure_user
from bot.utils.time_parse import DATE_TIME_FORMAT, parse_datetime


@dataclass
class GroupService:
    free_time: FreeTimeService
    task_service: TaskService
    _pending_group_date: dict[int, int] = field(default_factory=dict)

    def _generate_join_code(self) -> str:
        code = secrets.token_urlsafe(6)
        while Group.select().where(Group.join_code == code).exists():
            code = secrets.token_urlsafe(6)
        return code

    def _resolve_group(self, raw: str) -> Group | None:
        if raw.isdigit():
            return Group.get_or_none(Group.id == int(raw))
        return Group.get_or_none(Group.join_code == raw)

    def _get_member(self, group: Group, user: User) -> GroupMember | None:
        return GroupMember.get_or_none(
            (GroupMember.group == group) & (GroupMember.user == user)
        )

    def _resolve_group_by_id(self, group_id: int) -> Group | None:
        return Group.get_or_none(Group.id == group_id)

    def create_group(self, message: Message) -> str:
        user = ensure_user(message.from_user)
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            return "👥 Нужно имя группы. Пример: /group_create Название"
        name = parts[1].strip()
        join_code = self._generate_join_code()
        group = Group.create(name=name, join_code=join_code)
        GroupMember.create(group=group, user=user, is_admin=True)
        return f"✅ Группа создана. Код приглашения: {group.join_code}"

    def join_group(self, message: Message) -> str:
        user = ensure_user(message.from_user)
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            return "Нужен код приглашения. Пример: /group_join AbCd1234"
        code = parts[1].strip()
        if code.isdigit():
            return "⚠️ Используйте код приглашения, а не id"
        group = Group.get_or_none(Group.join_code == code)
        if group is None:
            return "⚠️ Группа не найдена"
        GroupMember.get_or_create(group=group, user=user, defaults={"is_admin": False})
        return (
            "🎉 Вы присоединились к группе. Добавьте задачи: /group_fetch "
            + group.join_code
        )

    def get_admin_groups(self, user: User) -> list[Group]:
        members = GroupMember.select().where(
            (GroupMember.user == user) & (GroupMember.is_admin == True)
        )
        return [m.group for m in members]

    def get_user_groups(self, user: User) -> list[Group]:
        members = GroupMember.select().where(GroupMember.user == user)
        return [m.group for m in members]

    def leave_group_by_id(self, tg_user: TgUser, group_id: int) -> str:
        group = Group.get_or_none(Group.id == group_id)
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(tg_user)
        member = self._get_member(group, user)
        if member is None:
            return "⚠️ Вы не состоите в этой группе"
        GroupMember.delete().where(GroupMember.id == member.id).execute()
        assignments = GroupTask.select(GroupTask.id).where(GroupTask.group == group)
        GroupTaskAssignment.delete().where(
            (GroupTaskAssignment.user == user)
            & (GroupTaskAssignment.group_task.in_(assignments))
        ).execute()
        return "✅ Вы вышли из группы"

    def fetch_group_tasks_by_id(self, tg_user: TgUser, group_id: int) -> str:
        group = Group.get_or_none(Group.id == group_id)
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(tg_user)
        if (
            not GroupMember.select()
            .where((GroupMember.group == group) & (GroupMember.user == user))
            .exists()
        ):
            return "⛔ Вы не состоите в этой группе"
        return self._run_fetch(user, group)

    def group_free_time_for_date(
        self, tg_user: TgUser, group_id: int, day: date
    ) -> str:
        group = Group.get_or_none(Group.id == group_id)
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(tg_user)
        if (
            not GroupMember.select()
            .where((GroupMember.group == group) & (GroupMember.user == user))
            .exists()
        ):
            return "⛔ Вы не состоите в этой группе"
        day_start = datetime.combine(day, datetime.min.time())
        members = GroupMember.select().where(GroupMember.group == group)
        intervals = [
            self.free_time.get_free_intervals(m.user.id, day_start) for m in members
        ]
        free = self.free_time.intersect_intervals(intervals)
        if not free:
            return "⛔ Свободного времени нет"
        lines = [
            f"🟢 {start.strftime('%H:%M')} - {end.strftime('%H:%M')}"
            for start, end in free
        ]
        return "🕒 Совместные свободные окна:\n" + "\n".join(lines)

    def set_group_notifications_by_id(
        self, tg_user: TgUser, group_id: int, muted: bool
    ) -> str:
        group = Group.get_or_none(Group.id == group_id)
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(tg_user)
        member = self._get_member(group, user)
        if member is None:
            return "⛔ Вы не состоите в этой группе"
        member.mute_notifications = muted
        member.save()
        if muted:
            return "🔕 Уведомления группы выключены"
        return "🔔 Уведомления группы включены"

    def _run_fetch(self, user: User, group: Group) -> str:
        group_tasks = list(GroupTask.select().where(GroupTask.group == group))
        if not group_tasks:
            return "📭 В группе нет задач"
        existing_assigned = (
            GroupTask.select(GroupTask.task)
            .join(GroupTaskAssignment)
            .where(GroupTaskAssignment.user == user)
        )
        added = 0
        collisions: dict[int, Task] = {}
        for group_task in group_tasks:
            created = GroupTaskAssignment.get_or_create(
                group_task=group_task,
                user=user,
            )[1]
            if not created:
                continue
            added += 1
            task = group_task.task
            if task.end_dt is not None:
                overlapping = Task.select().where(
                    (Task.id != task.id)
                    & (Task.is_muted == False)
                    & (Task.task_type != "work_session")
                    & (Task.end_dt.is_null(False))
                    & (Task.start_dt < task.end_dt)
                    & (Task.end_dt > task.start_dt)
                    & ((Task.user == user) | (Task.id.in_(existing_assigned)))
                )
            else:
                overlapping = Task.select().where(
                    (Task.id != task.id)
                    & (Task.is_muted == False)
                    & (Task.task_type != "work_session")
                    & (Task.end_dt.is_null(False))
                    & (Task.start_dt <= task.start_dt)
                    & (Task.end_dt > task.start_dt)
                    & ((Task.user == user) | (Task.id.in_(existing_assigned)))
                )
            for item in overlapping:
                collisions[item.id] = item
        if added == 0:
            return "✅ Все групповые задачи уже в расписании"
        if not collisions:
            log.info(
                "fetch_group_tasks user=%s group=%s added=%s no_collisions",
                user.id,
                group.id,
                added,
            )
            return f"✅ Добавлено задач: {added}"
        log.info(
            "fetch_group_tasks user=%s group=%s added=%s collisions=%s",
            user.id,
            group.id,
            added,
            list(collisions.keys()),
        )
        formatted = self.task_service._format_task_list(user, collisions.values())
        return f"✅ Добавлено задач: {added}\n⚠️ Найдены пересечения:\n{formatted}"

    def add_group_task_by_id(self, tg_user: TgUser, group_id: int) -> str:
        group = Group.get_or_none(Group.id == group_id)
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(tg_user)
        if (
            not GroupMember.select()
            .where(
                (GroupMember.group == group.id)
                & (GroupMember.user == user)
                & (GroupMember.is_admin == True)
            )
            .exists()
        ):
            return "⛔ Нет прав администратора"
        payload = {"step": "type", "is_group": True, "group_id": group.id}
        TaskWizardState.insert(
            user=user,
            step="type",
            payload=json.dumps(payload),
        ).on_conflict(
            conflict_target=[TaskWizardState.user],
            update={
                TaskWizardState.step: "type",
                TaskWizardState.payload: json.dumps(payload),
            },
        ).execute()
        return (
            "👥 Создаем групповую задачу!\n"
            "Выберите тип ниже или напишите: one_time | recurring | deadline"
        )

    def add_group_task(self, message: Message) -> str:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            return "Нужен код или id группы. Пример: /group_add_task AbCd1234"
        group = self._resolve_group(parts[1].strip())
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(message.from_user)
        if (
            not GroupMember.select()
            .where(
                (GroupMember.group == group.id)
                & (GroupMember.user == user)
                & (GroupMember.is_admin == True)
            )
            .exists()
        ):
            return "⛔ Нет прав администратора"
        payload = {"step": "type", "is_group": True, "group_id": group.id}
        TaskWizardState.insert(
            user=user,
            step="type",
            payload=json.dumps(payload),
        ).on_conflict(
            conflict_target=[TaskWizardState.user],
            update={
                TaskWizardState.step: "type",
                TaskWizardState.payload: json.dumps(payload),
            },
        ).execute()
        return (
            "👥 Создаем групповую задачу!\n"
            "Выберите тип ниже или напишите: one_time | recurring | deadline"
        )

    def group_free_time(self, message: Message) -> str:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            return (
                "Нужны код группы и дата. Пример: /group_free AbCd1234 24.05.2026 00:00"
            )
        group = self._resolve_group(parts[1].strip())
        if group is None:
            return "⚠️ Группа не найдена"
        try:
            day = parse_datetime(parts[2])
        except ValueError:
            return "Неверный формат даты. Пример: 24.05.2026 18:30"
        user = ensure_user(message.from_user)
        if (
            not GroupMember.select()
            .where((GroupMember.group == group.id) & (GroupMember.user == user))
            .exists()
        ):
            return "⛔ Вы не состоите в этой группе"
        members = GroupMember.select().where(GroupMember.group == group.id)
        intervals = [self.free_time.get_free_intervals(m.user.id, day) for m in members]
        free = self.free_time.intersect_intervals(intervals)
        if not free:
            return "⛔ Свободного времени нет"
        lines = [
            f"🟢 {start.strftime('%H:%M')} - {end.strftime('%H:%M')}"
            for start, end in free
        ]
        return "🕒 Совместные свободные окна:\n" + "\n".join(lines)

    def leave_group(self, message: Message) -> str:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            return "Нужен код или id группы. Пример: /group_leave AbCd1234"
        group = self._resolve_group(parts[1].strip())
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(message.from_user)
        member = self._get_member(group, user)
        if member is None:
            return "⚠️ Вы не состоите в этой группе"
        GroupMember.delete().where(GroupMember.id == member.id).execute()
        assignments = GroupTask.select(GroupTask.id).where(GroupTask.group == group)
        GroupTaskAssignment.delete().where(
            (GroupTaskAssignment.user == user)
            & (GroupTaskAssignment.group_task.in_(assignments))
        ).execute()
        return "✅ Вы вышли из группы"

    def fetch_group_tasks(self, message: Message) -> str:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            return "Нужен код или id группы. Пример: /group_fetch AbCd1234"
        group = self._resolve_group(parts[1].strip())
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(message.from_user)
        if (
            not GroupMember.select()
            .where((GroupMember.group == group) & (GroupMember.user == user))
            .exists()
        ):
            return "⛔ Вы не состоите в этой группе"
        return self._run_fetch(user, group)

    def get_group_members(self, group: Group) -> list[tuple[User, GroupMember]]:
        members = (
            GroupMember.select()
            .where(GroupMember.group == group)
            .order_by(GroupMember.id)
        )
        return [(m.user, m) for m in members]

    def promote_admin(self, message: Message) -> str:
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            return (
                "Нужны код группы и telegram id. Пример: /group_promote AbCd1234 12345"
            )
        group = self._resolve_group(parts[1].strip())
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(message.from_user)
        if (
            not GroupMember.select()
            .where(
                (GroupMember.group == group.id)
                & (GroupMember.user == user)
                & (GroupMember.is_admin == True)
            )
            .exists()
        ):
            return "⛔ Нет прав администратора"
        raw = parts[2].strip().lstrip("@")
        if not raw.isdigit():
            return "⚠️ Неверный telegram id. Пример: /group_promote AbCd1234 12345"
        target = User.get_or_none(User.telegram_id == int(raw))
        if target is None:
            return "⚠️ Пользователь не найден"
        member = GroupMember.get_or_none(
            (GroupMember.group == group) & (GroupMember.user == target)
        )
        if member is None:
            return "⚠️ Пользователь не в группе"
        if member.is_admin:
            return "⚠️ Пользователь уже администратор"
        member.is_admin = True
        member.save()
        return f"✅ {target.username or 'Пользователь'} назначен администратором"

    def promote_admin_by_id(
        self, tg_user: TgUser, group_id: int, target_user_id: int
    ) -> str:
        group = Group.get_or_none(Group.id == group_id)
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(tg_user)
        if (
            not GroupMember.select()
            .where(
                (GroupMember.group == group)
                & (GroupMember.user == user)
                & (GroupMember.is_admin == True)
            )
            .exists()
        ):
            return "⛔ Нет прав администратора"
        target = User.get_or_none(User.id == target_user_id)
        if target is None:
            return "⚠️ Пользователь не найден"
        member = GroupMember.get_or_none(
            (GroupMember.group == group) & (GroupMember.user == target)
        )
        if member is None:
            return "⚠️ Пользователь не в группе"
        if member.is_admin:
            return "⚠️ Пользователь уже администратор"
        member.is_admin = True
        member.save()
        return f"✅ {target.username or 'Пользователь'} назначен администратором"

    def mute_group_notifications(self, message: Message) -> str:
        return self._set_group_notifications(message, muted=True)

    def unmute_group_notifications(self, message: Message) -> str:
        return self._set_group_notifications(message, muted=False)

    def _set_group_notifications(self, message: Message, muted: bool) -> str:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            return "Нужен код или id группы. Пример: /group_mute AbCd1234"
        group = self._resolve_group(parts[1].strip())
        if group is None:
            return "⚠️ Группа не найдена"
        user = ensure_user(message.from_user)
        member = self._get_member(group, user)
        if member is None:
            return "⛔ Вы не состоите в этой группе"
        member.mute_notifications = muted
        member.save()
        if muted:
            return "🔕 Уведомления группы выключены"
        return "🔔 Уведомления группы включены"
