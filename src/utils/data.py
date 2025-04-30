from dataclasses import dataclass
from typing import List
from src.connectors.Connector import Connector
from src.utils.enums import  OrderSide, OrderType, OrderCancelType, Platform, OrderStatus, CancelReason
import decimal
import uuid
from src.utils.proxy import Proxy
from src.utils.enums import FunctionStatus

@dataclass
class Wallet:
    platform: str
    apiKey: str
    apiSecret: str
    privateKey: str
    proxy: Proxy
    connector: Connector
    uuid: str
    orderType: OrderType

    @classmethod
    def create(cls, yaml_data):
        return cls(
            platform=yaml_data['platform'],
            apiKey=yaml_data.get('apiKey', None),
            apiSecret=yaml_data.get('apiSecret', None),
            privateKey=yaml_data.get('privateKey', None),
            proxy=yaml_data.get('proxy', Proxy()),
            connector=yaml_data.get('connector', None),
            uuid = yaml_data.get('uuid', str(uuid.uuid4())),
            orderType = yaml_data.get('orderType', OrderType.LIMIT)
        )
    
@dataclass
class Market:
    symbol: str
    baseCurrency: str
    sizeTick: float
    priceTick: float
    minUSDCSize: float = None
    minTokenSize: float = None

@dataclass
class Order:
    id: str
    currency: str
    symbol: str
    size: decimal.Decimal
    price: decimal.Decimal
    type: OrderType
    side: OrderSide
    cancelType: OrderCancelType
    createdTs: int
    reduceOnly: bool
    status: OrderStatus
    cancelReason: CancelReason
    clientOrderId: str
    
@dataclass
class Position:
    size: decimal.Decimal
    side: OrderSide
    symbol: str
    entryPrice: decimal.Decimal
    createdTs: int
    maxLifeTime: int
    currency: str


@dataclass
class OrderBookOrder:
    price: float
    size: float 

@dataclass
class OrderBook:
    platform: Platform
    token: str
    asks: list[OrderBookOrder]
    bids: list[OrderBookOrder]

    def get_market_price(self, side: OrderSide):
        if side == OrderSide.BUY:
            return (float(self.bids[0].price) + float(self.bids[-1].price)) / 2
        else:
            return (float(self.asks[0].price) + float(self.asks[-1].price)) / 2
    
    @property
    def market_price_bid(self):
        if len(self.bids) == 0:
            return 0
        median = len(self.bids) // 2
        return float(self.bids[median].price)
    
    @property
    def market_price_ask(self):
        if len(self.asks) == 0:
            return 0
        median = len(self.asks) // 2
        return float(self.asks[median].price)
    
    @property
    def best_bid(self):
        if len(self.bids) == 0:
            return 0
        assert len(self.bids) == 0 or float(self.bids[0].price) >= float(self.bids[-1].price), f"{self.platform} {self.token} {self.bids[0].price} {self.bids[-1].price}"
        return float(self.bids[0].price)
    
    @property
    def best_ask(self):
        if len(self.asks) == 0:
            return 0
        assert len(self.asks) == 0 or float(self.asks[0].price) <= float(self.asks[-1].price), f"{self.platform} {self.token} {self.asks[0].price} {self.asks[-1].price}"
        return float(self.asks[0].price)
    
    def sort(self, side: OrderSide):
        if len(self.bids) == 0:
            return
        if len(self.asks) == 0:
            return
        if side == OrderSide.BUY:
            self.bids.sort(key=lambda x: x.price, reverse=True)
        else:
            self.asks.sort(key=lambda x: x.price)

    @property
    def empty(self):
        return len(self.bids) == 0 or len(self.asks) == 0
    
    

@dataclass
class Balance:
    currency: str 
    size: decimal.Decimal
    
@dataclass 
class WalletStats:
    uuid: str
    openPositions: List[str]
    volume_usdt: float
    balance: float
    platform: str
    
    def __str__(self):
        return f"{self.uuid} {self.platform}\nBALANCE: {round(self.balance, 2)}$\nVOLUME: {round(self.volume_usdt, 2)}$\nOPEN POSITIONS: {self.openPositions}"


@dataclass
class PositionStatus:
    symbol: str
    size: str
    side: str 

@dataclass
class FunctionOutput:
    status: FunctionStatus
    result: any 
    error: str 