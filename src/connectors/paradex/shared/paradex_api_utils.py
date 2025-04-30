import math
import statistics
import time
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional
decimal_zero = Decimal(0)

def time_now_milli_secs() -> float:
    return time.time() * 1_000


def time_now_micro_secs() -> float:
    return time.time() * 1_000_000


class OrderType(str, Enum):
    Market = "MARKET"
    Limit = "LIMIT"
    StopLimit = "STOP_LIMIT"
    StopMarket = "STOP_MARKET"


class OrderSide(str, Enum):
    Buy = "BUY"
    Sell = "SELL"
    

    def opposite_side(self):
        if self == OrderSide.Buy:
            return OrderSide.Sell
        else:
            return OrderSide.Buy

    def sign(self) -> int:
        if self == OrderSide.Buy:
            return 1
        else:
            return -1

    def chain_side(self) -> str:
        if self == OrderSide.Buy:
            return "1"
        else:
            return "2"


def quantity_side(amount: Decimal) -> OrderSide:
    if amount >= 0.0:
        return OrderSide.Buy
    else:
        return OrderSide.Sell


def price_more_aggressive(price1: Decimal, price2: Decimal, side: OrderSide) -> bool:
    if side == OrderSide.Buy:
        return price1 > price2
    else:
        return price1 < price2


def sign(a) -> int:
    if a > 0.000001:
        return 1
    elif a < -0.000001:
        return -1
    else:
        return 0


def time_millis() -> int:
    return int(time.time_ns() / 1_000_000)


