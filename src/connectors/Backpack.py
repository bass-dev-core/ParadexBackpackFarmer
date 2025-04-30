import asyncio
import base64
import copy
import json
from typing import Callable, Dict, Optional

import aiohttp
from loguru import logger
import websocket
from src.connectors.Connector import Connector
import decimal
from src.utils.data import FunctionOutput, Market, OrderBook, OrderBookOrder

from cryptography.hazmat.primitives.asymmetric import ed25519

from src.utils.data import Market, Position, Order, Balance, OrderStatus
from src.utils.enums import FunctionStatus, OrderType, OrderCancelType, OrderSide, Platform
import time

from src.utils.utils import handle_errors_async, send_request, truncate_decimal
from src.utils.constants import BACKPACK_FEE_PERCENT
from src.utils.proxy import Proxy
from src.utils.client import RequestClient
orderType2BackpackOrderType = {
    OrderType.LIMIT: "Limit",
    OrderType.MARKET: "Market",
    OrderType.STOP_LOSS: "StopLoss",
}


backpackStatus2OrderStatus = {
    "Filled": OrderStatus.FILLED,
    "New": OrderStatus.PENDING,
    "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
    "Canceled": OrderStatus.CANCELLED,
    "Rejected": OrderStatus.REJECTED,
}
url = "https://api.backpack.exchange/api/v1"

