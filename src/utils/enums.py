from enum import Enum

class Platform(str, Enum):
    paradex = "paradex"
    backpack = "backpack"

platformRow2platform = {k: k for k in Platform}

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"

class OrderCancelType(str, Enum):
    GTC = "gtc"
    IOC = "ioc"
    AOC = "aoc"
    POST_ONLY = "post_only"

class FunctionStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"

class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    PARTIALLY_FILLED = "partially_filled"

class CancelReason(str, Enum):
    NOT_ENOUGH_MARGIN = "not_enough_margin"
    REDUCE_ONLY_WILL_DECREASE = "reduce_only_will_decrease"
    REDUCE_ONLY_WILL_INCREASE = "reduce_only_will_increase"
    SELF_TRADE = "self_trade"
    USER_CANCEL = "user_cancel"
    POST_ONLY_WOULD_CROSS = "post_only_would_cross"
    ORDER_SIZE_BELOW_MIN = "order_size_below_min"

class FundingRegime(str, Enum):
    FULL = "full"
    ON = "on"
    OFF = "off"
