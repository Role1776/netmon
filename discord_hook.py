import re
import json
import requests

from notifier import ChatAction

_MD_SUBS = (
    (re.compile(r"<pre>(.*?)</pre>", re.DOTALL), r"```\1```"),
    (re.compile(r"<b>(.*?)</b>", re.DOTALL), r"**\1**"),
    (re.compile(r"<code>(.*?)</code>", re.DOTALL), r"`\1`"),
    (re.compile(r"<[^>]+>"), ""),
)

# Discord's plain `content` field is hard-capped at 2000 characters by the
# platform itself — that can't be raised. Embed descriptions go up to 4096,
# so reports are sent as an embed instead of plain content to avoid cutting
# a real (non-trivial) report off mid-sentence.
_DISCORD_EMBED_DESCRIPTION_LIMIT = 4096

def _html_to_discord_md(text: str) -> str:
    for pattern, replacement in _MD_SUBS:
        text = pattern.sub(replacement, text)
    return text.strip()


def _safe_embed_description(text: str) -> str:
    if len(text) <= _DISCORD_EMBED_DESCRIPTION_LIMIT:
        return text
    # Only reached if a report is unusually long (e.g. a much bigger/
    # verbose model ignoring the character-budget instruction in the
    # prompt) — truncate visibly with an ellipsis rather than a silent
    # unexplained cutoff.
    return text[: _DISCORD_EMBED_DESCRIPTION_LIMIT - 1].rstrip() + "…"


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
        content = _safe_embed_description(_html_to_discord_md(message))
        embed = {"description": content}

        response = requests.post(self.webhook_url, json={"embeds": [embed]}, timeout=self.timeout)
        if response.status_code not in (200, 204):
            raise RuntimeError(f"Failed to send message: {response.text}")

        return response.text

    def send_photo(self, photo: bytes, caption: str = "", parse_mode: str = "HTML") -> str:
        content = _safe_embed_description(_html_to_discord_md(caption))
        embed = {
            "description": content,
            # Ties the attached file to this embed's image slot by
            # referencing its multipart filename via the attachment://
            # scheme, so the graph renders inside the embed rather than
            # as a separate bare attachment below it.
            "image": {"url": "attachment://graph.png"},
        }
        payload_json = json.dumps({"embeds": [embed]})

        files = {"files[0]": ("graph.png", photo, "image/png")}
        response = requests.post(
            self.webhook_url,
            data={"payload_json": payload_json},
            files=files,
            timeout=self.timeout,
        )
        if response.status_code not in (200, 204):
            raise RuntimeError(f"Failed to send photo: {response.text}")

        return response.text

    def send_chat_action(self, action: ChatAction = ChatAction.TYPING) -> str:
        # Discord webhooks have no typing-indicator endpoint — no-op.
        return ""
