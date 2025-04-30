from src.utils.enums import OrderType


PARADEX_FEE_PERCENT = -0.005
BACKPACK_FEE_PERCENT = 0.02
NOTIFICATION_INTERVAL = 60 * 5

orderTypeMapping = {
    "limit": OrderType.LIMIT,
    "market": OrderType.MARKET
}

OPEN_INTEREST_SLEEP_INTERVAL = 60 * 1
RETRIES_MAX = 5