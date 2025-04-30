from copy import deepcopy
import dataclasses
import time
from typing import List

import requests
from data import Market, OrderBook as OrderBookDataclass, OrderBookOrder
from src.connectors.paradex.Paradex import Paradex 
from src.connectors.Backpack import Backpack
from src.utils.enums import OrderSide, Platform
from loguru import logger
from collections import deque
import threading

class OrderBook:
    def __init__(self, market2tokens: dict[Platform, List[Market]]):
        self.market2tokens = market2tokens
        self.ws = {}
        for platform, markets in market2tokens.items():
            if platform == Platform.paradex:
                self.ws[platform] = Paradex.createWs(markets, self.on_message)
            if platform == Platform.backpack:
                self.ws[platform] = Backpack.createWs(markets, self.on_message_backpack)

        self.orders = {}
        for platform, markets in market2tokens.items():
            self.orders[platform] = {}
            for market in markets:
                self.orders[platform][market.baseCurrency] = OrderBookDataclass(platform, market.baseCurrency, [], [])

        def update_orderbook_backpack():
            while True:
                try:
                    r = requests.get(f"https://api.backpack.exchange/api/v1/depth?symbol={market.symbol}")
                    data = r.json()
                    bids = []
                    asks = []
                    for i in data['asks']:
                        asks.append(OrderBookOrder(float(i[0]), float(i[1])))
                        if asks[-1].size == 0:
                            raise Exception("size is 0")
                    for i in data['bids']:
                        bids.append(OrderBookOrder(float(i[0]), float(i[1])))
                        if bids[-1].size == 0:
                            raise Exception("size is 0")

                    orderbook = OrderBookDataclass(Platform.backpack, market.baseCurrency, asks, bids)
                    orderbook.sort(OrderSide.BUY)

                    self.orders[Platform.backpack][market.baseCurrency] = orderbook
                    self.backpack_temp_updates[market.baseCurrency] = deque()
                    time.sleep(3)
                except Exception as e:
                    logger.error(f"Error updating orderbook: {e}")
                    time.sleep(3)

        thread = threading.Thread(target=update_orderbook_backpack)
        threads.append(thread)

        # thread = threading.Thread(target=log_best_price)
        # threads.append(thread)

        for thread in threads:
            thread.start()

        logger.info(f"created {len(self.ws)} websockets")
        
    def on_message(self, message):
        self.orders[message.platform][message.token] = message

    def on_message_backpack(self, message):
        base_currency = message['data']['s'].replace("_USDC", "")
        self.backpack_temp_updates[base_currency].append(message)