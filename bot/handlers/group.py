from __future__ import annotations

import json

from telebot import TeleBot
from telebot.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from telegram_bot_calendar import DetailedTelegramCalendar, WMonthTelegramCalendar

from bot.services.groups import GroupService
from bot.services.users import ensure_user


def _normalize_calendar_markup(calendar_markup: object) -> InlineKeyboardMarkup:
    if isinstance(calendar_markup, InlineKeyboardMarkup):
        return calendar_markup
    if isinstance(calendar_markup, str):
        calendar_markup = json.loads(calendar_markup)
    if isinstance(calendar_markup, dict):
        rows = calendar_markup.get("inline_keyboard", [])
    elif isinstance(calendar_markup, list):
        rows = calendar_markup
    else:
        rows = []
    keyboard = InlineKeyboardMarkup()
    for row in rows:
        if isinstance(row, dict):
            row = [row]
        if not isinstance(row, list):
            continue
        buttons: list[InlineKeyboardButton] = []
        for item in row:
            if isinstance(item, list):
                for nested in item:
                    if isinstance(nested, dict):
                        buttons.append(InlineKeyboardButton(**nested))
            elif isinstance(item, dict):
                buttons.append(InlineKeyboardButton(**item))
        if buttons:
            keyboard.row(*buttons)
    return keyboard


def _show_group_keyboard(
    bot: TeleBot,
    message: Message,
    groups: list,
    callback_prefix: str,
    empty_msg: str,
    prompt: str,
) -> None:
    if not groups:
        bot.reply_to(message, empty_msg)
        return
    keyboard = InlineKeyboardMarkup()
    for g in groups:
        keyboard.add(
            InlineKeyboardButton(g.name, callback_data=f"{callback_prefix}:{g.id}")
        )
    bot.reply_to(message, prompt, reply_markup=keyboard)


