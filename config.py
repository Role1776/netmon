import os
import argparse
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

class Config:
    def __init__(self, ai_api_key: str, db_path: str, model: str, base_url: str, tg_bot_token: str, tg_chat_id: str):
        self.ai_api_key: str = ai_api_key
        self.db_path: str = db_path
        self.model: str = model
        self.base_url: str = base_url
        self.tg_bot_token: str = tg_bot_token
        self.tg_chat_id: str = tg_chat_id

    
    @staticmethod
    def _parse_args():
        parser = argparse.ArgumentParser(description="App configuration")
        parser.add_argument(
            "--env",
            type=str,
            default=".env",
            help="Path to the .env file (default: .env)"
        )
        return parser.parse_args()    

    @classmethod
    def init(cls):
        args = cls._parse_args()
        load_dotenv(args.env)

        ai_key = os.getenv("AI_API_KEY", "")
        db_path = os.getenv("DB_PATH", "")
        model = os.getenv("AI_MODEL", "")
        base_url = os.getenv("AI_BASE_URL", "")
        tg_bot_token = os.getenv("TG_BOT_TOKEN", "")
        tg_chat_id = os.getenv("TG_CHAT_ID", "")

        if ai_key.strip() == "":
            raise RuntimeError("AI_API_KEY not found or empty in environment")
        if db_path.strip() == "":
            raise RuntimeError("DB_PATH not found or empty in environment")
        if model.strip() == "":
            raise RuntimeError("MODEL not found or empty in environment")
        if base_url.strip() == "":
            raise RuntimeError("BASE_URL not found or empty in environment")
        if tg_bot_token.strip() == "":
            raise RuntimeError("TG_BOT_TOKEN not found or empty in environment")
        if tg_chat_id.strip() == "":
            raise RuntimeError("TG_CHAT_ID not found or empty in environment")
        
        return cls(ai_key, db_path, model, base_url, tg_bot_token, tg_chat_id)