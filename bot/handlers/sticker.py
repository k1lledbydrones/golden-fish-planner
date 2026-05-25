from __future__ import annotations

import logging

from telebot import TeleBot
from telebot.types import Message

from bot.logging_config import setup_sticker_logging

TARGET_FILE_ID = (
    "CAACAgIAAxkBAAIEPmoS-ZU4vJAV6mV2AcYrDBftTp5vAAIXmQACGDKZS0JBbDHi2FwKOwQ"
)

sticker_log = logging.getLogger("stickers")


def register_sticker_handlers(bot: TeleBot) -> None:
    setup_sticker_logging()

    @bot.message_handler(content_types=["sticker"])
    def handle_sticker(message: Message) -> None:
        sticker_log.info(
            "",
            extra={
                "user_id": message.from_user.id,
                "chat_id": message.chat.id,
                "file_id": message.sticker.file_id,
            },
        )
        if message.sticker.file_id == TARGET_FILE_ID:
            bot.send_sticker(message.chat.id, TARGET_FILE_ID)