class Backpack(Connector):
    def __init__(self, api_key: str, private_key: str, uuid: str, proxy: Optional[Proxy] = None, **kwargs):
        self.available_markets = []
        self.orderbook = {}
        self.api_key = api_key
        self.private_key = ed25519.Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key))
        self.token2size_digits = {}
        self.token2price_digits = {}
        self.token2market = {}
        self.platform = Platform.backpack
        self.proxy = proxy
        self.uuid = uuid
        self.client = RequestClient(proxy=proxy)
        

    def _build_sign(self, instruction: str, ts: int, params=None, window: int = 5000):
        if params:
            params = params.copy()
            for key, value in params.items():
                if isinstance(value, bool):
                    params[key] = str(value).lower()

            param_str = "&" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        else:
            param_str = ""
        if not param_str:
            param_str = ""
        sign_str = f"instruction={instruction}{param_str}&timestamp={ts}&window={window}"
        signature = base64.b64encode(self.private_key.sign(sign_str.encode())).decode()
        return signature


    def _sign(self, instruction: str, params=None, window: int = 5000):
        ts = int(time.time() * 1e3)
        encoded_signature = self._build_sign(instruction, ts, params, window)
        headers = {
            "X-API-Key": self.api_key,
            "X-Signature": encoded_signature,
            "X-Timestamp": str(ts),
            "X-Window": str(window),
            "Content-Type": "application/json; charset=utf-8",
        }
        return headers
    
    

    @classmethod
    async def create(cls, apiKey: str, apiSecret: str, uuid: str, **kwargs):
        proxy = kwargs.get("proxy", Proxy())
        connector = cls(apiKey, apiSecret, uuid, proxy)
        
        available_markets = await connector.get_available_markets()
        connector.available_markets = available_markets.result

        if not proxy:
            logger.debug(f"CREATED: {connector.platform} {connector.api_key[:4]} NO PROXY")
        else:
            logger.debug(f"CREATED: {connector.platform} {connector.api_key[:4]} PROXY: {proxy}")
        return connector
    
    @handle_errors_async(logger_prefix="BACKPACK GET AVAILABLE MARKETS")
    async def get_available_markets(self) -> FunctionOutput:
        url = "https://api.backpack.exchange/api/v1/markets"
        headers = {'Accept': 'application/json'}
        res = await self.client.make_request(url=url, method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_available_markets")
        status = res['status']
        
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get available markets")
        res = [i for i in res if i['marketType'] != 'SPOT']
        res = [Market(i['symbol'], i['baseSymbol'], len(i['filters']['quantity']['stepSize'].replace(".", ""))-1, len(i['filters']['price']['tickSize'].replace(".", ""))-1) for i in res]
        self.available_markets = res
        self.token2size_digits = {i.baseCurrency: i.sizeTick for i in res}
        self.token2price_digits = {i.baseCurrency: i.priceTick for i in res}
        self.token2market = {i.baseCurrency: i for i in res}
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=res, error=None)

    @handle_errors_async(logger_prefix="BACKPACK GET BALANCES")
    async def get_balances(self) -> FunctionOutput:
        headers = self._sign("balanceQuery")
        res = await self.client.make_request(url=f"{url}/capital", method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_balances", errors_whitelist=["Request has expired"])
        status = res['status']
        res = res['data'] 
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get balances")
        res = [Balance(key, decimal.Decimal(value['available'])) for key, value in res.items()]
        balances = {i.currency: i.size for i in res}
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=balances, error=None)
    
    @handle_errors_async(logger_prefix="BACKPACK GET BALANCE")
    async def get_balance(self)->FunctionOutput:
        balances = await self.get_balances()
        currency = "USDC"
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=balances.result[currency], error=None)
    
            
    @handle_errors_async(logger_prefix="BACKPACK GET OPEN ORDERS")
    async def get_orders(self) -> FunctionOutput:
        headers = self._sign("orderQueryAll")
        res = await self.client.make_request(url=f"{url}/orders", method="GET", headers=headers, desired_status_code=200, return_json=True, errors_whitelist=["Request has expired"], logger_prefix=f"{self.uuid} {self.platform} get_open_orders")
        status = res['status']
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get open orders")
        
        orders = []
        for i in res:
            i['status'] = backpackStatus2OrderStatus[i['status']]
            order = Order(
                id=i['id'],
                symbol=i['symbol'],
                currency=i['symbol'].split('_')[0],
                side=OrderSide.BUY if i['side'] == 'Bid' else OrderSide.SELL,
                price=decimal.Decimal(i['price']),
                size=decimal.Decimal(i['quantity']),
                cancelType=OrderCancelType.GTC if not i['postOnly'] else OrderCancelType.POST_ONLY,
                createdTs=i['createdAt'],
                type=OrderType.LIMIT,
                status=i['status'],
                reduceOnly=i['reduceOnly'],
                cancelReason="",
                clientOrderId="",
            )
            orders.append(order)
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=orders, error=None)
            
    @handle_errors_async(logger_prefix="BACKPACK CLOSE ORDER")
    async def close_order(self, order_id: str, symbol: str = None):
        params = {'symbol': symbol}
        if len(order_id) > 0:
            params['orderId'] = order_id

        headers = self._sign("orderCancel", params=params)
        res = await self.client.make_request(url=f"{url}/order", method="DELETE", headers=headers, body=params, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} close_order", errors_whitelist=["Request has expired", "Order not found"]) 
        status = res['status']
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=False, error="Failed to close order")
        
        if res.get("status", False):
            self.open_orders = [i for i in self.open_orders if i.id != order_id]
            return FunctionOutput(status=FunctionStatus.SUCCESS, result=True, error=None)
        return FunctionOutput(status=FunctionStatus.ERROR, result=False, error="Failed to close order")
        
    @handle_errors_async(logger_prefix="BACKPACK GET OPEN POSITIONS")
    async def get_open_positions(self):
        headers = self._sign("positionQuery")
        res = await self.client.make_request(url=f"{url}/position", method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_open_positions", errors_whitelist=["Request has expired"])
        status = res['status']        
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get open positions")
        
        out = []
        for i in res:
            size = decimal.Decimal(abs(float(i['netQuantity'])))
            myothercontext = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_DOWN)
            size = size.quantize(decimal.Decimal('0.1') ** self.token2size_digits[i['symbol'].split('_')[0]], context=myothercontext)
            
            price = decimal.Decimal(float(i['entryPrice']))
            myothercontext = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_DOWN)
            price = price.quantize(decimal.Decimal('0.1') ** self.token2price_digits[i['symbol'].split('_')[0]], context=myothercontext)

            out.append(
                Position(
                    symbol=i['symbol'],
                    size=size,
                    entryPrice=price,
                    createdTs=-1,
                    maxLifeTime=-1,
                    currency=i['symbol'].split('_')[0],
                    side=OrderSide.BUY if float(i['estLiquidationPrice']) < float(i['entryPrice']) else OrderSide.SELL
                )
            )

        out = {item.symbol: item for item in out}
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=out, error=None)
            
    @handle_errors_async(logger_prefix="BACKPACK CREATE ORDER")
    async def create_order(self, order_side: OrderSide, size: decimal.Decimal, market: Market, price: decimal.Decimal, instruction: OrderCancelType, orderType: OrderType = OrderType.LIMIT, reduce_only: bool = False):
        size = str(round(float(size), market.sizeTick))
        price = str(round(float(price), market.priceTick))

        if orderType == OrderType.LIMIT:
            params = {
                'symbol': market.symbol,
                'side': "Bid" if order_side == OrderSide.BUY else "Ask",
                'orderType': "Limit",
                'quantity': str(size),
                'price': str(price),
                "postOnly": True if instruction == OrderCancelType.POST_ONLY else False
            }
        else:
            params = {
                'symbol': market.symbol,
                'side': "Bid" if order_side == OrderSide.BUY else "Ask",
                'orderType': "Market",
                'quantity': str(size)
            }
        if reduce_only:
            params['reduceOnly'] = True
        headers = self._sign("orderExecute", params=params)
        res = await self.client.make_request(url=f"{url}/order", method="POST", headers=headers, body=params, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} create_order", errors_whitelist=["Request has expired", "Insufficient margin"]) 
        status = res['status']
        error = res['error']
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=error)
        if res.get("status", False):
            order = Order(
                id=res['id'],
                currency=res['symbol'].split('_')[0],
                symbol=res['symbol'],
                size=decimal.Decimal(res['quantity']),
                price=decimal.Decimal(price),
                type=OrderType.LIMIT,
                side=OrderSide.BUY if res['side'] == 'Bid' else OrderSide.SELL,
                createdTs=res['createdAt'],
                cancelType=OrderCancelType.POST_ONLY if res.get('postOnly', False) else OrderCancelType.GTC,
                status=backpackStatus2OrderStatus[res['status']],
                reduceOnly=reduce_only,
                cancelReason="",
                clientOrderId="",
            )
            logger.debug(res)
            return FunctionOutput(status=FunctionStatus.SUCCESS, result=order, error=None)
        return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to create order")
    
    @handle_errors_async(logger_prefix="BACKPACK GET DEPTH")
    async def get_depth(self, symbol: str):
        res = await self.client.make_request(url=f"{url}/depth?symbol={symbol}", method="GET", headers={}, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_depth", errors_whitelist=["Request has expired"])
        status = res['status']
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get depth")
        
        bids = []
        asks = []
        for i in res['bids']:
            bids.append(OrderBookOrder(float(i[0]), float(i[1])))
            if bids[-1].size == 0:
                raise Exception("size is 0")
        for i in res['asks']:
            asks.append(OrderBookOrder(float(i[0]), float(i[1])))
            if asks[-1].size == 0:
                raise Exception("size is 0")
        orderbook = OrderBook(Platform.backpack, symbol.split('_')[0], asks, bids)
        orderbook.sort(OrderSide.BUY)
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=orderbook, error=None)

            
    def calculate_fee(self, size: decimal.Decimal, price: decimal.Decimal):
        return size * price * BACKPACK_FEE_PERCENT / 100
    
    @handle_errors_async(error_value=decimal.Decimal(0), logger_prefix="BACKPACK CALCULATE MAX SIZE")
    async def calculate_max_size(self, market: Market, side: OrderSide, balance: decimal.Decimal, price: decimal.Decimal):
        headers = self._sign("maxOrderQuantity", params={'symbol': market.symbol, 'side': 'Bid' if side == OrderSide.BUY else 'Ask'})
        side = 'Bid' if side == OrderSide.BUY else 'Ask'
        res = await self.client.make_request(url=f"{url}/account/limits/order?symbol={market.symbol}&side={side}", method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_available_leverage", errors_whitelist=["Request has expired"])
        status = res['status']
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=decimal.Decimal(0), error="Failed to get available leverage")
        res = res['maxOrderQuantity']
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=decimal.Decimal(res), error=None)

    @handle_errors_async(logger_prefix="BACKPACK OPEN POSITION")
    async def open_position(self, market: Market, side: OrderSide, size: decimal.Decimal, order_type: OrderType, close_position: bool) -> FunctionOutput:
        size = decimal.Decimal(truncate_decimal(float(size), market.sizeTick))
        myothercontext = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_DOWN)
        size = size.quantize(decimal.Decimal('0.1') ** market.sizeTick, context=myothercontext)

        if order_type == OrderType.MARKET or order_type == OrderType.LIMIT:
            price = decimal.Decimal(0)
            position = await self.create_order(side, size, market, price, OrderCancelType.GTC, OrderType.MARKET, reduce_only=close_position)
            
            if position.status == FunctionStatus.ERROR:
                return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=position.error)
            
            result = position.result
            if result.status == OrderStatus.FILLED:
                return FunctionOutput(status=FunctionStatus.SUCCESS, result=result, error=None)
            elif result.status == OrderStatus.PENDING:
                positions = await self.get_open_positions()
                if positions.status == FunctionStatus.ERROR:
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=positions.error)
                
                position = [i for i in positions.result if i.symbol == market.symbol and i.size == size][0]
                
                if position:
                    return FunctionOutput(status=FunctionStatus.SUCCESS, result=position, error=None)
                else:
                    return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Position not found")
                
    @handle_errors_async(logger_prefix="BACKPACK GET MARK PRICE")
    async def get_mark_price(self, market: Market):
        url = f"https://api.backpack.exchange/api/v1/markPrices?symbol={market.symbol}"
        headers = {'Accept': 'application/json'}
        res = await self.client.make_request(url=url, method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_mark_price")
        status = res['status']
        
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get mark price")
    
        if len(res) == 0:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get mark price")
        
        mark_price = decimal.Decimal(res[0]['markPrice'])
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=mark_price, error=None)

    @handle_errors_async(logger_prefix="BACKPACK GET FUNDING RATE")
    async def get_funding_rate(self, market: Market):
        url = f"https://api.backpack.exchange/api/v1/markPrices?symbol={market.symbol}"
        headers = {'Accept': 'application/json'}
        res = await self.client.make_request(url=url, method="GET", headers=headers, desired_status_code=200, return_json=True, logger_prefix=f"{self.uuid} {self.platform} get_funding_rate")
        status = res['status']
        
        res = res['data']
        if not status:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get mark price")
    
        if len(res) == 0:
            return FunctionOutput(status=FunctionStatus.ERROR, result=None, error="Failed to get mark price")
        
        funding_rate = decimal.Decimal(res[0]['fundingRate']) # IT IS NOT PERCENT
        return FunctionOutput(status=FunctionStatus.SUCCESS, result=funding_rate, error=None)
