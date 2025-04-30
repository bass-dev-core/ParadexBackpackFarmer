import asyncio
import logging
import os
import time
import traceback
from typing import Dict, List, Optional

import aiohttp
from starknet_py.common import int_from_bytes
from src.connectors.paradex.utils import (
    build_auth_message,
    build_onboarding_message,
    generate_paradex_account,
    get_account,
    get_l1_eth_account,
)
from src.connectors.paradex.shared.api_client import get_paradex_config
from src.utils.proxy import Proxy

paradex_http_url = "https://api.testnet.paradex.trade/v1"


async def perform_onboarding(
    paradex_config: Dict,
    paradex_http_url: str,
    account_address: str,
    private_key: str,
    ethereum_account: str,
    proxy: Optional[Dict] = None
):
    chain_id = int_from_bytes(paradex_config["starknet_chain_id"].encode())
    account = get_account(account_address, private_key, paradex_config)

    message = build_onboarding_message(chain_id)
    sig = account.sign_message(message)

    headers = {
        "PARADEX-ETHEREUM-ACCOUNT": ethereum_account,
        "PARADEX-STARKNET-ACCOUNT": account_address,
        "PARADEX-STARKNET-SIGNATURE": f'["{sig[0]}","{sig[1]}"]',
    }

    url = paradex_http_url + '/onboarding'
    body = {'public_key': hex(account.signer.public_key)}

    logging.info(f"POST {url}")
    logging.info(f"Headers: {headers}")
    logging.info(f"Body: {body}")

    proxy_url = f"http://{proxy['ip']}:{proxy['port']}" if proxy else None
    proxy_auth = aiohttp.BasicAuth(proxy['login'], proxy['password']) if proxy else None

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body, proxy=proxy_url, proxy_auth=proxy_auth) as response:
            status_code: int = response.status
            if status_code == 200:
                logging.info(f"Success: {response}")
                logging.info("Onboarding successful")
            else:
                logging.error(f"Status Code: {status_code}")
                logging.error(f"Response Text: {response}")
                logging.error("Unable to POST /onboarding")
    return response


async def get_jwt_token(
    paradex_config: Dict, paradex_http_url: str, account_address: str, private_key: str, proxy: Proxy = None
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

    logging.info(f"POST {url}")
    logging.info(f"Headers: {headers}")

    proxy_url, proxy_auth = proxy.get()

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, proxy=proxy_url, proxy_auth=proxy_auth) as response:
            status_code: int = response.status
            response: Dict = await response.json()
            if status_code == 200:
                logging.info(f"Success: {response}")
                logging.info("Get JWT successful")
            else:
                logging.error(f"Status Code: {status_code}")
                logging.error(f"Response Text: {response}")
                logging.error("Unable to POST /onboarding")
            token = response["jwt_token"]
    return token


async def get_open_orders(
    paradex_http_url: str,
    paradex_jwt: str,
    proxy: Optional[Dict] = None
) -> List[Dict]:
    headers = {"Authorization": f"Bearer {paradex_jwt}"}

    url = paradex_http_url + '/orders'

    logging.info(f"GET {url}")
    logging.info(f"Headers: {headers}")

    proxy_url = f"http://{proxy['ip']}:{proxy['port']}" if proxy else None
    proxy_auth = aiohttp.BasicAuth(proxy['login'], proxy['password']) if proxy else None

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, proxy=proxy_url, proxy_auth=proxy_auth) as response:
            status_code: int = response.status
            response: Dict = await response.json()
            if status_code == 200:
                logging.info(f"Success: {response}")
                logging.info("Get Open Orders successful")
                return response["results"]
            else:
                logging.error(f"Status Code: {status_code}")
                logging.error(f"Response Text: {response}")
                logging.error("Unable to POST /onboarding")
    return []



