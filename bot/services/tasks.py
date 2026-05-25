from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import datetime as dt
import json
import logging
from typing import Iterable

from telebot.types import Message, User as TgUser

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
from bot.services.scheduler import ReminderScheduler
from bot.services.free_time import FreeTimeService
from bot.services.users import ensure_user
from bot.utils.time_parse import DATE_TIME_FORMAT, TIME_FORMAT, parse_datetime
from bot.utils.timezone import attach_timezone, from_utc, get_zoneinfo, to_utc

log = logging.getLogger(__name__)


@dataclass
class TaskService:
    scheduler: ReminderScheduler
    free_time: FreeTimeService
    default_start_hour: int = 8
    default_end_hour: int = 23

    def start_task_wizard(self, message: Message) -> str:
        user = ensure_user(message.from_user)
        payload = {"step": "type"}
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
            "🧩 Создаем задачу!\n"
            "Выберите тип ниже или напишите: one_time | recurring | deadline"
        )

    def set_wizard_type(self, tg_user: TgUser, task_type: str) -> None:
        user = ensure_user(tg_user)
        payload = self._get_wizard_payload(user) or {}
        payload["task_type"] = task_type
        if task_type == "deadline":
            log.info("deadline_wizard_type_selected user_id=%s", user.id)
        self._set_wizard_step(user, "name", payload)

    def set_wizard_recurrence(self, tg_user: TgUser, rule: str) -> str:
        user = ensure_user(tg_user)
        payload = self._get_wizard_payload(user) or {}
        payload["recurrence_rule"] = rule
        if rule == "every_n_days":
            self._set_wizard_step(user, "recurrence_interval", payload)
            return "recurrence_interval"
        self._set_wizard_step(user, "start_dt", payload)
        return "start_dt"

    def ensure_user_for_callback(self, tg_user: TgUser) -> User:
        return ensure_user(tg_user)

    def set_wizard_substep(self, tg_user: TgUser, step: str) -> None:
        user = ensure_user(tg_user)
        payload = self._get_wizard_payload(user) or {}
        payload["category"] = None
        self._set_wizard_step(user, step, payload)

    def set_wizard_category(self, tg_user: TgUser, category_name: str) -> bool:
        user = ensure_user(tg_user)
        state = TaskWizardState.get_or_none(TaskWizardState.user == user)
        if state is None:
            return False
        payload = json.loads(state.payload)
        payload["category"] = category_name
        self._set_wizard_step(user, "reminders", payload)
        return True

    def set_wizard_date(
        self, tg_user: TgUser, date_value: date | datetime
    ) -> tuple[str, str]:
        user = ensure_user(tg_user)
        payload = self._get_wizard_payload(user) or {}
        if isinstance(date_value, datetime):
            date_value = date_value.date()
        step = payload.get("step")
        if step is None:
            state = TaskWizardState.get_or_none(TaskWizardState.user == user)
            if state:
                step = state.step
        now_local = datetime.now(get_zoneinfo(user.timezone))
        if step in ("start_dt", "end_dt") and date_value < now_local.date():
            return "error", "⚠️ Нельзя создавать задачу в прошлом"
        if step == "start_dt":
            payload["start_date"] = date_value.isoformat()
            self._set_wizard_step(user, "start_time", payload)
            return "start_time", "🕒 Введите время начала (ЧЧ:ММ)"
        if step == "end_dt":
            payload["end_date"] = date_value.isoformat()
            self._set_wizard_step(user, "end_time", payload)
            if payload.get("task_type") == "deadline":
                log.info(
                    "deadline_wizard_end_date_selected user_id=%s end_date=%s",
                    user.id,
                    payload["end_date"],
                )
            return "end_time", "⏰ Введите время дедлайна (ЧЧ:ММ)"
        return "", ""

    def list_tasks_by_category(self, message: Message) -> str:
        user = ensure_user(message.from_user)
        return self._list_tasks_by_category(user)

    def list_tasks_by_category_id(self, user: User, category_id: int) -> str:
        from bot.db.models import Category as CategoryModel

        category = CategoryModel.get_or_none(
            CategoryModel.id == category_id, CategoryModel.user == user
        )
        if category is None:
            return "🏷️ Категория не найдена"
        tasks = (
            self._select_user_tasks(user)
            .where(Task.category == category)
            .order_by(Task.start_dt)
        )
        if not tasks:
            return f"🏷️ В категории «{category.name}» задач нет"
        return self._format_task_list(user, tasks)

    def list_tasks_for_date(self, user: User, selected_date: date) -> str:
        day_start = datetime.combine(selected_date, time(0, 0))
        day_start = attach_timezone(day_start, user.timezone)
        return self._list_tasks_by_day(user, day_start)

    def _list_tasks_by_day(self, user: User, day_start: datetime) -> str:
        day_end = day_start + timedelta(days=1)
        start_utc = to_utc(day_start.replace(tzinfo=None), user.timezone)
        end_utc = to_utc(day_end.replace(tzinfo=None), user.timezone)
        tasks = self._select_user_tasks(user).order_by(Task.start_dt)
        entries: list[tuple[Task, datetime, datetime | None]] = []
        for task in tasks:
            if task.task_type in ("recurring", "deadline"):
                if task.task_type == "recurring":
                    occurrence = self._recurring_occurrence_on_day(
                        task, day_start, day_end, user
                    )
                    if occurrence:
                        occ_start, occ_end = occurrence
                        entries.append((task, occ_start, occ_end))
                continue
            if task.start_dt < start_utc or task.start_dt >= end_utc:
                continue
            start_local = from_utc(task.start_dt, user.timezone)
            end_local = None
            if task.end_dt:
                end_local = from_utc(task.end_dt, user.timezone)
            entries.append((task, start_local, end_local))
        if not entries:
            return "📭 На этот день задач нет"
        return self._format_task_entries(user, entries, time_only=True)

    def _list_tasks_by_category(self, user: User) -> str:
        tasks = self._select_user_tasks(user).order_by(Task.category, Task.start_dt)
        if tasks.count() == 0:
            return "📭 Задач пока нет"
        return self._format_task_list(user, tasks, show_category=True)

    def _format_task_list(
        self, user: User, tasks: Iterable[Task], show_category: bool = False
    ) -> str:
        entries: list[tuple[Task, datetime, datetime | None]] = []
        for task in tasks:
            start_local = from_utc(task.start_dt, user.timezone)
            end_local = None
            if task.end_dt:
                end_local = from_utc(task.end_dt, user.timezone)
            entries.append((task, start_local, end_local))
        return self._format_task_entries(user, entries, show_category=show_category)

    def _format_task_entries(
        self,
        user: User,
        entries: list[tuple[Task, datetime, datetime | None]],
        show_category: bool = False,
        time_only: bool = False,
    ) -> str:
        lines: list[str] = []
        for task, start_local, end_local in entries:
            fmt = TIME_FORMAT if time_only else DATE_TIME_FORMAT
            time_part = start_local.strftime(fmt)
            if end_local:
                time_part += f" - {end_local.strftime(fmt)}"
            category_part = ""
            if show_category and task.category:
                category_part = f" 🏷️ {task.category.name}"
            group_part = ""
            if task.is_group:
                group_part = " 👥"
            name = task.name or task.task_type
            if task.task_type == "deadline":
                type_marker = "⏰"
            elif task.task_type == "recurring":
                type_marker = "🔁"
            elif task.task_type == "work_session":
                type_marker = "🧩"
            else:
                type_marker = "🗓️"
            lines.append(
                f"{type_marker} #{task.id} {name}{category_part}{group_part} — {time_part}"
            )
        return "\n".join(lines)

    def list_free_time(self, message: Message) -> str:
        return "📅 Выберите дату в календаре"

    def list_free_time_for_date(self, user: User, day: date) -> str:
        day_start = datetime.combine(day, time(0, 0))
        intervals = self.free_time.get_free_intervals(user.id, day_start)
        if not intervals:
            return "⛔ Свободного времени нет"
        lines = [
            f"🟢 {start.strftime('%H:%M')} - {end.strftime('%H:%M')}"
            for start, end in intervals
        ]
        return "🕒 Свободные окна:\n" + "\n".join(lines)

    def _parse_task_ids(self, raw: str) -> list[int] | None:
        ids: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                range_parts = part.split("-", 1)
                try:
                    start, end = int(range_parts[0]), int(range_parts[1])
                except ValueError:
                    return None
                if start > end or start <= 0:
                    return None
                ids.extend(range(start, end + 1))
            else:
                try:
                    ids.append(int(part))
                except ValueError:
                    return None
        return ids

    def delete_task(self, message: Message) -> str:
        user = ensure_user(message.from_user)
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            return (
                "Нужен id задачи. Примеры:\n"
                "• /delete 123\n"
                "• /delete 2,3,4\n"
                "• /delete 1-8"
            )
        raw = parts[1].strip()
        task_ids = self._parse_task_ids(raw)
        if task_ids is None:
            return self._delete_task_by_name(user, raw)
        if not task_ids:
            return "⚠️ Не указаны id задач"
        results: list[str] = []
        for task_id in task_ids:
            results.append(self._delete_task_by_id(user, task_id))
        return "\n".join(results)

    def _delete_task_by_name(self, user: User, name: str) -> str:
        if not name:
            return "⚠️ Укажите название задачи"
        tasks = (
            self._select_user_tasks(user)
            .where(Task.name == name)
            .order_by(Task.start_dt)
        )
        if tasks.count() == 0:
            return f"⚠️ Задача с названием «{name}» не найдена"
        if tasks.count() == 1:
            task = tasks.first()
            return self._delete_task_by_id(user, task.id)
        formatted = self._format_task_list(user, tasks)
        return (
            f"Найдено несколько задач с названием «{name}».\n"
            "Удалите нужную по id: /delete 123\n"
            f"{formatted}"
        )

    def _delete_task_by_id(self, user: User, task_id: int) -> str:
        task = self._select_user_tasks(user).where(Task.id == task_id).first()
        if task is None:
            return f"⚠️ #{task_id} не найдена"
        self.scheduler.remove_task_reminders(task_id)
        if task.task_type == "recurring":
            task.is_muted = True
            task.save()
            return f"🔕 #{task_id} заглушена (повтор выключен)"
        Task.delete().where(Task.id == task_id).execute()
        Reminder.delete().where(Reminder.task == task_id).execute()
        GroupTask.delete().where(GroupTask.task == task_id).execute()
        return f"🗑️ #{task_id} удалена"

    def unmute_task(self, task_id: int) -> str:
        task = Task.get_or_none(Task.id == task_id)
        if task is None:
            return "⚠️ Задача не найдена"
        if not task.is_muted:
            return "🔔 Задача уже активна"
        task.is_muted = False
        task.save()
        from bot.db.models import Reminder as ReminderModel

        reminders = ReminderModel.select().where(ReminderModel.task == task)
        offsets = [r.offset_minutes for r in reminders]
        if offsets:
            self.schedule_reminders(task.id, offsets)
        return "🔔 Повтор включен обратно"

    def create_task(
        self, user: User, payload: dict
    ) -> tuple[Task | None, list[int], str]:
        if not payload:
            return None, [], ""
        task_type = payload.get("task_type")
        start_raw = payload.get("start_dt")
        end_raw = payload.get("end_dt")
        name = payload.get("name", "")
        category_name = payload.get("category")
        expected_work_hours = payload.get("expected_work_hours")
        recurrence_rule = payload.get("recurrence_rule")
        recurrence_interval = payload.get("recurrence_interval")
        is_group = bool(payload.get("is_group"))
        group_id = payload.get("group_id")

        if task_type == "recurring" and not recurrence_rule:
            return None, [], ""
        if task_type == "deadline" and not expected_work_hours:
            return None, [], ""
        if is_group and group_id:
            is_admin = (
                GroupMember.select()
                .where(
                    (GroupMember.group == group_id)
                    & (GroupMember.user == user)
                    & (GroupMember.is_admin == True)
                )
                .exists()
            )
            if not is_admin:
                return None, [], "⛔ Нет прав администратора"

        if task_type == "deadline":
            log.info(
                "deadline_create_attempt user_id=%s name=%r end_raw=%r expected_hours=%r reminders=%s category=%r is_group=%s group_id=%r",
                user.id,
                name,
                end_raw,
                expected_work_hours,
                payload.get("reminders", []),
                category_name,
                is_group,
                group_id,
            )

        if task_type == "deadline":
            start_dt = datetime.utcnow()
        elif not start_raw:
            return None, [], ""
        else:
            now_local = datetime.now(get_zoneinfo(user.timezone)).replace(tzinfo=None)
            start_local = parse_datetime(start_raw)
            if start_local <= now_local:
                log.info(
                    "task_create_rejected_past_start user_id=%s task_type=%s start=%s now=%s",
                    user.id,
                    task_type,
                    start_local,
                    now_local,
                )
                return None, [], "⚠️ Нельзя создавать задачу в прошлом"
            start_dt = to_utc(parse_datetime(start_raw), user.timezone)
        end_dt = None
        if end_raw:
            end_dt = to_utc(parse_datetime(end_raw), user.timezone)

        if task_type == "deadline":
            if end_dt is None:
                log.info("deadline_create_rejected_missing_end user_id=%s", user.id)
                return None, [], "⚠️ Нужен дедлайн"
            end_local = parse_datetime(end_raw)
            now_local = from_utc(start_dt, user.timezone).replace(tzinfo=None)
            if end_local <= now_local:
                log.info(
                    "deadline_create_rejected_past_end user_id=%s end=%s now=%s",
                    user.id,
                    end_local,
                    now_local,
                )
                return None, [], "⚠️ Дедлайн должен быть в будущем"
            required_minutes = int(expected_work_hours) * 60
            max_minutes = self._max_possible_minutes(user, now_local, end_local)
            if max_minutes <= 0 or required_minutes > max_minutes:
                log.info(
                    "deadline_create_rejected_impossible_workload user_id=%s required_minutes=%s max_minutes=%s start=%s end=%s",
                    user.id,
                    required_minutes,
                    max_minutes,
                    now_local,
                    end_local,
                )
                return (
                    None,
                    [],
                    "⚠️ Нереалистичный объём работы для выбранного дедлайна",
                )

        category = None
        if category_name:
            category, _ = Category.get_or_create(user=user, name=category_name)

        task = Task.create(
            user=user,
            category=category,
            task_type=task_type,
            name=name,
            start_dt=start_dt,
            end_dt=end_dt,
            expected_work_hours=expected_work_hours,
            is_group=is_group,
        )

        if task_type == "deadline":
            log.info(
                "deadline_created task_id=%s user_id=%s start_utc=%s end_utc=%s expected_hours=%s",
                task.id,
                user.id,
                start_dt,
                end_dt,
                expected_work_hours,
            )

        if is_group and group_id:
            GroupTask.create(group=Group.get_by_id(group_id), task=task)

        if recurrence_rule:
            Recurrence.create(
                task=task,
                rule=recurrence_rule,
                interval=recurrence_interval,
            )

        offsets = payload.get("reminders", [])
        for offset in offsets:
            Reminder.create(task=task, offset_minutes=int(offset))

        self.schedule_reminders(task.id, offsets)
        if task_type == "deadline":
            log.info(
                "deadline_reminders_scheduled task_id=%s user_id=%s offsets=%s",
                task.id,
                user.id,
                list(offsets),
            )

        warning = ""
        if task_type == "deadline" and expected_work_hours:
            unscheduled = self._plan_deadline_sessions(user, task)
            if unscheduled > 0:
                log.info(
                    "deadline_work_sessions_unscheduled task_id=%s user_id=%s unscheduled_minutes=%s",
                    task.id,
                    user.id,
                    unscheduled,
                )
                start_h = user.day_start_hour
                end_h = user.day_end_hour
                total_minutes = expected_work_hours * 60
                scheduled_minutes = total_minutes - unscheduled
                h = unscheduled // 60
                m = unscheduled % 60
                if h > 0 and m > 0:
                    short_str = f"{h} ч. {m} мин."
                elif h > 0:
                    short_str = f"{h} ч."
                else:
                    short_str = f"{m} мин."
                sh = scheduled_minutes // 60
                sm = scheduled_minutes % 60
                if sh > 0 and sm > 0:
                    scheduled_str = f"{sh} ч. {sm} мин."
                elif sh > 0:
                    scheduled_str = f"{sh} ч."
                else:
                    scheduled_str = f"{sm} мин."
                warning = (
                    "⚠️ Дедлайн близко. "
                    f"Запланировано {scheduled_str} из {expected_work_hours} ч. "
                    f"Окно активности: {start_h}:00–{end_h}:00. "
                    f"Осталось {short_str}. "
                    "Подстройте часы: /active_start и /active_end."
                )

        TaskWizardState.delete().where(TaskWizardState.user == user).execute()
        conflicts = self._find_overlaps(user, task)
        if task_type == "deadline":
            log.info(
                "deadline_create_done task_id=%s user_id=%s conflicts=%s warning=%s",
                task.id,
                user.id,
                conflicts,
                bool(warning),
            )
        return task, conflicts, warning

    def cancel_wizard(self, user_id: int) -> bool:
        user = User.get_or_none(User.telegram_id == user_id)
        if user is None:
            return False
        state = TaskWizardState.get_or_none(TaskWizardState.user == user)
        if state is None:
            return False
        TaskWizardState.delete().where(TaskWizardState.user == user).execute()
        return True

    def schedule_reminders(self, task_id: int, offsets: Iterable[int]) -> None:
        self.scheduler.schedule_task_reminders(task_id, offsets)

    def handle_wizard_message(self, message: Message) -> str | None:
        user = ensure_user(message.from_user)
        state = TaskWizardState.get_or_none(TaskWizardState.user == user)
        if state is None:
            return None
        payload = json.loads(state.payload)
        step = state.step
        text = (message.text or "").strip()

        if step == "type":
            return "type"
        if step == "group_id":
            if text and not text.isdigit():
                return "⚠️ Неверный id группы. Пример: 12"
            payload["is_group"] = bool(text)
            payload["group_id"] = int(text) if text else None
            return self._set_wizard_step(user, "start_dt", payload)
        if step == "name":
            if not text or len(text) > 100:
                return "⚠️ Название должно быть от 1 до 100 символов"
            payload["name"] = text
            task_type = payload.get("task_type")
            if task_type == "deadline":
                log.info("deadline_wizard_name_set user_id=%s name=%r", user.id, text)
                return self._set_wizard_step(user, "expected_work_hours", payload)
            if task_type == "recurring":
                return self._set_wizard_step(user, "recurrence_rule", payload)
            return self._set_wizard_step(user, "start_dt", payload)
        if step == "expected_work_hours":
            if not text.isdigit() or int(text) <= 0:
                return "⚠️ Неверное значение. Пример: 5"
            payload["expected_work_hours"] = int(text)
            if payload.get("task_type") == "deadline":
                log.info(
                    "deadline_wizard_expected_hours_set user_id=%s expected_hours=%s",
                    user.id,
                    payload["expected_work_hours"],
                )
                return self._set_wizard_step(user, "end_dt", payload)
            return self._set_wizard_step(user, "start_dt", payload)
        if step == "recurrence_rule":
            return "recurrence_rule"
        if step == "recurrence_interval":
            if not text.isdigit() or int(text) <= 0:
                return "⚠️ Неверный интервал. Пример: 3"
            payload["recurrence_interval"] = int(text)
            return self._set_wizard_step(user, "start_dt", payload)
        if step == "start_dt":
            if text.lower() in {"now", "сейчас"}:
                now_val = datetime.now()
                payload["start_dt"] = now_val.strftime(DATE_TIME_FORMAT)
                payload["start_date"] = now_val.date().isoformat()
                return self._set_wizard_step(user, "end_time", payload)
            if not self._is_valid_datetime(text):
                return "⚠️ Неверный формат даты. Пример: 24.05.2026 18:30"
            parsed = parse_datetime(text)
            now_local = datetime.now(get_zoneinfo(user.timezone))
            if parsed.replace(tzinfo=get_zoneinfo(user.timezone)) <= now_local:
                return "⚠️ Нельзя создавать задачу в прошлом"
            payload["start_dt"] = text
            payload["start_date"] = parsed.date().isoformat()
            return self._set_wizard_step(user, "end_time", payload)
        if step == "start_time":
            start_date = payload.get("start_date")
            if not start_date:
                return "⚠️ Неверная дата"
            time_value = self._parse_time(text)
            if time_value is None:
                return "⚠️ Неверный формат времени. Пример: 09:30"
            date_value = date.fromisoformat(start_date)
            start_dt = datetime.combine(date_value, time_value)
            now_local = datetime.now(get_zoneinfo(user.timezone))
            if start_dt.replace(tzinfo=get_zoneinfo(user.timezone)) <= now_local:
                return "⚠️ Нельзя создавать задачу в прошлом"
            payload["start_dt"] = start_dt.strftime(DATE_TIME_FORMAT)
            return self._set_wizard_step(user, "end_time", payload)
        if step == "end_time":
            if text.lower() in {"skip", "нет", "none", ""}:
                payload["end_dt"] = None
                payload.pop("start_date", None)
                payload.pop("end_date", None)
                return self._set_wizard_step(user, "category", payload)
            step_date = payload.get("end_date") or payload.get("start_date")
            if not step_date:
                return "⚠️ Неверная дата"
            time_value = self._parse_time(text)
            if time_value is None:
                return "⚠️ Неверный формат времени. Пример: 18:00"
            date_value = date.fromisoformat(step_date)
            end_dt = datetime.combine(date_value, time_value)
            if payload.get("task_type") == "deadline":
                now_local = datetime.now(get_zoneinfo(user.timezone)).replace(
                    tzinfo=None
                )
                if end_dt <= now_local:
                    log.info(
                        "deadline_wizard_end_time_rejected_past user_id=%s end_dt=%s now=%s",
                        user.id,
                        end_dt,
                        now_local,
                    )
                    return "⚠️ Дедлайн должен быть в будущем"
                log.info(
                    "deadline_wizard_end_time_set user_id=%s end_dt=%s",
                    user.id,
                    end_dt,
                )
            start_raw = payload.get("start_dt")
            if start_raw:
                start_val = parse_datetime(start_raw)
                if end_dt <= start_val:
                    return "⚠️ Конец должен быть позже начала"
            payload["end_dt"] = end_dt.strftime(DATE_TIME_FORMAT)
            payload.pop("start_date", None)
            payload.pop("end_date", None)
            return self._set_wizard_step(user, "category", payload)
        if step == "category":
            return "category"
        if step == "awaiting_category_name":
            if not text or len(text) > 50:
                return "⚠️ Название должно быть от 1 до 50 символов"
            category, _ = Category.get_or_create(user=user, name=text)
            payload["category"] = category.name
            if payload.get("task_type") == "deadline":
                log.info(
                    "deadline_wizard_category_set user_id=%s category=%r",
                    user.id,
                    category.name,
                )
            return self._set_wizard_step(user, "reminders", payload)
        if step == "reminders":
            payload["reminders"] = self._parse_offsets(text)
            if payload.get("task_type") == "deadline":
                log.info(
                    "deadline_wizard_reminders_set user_id=%s offsets=%s",
                    user.id,
                    payload["reminders"],
                )
            self._set_wizard_step(user, "complete", payload)
            task, conflicts, warning = self.create_task(user, payload)
            if task is None:
                if warning:
                    return warning
                return "⚠️ Не удалось создать задачу"
            parts = []
            if conflicts:
                conflict_tasks = list(Task.select().where(Task.id.in_(conflicts)))
                conflict_lines = "\n".join(
                    f"  #{t.id} {t.name or t.task_type}" for t in conflict_tasks
                )
                parts.append(f"⚠️ Есть пересечения с задачами:\n{conflict_lines}")
                log.info(
                    "wizard_conflict user=%s task=%s conflicts=%s",
                    user.id,
                    task.id,
                    conflicts,
                )
            if warning:
                parts.append(warning)
            if parts:
                parts.append("✅ Задача создана")
                result = "\n".join(parts)
                log.info("wizard_result user=%s task=%s: %s", user.id, task.id, result)
                return result
            return "complete"

        return None

    def _set_wizard_step(self, user: User, step: str, payload: dict) -> str:
        payload["step"] = step
        TaskWizardState.update(step=step, payload=json.dumps(payload)).where(
            TaskWizardState.user == user
        ).execute()
        return step

    def _get_wizard_payload(self, user: User) -> dict | None:
        state = TaskWizardState.get_or_none(TaskWizardState.user == user)
        if state is None:
            return None
        return json.loads(state.payload)

    def _parse_offsets(self, text: str) -> list[int]:
        if not text or text.strip().lower() in {"skip", "нет", "-", "none"}:
            return []
        parts = [part.strip() for part in text.split(",")]
        offsets: list[int] = []
        for part in parts:
            if not part:
                continue
            offsets.append(int(part))
        return offsets

    def _select_user_tasks(self, user: User):
        group_tasks = (
            GroupTask.select(GroupTask.task)
            .join(GroupTaskAssignment)
            .where(GroupTaskAssignment.user == user)
        )
        return Task.select().where(
            ((Task.user == user) | (Task.id.in_(group_tasks)))
            & (Task.is_muted == False)
        )

    def _plan_deadline_sessions(self, user: User, task: Task) -> int:
        expected_hours = task.expected_work_hours or 0
        if expected_hours <= 0:
            return 0
        start_day = from_utc(task.start_dt, user.timezone)
        end_day = start_day
        if task.end_dt:
            end_day = from_utc(task.end_dt, user.timezone)
        available_days = self._generate_days(start_day, end_day)
        remaining_minutes = expected_hours * 60
        while remaining_minutes > 0:
            best_free: list[tuple[datetime, datetime]] = []
            best_total = 0
            for day in available_days:
                free = self.free_time.get_free_intervals(user.id, day)
                if day.date() == start_day.date():
                    free = [(max(s, start_day), e) for s, e in free if e > start_day]
                if day.date() == end_day.date():
                    free = [(s, min(e, end_day)) for s, e in free if s < end_day]
                total = self._max_minutes_from_intervals(free)
                if total > best_total:
                    best_total = total
                    best_free = free
            if best_total <= 0:
                break
            consume = min(remaining_minutes, best_total)
            self._create_work_sessions(user, task, best_free, consume)
            remaining_minutes -= consume
        return remaining_minutes

    def _generate_days(self, start_day: datetime, end_day: datetime) -> list[datetime]:
        days: list[datetime] = []
        current = start_day
        while current.date() <= end_day.date():
            days.append(current)
            current = current + timedelta(days=1)
        return days

    def _max_possible_minutes(
        self, user: User, start_dt: datetime, end_dt: datetime
    ) -> int:
        if end_dt <= start_dt:
            return 0
        day_hours = max(0, user.day_end_hour - user.day_start_hour)
        if day_hours <= 0:
            return 0
        start_day = start_dt
        end_day = end_dt
        total = 0
        current = start_day
        while current.date() <= end_day.date():
            if current.date() == start_day.date() and current.date() == end_day.date():
                current_start = max(
                    start_day,
                    dt.datetime.combine(
                        start_day.date(), dt.time(user.day_start_hour, 0)
                    ),
                )
                current_end = min(
                    end_day,
                    dt.datetime.combine(
                        start_day.date(), dt.time(user.day_end_hour, 0)
                    ),
                )
            elif current.date() == start_day.date():
                current_start = max(
                    start_day,
                    dt.datetime.combine(
                        start_day.date(), dt.time(user.day_start_hour, 0)
                    ),
                )
                current_end = dt.datetime.combine(
                    start_day.date(), dt.time(user.day_end_hour, 0)
                )
            elif current.date() == end_day.date():
                current_start = dt.datetime.combine(
                    end_day.date(), dt.time(user.day_start_hour, 0)
                )
                current_end = min(
                    end_day,
                    dt.datetime.combine(end_day.date(), dt.time(user.day_end_hour, 0)),
                )
            else:
                current_start = dt.datetime.combine(
                    current.date(), dt.time(user.day_start_hour, 0)
                )
                current_end = dt.datetime.combine(
                    current.date(), dt.time(user.day_end_hour, 0)
                )
            if current_end > current_start:
                total += int((current_end - current_start).total_seconds() / 60)
            current = current + timedelta(days=1)
        return total

    def _max_minutes_from_intervals(
        self, intervals: list[tuple[datetime, datetime]]
    ) -> int:
        minutes = 0
        for start, end in intervals:
            minutes += int((end - start).total_seconds() / 60)
        return minutes

    def _create_work_sessions(
        self,
        user: User,
        task: Task,
        free: list[tuple[datetime, datetime]],
        minutes: int,
    ) -> None:
        remaining = minutes
        for start_local, end_local in free:
            if remaining <= 0:
                break
            available = int((end_local - start_local).total_seconds() / 60)
            if available <= 0:
                continue
            consume = min(remaining, available)
            session_end = start_local + timedelta(minutes=consume)
            start_utc = to_utc(start_local.replace(tzinfo=None), user.timezone)
            end_utc = to_utc(session_end.replace(tzinfo=None), user.timezone)
            Task.create(
                user=user,
                category=task.category,
                task_type="work_session",
                name=task.name,
                start_dt=start_utc,
                end_dt=end_utc,
                expected_work_hours=None,
            )
            remaining -= consume

    def _recurring_occurrence_on_day(
        self,
        task: Task,
        day_start: datetime,
        day_end: datetime,
        user: User,
    ) -> tuple[datetime, datetime | None] | None:
        recurrence = Recurrence.get_or_none(Recurrence.task == task)
        if recurrence is None:
            return None
        start_local = from_utc(task.start_dt, user.timezone)
        if day_start.date() < start_local.date():
            return None
        day_date = day_start.date()
        if recurrence.rule == "daily":
            occurs = True
        elif recurrence.rule == "weekly":
            occurs = day_date.weekday() == start_local.weekday()
        elif recurrence.rule == "monthly":
            occurs = day_date.day == start_local.day
        elif recurrence.rule == "every_n_days" and recurrence.interval:
            delta = (day_date - start_local.date()).days
            occurs = delta % recurrence.interval == 0
        else:
            occurs = False
        if not occurs:
            return None
        occ_start = datetime.combine(
            day_date, start_local.time(), tzinfo=start_local.tzinfo
        )
        occ_end = None
        if task.end_dt:
            end_local = from_utc(task.end_dt, user.timezone)
            duration = end_local - start_local
            occ_end = occ_start + duration
        if occ_start >= day_end:
            return None
        return (occ_start, occ_end)

    def _is_valid_datetime(self, text: str) -> bool:
        try:
            parse_datetime(text)
        except ValueError:
            return False
        return True

    def _parse_time(self, text: str) -> time | None:
        try:
            return datetime.strptime(text, "%H:%M").time()
        except ValueError:
            return None

    def _find_overlaps(self, user: User, task: Task) -> list[int]:
        assigned_group = (
            GroupTask.select(GroupTask.task)
            .join(GroupTaskAssignment)
            .where(GroupTaskAssignment.user == user)
        )
        if task.end_dt is not None:
            overlapping = Task.select(Task.id).where(
                (Task.id != task.id)
                & (Task.is_muted == False)
                & (Task.task_type != "work_session")
                & (Task.end_dt.is_null(False))
                & (Task.start_dt < task.end_dt)
                & (Task.end_dt > task.start_dt)
                & ((Task.user == user) | (Task.id.in_(assigned_group)))
            )
        else:
            overlapping = Task.select(Task.id).where(
                (Task.id != task.id)
                & (Task.is_muted == False)
                & (Task.task_type != "work_session")
                & (Task.end_dt.is_null(False))
                & (Task.start_dt <= task.start_dt)
                & (Task.end_dt > task.start_dt)
                & ((Task.user == user) | (Task.id.in_(assigned_group)))
            )
        result = [item.id for item in overlapping]
        if result:
            log.info(
                "_find_overlaps user=%s task=%s conflicts=%s", user.id, task.id, result
            )
        return result
