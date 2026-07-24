import re
from enum import Enum
import requests


class ChatAction(str, Enum):
    TYPING = "typing"
    UPLOAD_PHOTO = "upload_photo"


def _html_to_discord_md(text: str) -> str:
    text = re.sub(r"<pre>(.*?)</pre>", r"```\1```", text, flags=re.DOTALL)
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.DOTALL)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


class Bot:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    @classmethod
    def init(cls, webhook_url: str) -> "Bot":
        if webhook_url.strip() == "":
            raise ValueError("Discord webhook URL cannot be empty")
        return cls(webhook_url)

    def send_message(self, message: str, parse_mode: str = "HTML") -> str:
        content = _html_to_discord_md(message)[:1990]
        response = requests.post(self.webhook_url, json={"content": content})
        if response.status_code not in (200, 204):
            raise RuntimeError(f"Failed to send message: {response.text}")
        return response.text

    def send_photo(self, photo: bytes, caption: str = "", parse_mode: str = "HTML") -> str:
        content = _html_to_discord_md(caption)[:1990]
        files = {"file": ("graph.png", photo, "image/png")}
        response = requests.post(self.webhook_url, data={"content": content}, files=files)
        if response.status_code not in (200, 204):
            raise RuntimeError(f"Failed to send photo: {response.text}")
        return response.text

    def send_chat_action(self, action: "ChatAction" = ChatAction.TYPING) -> str:
        # Discord webhooks have no typing-indicator endpoint — no-op.
        return ""
