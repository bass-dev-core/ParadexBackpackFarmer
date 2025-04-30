import asyncio
import copy
import decimal
import json
import time
from typing import Dict, Optional
import uuid
from loguru import logger
from typing_extensions import Callable
import websocket
from src.connectors.paradex.shared.api_client_utils import DecimalEncoder
from src.connectors.Connector import Connector
from src.utils.data import Market, OrderBook, OrderBookOrder, Position, Order, Balance, FunctionOutput
from src.utils.enums import Platform, OrderType, OrderCancelType, OrderSide, FunctionStatus, OrderStatus, CancelReason
import aiohttp
from src.connectors.paradex.utils import get_l1_eth_account
from src.connectors.paradex.shared.api_client import check_token_expiry, create_rest_headers, get_paradex_config
from src.connectors.paradex.shared.api_client import post_order_payload, ApiConfig
from src.connectors.paradex.onboarding import generate_paradex_account
from src.connectors.paradex.onboarding import get_jwt_token
from src.connectors.paradex.shared.paradex_api_utils import Order as ParadexOrder, OrderSide as ParadexOrderSide, OrderType as ParadexOrderType
from src.connectors.paradex.shared.api_client import post_order_payload, sign_order
from src.utils.utils import handle_errors_async, handle_errors_sync, send_request, truncate_decimal
from src.utils.constants import PARADEX_FEE_PERCENT
from src.utils.proxy import Proxy
from src.utils.client import RequestClient
from starknet_py.common import int_from_bytes
from src.connectors.paradex.utils import (
    build_auth_message,
    build_onboarding_message,
    generate_paradex_account,
    get_account,
    get_l1_eth_account,
)

paradex_http_url = "https://api.prod.paradex.trade/v1"
paradexType2OrderType = {
    "LIMIT": OrderType.LIMIT,
    "MARKET": OrderType.MARKET,
    "STOP_LOSS": OrderType.STOP_LOSS,
    "TAKE_PROFIT": OrderType.TAKE_PROFIT,
    "STOP_MARKET": OrderType.TAKE_PROFIT,
}

paradexInstruction2OrderCancelType = {
    "IOC": OrderCancelType.IOC,
    "GTC": OrderCancelType.GTC,
    "AOC": OrderCancelType.AOC,
    "POST_ONLY": OrderCancelType.POST_ONLY,
}

OrderSide2ParadexOrderSide = {
    OrderSide.BUY: ParadexOrderSide.Buy,
    OrderSide.SELL: ParadexOrderSide.Sell
}

OrderCancelType2ParadexOrderCancelType = {
    OrderCancelType.IOC: "IOC",
    OrderCancelType.GTC: "GTC",
    OrderCancelType.AOC: "POST_ONLY",
    OrderCancelType.POST_ONLY: "POST_ONLY"
}

paradex_order_status_mapping = {
    "OPEN": OrderStatus.PENDING,
    "CLOSED": OrderStatus.FILLED,
    "CANCELLED": OrderStatus.CANCELLED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.EXPIRED,
    "NEW": OrderStatus.PENDING,
}

