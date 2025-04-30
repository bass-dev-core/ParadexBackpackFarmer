import asyncio
import copy
import decimal
import math
import random
import sys
import time
from turtle import pd
from typing import Dict, List, Union
import uuid
import aiohttp
import yaml
from src.utils.data import Market, Order, OrderBook, Position, Wallet, WalletStats, FunctionOutput
from src.utils.enums import FundingRegime, OrderCancelType, OrderSide, OrderStatus, OrderType, platformRow2platform, Platform, FunctionStatus
from loguru import logger
import os
from src.connectors.paradex.Paradex import Paradex
from src.connectors.Backpack import Backpack
from src.connectors.Connector import Connector
from src.utils.stats import Stats
from collections import defaultdict
from src.utils.utils import calculate_funding_delta, calculate_pnl, hash
from src.utils.tg import Tg
from src.utils.constants import NOTIFICATION_INTERVAL, orderTypeMapping, OPEN_INTEREST_SLEEP_INTERVAL
from src.utils.pair import Pair
from src.utils.constants import RETRIES_MAX
from tqdm import tqdm
import pandas as pd


class DeFutureBot:
    def __init__(self, stats: Stats, tg: Tg):
        self.stats = stats
        self.tg = tg
        self.last_notification_ts = 0
        self.tasks = {}
        self.pair_uuid_to_pair= {}

    async def add_task(self, pair: Pair, user_id: str):
        task = asyncio.create_task(self._run(pair, user_id))
        self.tasks[pair.uuid] = task
        self.pair_uuid_to_pair[pair.uuid] = pair

        logger.info(f"TASKS {self.tasks.keys()}")
        logger.info(f"PAIR_UUID_TO_PAIR {self.pair_uuid_to_pair.keys()}")
        return pair.uuid

    async def remove_task(self, task_id: str, user_id: str):
        task = self.tasks.pop(task_id)
        try:
            task.cancel()
        except:
            pass

        try:
            pair: Pair = self.pair_uuid_to_pair.pop(task_id)
            await self.stats.set_status(pair.uuid, "STOPPED")
            logger.info(f"PAIR_UUID {pair.uuid} STOPPED")

            await self._clear_all_orders_and_positions(pair.walletA.connector, user_id)
            await self._clear_all_orders_and_positions(pair.walletB.connector, user_id)   

            await pair.walletA.connector.client.close()
            await pair.walletB.connector.client.close()

            logger.info(f"PAIR_UUID {pair.uuid} SESSIONS CLOSED AND POSITIONS CLEARED")
        except Exception as e:
            logger.error(f"PAIR_UUID {pair.uuid} ERROR CLOSING SESSIONS {e}")

        logger.info(f"TASKS {self.tasks.keys()}")
        logger.info(f"PAIR_UUID_TO_PAIR {self.pair_uuid_to_pair.keys()}")

    async def _run(self, pair: Pair, user_id: str):
        walletA = pair.walletA.connector
        walletB = pair.walletB.connector
        walletA_uuid = pair.walletA.uuid
        walletB_uuid = pair.walletB.uuid
        pair_uuid = pair.uuid

        logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_A_PLATFORM {walletA.platform} WALLET_B_UUID {walletB_uuid} WALLET_B_PLATFORM {walletB.platform}")
        if pair.funding_regime == FundingRegime.FULL:
            logger.info(f"PAIR UUID: {pair_uuid} FUNDING ARBITRAGE MODE IS IN FULL MODE")
        elif pair.funding_regime == FundingRegime.ON:
            logger.info(f"PAIR UUID: {pair_uuid} FUNDING ARBITRAGE MODE IS IN ON MODE")
        else:
            logger.info(f"PAIR UUID: {pair_uuid} FUNDING ARBITRAGE MODE IS IN OFF MODE")

        # pause 
        if pair.holdTimeBeforeMin < pair.holdTimeBeforeMax:
            pause_interval = round(random.uniform(pair.holdTimeBeforeMin, pair.holdTimeBeforeMax) * 60, 2)
            logger.info(f"PAIR_UUID {pair_uuid} HOLD TIME BEFORE MIN {pair.holdTimeBeforeMin} minutes HOLD TIME BEFORE MAX {pair.holdTimeBeforeMax} minutes PAUSE INTERVAL {pause_interval} seconds")
            await asyncio.sleep(pause_interval)
 
        # close all positions and orders
        positionsA: List[Position] = await walletA.get_open_positions()
        positionsB: List[Position] = await walletB.get_open_positions()

        if positionsA.status == FunctionStatus.ERROR or positionsB.status == FunctionStatus.ERROR:
            logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error getting open positions")
            return

        await self.stats.set_positions(walletA_uuid, positionsA.result)
        await self.stats.set_positions(walletB_uuid, positionsB.result)
        
        await asyncio.sleep(1)

        await self._clear_all_orders_and_positions(walletA, user_id)
        await self._clear_all_orders_and_positions(walletB, user_id)

        await asyncio.sleep(1)


        position_symbol = None
        position_creation_ts = None
        lifetime = None
        status = None
        last_funding_update_ts = None
        # main algo
        while True:
            
            position_symbol, position_creation_ts, lifetime, status, finished, last_funding_update_ts = await self._main_algo(pair, user_id, position_symbol, position_creation_ts, lifetime, status, last_funding_update_ts)
            await asyncio.sleep(0.1)

            if finished:
                break
        
        logger.success(f"PAIR_UUID {pair_uuid} FINISHED")
        
            
    async def _clear_all_orders_and_positions(self, wallet: Connector, user_id: str):
        positions: List[Position] = await wallet.get_open_positions()
        if positions.status == FunctionStatus.ERROR:
            logger.error(f"WALLET_UUID {wallet.uuid} error getting open positions")
            return
        
        for position_name, position in positions.result.items():
            position: Position = position
            reverseSide = OrderSide.BUY if position.side == OrderSide.SELL else OrderSide.SELL
            size = position.size
            market = wallet.token2market[position.currency]
            res: FunctionOutput = await wallet.open_position(market, reverseSide, size, order_type=OrderType.MARKET, close_position=True)
            if res.status == FunctionStatus.ERROR:
                logger.error(f"WALLET_UUID {wallet.uuid} error closing position {position.symbol}: {res.error}")
                continue

            logger.success(f"{user_id} {wallet.platform} {wallet.uuid} closed position {position.symbol}")

            markPrice = await wallet.get_mark_price(market)
            if markPrice.status != FunctionStatus.ERROR:
                markPrice = markPrice.result
                usdc_pos = decimal.Decimal(position.size) * decimal.Decimal(markPrice)
                usdc_pos = round(float(usdc_pos), 2)
                await self.stats.increment_madeUpVolume(wallet.uuid, usdc_pos)
        await asyncio.sleep(1)
        orders: List[Order] = await wallet.get_orders()

        if orders.status == FunctionStatus.ERROR:
            logger.error(f"WALLET_UUID {wallet.uuid} error getting orders")
            return

        for order in orders.result:
            order: Order = order
            if order.status == OrderStatus.PENDING:
                res: FunctionOutput = await wallet.close_order(order.id, order.symbol)
                if res.status == FunctionStatus.ERROR:
                    logger.error(f"WALLET_UUID {wallet.uuid} error canceling order {order.symbol}: {res.error}")
                    continue

                logger.success(f"WALLET_UUID {wallet.uuid} closed order {order.symbol}")

    def _check_position_lifetime(self, position_symbol: str, position_creation_ts: int, lifetime: int):
        if lifetime is None or position_creation_ts is None:
            return False
        
        if time.time() - position_creation_ts > lifetime:
            return True
        return False

    async def _main_algo(self, pair: Pair, user_id: str, position_symbol: Union[str, None], position_creation_ts: Union[int, None], lifetime: Union[int, None], status: Union[str, None], last_funding_update_ts: Union[int, None]):
        walletA: Connector = pair.walletA.connector
        walletB: Connector = pair.walletB.connector
        walletA_uuid: str = pair.walletA.uuid
        walletB_uuid: str = pair.walletB.uuid
        walletA_order_type: OrderType = pair.walletA.orderType
        walletB_order_type: OrderType = pair.walletB.orderType
        pair_uuid: str = pair.uuid

        positionsA, positionsB = await asyncio.gather(
            walletA.get_open_positions(),
            walletB.get_open_positions()
        )

        if positionsA.status == FunctionStatus.ERROR or positionsB.status == FunctionStatus.ERROR:
            logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error getting open positions")
            return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts

        positionsA: Dict[str, Position] = positionsA.result
        positionsB: Dict[str, Position] = positionsB.result
        await self.stats.set_positions(walletA_uuid, positionsA)
        await self.stats.set_positions(walletB_uuid, positionsB)

        balanceA, balanceB = await asyncio.gather(
            walletA.get_balance(),
            walletB.get_balance()
        )

        if balanceA.status == FunctionStatus.ERROR or balanceB.status == FunctionStatus.ERROR:
            logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error getting balance")
            return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts

        balanceA = balanceA.result
        balanceB = balanceB.result

        await self.stats.set_balance(walletA_uuid, balanceA)
        await self.stats.set_balance(walletB_uuid, balanceB)

        await asyncio.sleep(1)

        volumeA = await self.stats.get_volume(user_id, walletA_uuid)
        volumeB = await self.stats.get_volume(user_id, walletB_uuid)

        if volumeA > decimal.Decimal(pair.volumeUSDT) or volumeB > decimal.Decimal(pair.volumeUSDT):
            status = "VOLUME EXCEEDED. FINISHING"
            await self.stats.set_status(pair_uuid, status)
            logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")

            await asyncio.gather(
                self._clear_all_orders_and_positions(walletA, user_id),
                self._clear_all_orders_and_positions(walletB, user_id)
            )

            await asyncio.sleep(1)
            return None, None, None, status, True, last_funding_update_ts
        else:
            logger.info(f"PAIR_UUID {pair_uuid} VOLUME A {volumeA}$ VOLUME B {volumeB}$")

        if position_symbol is not None:

            marketA = [i for i in walletA.token2market.values() if i.baseCurrency == position_symbol]
            marketB = [i for i in walletB.token2market.values() if i.baseCurrency == position_symbol]

            if len(marketA) == 0 or len(marketB) == 0:
                logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} position symbol {position_symbol} not found")
                return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts

            marketA = marketA[0]
            marketB = marketB[0]
            positionA: Position = positionsA.get(marketA.symbol, None)
            positionB: Position = positionsB.get(marketB.symbol, None)

            # check liquidation
            if positionA is None or positionB is None or positionA.size != positionB.size or positionA.side == positionB.side:

                status = "POSITION LIQUIDATION. CLOSING POSITIONS"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} position exists {positionA is not None}, {walletB.platform} position exists {positionB is not None}")
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} position size {positionA.size if positionA is not None else 0}, {walletB.platform} position size {positionB.size if positionB is not None else 0}")
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} position side {positionA.side if positionA is not None else None}, {walletB.platform} position side {positionB.side if positionB is not None else None}")

                await asyncio.gather(
                    self._clear_all_orders_and_positions(walletA, user_id),
                    self._clear_all_orders_and_positions(walletB, user_id)
                )

                timeout = round(random.uniform(pair.timeoutMin, pair.timeoutMax) * 60, 2)
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} timeout {timeout} seconds")
                status = f"TIMEOUT {timeout} seconds"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                await asyncio.sleep(timeout)

                return None, None, None, status, False, last_funding_update_ts


            should_close = self._check_position_lifetime(position_symbol, position_creation_ts, lifetime)
            if (pair.funding_regime != FundingRegime.FULL) and should_close:
                status = "POSITION LIFETIME EXPIRED. CLOSING POSITIONS"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} position lifetime ({lifetime}) expired. Closing positions")
                

                await asyncio.gather(
                    self._clear_all_orders_and_positions(walletA, user_id),
                    self._clear_all_orders_and_positions(walletB, user_id)
                )


                timeout = round(random.uniform(pair.timeoutMin, pair.timeoutMax) * 60, 2)
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} timeout {timeout} seconds")
                status = f"TIMEOUT {timeout} seconds"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                await asyncio.sleep(timeout)

                return None, None, None, status, False, last_funding_update_ts
            
            markPriceA = await walletA.get_mark_price(marketA)
            markPriceB = await walletB.get_mark_price(marketB)

            if markPriceA.status == FunctionStatus.ERROR or markPriceB.status == FunctionStatus.ERROR:
                logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error getting mark price")
                return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts

            markPriceA = markPriceA.result
            markPriceB = markPriceB.result

            usdc_pos_a = positionA.size * positionA.entryPrice
            usdc_pos_b = positionB.size * positionB.entryPrice

            leverage_a = usdc_pos_a / balanceA
            leverage_b = usdc_pos_b / balanceB

            pnlA = calculate_pnl(positionA.entryPrice, markPriceA, leverage_a, positionA.side) * decimal.Decimal(100) # PERCENTS
            pnlB = calculate_pnl(positionB.entryPrice, markPriceB, leverage_b, positionB.side) * decimal.Decimal(100) # PERCENTS

            logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} usdc_pos_a: {usdc_pos_a} usdc_pos_b: {usdc_pos_b} leverage_a: {leverage_a} leverage_b: {leverage_b} pnlA: {pnlA} pnlB: {pnlB}")

            max_loss_percents = decimal.Decimal(pair.maxLossPercents)
            if abs(pnlA) > max_loss_percents or abs(pnlB) > max_loss_percents:
                status = "MAX LOSS/PROFIT EXCEEDED. CLOSING POSITIONS"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} closing position {position_symbol} because of max loss/profit {max_loss_percents}")

                
                await asyncio.gather(
                    self._clear_all_orders_and_positions(walletA, user_id),
                    self._clear_all_orders_and_positions(walletB, user_id)
                )


                timeout = round(random.uniform(pair.timeoutMin, pair.timeoutMax) * 60, 2)
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} timeout {timeout} seconds")
                status = f"TIMEOUT {timeout} seconds"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                await asyncio.sleep(timeout)

                return None, None, None, status, False, last_funding_update_ts

            if pair.funding_regime == FundingRegime.ON:
                funding_rateA = await walletA.get_funding_rate(marketA)
                funding_rateB = await walletB.get_funding_rate(marketB)

                if funding_rateA.status == FunctionStatus.ERROR or funding_rateB.status == FunctionStatus.ERROR:
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error getting funding rate")
                    return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts

                funding_rateA = funding_rateA.result
                funding_rateB = funding_rateB.result

                funding_profit_A = funding_rateA * usdc_pos_a 
                funding_profit_B = funding_rateB * usdc_pos_b

                funding_profit_A = funding_profit_A * decimal.Decimal(-1) if positionA.side == OrderSide.BUY else funding_profit_A
                funding_profit_B = funding_profit_B * decimal.Decimal(-1) if positionB.side == OrderSide.BUY else funding_profit_B

                total = funding_profit_A + funding_profit_B

                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} funding_rateA: {funding_rateA} funding_rateB: {funding_rateB} funding_profit_A: {funding_profit_A} funding_profit_B: {funding_profit_B} total: {total}")

                if total < decimal.Decimal(0):
                    status = "FUNDING PROFIT IS NEGATIVE. CLOSING POSITIONS"
                    await self.stats.set_status(pair_uuid, status)
                    logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                    logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} funding profit is negative. Closing positions")


                    await asyncio.gather(
                        self._clear_all_orders_and_positions(walletA, user_id),
                        self._clear_all_orders_and_positions(walletB, user_id)
                    )


                    timeout = round(random.uniform(pair.timeoutMin, pair.timeoutMax) * 60, 2)
                    logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} timeout {timeout} seconds")
                    status = f"TIMEOUT {timeout} seconds"
                    await self.stats.set_status(pair_uuid, status)
                    logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                    await asyncio.sleep(timeout)
                    return None, None, None, status, False, last_funding_update_ts
            
            if pair.funding_regime == FundingRegime.FULL:
                if not last_funding_update_ts or time.time() - last_funding_update_ts > 3 * 60:
                    status = "FETCHING FUNDING RATES"
                    await self.stats.set_status(pair_uuid, status)
                    logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                    
                    funding_rates_df = await self.__fetch_funding_rates([walletA, walletB])
                    last_funding_update_ts = time.time()

                    if len(funding_rates_df) == 0:
                        logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error fetching funding rates. EMPTY DATAFRAME")
                        return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts

                    funding_rates_df = funding_rates_df.dropna(subset=[walletA.platform, walletB.platform], how='any')

                    if len(funding_rates_df) == 0:
                        logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error fetching funding rates. EMPTY DATAFRAME")
                        return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts

                    funding_rates_df = funding_rates_df.iloc[0]

                    funding_rate_a = funding_rates_df[walletA.platform]
                    funding_rate_b = funding_rates_df[walletB.platform]

                    token = funding_rates_df["token"]

                    if token != positionA.currency:
                        logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid}. Found more profitable token {token} != {positionA.currency}")
                        status = f"MORE PROFITABLE TOKEN FOUND {token}. CLOSING POSITIONS"
                        await self.stats.set_status(pair_uuid, status)
                        logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")

                        await asyncio.gather(
                            self._clear_all_orders_and_positions(walletA, user_id),
                            self._clear_all_orders_and_positions(walletB, user_id)
                        )

                        return None, None, None, status, False, last_funding_update_ts

                    walletA_side = None
                    walletB_side = None
                    if abs(funding_rate_a) > abs(funding_rate_b):
                        if funding_rate_a > decimal.Decimal(0):
                            walletA_side = OrderSide.SELL
                            walletB_side = OrderSide.BUY
                        else:
                            walletA_side = OrderSide.BUY
                            walletB_side = OrderSide.SELL
                    else:
                        if funding_rate_b > decimal.Decimal(0):
                            walletB_side = OrderSide.SELL
                            walletA_side = OrderSide.BUY
                        else:
                            walletB_side = OrderSide.BUY
                            walletA_side = OrderSide.SELL

                    if walletA_side != positionA.side or walletB_side != positionB.side:
                        status = f"NO ITS PROFITABLE TO SWITCH SIDE OF CURRENT TOKEN. CLOSING POSITIONS"
                        await self.stats.set_status(pair_uuid, status)
                        logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")

                        await asyncio.gather(
                            self._clear_all_orders_and_positions(walletA, user_id),
                            self._clear_all_orders_and_positions(walletB, user_id)
                        )

                        return None, None, None, status, False, last_funding_update_ts
  
        else:
            if len(positionsA) > 0 or len(positionsB) > 0:
                status = "NO POSITION. CLOSING EXTRA POSITIONS"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} closing extra positions because of no main position")

                await asyncio.gather(
                    self._clear_all_orders_and_positions(walletA, user_id),
                    self._clear_all_orders_and_positions(walletB, user_id)
                )
                return None, None, None, status, False, last_funding_update_ts
            
            if balanceA < decimal.Decimal(1) or balanceB < decimal.Decimal(1):
                status = "LOW BALANCE. CANNOT OPEN POSITION"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} cannot open position because of low balance")
                
                return None, None, None, status, False, last_funding_update_ts
            
            funding_rateA = None
            funding_rateB = None
            walletA_side = None
            walletB_side = None
            random_token = None 
            random_marketA = None
            random_marketB = None

            if pair.funding_regime != FundingRegime.FULL:
                random_token = pair.tokens[random.randint(0, len(pair.tokens) - 1)]
                random_marketA: Market = walletA.token2market[random_token]
                random_marketB: Market = walletB.token2market[random_token]


                if pair.funding_regime == FundingRegime.ON:
                    funding_rateA, funding_rateB = await asyncio.gather(
                        walletA.get_funding_rate(random_marketA),
                        walletB.get_funding_rate(random_marketB)
                    )

                    if funding_rateA.status == FunctionStatus.ERROR or funding_rateB.status == FunctionStatus.ERROR:
                        logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error getting funding rate")
                        return None, None, None, status, False, last_funding_update_ts
                    
                    funding_rateA = funding_rateA.result
                    funding_rateB = funding_rateB.result

                    if abs(funding_rateA) > abs(funding_rateB):
                        if funding_rateA > decimal.Decimal(0):
                            walletA_side = OrderSide.SELL
                            walletB_side = OrderSide.BUY
                        else:
                            walletA_side = OrderSide.BUY
                            walletB_side = OrderSide.SELL
                    else:
                        if funding_rateB > decimal.Decimal(0):
                            walletB_side = OrderSide.SELL
                            walletA_side = OrderSide.BUY
                        else:
                            walletB_side = OrderSide.BUY
                            walletA_side = OrderSide.SELL
                else:
                    walletA_side = random.choice([OrderSide.BUY, OrderSide.SELL])
                    walletB_side = OrderSide.BUY if walletA_side == OrderSide.SELL else OrderSide.SELL
            else:
                funding_rates_df = await self.__fetch_funding_rates([walletA, walletB])
                if len(funding_rates_df) == 0:
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error fetching funding rates. EMPTY DATAFRAME")
                    return None, None, None, status, False, last_funding_update_ts
                
                funding_rates_df = funding_rates_df.dropna(subset=[walletA.platform, walletB.platform], how='any')

                if len(funding_rates_df) == 0:
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error fetching funding rates. EMPTY DATAFRAME")
                    return None, None, None, status, False, last_funding_update_ts
                
                funding_rates_df = funding_rates_df.iloc[0]

                funding_rate_a = funding_rates_df[walletA.platform]
                funding_rate_b = funding_rates_df[walletB.platform]

                token = funding_rates_df["token"]

                random_token = token
                random_marketA: Market = walletA.token2market[random_token]
                random_marketB: Market = walletB.token2market[random_token]

                funding_rateA = decimal.Decimal(float(funding_rate_a))
                funding_rateB = decimal.Decimal(float(funding_rate_b))


                if abs(funding_rateA) > abs(funding_rateB):
                    if funding_rateA > decimal.Decimal(0):
                        walletA_side = OrderSide.SELL
                        walletB_side = OrderSide.BUY
                    else:
                        walletA_side = OrderSide.BUY
                        walletB_side = OrderSide.SELL
                else:
                    if funding_rateB > decimal.Decimal(0):
                        walletB_side = OrderSide.SELL
                        walletA_side = OrderSide.BUY
                    else:
                        walletB_side = OrderSide.BUY
                        walletA_side = OrderSide.SELL

            mark_priceA, mark_priceB = await asyncio.gather(
                walletA.get_mark_price(random_marketA),
                walletB.get_mark_price(random_marketB)
            )

            if mark_priceA.status == FunctionStatus.ERROR or mark_priceB.status == FunctionStatus.ERROR:
                logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error getting mark price")
                return None, None, None, status, False, last_funding_update_ts
            
            mark_priceA = mark_priceA.result
            mark_priceB = mark_priceB.result

            max_order_sizeA, max_order_sizeB = await asyncio.gather(
                walletA.calculate_max_size(random_marketA, walletA_side, balanceA, mark_priceA),
                walletB.calculate_max_size(random_marketB, walletB_side, balanceB, mark_priceB)
            )

            if max_order_sizeA.status == FunctionStatus.ERROR or max_order_sizeB.status == FunctionStatus.ERROR:
                logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error getting max order size")
                return None, None, None, status, False, last_funding_update_ts
            
            max_order_sizeA = max_order_sizeA.result
            max_order_sizeB = max_order_sizeB.result

            minMaxOrderSize = min(max_order_sizeA, max_order_sizeB)
            minBalance = min(balanceA, balanceB) / mark_priceA
            minBalance = decimal.Decimal(minBalance) * decimal.Decimal(pair.leverage)
            order_size = decimal.Decimal(min(minMaxOrderSize, minBalance)) * decimal.Decimal(0.9)
            
            minSizeTick = min(random_marketA.sizeTick, random_marketB.sizeTick)
            myothercontext = decimal.Context(prec=60, rounding=decimal.ROUND_HALF_DOWN)
            order_size = order_size.quantize(decimal.Decimal('0.1') ** minSizeTick, context=myothercontext)

            lifetime = round(random.uniform(pair.positionHoldTimeMin, pair.positionHoldTimeMax) * 60, 2)
            position_symbol = random_marketA.baseCurrency

            logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} OPENING POSITION {random_marketA.symbol} WITH SIZE {order_size} AND LIFETIME {lifetime}")
            logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} MAX ORDER SIZE A {max_order_sizeA} MAX ORDER SIZE B {max_order_sizeB} MIN MAX ORDER SIZE {minMaxOrderSize} MIN BALANCE {minBalance} ORDER SIZE {order_size}")
            if pair.funding_regime == FundingRegime.FULL or pair.funding_regime == FundingRegime.ON:
                logger.info(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} FUNDING RATE A {funding_rateA} FUNDING RATE B {funding_rateB} WALLET A SIDE {walletA_side} WALLET B SIDE {walletB_side}")

            
            if walletA_order_type == OrderType.LIMIT and walletB_order_type == OrderType.MARKET:
                status = "OPENING POSITION"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                resA: FunctionOutput = await walletA.open_position(random_marketA, walletA_side, order_size, order_type=walletA_order_type, close_position=False)
                if resA.status == FunctionStatus.ERROR:
                    status = "ERROR OPENING POSITION"
                    await self.stats.set_status(pair_uuid, status)
                    logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error opening position A: {resA.error}")
                    return None, None, None, status, False, last_funding_update_ts
                
                resB: FunctionOutput = await walletB.open_position(random_marketB, walletB_side, order_size, order_type=walletB_order_type, close_position=False)

                if resB.status == FunctionStatus.ERROR:
                    status = "ERROR OPENING POSITION"
                    await self.stats.set_status(pair_uuid, status)
                    logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error opening position B: {resB.error}")
                    await asyncio.gather(
                        self._clear_all_orders_and_positions(walletA, user_id),
                        self._clear_all_orders_and_positions(walletB, user_id)
                    )
                    return None, None, None, status, False, last_funding_update_ts
                
                position_creation_ts = time.time()
                status = "POSITION OPENED"
                await self.stats.set_status(pair_uuid, status)
                logger.success(f"PAIR_UUID {pair_uuid} STATUS {status}")

                mark_priceA = await walletA.get_mark_price(random_marketA)
                mark_priceB = await walletB.get_mark_price(random_marketB)

                if mark_priceA.status != FunctionStatus.ERROR and mark_priceB.status != FunctionStatus.ERROR:
                    mark_priceA = mark_priceA.result
                    mark_priceB = mark_priceB.result

                    usdc_pos_a = decimal.Decimal(order_size) * decimal.Decimal(mark_priceA)
                    usdc_pos_b = decimal.Decimal(order_size) * decimal.Decimal(mark_priceB)

                    usdc_pos_a = round(float(usdc_pos_a), 2)
                    usdc_pos_b = round(float(usdc_pos_b), 2)

                    await self.stats.increment_madeUpVolume(walletA_uuid, usdc_pos_a)
                    await self.stats.increment_madeUpVolume(walletB_uuid, usdc_pos_b)
                return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts
            elif walletA_order_type == OrderType.MARKET and walletB_order_type == OrderType.LIMIT:
                status = "OPENING POSITION"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                resB: FunctionOutput = await walletB.open_position(random_marketB, walletB_side, order_size, order_type=walletB_order_type, close_position=False)

                if resB.status == FunctionStatus.ERROR:
                    status = "ERROR OPENING POSITION"
                    await self.stats.set_status(pair_uuid, status)
                    logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error opening position B: {resB.error}")
                    return None, None, None, status, False, last_funding_update_ts
                
                resA: FunctionOutput = await walletA.open_position(random_marketA, walletA_side, order_size, order_type=walletA_order_type, close_position=False)

                if resA.status == FunctionStatus.ERROR:
                    status = "ERROR OPENING POSITION"
                    await self.stats.set_status(pair_uuid, status)
                    logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error opening position A: {resA.error}")
                    await asyncio.gather(
                        self._clear_all_orders_and_positions(walletA, user_id),
                        self._clear_all_orders_and_positions(walletB, user_id)
                    )
                    return None, None, None, status, False, last_funding_update_ts

                position_creation_ts = time.time()
                status = "POSITION OPENED"

                await self.stats.set_status(pair_uuid, status)
                logger.success(f"PAIR_UUID {pair_uuid} STATUS {status}")

                mark_priceA = await walletA.get_mark_price(random_marketA)
                mark_priceB = await walletB.get_mark_price(random_marketB)

                if mark_priceA.status != FunctionStatus.ERROR and mark_priceB.status != FunctionStatus.ERROR:
                    mark_priceA = mark_priceA.result
                    mark_priceB = mark_priceB.result

                    usdc_pos_a = decimal.Decimal(order_size) * decimal.Decimal(mark_priceA)
                    usdc_pos_b = decimal.Decimal(order_size) * decimal.Decimal(mark_priceB)

                    usdc_pos_a = round(float(usdc_pos_a), 2)
                    usdc_pos_b = round(float(usdc_pos_b), 2)

                    await self.stats.increment_madeUpVolume(walletA_uuid, usdc_pos_a)
                    await self.stats.increment_madeUpVolume(walletB_uuid, usdc_pos_b)
                
                return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts
            else:
                status = "OPENING POSITION"
                await self.stats.set_status(pair_uuid, status)
                logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                res1, res2 = await asyncio.gather(
                    walletA.open_position(random_marketA, walletA_side, order_size, order_type=walletA_order_type, close_position=False),
                    walletB.open_position(random_marketB, walletB_side, order_size, order_type=walletB_order_type, close_position=False)
                )

                if res1.status == FunctionStatus.ERROR or res2.status == FunctionStatus.ERROR:
                    status = "ERROR OPENING POSITION"
                    await self.stats.set_status(pair_uuid, status)
                    logger.info(f"PAIR_UUID {pair_uuid} STATUS {status}")
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error opening position A: {res1.error}")
                    logger.error(f"PAIR_UUID {pair_uuid} WALLET_A_UUID {walletA_uuid} WALLET_B_UUID {walletB_uuid} error opening position B: {res2.error}")

                    await asyncio.gather(
                        self._clear_all_orders_and_positions(walletA, user_id),
                        self._clear_all_orders_and_positions(walletB, user_id)
                    )
                    return None, None, None, status, False, last_funding_update_ts

                position_creation_ts = time.time()
                status = "POSITION OPENED"

                await self.stats.set_status(pair_uuid, status)
                logger.success(f"PAIR_UUID {pair_uuid} STATUS {status}")

                mark_priceA = await walletA.get_mark_price(random_marketA)
                mark_priceB = await walletB.get_mark_price(random_marketB)

                if mark_priceA.status != FunctionStatus.ERROR and mark_priceB.status != FunctionStatus.ERROR:
                    mark_priceA = mark_priceA.result
                    mark_priceB = mark_priceB.result

                    usdc_pos_a = decimal.Decimal(order_size) * decimal.Decimal(mark_priceA)
                    usdc_pos_b = decimal.Decimal(order_size) * decimal.Decimal(mark_priceB)

                    usdc_pos_a = round(float(usdc_pos_a), 2)
                    usdc_pos_b = round(float(usdc_pos_b), 2)

                    await self.stats.increment_madeUpVolume(walletA_uuid, usdc_pos_a)
                    await self.stats.increment_madeUpVolume(walletB_uuid, usdc_pos_b)
                
                return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts
        return position_symbol, position_creation_ts, lifetime, status, False, last_funding_update_ts
    
    async def __fetch_funding_rate_for_token(self, token: str, connector: Connector):
        if token not in connector.token2market: 
            return None

        market = connector.token2market[token]
        funding_rate = await connector.get_funding_rate(market)
        if funding_rate.status != FunctionStatus.ERROR:
            return funding_rate.result
        else:
            return None
                
    async def __fetch_funding_rates(self, connectors: List[Connector]):
        try:
            funding_rates = []
            all_tokens = set()
            for connector in connectors:
                all_tokens.update(connector.token2market.keys())
            
            logger.info(f"ALL TOKENS {all_tokens}")
            
            for token in tqdm(all_tokens):
                funding_rates.append({"token": token})

                funding_rates_for_token = await asyncio.gather(*[self.__fetch_funding_rate_for_token(token, connector) for connector in connectors])
                for funding_rate, connector in zip(funding_rates_for_token, connectors):
                    funding_rates[-1][connector.platform] = funding_rate

                max_delta = float("-inf")
                max_delta_platform_a = None
                max_delta_platform_b = None

                for platform_a in funding_rates[-1]:
                    if platform_a == "token":
                        continue
                    for platform_b in funding_rates[-1]:
                        if platform_b == "token":
                            continue
                        if platform_a == platform_b:
                            continue

                        if funding_rates[-1][platform_a] is None or funding_rates[-1][platform_b] is None:
                            continue

                        funding_a = float(funding_rates[-1][platform_a])
                        funding_b = float(funding_rates[-1][platform_b])

                        funding_delta = calculate_funding_delta(funding_a, funding_b)
                        if funding_delta > max_delta:
                            max_delta = funding_delta
                            max_delta_platform_a = platform_a
                            max_delta_platform_b = platform_b

                funding_rates[-1]["max_delta"] = max_delta
                funding_rates[-1]["max_delta_platform_a"] = max_delta_platform_a
                funding_rates[-1]["max_delta_platform_b"] = max_delta_platform_b
            df = pd.DataFrame(funding_rates)
            df = df.sort_values(by="max_delta", ascending=False)
            columns = ['token', 'max_delta', 'max_delta_platform_a', 'max_delta_platform_b']
            columns.extend([connector.platform for connector in connectors])
            df = df[columns]

            df = df.head(10)
            print(df)

            return df
        except Exception as e:
            logger.error(f"ERROR FETCHING ALL FUNDING RATES {e}")
            return pd.DataFrame()

                                    




        
        
        
        
        
        