from enum import Enum
import requests

class ChatAction(str, Enum):
    TYPING = "typing"
    UPLOAD_PHOTO = "upload_photo"
    

class Bot:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @classmethod
    def init(cls, bot_token: str, chat_id: str) -> "Bot":
        if bot_token.strip() == "" or chat_id.strip() == "":
            raise ValueError("Bot token and chat ID cannot be empty")
        return cls(bot_token, chat_id)

    def send_message(self, message: str, parse_mode: str = "HTML") -> str:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode
        }
        response = requests.post(url, data=payload)

        if response.status_code != 200:
            raise RuntimeError(f"Failed to send message: {response.text}")
        return response.text

    def send_photo(self, photo: bytes, caption: str = "", parse_mode: str = "HTML") -> str:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        payload = {
            "chat_id": self.chat_id,
            "caption": caption,
            "parse_mode": parse_mode
        }
        files = {
            "photo": ("graph.png", photo, "image/png")
        }
        response = requests.post(url, data=payload, files=files)

        if response.status_code != 200:
            raise RuntimeError(f"Failed to send photo: {response.text}")
        return response.text
    
    def send_chat_action(self, action: ChatAction = ChatAction.TYPING) -> str:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendChatAction"
        payload = {
            "chat_id": self.chat_id,
            "action": action.value if hasattr(action, 'value') else action
        }
        response = requests.post(url, data=payload)

        if response.status_code != 200:
            raise RuntimeError(f"Failed to send chat action: {response.text}")
        return response.text