paradex_cancel_reason_mapping = {
    "NOT_ENOUGH_MARGIN": CancelReason.NOT_ENOUGH_MARGIN,
    "REDUCE_ONLY_WILL_INCREASE": CancelReason.REDUCE_ONLY_WILL_INCREASE,
    "REDUCE_ONLY_WILL_DECREASE": CancelReason.REDUCE_ONLY_WILL_DECREASE,
    "SELF_TRADE": CancelReason.SELF_TRADE,
    "USER_CANCELED": CancelReason.USER_CANCEL,
    "POST_ONLY_WOULD_CROSS": CancelReason.POST_ONLY_WOULD_CROSS,
    "ORDER_SIZE_BELOW_MIN": CancelReason.ORDER_SIZE_BELOW_MIN
}
class Paradex(Connector):
    def __init__(self, eth_account, paradex_config: ApiConfig, paradex_account_address: str, paradex_account_private_key_hex: str, uuid: str, client: RequestClient = None):
        self.eth_account = eth_account
        self.available_markets = []
        self.last_refresh = None
        self.paradex_jwt = None
        self.paradex_config = paradex_config
        self.paradex_account_address = paradex_account_address
        self.paradex_account_private_key_hex = paradex_account_private_key_hex
        self.config = ApiConfig()
        self.config.paradex_config = paradex_config
        self.config.paradex_account = paradex_account_address
        self.config.paradex_account_private_key = paradex_account_private_key_hex
        self.config.paradex_http_url = paradex_http_url
        self.token2size_digits = {}
        self.token2price_digits = {}
        self.token2market = {}
        self.platform = Platform.paradex
        self.uuid = uuid
        self.client = client
       
    
    @classmethod 
    async def create(cls, privateKey: str, uuid: str, **kwargs):
        proxy = kwargs.get("proxy", Proxy())
        _, eth_account = get_l1_eth_account(privateKey)
        # paradex_config = await get_paradex_config(paradex_http_url, proxy)
        client = RequestClient(proxy=proxy)
        paradex_config = await client.make_request(url=paradex_http_url + "/system/config", method="GET", headers={}, desired_status_code=200, return_json=True, logger_prefix=f"{uuid} {Platform.paradex} get_paradex_config")
        paradex_config = paradex_config['data']
        if not paradex_config:
            raise Exception("Failed to get Paradex config")
        
        paradex_account_address, paradex_account_private_key_hex = generate_paradex_account(
            paradex_config, eth_account.key.hex()
        )

        
        connector = cls(eth_account, paradex_config, paradex_account_address, paradex_account_private_key_hex, uuid, client)
        await connector.refresh_token()
        await connector.get_available_markets()

        if not proxy:
            logger.debug(f"CREATED: {connector.platform} {connector.paradex_account_address[:4]} NO PROXY")
        else:
            logger.debug(f"CREATED: {connector.platform} {connector.paradex_account_address[:4]} PROXY: {proxy.ip}:{proxy.port}")
        return connector
    
    @handle_errors_async(logger_prefix="PARADEX REFRESH TOKEN")
    async def refresh_token(self):
        if self.last_refresh is None or time.time() - self.last_refresh > 60 * 3:
            logger.debug("refreshing token")
            self.paradex_jwt = await self.get_jwt_token(self.paradex_config, paradex_http_url, self.paradex_account_address, self.paradex_account_private_key_hex)
            self.last_refresh = time.time()


    # @handle_errors_async(logger_prefix="PARADEX GET OPEN POSITIONS")
    async def get_open_positions(self) -> FunctionOutput:
        await self.refresh_token()
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.paradex_jwt}'
        }
        res = await self.client.make_request(url=paradex_http_url + "/positions", method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_open_positions")
        status = res['status']
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get open positions")
        res = res['results']
        res = [i for i in res if i['status'] != 'CLOSED']    
        out = []
        for i in res:
            size = decimal.Decimal(truncate_decimal(abs(float(i['size'])), self.token2size_digits[i['market'].split("-")[0]]))
            myothercontext = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_DOWN)
            size = size.quantize(decimal.Decimal('0.1') ** self.token2size_digits[i['market'].split("-")[0]], context=myothercontext)

            price = decimal.Decimal(float(i['average_entry_price']))
            myothercontext = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_DOWN)
            price = price.quantize(decimal.Decimal('0.1') ** self.token2price_digits[i['market'].split("-")[0]], context=myothercontext)

            out.append(
                Position(
                    size=size,
                    entryPrice=price,
                    currency=i['market'].split("-")[0],
                    createdTs=-1,
                    side=OrderSide.BUY if i['side'] == 'LONG' else OrderSide.SELL,
                    symbol=i['market'],
                    maxLifeTime=-1,
                )
            )
        out = {item.symbol: item for item in out}
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=out, error=None)
       
    
    @handle_errors_async(logger_prefix="PARADEX GET OPEN ORDERS")
    async def get_orders(self) -> FunctionOutput:
        await self.refresh_token()
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.paradex_jwt}'
        }
        res = await self.client.make_request(url=paradex_http_url + "/orders-history", method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_open_orders")
        status = res['status']
        res = res['data']

        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get open orders")
        res = res['results']
        orders = []
        for i in res:
            type_ = i['type']
            cancel_reason = i.get("cancel_reason", "")
            status = i['status']
            flags = i.get("flags", [])
            reduce_only = "REDUCE_ONLY" in flags

            order = Order(
                id=i['id'],
                currency=i['market'].split("-")[0],
                symbol=i['market'],
                size=decimal.Decimal(abs(float(i['size']))),
                price=decimal.Decimal(float(i['price'])),
                type=paradexType2OrderType[type_],
                side=OrderSide.BUY if i['side'] == 'BUY' else OrderSide.SELL,
                cancelType=paradexInstruction2OrderCancelType[i['instruction']],
                createdTs=i['published_at'],
                reduceOnly=reduce_only,
                status=paradex_order_status_mapping[status],
                cancelReason=paradex_cancel_reason_mapping.get(cancel_reason, ""),
                clientOrderId=i.get('client_id', "")
            )
            orders.append(order)
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=orders, error=None)
    
    @handle_errors_async(logger_prefix="PARADEX CLOSE ORDER")
    async def close_order(self, order_id: str, symbol: str = None):
        await self.refresh_token()
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.paradex_jwt}'
        }
        res = await self.client.make_request(url=paradex_http_url + f"/orders/{order_id}", method="DELETE", headers=headers, desired_status_code=204, return_json=False, errors_whitelist=["ORDER_IS_CLOSED"], logger_prefix=f"{self.uuid} {self.platform} close_order")
        status = res['status']
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=False, error="Failed to close order")
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=not res, error=None)
            
        
    @handle_errors_async(logger_prefix="PARADEX GET BALANCES")
    async def get_balances(self) -> FunctionOutput:     
        await self.refresh_token()
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.paradex_jwt}'
        }

        res = await self.client.make_request(url=paradex_http_url + "/balance", method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_balances")
        status = res['status']
        res = res['data']
        
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get balances")
        res = res['results']
        res = [Balance(i['token'], decimal.Decimal(i['size'])) for i in res]
        res = {i.currency: i.size for i in res}
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=res, error=None)
    
    @handle_errors_async(logger_prefix="PARADEX GET BALANCE")
    async def get_balance(self) -> FunctionOutput:
        balances = await self.get_balances()
        if balances.status == FunctionStatus.SUCCESS:
            return FunctionOutput(status=FunctionStatus.SUCCESS, result=balances.result.get("USDC", decimal.Decimal(0)), error=None)
        return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=balances.error)
    
    @handle_errors_async(logger_prefix="PARADEX CREATE ORDER")
    async def create_order(self, order_side: OrderSide, size: decimal.Decimal, market: Market, price: decimal.Decimal, instruction: OrderCancelType, orderType: OrderType = OrderType.LIMIT, reduce_only: bool = False):
        await self.refresh_token()
        client_id = str(uuid.uuid4())
        
        order = ParadexOrder(
            market=market.symbol,
            order_type=ParadexOrderType.Limit if orderType == OrderType.LIMIT else ParadexOrderType.Market,
            order_side=OrderSide2ParadexOrderSide[order_side],
            size=size,
            limit_price=price,
            client_id=client_id,
            signature_timestamp=time.time_ns() // 1_000_000,
            instruction=OrderCancelType2ParadexOrderCancelType[instruction],
            reduce_only=reduce_only
        )
        sig = sign_order(self.config, order)
        order.signature = sig

        method: str = "POST"
        path: str = "/orders"
        _payload: str = json.dumps(order.dump_to_dict(), cls=DecimalEncoder)
        headers: Dict = await create_rest_headers(
            paradex_jwt=self.paradex_jwt,
            paradex_maker_secret_key="",
            method=method,
            path=path,
            body=_payload,
        )
        res = await self.client.make_request(url=paradex_http_url + path, method="POST", body=order.dump_to_dict(), headers=headers, desired_status_code=201, return_json=True, logger_prefix=f"{self.uuid} {self.platform} create_order")
        status = res['status']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to create order")
        res = res['data']
        order_status = res['status']
        cancel_reason = res.get("cancel_reason", "")
        

        order = Order(
            id=res['id'],
            currency=market.baseCurrency,
            symbol=market.symbol,
            size=size,
            price=price,
            type=orderType,
            side=order_side,
            cancelType=instruction,
            createdTs=res['published_at'],
            reduceOnly=reduce_only,
            status=paradex_order_status_mapping[order_status],
            cancelReason=paradex_cancel_reason_mapping.get(cancel_reason, ""),
            clientOrderId=client_id
        )
        if order.cancelReason != "":
            return FunctionOutput(status=FunctionStatus.ERROR, result=order, error=order.cancelReason)
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=order, error=None)
    
    @handle_errors_async(logger_prefix="PARADEX MODIFY ORDER")
    async def modify_order(self, client_id: str, order_id: str, order_side: OrderSide, size: decimal.Decimal, market: Market, price: decimal.Decimal, instruction: OrderCancelType, orderType: OrderType = OrderType.LIMIT, reduce_only: bool = False):
        await self.refresh_token()
        order = ParadexOrder(
            market=market.symbol,
            order_type=ParadexOrderType.Limit if orderType == OrderType.LIMIT else ParadexOrderType.Market,
            order_side=OrderSide2ParadexOrderSide[order_side],
            size=size,
            order_id=order_id,
            limit_price=price,
            client_id=client_id,
            signature_timestamp=time.time_ns() // 1_000_000,
            instruction=OrderCancelType2ParadexOrderCancelType[instruction],
            reduce_only=reduce_only
        )
        sig = sign_order(self.config, order)
        order.signature = sig

        method: str = "PUT"
        path: str = f"/orders/{order_id}"
        _payload: str = json.dumps(order.dump_to_dict(), cls=DecimalEncoder)
        headers: Dict = await create_rest_headers(
            paradex_jwt=self.paradex_jwt,
            paradex_maker_secret_key="",
            method=method,
            path=path,
            body=_payload,
        )
        res = await self.client.make_request(url=paradex_http_url + path, method=method, body=order.dump_to_dict(), headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} modify_order", errors_whitelist=["order is not open", "no order parameters changed"])
        status = res['status']
        error = res['error']
        if error is not None and ("no order parameters changed" in error or "order is not open" in error):
            return FunctionOutput(status=FunctionStatus.SUCCESS, result=None, error=None)
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to modify order")
        res = res['data']
        order_status = res['status']
    
        order = Order(
            id=res['id'],
            currency=market.baseCurrency,
            symbol=market.symbol,
            size=size,
            price=price,
            type=orderType,
            side=order_side,
            cancelType=instruction,
            createdTs=res['published_at'],
            reduceOnly=reduce_only,
            status=paradex_order_status_mapping[order_status],
            cancelReason=paradex_cancel_reason_mapping.get("", ""),
            clientOrderId=client_id
        )
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=order, error=None)

    @handle_errors_async(logger_prefix="PARADEX GET AVAILABLE MARKETS")
    async def get_available_markets(self) -> FunctionOutput:
        url = f"{paradex_http_url}/markets"
        headers = {'Accept': 'application/json'}
        res = await self.client.make_request(url=url, method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_available_markets")
        status = res['status']

        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get available markets")
        res = res['results']
        if not res:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get available markets")
        
        res = [Market(symbol=i['symbol'], baseCurrency=i['base_currency'], sizeTick=len(i['order_size_increment'].replace(".", ""))-1, priceTick=len(i['price_tick_size'].replace(".", ""))-1, minUSDCSize=i['min_notional']) for i in res]
        res = [i for i in res if i.symbol.endswith("PERP")]
        self.available_markets = res
        self.token2size_digits = {i.baseCurrency: i.sizeTick for i in res}
        self.token2price_digits = {i.baseCurrency: i.priceTick for i in res}
        self.token2market = {i.baseCurrency: i for i in res}
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=res, error=None)

    def calculate_fee(self, size: decimal.Decimal, price: decimal.Decimal) -> decimal.Decimal:
        return size * price * PARADEX_FEE_PERCENT / 100

    @handle_errors_async(logger_prefix="PARADEX GET DEPTH")
    async def get_depth(self, symbol: str) -> FunctionOutput:
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.paradex_jwt}'
        }
        res = await self.client.make_request(url=paradex_http_url + f"/orderbook/{symbol}", method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_depth")
        status = res['status']
     
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get depth")
        bids = []
        asks = []
        for a in res['asks']:
            asks.append(OrderBookOrder(a[0], a[1]))
        for b in res['bids']:
            bids.append(OrderBookOrder(b[0], b[1]))
        orderbook = OrderBook(Platform.paradex, symbol.split("-")[0], asks, bids)
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=orderbook, error=None)
    

    async def get_jwt_token(self, paradex_config: Dict, paradex_http_url: str, account_address: str, private_key: str
    ) -> str:
        token = ""

        chain_id = int_from_bytes(paradex_config["starknet_chain_id"].encode())
        account = get_account(account_address, private_key, paradex_config)

        now = int(time.time())
        expiry = now + 24 * 60 * 60
        message = build_auth_message(chain_id, now, expiry)
        sig = account.sign_message(message)

        headers: Dict = {
            "PARADEX-STARKNET-ACCOUNT": account_address,
            "PARADEX-STARKNET-SIGNATURE": f'["{sig[0]}","{sig[1]}"]',
            "PARADEX-TIMESTAMP": str(now),
            "PARADEX-SIGNATURE-EXPIRATION": str(expiry),
        }

        url = paradex_http_url + '/auth'
        res = await self.client.make_request(url=url, method="POST", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_jwt_token")
        status = res['status']
        res = res['data']
        if not status:
            raise Exception("Failed to get JWT token")
        token = res['jwt_token']
        return token
    
    @handle_errors_async(error_value=decimal.Decimal(0), logger_prefix="PARADEX CALCULATE MAX SIZE")
    async def calculate_max_size(self, market: Market, side: OrderSide, balance: decimal.Decimal, price: decimal.Decimal):
        await self.refresh_token()
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.paradex_jwt}'
        }
        res = await self.client.make_request(url=paradex_http_url + f"/account/margin?market={market.symbol}", method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_available_leverage")
        status = res['status']
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=decimal.Decimal(0), error="Failed to get available leverage")
        
        res = res['configs'][0]['leverage']
        max_size = decimal.Decimal(balance) * decimal.Decimal(res)
        max_size = max_size / price

        return FunctionOutput(status=FunctionStatus.SUCCESS, result=max_size, error=None)
    
    @handle_errors_async(logger_prefix="PARADEX OPEN POSITION")
    async def open_position(self, market: Market, side: OrderSide, size: decimal.Decimal, order_type: OrderType, close_position: bool) -> FunctionOutput:
        size = decimal.Decimal(truncate_decimal(float(size), market.sizeTick))
        myothercontext = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_DOWN)
        size = size.quantize(decimal.Decimal('0.1') ** market.sizeTick, context=myothercontext)
        start_time = time.time()

        if order_type == OrderType.MARKET:
            price = decimal.Decimal(0)
            position = await self.create_order(side, size, market, price, OrderCancelType.GTC, OrderType.MARKET, reduce_only=close_position)
            
            if position.status == FunctionStatus.ERROR:
                return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=position.error)
            
            result = position.result
            if result.status == OrderStatus.FILLED:
                return FunctionOutput(status=FunctionStatus.SUCCESS, result=result, error=None)
            elif result.status == OrderStatus.PENDING:
                orders = await self.get_orders()
                if orders.status == FunctionStatus.ERROR:
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=orders.error)
                orders = orders.result
                order_id = result.id
                position = [i for i in orders if str(i.id) == str(order_id)][0]
                
                if position.status == OrderStatus.FILLED:
                    return FunctionOutput(status=FunctionStatus.SUCCESS, result=position, error=None)
                else:
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=position.error)
            else:
                return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=position.error)
        else:
            order_id = None 
            order_price_old = None
            while True:
                step = 10 ** (-market.priceTick)
                if side == OrderSide.BUY:
                    orders = (await self.get_depth(market.symbol)).result.bids

                    depth = min(5, len(orders) - 1)

                    for i in range(0, depth):
                        price_1, _ = float(orders[i].price), float(orders[i].size)
                        price_2, _ = float(orders[i + 1].price), float(orders[i + 1].size)

                        step_gap = (price_1 - price_2) / step

                        if step_gap >= 0:
                            order_price = decimal.Decimal(
                                min(price_2 + step, float(orders[0].price) - step))
                            break 
                    else:
                        order_price = min(float(orders[0].price) + step, float(orders[0].price) - step)
                else:
                    orders = (await self.get_depth(market.symbol)).result.asks

                    depth = min(5, len(orders) - 1)

                    for i in range(0, depth):
                        price_1, _ = float(orders[i].price), float(orders[i].size)
                        price_2, _ = float(orders[i + 1].price), float(orders[i + 1].size)

                        step_gap = (price_2 - price_1) / step

                        if step_gap >= 0:
                            order_price = decimal.Decimal(
                                max(price_2 - step, float(orders[0].price) + step))
                            break
                        else:
                            order_price = max(float(orders[0].price) - step, float(orders[0].price) + step)
                
                order_price = decimal.Decimal(truncate_decimal(float(order_price), market.priceTick))
                myothercontext = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_DOWN)
                order_price = order_price.quantize(decimal.Decimal('0.1') ** market.priceTick, context=myothercontext)
                
                if order_id is None:
                    logger.debug(f"Creating order side: {side} size: {size} symbol: {market.symbol} price: {order_price} cancel_type: {OrderCancelType.GTC} order_type: {OrderType.LIMIT} reduce_only={close_position}")
                    order = await self.create_order(side, size, market, order_price, OrderCancelType.POST_ONLY, OrderType.LIMIT, reduce_only=close_position)
                    if order.status == FunctionStatus.ERROR:
                        return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=order.error)
                
                    order = order.result
                    order_id = order.id
                    order_price_old = order_price 
                else:
                    if order_price_old != order_price:
                        logger.debug(f"Modifying order side: {side} size: {size} symbol: {market.symbol} price: {order_price} cancel_type: {OrderCancelType.GTC} order_type: {OrderType.LIMIT} reduce_only={close_position}")
                        order = await self.modify_order(order_id, order_id, side, size, market, order_price, OrderCancelType.GTC, OrderType.LIMIT, reduce_only=close_position)
                        if order.status == FunctionStatus.ERROR:
                            if "ORDER_IS_NOT_OPEN" in order.error:
                                return FunctionOutput(status=FunctionStatus.SUCCESS, result=None, error=order.error)
                            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=order.error)
                        order_price_old = order_price 
                    
                orders = await self.get_orders()
                if orders.status == FunctionStatus.ERROR:
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=orders.error)
                orders = orders.result
                position = [i for i in orders if i.id == order_id][0]
                
                if position.cancelReason == CancelReason.NOT_ENOUGH_MARGIN:
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=position.cancelReason)
                
                if position.cancelReason == CancelReason.POST_ONLY_WOULD_CROSS:
                    order_id = None 
                    
                    continue 

                if position.cancelReason == CancelReason.ORDER_SIZE_BELOW_MIN:
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=position.cancelReason)
                
                if position.cancelReason != "":
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=position.cancelReason)
                
                if position.status == OrderStatus.FILLED:
                    return FunctionOutput(status=FunctionStatus.SUCCESS, result=position, error=None)
                
                if position.status == OrderStatus.REJECTED:
                    continue 

                if time.time() - start_time > 10 * 60:
                    await self.close_order(order_id, market.symbol)
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to open position. Is the market liquid?")

    @handle_errors_async(logger_prefix="PARADEX GET FUNDING RATE")
    async def get_funding_rate(self, market: Market):
        url = f"https://api.prod.paradex.trade/v1/markets/summary?market={market.symbol}"
        headers = {'Accept': 'application/json'}
        res = await self.client.make_request(url=url, method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_mark_price")
        status = res['status']
        res = res['data']

        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get mark price")
        results = res['results']
        if len(results) == 0:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get mark price")
        funding_rate = decimal.Decimal(results[0]['funding_rate']) # IT IS NOT PERCENT
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=funding_rate, error=None)

    @handle_errors_async(logger_prefix="PARADEX GET MARK PRICE")
    async def get_mark_price(self, market: Market):
        url = f"https://api.prod.paradex.trade/v1/markets/summary?market={market.symbol}"
        headers = {'Accept': 'application/json'}
        res = await self.client.make_request(url=url, method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_mark_price")
        status = res['status']
        res = res['data']

        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get mark price")
        results = res['results']
        if len(results) == 0:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get mark price")
        mark_price = decimal.Decimal(results[0]['mark_price'])
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=mark_price, error=None)

