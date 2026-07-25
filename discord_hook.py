import re
import requests

from notifier import ChatAction

_MD_SUBS = (
    (re.compile(r"<pre>(.*?)</pre>", re.DOTALL), r"```\1```"),
    (re.compile(r"<b>(.*?)</b>", re.DOTALL), r"**\1**"),
    (re.compile(r"<code>(.*?)</code>", re.DOTALL), r"`\1`"),
    (re.compile(r"<[^>]+>"), ""),
)

def _html_to_discord_md(text: str) -> str:
    for pattern, replacement in _MD_SUBS:
        text = pattern.sub(replacement, text)
    return text.strip()


class Bot:
    def __init__(self, webhook_url: str, timeout: int):
        self.webhook_url = webhook_url
        self.timeout = timeout

    @classmethod
    def init(cls, webhook_url: str, timeout: int) -> "Bot":
        if webhook_url.strip() == "":
            raise ValueError("Discord webhook URL cannot be empty")

        return cls(webhook_url, timeout)

    def send_message(self, message: str, parse_mode: str = "HTML") -> str:
        content = _html_to_discord_md(message)[:1990]

        response = requests.post(self.webhook_url, json={"content": content}, timeout=self.timeout)
        if response.status_code not in (200, 204):
            raise RuntimeError(f"Failed to send message: {response.text}")
        
        return response.text

    def send_photo(self, photo: bytes, caption: str = "", parse_mode: str = "HTML") -> str:
        content = _html_to_discord_md(caption)[:1990]

        files = {"file": ("graph.png", photo, "image/png")}
        response = requests.post(self.webhook_url, data={"content": content}, files=files, timeout=self.timeout)
        if response.status_code not in (200, 204):
            raise RuntimeError(f"Failed to send photo: {response.text}")
        
        return response.text

    def send_chat_action(self, action: ChatAction = ChatAction.TYPING) -> str:
        # Discord webhooks have no typing-indicator endpoint — no-op.
        return ""
