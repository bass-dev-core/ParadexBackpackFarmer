import asyncio
from typing import Dict, Any
from loguru import logger
import random

from aiohttp import ClientSession, TCPConnector
from aiohttp_socks import ProxyConnector
from src.utils.proxy import Proxy
import json 

class RequestClient:
    def __init__(self, proxy: Proxy | None):
        self.session = None
        self.create_session(proxy)
        self.proxy = proxy

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    def create_session(self, proxy: Proxy | None):
        try:
            connector = ProxyConnector.from_url(proxy.proxy_url) if proxy.proxy_url else TCPConnector(verify_ssl=False)
            self.session = ClientSession(connector=connector)
        except Exception as ex:
            logger.error(f"Failed to create session with proxy. | Error: {ex}")
            raise RuntimeError("Failed to create a session and no proxies are available.")

    async def make_request(
            self,
            method: str = 'GET',
            url: str = None,
            headers: Dict[str, Any] = None,
            data: str = None,
            body: Dict[str, Any] = None,
            params: Dict[str, Any] = None,
            return_json: bool = True,
            desired_status_code: int = 200,
            max_attempts: int = 5,
            base_delay: int = 1,
            max_delay: int = 16,
            errors_whitelist: list = [],
            logger_prefix: str = ""
    ):
        if self.proxy:
            await self.proxy.change_ip()
        attempts = 0
        while True:
            try:
                async with self.session.request(
                        method=method, url=url, headers=headers, data=data, params=params, json=body
                ) as response:
                    status_code = response.status
                    text = await response.text()
                    if status_code != desired_status_code:
                        for error in errors_whitelist:
                            if error in text:
                                return {"status": False, "data": None, "error": f"Error: {status_code} {text}"}
                        else:
                            if attempts < max_attempts:
                                logger.error(f"{logger_prefix} {status_code} {text} {attempts+1}/{max_attempts}")
                                attempts += 1
                                wait_time = min(base_delay * (2 ** attempts), max_delay)
                                wait_time += random.uniform(0, 0.5)
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                raise Exception(f"{logger_prefix} {status_code} {text}")
                    else:
                        if return_json:
                            data = json.loads(text)
                        else:
                            data = text
                        return {"status": True, "data": data, "error": None}
                    
            except Exception as ex:
                if attempts < max_attempts:
                    logger.error(f"{logger_prefix} {ex} {attempts+1}/{max_attempts}")
                    await asyncio.sleep(base_delay * (2 ** attempts))
                    attempts += 1
                    continue
                else:
                    return {"status": False, "data": None, "error": ex}

    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None