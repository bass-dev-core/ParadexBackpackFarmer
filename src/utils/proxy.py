from asyncio import sleep
import aiohttp
from loguru import logger

class Proxy:
    def __init__(self, ip: str = None, port: int = None, login: str = None, password: str = None, change_link: str = None, mobile: bool = False):
        self.ip = ip
        self.port = port
        self.login = login
        self.password = password
        self.mobile = mobile
        self.change_link = change_link

    def __str__(self):
        return f"{self.ip}:{self.port} {self.login}:{self.password} {self.change_link} {self.mobile}"
    
    def __repr__(self):
        return self.__str__()
    
    @property
    def proxy_url(self):
        if self.ip is None:
            return None
        return f"http://{self.login}:{self.password}@{self.ip}:{self.port}"


    @staticmethod
    def parse(proxy_str: str | None):
        if not bool(proxy_str):
            return Proxy()
        
        change_link = None

        if "|" in proxy_str:
            proxy_str, change_link = proxy_str.split("|")
            
        
        login_and_password, ip_and_port = proxy_str.split("@")
        login, password = login_and_password.split(":")
        ip, port = ip_and_port.split(":")

        mobile = False
        if change_link is not None:
            mobile = True


        return Proxy(ip, port, login, password, change_link=change_link, mobile=mobile)
    

    async def change_ip(self) -> None:
        if self.change_link is None:
            return
        
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    response = await session.get(self.change_link)
                    if response.status != 200:
                        logger.error(f'Failed to change ip')
                        continue
                    break

            except Exception as ex:
                logger.error(ex)
                await sleep(4)
                continue
    