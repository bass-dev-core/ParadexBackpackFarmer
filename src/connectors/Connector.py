from typing import Callable
from abc import ABC, abstractmethod
from src.utils.enums import FunctionStatus, Platform
from dataclasses import dataclass

@dataclass
class FunctionOutput:
    status: FunctionStatus
    result: any 
    error: str 

class Connector(ABC):
    def __init__(self, **kwargs):
        self.available_markets = []
        self.positions = {}
        self.balances = {}
        self.open_orders = []
        self.token2size_digits = {}
        self.token2price_digits = {}
        self.token2market = {}
        self.platform = kwargs.get("platform", None)
        self.uuid = kwargs.get("uuid", None)
        self.client = None

    @staticmethod
    @abstractmethod
    def get_available_markets() -> FunctionOutput:
        pass 

    @abstractmethod
    async def create_order(self, order_side, size, market, price, instruction, orderType, reduce_only) -> FunctionOutput:
        pass 

    @abstractmethod
    async def calculate_max_size(self, symbol, side, balance, price) -> FunctionOutput:
        pass

    @abstractmethod
    async def get_balances(self) -> FunctionOutput:
        pass

    @abstractmethod
    async def get_orders(self) -> FunctionOutput:
        pass

    @abstractmethod
    async def close_order(self, order_id, symbol) -> FunctionOutput:
        pass

    @abstractmethod
    async def get_open_positions(self) -> FunctionOutput:
        pass

    @abstractmethod
    async def get_depth(self, symbol) -> FunctionOutput:
        pass

    @abstractmethod
    async def open_position(self, market, side, size, order_type, close_position):
        pass

    @abstractmethod
    async def get_funding_rate(self, market) -> FunctionOutput:
        pass

    @abstractmethod
    async def get_mark_price(self, market) -> FunctionOutput:
        pass

    async def get_balance(self) -> FunctionOutput:
        pass


    
    
    
    
    
    

