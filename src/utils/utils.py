import asyncio
from decimal import Decimal
import decimal
import hashlib
import json
import math
import random
import aiohttp
from loguru import logger
import functools
from src.utils.enums import FundingRegime, OrderSide, FunctionStatus
from src.utils.data import OrderBook, FunctionOutput
from src.utils.proxy import Proxy
from copy import deepcopy
import base64
import json
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from eth_account import Account
from eth_keys import keys

def handle_errors_async(error_value = None, logger_prefix: str = ""):
    def outer(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # raise e
                logger.error(f"{logger_prefix} {func.__name__}: {str(e)}")
                return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=str(e))
    
        return wrapper
    return outer

def handle_errors_sync(error_value = None, logger_prefix: str = ""):
    def outer(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"{logger_prefix} {func.__name__}: {str(e)}")
                return FunctionOutput(status=FunctionStatus.ERROR, result=None, error=str(e))

        return wrapper
    return outer

def calculate_pnl(entry_price: Decimal, markPrice: Decimal, leverage: Decimal, side: OrderSide):
    if side == OrderSide.BUY:
        exit_price = markPrice
        pnl = (exit_price - entry_price) / entry_price * leverage
    else:
        exit_price = markPrice
        pnl = (entry_price - exit_price) / entry_price * leverage

    return pnl
    
    
def hash(string: str):
    return hashlib.sha256(string.encode()).hexdigest()


async def _request(url: str, method: str, body: dict = {}, headers: dict = {}, proxy: Proxy = Proxy()):
    if method == "POST":
        proxy_url, proxy_auth = proxy.get()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    url, headers=headers, json=body, proxy=proxy_url, proxy_auth=proxy_auth
                ) as response:
                    return response.status, await response.text()
    elif method == "GET":
        proxy_url, proxy_auth = proxy.get()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    url, headers=headers, proxy=proxy_url, proxy_auth=proxy_auth
                ) as response:
                    return response.status, await response.text()
    elif method == "DELETE":
        proxy_url, proxy_auth = proxy.get()
        async with aiohttp.ClientSession() as session:
            if body:
                async with session.delete(
                        url, headers=headers, proxy=proxy_url, data=json.dumps(body), proxy_auth=proxy_auth
                    ) as response:
                        return response.status, await response.text()
            else:
                async with session.delete(
                        url, headers=headers, proxy=proxy_url, proxy_auth=proxy_auth
                    ) as response:
                        return response.status, await response.text()
    else:
        raise ValueError(f"Invalid method: {method}")

async def send_request(url: str, method: str, body: dict = {}, headers: dict = {}, proxy: Proxy = Proxy(), desired_status_code: int = 200, return_json=True, max_attempts: int = 5, base_delay: int = 1, max_delay: int = 64, errors_whitelist: list = [], logger_prefix: str = ""):
    try:
        attempts = 0
        while True:
            status_code, text = await _request(url=url, method=method, body=body, headers=headers, proxy=proxy)            
            if status_code != desired_status_code:
                for error in errors_whitelist:
                    if error in text:
                        return {"status": False, "data": None, "error": f"Error: {status_code} {text}"}
                else:
                    if attempts < max_attempts:
                        logger.error(f"{logger_prefix} {status_code} {text}")
                        attempts += 1
                        wait_time = min(base_delay * (2 ** attempts), max_delay)
                        wait_time += random.uniform(0, 0.5)
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise Exception(f"{logger_prefix} {status_code} {text}")
            
            if return_json:
                data = json.loads(text)
            else:
                data = text
            return {"status": True, "data": data, "error": None}
    except Exception as e:
        logger.error(f"{logger_prefix} {e}")
        return {"status": False, "data": None, "error": e}


def uuid(input_string: str) -> str:
    input_string = str(input_string)
    hash_object = hashlib.sha256(input_string.encode())
    return hash_object.hexdigest()[:8]


def validate_config(config: dict) -> bool:
    pass 

def to_structured_config(item):
    return {
        "walletA": {
            "platform": item["wallet_a_platform"],
            "apiKey": item["wallet_a_api_key"],
            "apiSecret": item["wallet_a_secret_api"],
            "privateKey": item["wallet_a_private_key"],
            "proxy": item["wallet_a_proxy"],
            "orderType": item["wallet_a_order_type"],

        },
        "walletB": {
            "platform": item["wallet_b_platform"],
            "apiKey": item["wallet_b_api_key"],
            "apiSecret": item["wallet_b_secret_api"],
            "privateKey": item["wallet_b_private_key"],
            "proxy": item["wallet_b_proxy"],
            "orderType": item["wallet_b_order_type"],
        },
        "tokens": [i.strip() for i in item["tokens"].split(",")],
        "timeoutMin": item["timeoutMin"],
        "timeoutMax": item["timeoutMax"],
        "positionHoldTimeMin": item["positionHoldTimeMin"],
        "positionHoldTimeMax": item["positionHoldTimeMax"],
        "leverage": item["leverage"],
        "volumeUSDT": item["volumeUSDT"],
        "maxLossPercents": item["maxLossPercents"],
        "holdTimeBeforeMin": item.get("holdTimeBeforeMin", 0),
        "holdTimeBeforeMax": item.get("holdTimeBeforeMax", 0),
        "secret": item.get("secret", ""),
        "fundingRegime": item.get("fundingRegime", FundingRegime.OFF),
    }



def generate_key_from_password(password, salt=b'sun_araw'):
    """Generate a Fernet key from a password and salt."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key


def decrypt_sensitive_data(encrypted_data, secret_key):
    if not encrypted_data:
        return encrypted_data
    """Decrypt data that was encrypted with the given key."""
    key = generate_key_from_password(secret_key)
    f = Fernet(key)
    
    try:
        # Decode the base64 encoded encrypted data
        decoded_data = base64.urlsafe_b64decode(encrypted_data.encode())
        
        # Decrypt the data
        decrypted_data = f.decrypt(decoded_data).decode()
        return decrypted_data
    except Exception as e:
        # If decryption fails, return the original data
        print(f"Decryption failed: {e}")
        return encrypted_data

def encrypt_sensitive_data(data, secret_key):
    """Encrypt sensitive data with the given key."""
    key = generate_key_from_password(secret_key)
    f = Fernet(key)
    
    # Convert data to string if it's not already
    if not isinstance(data, str):
        data = str(data)    
    # Encrypt the data
    encrypted_data = f.encrypt(data.encode())
    return base64.urlsafe_b64encode(encrypted_data).decode()

def get_public_key_from_private_key(private_key: str) -> str:
    account = Account.from_key(private_key)
    return account.address


async def send_message(message: str, bot_token: str, chat_id: str, thread_id: str):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        params = {
            "chat_id": chat_id,
            "message_thread_id": thread_id,
            "text": message
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                return await response.json()
    except Exception as e:
        logger.error(f"error sending message to Telegram: {e}")
        return None


def truncate_decimal(number, digits) -> float:
    # Improve accuracy with floating point operations, to avoid truncate(16.4, 2) = 16.39 or truncate(-1.13, 2) = -1.12
    nbDecimals = len(str(number).split('.')[1]) 
    if nbDecimals <= digits:
        return number
    stepper = 10.0 ** digits
    return math.trunc(stepper * number) / stepper

def calculate_funding_delta(funding_rate_a: float, funding_rate_b: float) -> float:
    return float(abs(funding_rate_a - funding_rate_b))