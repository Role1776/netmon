from enum import StrEnum
from typing import Protocol


class ChatAction(StrEnum):
    TYPING = "typing"
    UPLOAD_PHOTO = "upload_photo"


class Notifier(Protocol):
    def send_message(self, message: str, parse_mode: str = "HTML") -> str: ...

    def send_photo(self, photo: bytes, caption: str = "", parse_mode: str = "HTML") -> str: ...

    def send_chat_action(self, action: ChatAction = ChatAction.TYPING) -> str: ...
