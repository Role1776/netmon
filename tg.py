import requests

from notifier import ChatAction

# Telegram's Bot API hard-caps sendPhoto captions at 1024 characters — this
# is a real platform limit, not a design choice, and unlike sendMessage
# (4096 chars), it cannot be raised. If exceeded, Telegram rejects the
# request outright rather than truncating it server-side, so this is
# enforced client-side as a safety net in case the AI ever overshoots its
# instructed budget.
_TELEGRAM_CAPTION_LIMIT = 1024
_TELEGRAM_MESSAGE_LIMIT = 4096


def _safe_caption(text: str) -> str:
    if len(text) <= _TELEGRAM_CAPTION_LIMIT:
        return text
    return text[: _TELEGRAM_CAPTION_LIMIT - 1].rstrip() + "…"


def _safe_message(text: str) -> str:
    if len(text) <= _TELEGRAM_MESSAGE_LIMIT:
        return text
    return text[: _TELEGRAM_MESSAGE_LIMIT - 1].rstrip() + "…"


class Bot:
    def __init__(self, bot_token: str, chat_id: str, timeout: int):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    @classmethod
    def init(cls, bot_token: str, chat_id: str, timeout: int) -> "Bot":
        if bot_token.strip() == "" or chat_id.strip() == "":
            raise ValueError("Bot token and chat ID cannot be empty")

        return cls(bot_token, chat_id, timeout)

    def send_message(self, message: str, parse_mode: str = "HTML") -> str:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": _safe_message(message),
            "parse_mode": parse_mode
        }
        response = requests.post(url, data=payload, timeout=self.timeout)

        if response.status_code != 200:
            raise RuntimeError(f"Failed to send message: {response.text}")
        return response.text

    def send_photo(self, photo: bytes, caption: str = "", parse_mode: str = "HTML") -> str:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        payload = {
            "chat_id": self.chat_id,
            "caption": _safe_caption(caption),
            "parse_mode": parse_mode
        }
        files = {
            "photo": ("graph.png", photo, "image/png")
        }
        response = requests.post(url, data=payload, files=files, timeout=self.timeout)

        if response.status_code != 200:
            raise RuntimeError(f"Failed to send photo: {response.text}")
        return response.text

    def send_chat_action(self, action: ChatAction = ChatAction.TYPING) -> str:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendChatAction"
        payload = {
            "chat_id": self.chat_id,
            "action": action
        }
        response = requests.post(url, data=payload, timeout=self.timeout)

        if response.status_code != 200:
            raise RuntimeError(f"Failed to send chat action: {response.text}")
        return response.text