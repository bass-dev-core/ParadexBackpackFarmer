import decimal
import sqlite3
from typing import Dict, List

from loguru import logger
from src.utils.data import Position, PositionStatus, WalletStats
import aiohttp

class Stats:
    def __init__(self, url: str = None):
        self.url = url
        if url:
            self.db = None 
        else:
            self.db = sqlite3.connect("db.sqlite")
            self.cursor = self.db.cursor()
            self.create_table()

    def create_table(self):
        if self.url:
            return
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS wallets (
                uuid TEXT PRIMARY KEY,
                openPositions TEXT,
                balance REAL,
                volume_usdt REAL,
                platform TEXT,
                status TEXT,
                sides TEXT,
                sizes TEXT
            )
        ''')
        self.db.commit()

    def add_wallet(self, uuid: str, platform: str):
        try:
            if self.url:
                return
            
            balance = 0
            volume_usdt = 0
            openPositions = ""  
            status = ""
            sides = ""
            sizes = ""
            try:
                self.cursor.execute('''
                    INSERT INTO wallets (uuid, openPositions, balance, volume_usdt, platform, status, sides, sizes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (uuid, openPositions, balance, volume_usdt, platform, status, sides, sizes))
                self.db.commit() 
            except sqlite3.IntegrityError:
                pass
        except Exception as e:
            logger.error(f"ERROR ADDING WALLET {e}")
        
    async def increment_madeUpVolume(self, uuid: str, volume: float):
        try:
            if type(volume) != float:
                volume = float(volume)
            if self.url:
                endpoint = f"{self.url}/wallets"
                async with aiohttp.ClientSession() as session:
                    async with session.put(endpoint, json={"volume_usdt": volume}, params={"wallet_id": uuid}) as response:
                        return await response.json()
            
            self.cursor.execute('''
                UPDATE wallets SET volume_usdt = volume_usdt + ? WHERE uuid = ?
            ''', (volume, uuid))
            self.db.commit()
        except Exception as e:
            logger.error(f"ERROR INCREMENTING MADE UP VOLUME {e}")

    async def set_balance(self, uuid: str, balance: float):
        try:
            if type(balance) != float:
                balance = float(balance)
            if self.url:
                endpoint = f"{self.url}/wallets"
                async with aiohttp.ClientSession() as session:
                    async with session.put(endpoint, json={"balance": balance}, params={"wallet_id": uuid}) as response:
                        return await response.json()
        
            self.cursor.execute('''
                UPDATE wallets SET balance = ? WHERE uuid = ?
            ''', (balance, uuid))
            self.db.commit()
        except Exception as e:
            logger.error(f"ERROR SETTING BALANCE {e}")

    async def set_status(self, pair_uuid: str, status: str):
        try:
            if self.url:
                endpoint = f"{self.url}/pairs/update_status"
                async with aiohttp.ClientSession() as session:
                    async with session.put(endpoint, json={"status": status}, params={"pair_id": pair_uuid}) as response:
                        return await response.json()
                    
            # self.cursor.execute('''
            #     UPDATE pairs SET status = ? WHERE pair_id = ?
            # ''', (status, pair_uuid))
            # self.db.commit()
        except Exception as e:
            logger.error(f"ERROR SETTING STATUS {e}")

    async def set_positions(self, uuid: str, positions: dict[str, Position]):
        try:
            openPositions = [position.symbol for position in positions.values()]
            sizes = [str(float(position.size)) for position in positions.values()]
            sides = [str(position.side) for position in positions.values()]

            openPositions = ";".join(openPositions)
            sizes = ";".join(sizes)
            sides = ";".join(sides)

            if self.url:
                endpoint = f"{self.url}/wallets"
                async with aiohttp.ClientSession() as session:
                    async with session.put(endpoint, json={"openPositions": openPositions, "sizes": sizes, "sides": sides}, params={"wallet_id": uuid}) as response:
                        return await response.json()
        except Exception as e:
            logger.error(f"ERROR SETTING POSITIONS {e}")
    

    async def get_volume(self, user_id: str, wallet_id: str) -> decimal.Decimal:
        try:
            if self.url:
                endpoint = f"{self.url}/wallets"
                async with aiohttp.ClientSession() as session:
                    async with session.get(endpoint, params={"user_id": user_id}) as response:
                        res = await response.json()
                        res = [WalletStats(uuid=row['wallet_id'], openPositions=row['openPositions'], balance=row['balance'], volume_usdt=row['volume_usdt'], platform=row['platform']) for row in res]

                        for wallet in res:
                            if str(wallet.uuid) == str(wallet_id):
                                return decimal.Decimal(wallet.volume_usdt)
                        logger.error(f"WALLET NOT FOUND {wallet_id}")
                        return decimal.Decimal(0)
            else:
                self.cursor.execute('''
                    SELECT * FROM wallets
                ''')
                res = [WalletStats(uuid=row[0], openPositions=row[1], balance=row[2], volume_usdt=row[3], platform=row[4]) for row in self.cursor.fetchall()]

            for wallet in res:
                if str(wallet.uuid) == str(wallet_id):
                    return decimal.Decimal(wallet.volume_usdt)
        except Exception as e:
            logger.error(f"ERROR GETTING VOLUME {e}")
            return decimal.Decimal(0)