import asyncio
import aiohttp
from loguru import logger
from typing import Optional, Dict

class Tg:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token
        self.chat_id = chat_id
      

    async def send_message(self, message: str):
        if self.token is None or self.chat_id is None:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            params = {
                "chat_id": self.chat_id,
                "text": message
            }
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as response:
                    await response.json()
            pass
        except Exception as e:
            logger.error(f"error sending message to Telegram: {e}")