class OrderStatus(Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# rounding a price to the tick size
def round_to_tick(value, tick):
    return round(value / tick, 0) * tick


def round_to_tick_with_side(value, tick: Decimal, side: OrderSide) -> Decimal:
    if side == OrderSide.Buy:
        return math.floor(value / tick) * tick
    else:
        return math.ceil(value / tick) * tick


# capping price aggressiveness by most_aggressive_price
def cap_price(price: Decimal, most_aggressive_price: Decimal, side: OrderSide) -> Decimal:
    if side == OrderSide.Buy:
        if isinstance(most_aggressive_price, Decimal) and most_aggressive_price != Decimal('0'):
            return price.min(most_aggressive_price)
        else:
            return price
    else:
        if isinstance(most_aggressive_price, Decimal) and most_aggressive_price != Decimal('0'):
            return price.max(most_aggressive_price)
        else:
            return price


def add_price_offset(price: Decimal, offset: Decimal, side: OrderSide) -> Decimal:
    if not offset or price is None:
        return price
    else:
        return price + side.sign() * offset


def calc_price_offset(target_price: Decimal, price: Decimal, side: OrderSide) -> Decimal:
    """Calculates by how much price is more passive than target_price.
        Or how much to make price more aggressive to match target_price
    i.e. side = Buy , target_price = 100, price = 99, returns 1
    i.e. side = Buy , target_price = 100, price = 101, returns -1
         side = Sell, target_price = 100, price = 99, returns -1
    """
    return Decimal(side.sign() * (target_price - price))


class OrderAction(Enum):
    NAN = "NAN"
    Send = "SEND"
    SendCancel = "SEND_CANCEL"

class Order:
    def __init__(
        self,
        market: str,
        order_type: OrderType,
        order_side: OrderSide,
        size: Decimal,
        limit_price: Decimal = decimal_zero,
        client_id: str = "",
        signature_timestamp: Optional[int] = None,
        instruction: str = "GTC",
        reduce_only: bool = False,
        recv_window: Optional[int] = None,
        stp: Optional[
            str
        ] = None,  # Self Trade Prevention, EXPIRE_MAKER, EXPIRE_TAKER or EXPIRE_BOTH, default: EXPIRE_TAKER
        trigger_price: Optional[Decimal] = None,
        order_id: Optional[str] = None,
    ) -> None:
        ts = time_now_milli_secs()
        self.id = order_id
        self.account: str = ""
        self.status = OrderStatus.NEW
        self.limit_price = limit_price
        self.size = size
        self.market = market
        self.remaining = size
        self.order_type = order_type
        self.order_side = order_side
        self.client_id = client_id
        self.instruction = instruction
        self.reduce_only = reduce_only
        self.created_at = ts  # milliseconds
        self.cancel_reason = ""
        self.last_action = OrderAction.NAN
        self.last_action_time = 0
        self.cancel_attempts = 0
        self.signature = ""
        self.signature_timestamp = ts if signature_timestamp is None else signature_timestamp
        self.recv_window = recv_window
        self.stp = stp
        self.trigger_price = trigger_price

    def __repr__(self) -> str:
        ord_status = self.status.value
        if self.status == OrderStatus.CLOSED:
            ord_status += f"({self.cancel_reason})"
        msg = f"{self.market} {ord_status} {self.order_type.name} "
        msg += f"{self.order_side} {self.remaining}/{self.size}"
        msg += f"@{self.limit_price}" if self.is_limit_type() else ""
        msg += f"trigger@{self.trigger_price}" if self.trigger_price else ""
        msg += f"recv_window={self.recv_window}" if self.recv_window else ""
        msg += f";id={self.id}" if self.id else ""
        msg += f";client_id={self.client_id}" if self.client_id else ""
        msg += f";last_action:{self.last_action}" if self.last_action != OrderAction.NAN else ""
        msg += f";signed with:{self.signature}@{self.signature_timestamp}"
        return msg

    def __eq__(self, __o) -> bool:
        return self.id == __o.id

    def __hash__(self) -> int:
        return hash(self.id)

    def dump_to_dict(self) -> Dict[Any, Any]:
        order_dict: Dict[Any, Any] = {
            "market": self.market,
            "side": self.order_side.value,
            "size": str(self.size),
            "type": self.order_type.value,
            "client_id": self.client_id,
            "instruction": self.instruction,
            "signature": self.signature,
            "signature_timestamp": self.signature_timestamp,
            "recv_window": self.recv_window,
            "stp": self.stp,
        }
        if self.is_limit_type():
            order_dict["price"] = str(self.limit_price)
        if self.trigger_price:
            order_dict["trigger_price"] = str(self.trigger_price)
        if self.reduce_only:
            order_dict["flags"] = ["REDUCE_ONLY"]

        # For modify order
        if self.id:
            order_dict["id"] = self.id
        return order_dict

    def chain_price(self) -> str:
        if self.order_type == OrderType.Market:
            return "0"
        return str(int(self.limit_price.scaleb(8)))

    def chain_size(self) -> str:
        return str(int(self.size.scaleb(8)))

    def is_limit_type(self) -> bool:
        return self.order_type == OrderType.Limit or self.order_type == OrderType.StopLimit
    
def calc_order_age_stats(orders: list) -> dict:
    age_stats = {}
    if orders:
        now = time_millis()
        age_stats['count'] = len(orders)
        age_stats['mean_age'] = sum([(now - o.created_at) / 1_000 for o in orders]) / len(orders)
        age_stats['median_age'] = statistics.median([(now - o.created_at) / 1_000 for o in orders])
        age_stats['max_age'] = max([(now - o.created_at) / 1_000 for o in orders])
        age_stats['buy_size'] = sum([o.remaining for o in orders if o.order_side == OrderSide.Buy])
        age_stats['sell_size'] = sum(
            [o.remaining for o in orders if o.order_side == OrderSide.Sell]
        )
    return age_stats


class WSSubscription(Enum):
    ACCOUNT_SUMMARY = 1
    BALANCES = 2
    FILLS = 3
    FUNDING_INDEX = 4
    MARKETS_SUMMARY = 5
    ORDERS = 6
    ORDER_BOOK = 7
    POSITIONS = 8
    TRADES = 9
    TRADEBUSTS = 10
    TRANSACTIONS = 11


class ApiConfigInterface:
    def __init__(self):
        self.load_config()

    def load_config(self):
        pass


class DatastoreInterface:
    def __init__(self, account: str):
        pass


class ParadexApiInterface:
    @classmethod
    async def create(cls, datastore: DatastoreInterface, config: dict, loop):
        pass

    def __init__(
        self,
        datastore: DatastoreInterface,
        config: dict,
        loop,
    ):
        pass

    def init_subscription_channels(self, markets: list):
        pass

    async def create_tasks(self, order_creator_cb):
        pass

    def refresh_state(self, market: str):
        pass

    def get_time_now_milli_secs(self) -> float:
        pass

    async def cancel_order_async(self, order: Order):
        pass

    async def submit_order_async(self, order: Order):
        pass