def register_group_handlers(bot: TeleBot, group_service: GroupService) -> None:
    @bot.message_handler(commands=["group_create"])
    def handle_group_create(message: Message) -> None:
        response = group_service.create_group(message)
        bot.reply_to(message, response)

    @bot.message_handler(commands=["group_join"])
    def handle_group_join(message: Message) -> None:
        response = group_service.join_group(message)
        bot.reply_to(message, response)

    @bot.message_handler(commands=["group_add_task"])
    def handle_group_add_task(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) >= 2:
            response = group_service.add_group_task(message)
            bot.reply_to(message, response)
            return
        user = ensure_user(message.from_user)
        groups = group_service.get_admin_groups(user)
        _show_group_keyboard(
            bot,
            message,
            groups,
            "group_add_task",
            "⛔ У вас нет групп с правами администратора",
            "👥 Выберите группу:",
        )

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("group_add_task:")
    )
    def handle_group_add_task_callback(call: CallbackQuery) -> None:
        group_id = int(call.data.split(":", 1)[1])
        response = group_service.add_group_task_by_id(call.from_user, group_id)
        if response.startswith("⛔") or response.startswith("⚠️"):
            bot.edit_message_text(
                response, call.message.chat.id, call.message.message_id
            )
            return
        keyboard = InlineKeyboardMarkup()
        keyboard.add(
            InlineKeyboardButton("Разовая 🗓️", callback_data="task_type:one_time"),
            InlineKeyboardButton("Повтор 🔁", callback_data="task_type:recurring"),
            InlineKeyboardButton("Дедлайн ⏰", callback_data="task_type:deadline"),
        )
        bot.edit_message_text(
            response,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
        )

    @bot.message_handler(commands=["group_free"])
    def handle_group_free(message: Message) -> None:
        parts = message.text.split(maxsplit=2)
        if len(parts) >= 3:
            response = group_service.group_free_time(message)
            bot.reply_to(message, response)
            return
        user = ensure_user(message.from_user)
        groups = group_service.get_user_groups(user)
        _show_group_keyboard(
            bot,
            message,
            groups,
            "group_free",
            "⛔ У вас нет групп",
            "👥 Выберите группу для просмотра свободного времени:",
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("group_free:"))
    def handle_group_free_callback(call: CallbackQuery) -> None:
        group_id = int(call.data.split(":", 1)[1])
        group_service._pending_group_date[call.from_user.id] = group_id
        calendar, _ = WMonthTelegramCalendar(
            calendar_id="groupfree",
            locale="ru",
            additional_buttons=[
                {"text": "Выбрать год", "callback_data": "calendar:group_free_year"}
            ],
        ).build()
        bot.edit_message_text(
            "📅 Выберите дату",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_normalize_calendar_markup(calendar),
        )

    @bot.callback_query_handler(
        func=lambda call: call.data == "calendar:group_free_year"
    )
    def handle_group_free_year_switch(call: CallbackQuery) -> None:
        calendar, _ = DetailedTelegramCalendar(
            calendar_id="groupfreefull", locale="ru"
        ).build()
        bot.edit_message_text(
            "📅 Выберите дату",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_normalize_calendar_markup(calendar),
        )

    @bot.callback_query_handler(
        func=WMonthTelegramCalendar.func(calendar_id="groupfree")
    )
    def handle_group_free_calendar(call: CallbackQuery) -> None:
        result, key, _ = WMonthTelegramCalendar(
            calendar_id="groupfree", locale="ru"
        ).process(call.data)
        if not result and key:
            bot.edit_message_text(
                "📅 Выберите дату",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=_normalize_calendar_markup(key),
            )
            return
        if result:
            group_id = group_service._pending_group_date.pop(call.from_user.id, None)
            if group_id is None:
                bot.edit_message_text(
                    "⏳ Выберите группу заново: /group_free",
                    call.message.chat.id,
                    call.message.message_id,
                )
                return
            response = group_service.group_free_time_for_date(
                call.from_user, group_id, result
            )
            bot.edit_message_text(
                response, call.message.chat.id, call.message.message_id
            )

    @bot.callback_query_handler(
        func=DetailedTelegramCalendar.func(calendar_id="groupfreefull")
    )
    def handle_group_free_full_calendar(call: CallbackQuery) -> None:
        result, key, _ = DetailedTelegramCalendar(
            calendar_id="groupfreefull", locale="ru"
        ).process(call.data)
        if not result and key:
            bot.edit_message_text(
                "📅 Выберите дату",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=_normalize_calendar_markup(key),
            )
            return
        if result:
            group_id = group_service._pending_group_date.pop(call.from_user.id, None)
            if group_id is None:
                bot.edit_message_text(
                    "⏳ Выберите группу заново: /group_free",
                    call.message.chat.id,
                    call.message.message_id,
                )
                return
            response = group_service.group_free_time_for_date(
                call.from_user, group_id, result
            )
            bot.edit_message_text(
                response, call.message.chat.id, call.message.message_id
            )

    @bot.message_handler(commands=["group_leave"])
    def handle_group_leave(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) >= 2:
            response = group_service.leave_group(message)
            bot.reply_to(message, response)
            return
        user = ensure_user(message.from_user)
        groups = group_service.get_user_groups(user)
        _show_group_keyboard(
            bot,
            message,
            groups,
            "group_leave",
            "⛔ У вас нет групп",
            "👥 Выберите группу для выхода:",
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("group_leave:"))
    def handle_group_leave_callback(call: CallbackQuery) -> None:
        group_id = int(call.data.split(":", 1)[1])
        response = group_service.leave_group_by_id(call.from_user, group_id)
        bot.edit_message_text(response, call.message.chat.id, call.message.message_id)

    @bot.message_handler(commands=["group_fetch"])
    def handle_group_fetch(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) >= 2:
            response = group_service.fetch_group_tasks(message)
            bot.reply_to(message, response)
            return
        user = ensure_user(message.from_user)
        groups = group_service.get_user_groups(user)
        _show_group_keyboard(
            bot,
            message,
            groups,
            "group_fetch",
            "⛔ У вас нет групп",
            "👥 Выберите группу для загрузки задач:",
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("group_fetch:"))
    def handle_group_fetch_callback(call: CallbackQuery) -> None:
        group_id = int(call.data.split(":", 1)[1])
        response = group_service.fetch_group_tasks_by_id(call.from_user, group_id)
        bot.edit_message_text(response, call.message.chat.id, call.message.message_id)

    @bot.message_handler(commands=["group_promote"])
    def handle_group_promote(message: Message) -> None:
        parts = message.text.split(maxsplit=2)
        if len(parts) >= 3:
            response = group_service.promote_admin(message)
            bot.reply_to(message, response)
            return
        user = ensure_user(message.from_user)
        groups = group_service.get_admin_groups(user)
        _show_group_keyboard(
            bot,
            message,
            groups,
            "group_promote",
            "⛔ У вас нет групп с правами администратора",
            "👥 Выберите группу:",
        )

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("group_promote:")
    )
    def handle_group_promote_callback(call: CallbackQuery) -> None:
        group_id = int(call.data.split(":", 1)[1])
        group = group_service._resolve_group_by_id(group_id)
        if group is None:
            bot.edit_message_text(
                "⚠️ Группа не найдена", call.message.chat.id, call.message.message_id
            )
            return
        members = group_service.get_group_members(group)
        if not members:
            bot.edit_message_text(
                "В группе нет участников", call.message.chat.id, call.message.message_id
            )
            return
        keyboard = InlineKeyboardMarkup()
        for member_user, member in members:
            label = member_user.username or f"id{member_user.telegram_id}"
            keyboard.add(
                InlineKeyboardButton(
                    label,
                    callback_data=f"group_promote_member:{group_id}:{member_user.id}",
                )
            )
        bot.edit_message_text(
            "👥 Выберите участника для повышения:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboard,
        )

    @bot.callback_query_handler(
        func=lambda call: call.data.startswith("group_promote_member:")
    )
    def handle_group_promote_member_callback(call: CallbackQuery) -> None:
        _, group_id_str, target_id_str = call.data.split(":", 2)
        response = group_service.promote_admin_by_id(
            call.from_user, int(group_id_str), int(target_id_str)
        )
        bot.edit_message_text(response, call.message.chat.id, call.message.message_id)

    @bot.message_handler(commands=["group_mute"])
    def handle_group_mute(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) >= 2:
            response = group_service.mute_group_notifications(message)
            bot.reply_to(message, response)
            return
        user = ensure_user(message.from_user)
        groups = group_service.get_user_groups(user)
        _show_group_keyboard(
            bot,
            message,
            groups,
            "group_mute",
            "⛔ У вас нет групп",
            "🔕 Выберите группу для отключения уведомлений:",
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("group_mute:"))
    def handle_group_mute_callback(call: CallbackQuery) -> None:
        group_id = int(call.data.split(":", 1)[1])
        response = group_service.set_group_notifications_by_id(
            call.from_user, group_id, muted=True
        )
        bot.edit_message_text(response, call.message.chat.id, call.message.message_id)

    @bot.message_handler(commands=["group_unmute"])
    def handle_group_unmute(message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) >= 2:
            response = group_service.unmute_group_notifications(message)
            bot.reply_to(message, response)
            return
        user = ensure_user(message.from_user)
        groups = group_service.get_user_groups(user)
        _show_group_keyboard(
            bot,
            message,
            groups,
            "group_unmute",
            "⛔ У вас нет групп",
            "🔔 Выберите группу для включения уведомлений:",
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("group_unmute:"))
    def handle_group_unmute_callback(call: CallbackQuery) -> None:
        group_id = int(call.data.split(":", 1)[1])
        response = group_service.set_group_notifications_by_id(
            call.from_user, group_id, muted=False
        )
        bot.edit_message_text(response, call.message.chat.id, call.message.message_id)
