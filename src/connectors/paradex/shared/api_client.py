"""
Description:
    Paradex client. To be replaced by generated stubs
"""

# built ins
import asyncio
import base64
import hmac
import json
import logging
import sys
import time
from typing import Dict, List, Optional, Tuple
from loguru import logger as logger_loguru
import aiohttp
import websockets

from src.utils.proxy import Proxy
from .api_client_utils import (
    DecimalEncoder,
    auth_message,
    build_modify_order_message,
    derive_stark_key_from_eth_key,
    flatten_signature,
    gen_and_save_recovery_phrase,
    generate_keys,
    get_acc_contract_address_and_call_data,
    get_account,
    is_token_expired,
    onboarding_message,
    order_sign_message,
    stark_key_message,
)
from .api_config import ApiConfig
from .paradex_api_utils import Order
from starknet_py.common import int_from_bytes
from starknet_py.contract import Contract
from starknet_py.net.signer.stark_curve_signer import KeyPair
from .starknet_utils import get_proxy_config
from web3.auto import w3

from src.connectors.paradex.helpers.account import Account


# RESToverHTTP Interface
async def sign_request(
    paradex_maker_secret_key: str, method: str, path: str, body: Dict
) -> Tuple[int, bytes]:
    """
    Creates the required signature necessary
    as apart of all RESToverHTTP requests with Paradex.
    """
    _secret_key: bytes = paradex_maker_secret_key.encode("utf-8")
    _method: bytes = method.encode("utf-8")
    _path: bytes = path.encode("utf-8")
    _body: bytes = body.encode("utf-8")
    signing_key: bytes = base64.b64decode(_secret_key)
    timestamp: str = str(int(time.time() * 1000)).encode("utf-8")
    message: bytes = b"\n".join([timestamp, _method.upper(), _path, _body])
    digest: hmac.digest = hmac.digest(signing_key, message, "sha256")
    signature: bytes = base64.b64encode(digest)

    return timestamp, signature


async def create_rest_headers(
    paradex_jwt: str,
    paradex_maker_secret_key: str,
    method: str,
    path: str,
    body: Dict,
) -> Dict:
    """
    Creates the required headers to authenticate
    Paradex RESToverHTTP requests.
    """
    # timestamp, signature = await sign_request(
    #     paradex_maker_secret_key=paradex_maker_secret_key,
    #     method=method,
    #     path=path,
    #     body=body
    #     )

    headers: Dict = {
        # 'Paradex-API-Timestamp': timestamp.decode('utf-8'),
        # 'Paradex-API-Signature': signature.decode('utf-8'),
        "Authorization": f"Bearer {paradex_jwt}"
    }

    return headers

def check_token_expiry(status_code: int, response: Dict) -> None:
    """
    Checks the response from the Paradex API
    to see if the token has expired.
    """
    if is_token_expired(status_code, response):
        logging.info(response["message"])
        logging.error("Token has expired, please restart the bot.")
        sys.exit(1)


async def post_order_payload(paradex_http_url: str, paradex_jwt: str, payload: dict, proxy: Optional[Dict] = None) -> dict:
    """
    Paradex RESToverHTTP endpoint.
    [POST] /orders
    """
    method: str = "POST"
    path: str = "/orders"
    _payload: str = json.dumps(payload, cls=DecimalEncoder)
    headers: Dict = await create_rest_headers(
        paradex_jwt=paradex_jwt,
        paradex_maker_secret_key="",
        method=method,
        path=path,
        body=_payload,
    )
    response = {}
    logging.debug(f"post_order_payload:{payload}")
    proxy_url = f"http://{proxy['ip']}:{proxy['port']}" if proxy else None
    proxy_auth = aiohttp.BasicAuth(proxy['login'], proxy['password']) if proxy else None

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                paradex_http_url + path, headers=headers, json=payload, proxy=proxy_url, proxy_auth=proxy_auth
            ) as response:
                status_code: int = response.status
                if status_code != 201:
                    logger_loguru.error(f"error creating order: {status_code} {await response.text()}")
                    return {}
                response: Dict = await response.json(content_type=None)
                response["status_code"] = status_code
                check_token_expiry(status_code=status_code, response=response)
                if status_code == 201:
                    logging.info(f"Order Created: {status_code} | Response: {response}")
                else:
                    logging.warning(
                        "Unable to [POST] /orders"
                        f" Status Code:{status_code}"
                        f" Response Text:{response}"
                        f" Order Payload:{payload}"
                    )
        except aiohttp.ClientConnectorError as e:
            logging.error(f"[POST] /orders ClientConnectorError: {e}")
    return response

async def get_paradex_config(
    paradex_http_url: str,
    proxy: Proxy = None,
) -> Dict:
    """
    Paradex RESToverHTTP endpoint.
    [GET] /config
    """
    logging.info("Getting config...")
    path: str = "/system/config"

    headers = dict()
    proxy_url, proxy_auth = proxy.get()
    async with aiohttp.ClientSession() as session:
        async with session.get(paradex_http_url + path, headers=headers, proxy=proxy_url, proxy_auth=proxy_auth) as response:
            status_code: int = response.status
            response: Dict = await response.json()
            logging.info(response)
            if status_code != 200:
                message: str = "Unable to [GET] /system/config"
                logging.error(message)
                logging.error(f"Status Code: {status_code}")
                logging.error(f"Response Text: {response}")
    return response


# JSON-RPCoverWebsocket Interface
async def send_heartbeat_id(websocket: websockets.WebSocketClientProtocol, id: int) -> None:
    """
    Sends a Heartbeat to keep the Paradex WebSocket connection alive.
    """
    await websocket.send(json.dumps({"id": id, "jsonrpc": "2.0", "method": "heartbeat"}))
    logging.debug(f"send_heartbeat_id:{id}")


async def send_auth_id(
    websocket: websockets.WebSocketClientProtocol, paradex_jwt: str, msg_id: str
) -> None:
    """
    Sends an authentication message to the Paradex WebSocket.
    """
    await websocket.send(
        json.dumps(
            {
                "id": msg_id,
                "jsonrpc": "2.0",
                "method": "auth",
                "params": {"bearer": paradex_jwt},
            }
        )
    )


async def subscribe_channel_with_id(
    websocket: websockets.WebSocketClientProtocol, channel: str, sub_id: int
) -> None:
    """
    Subscribe to a named `` WS Channel.
    """
    await websocket.send(
        json.dumps(
            {
                "id": sub_id,
                "jsonrpc": "2.0",
                "method": "subscribe",
                "params": {"channel": channel},
            }
        )
    )


def starknet_account(config: ApiConfig) -> Account:
    if config.starknet_account is not None:
        return config.starknet_account
    
    account = get_account(
        account_address=config.paradex_account,
        account_key=config.paradex_account_private_key,
        paradex_config=config.paradex_config,
    )
    config.starknet_account = account
    return account


async def get_usdc_balance(config: ApiConfig) -> int:
    logging.info("get_usdc_balance")
    usdc_address = config.paradex_config["bridged_tokens"][0]["l2_token_address"]
    account = starknet_account(config)
    usdc_contract_balance = await account.get_balance(usdc_address)
    return usdc_contract_balance


async def deposit_to_paraclear(config: ApiConfig, amount: int) -> None:
    paraclear_address = config.paradex_config["paraclear_address"]
    account = starknet_account(config)
    paraclear_contract = await Contract.from_address(
        provider=account, address=paraclear_address, proxy_config=get_proxy_config()
    )
    logging.info(f"Paraclear Contract: {hex(paraclear_contract.address)}")
    usdc_address = config.paradex_config["bridged_tokens"][0]["l2_token_address"]
    usdc_decimals = config.paradex_config["bridged_tokens"][0]["decimals"]
    usdc_contract = await Contract.from_address(
        provider=account, address=usdc_address, proxy_config=get_proxy_config()
    )
    logging.info(f"USDC Contract: {usdc_contract}")

    amount_usdc = await get_usdc_balance(config)
    amount_paraclear = int(amount * 10 ** (8 - usdc_decimals))
    calls = [
        usdc_contract.functions["increaseAllowance"].prepare_invoke_v1(
            spender=int(paraclear_address, 16), addedValue=amount_usdc
        ),
        paraclear_contract.functions["deposit"].prepare_invoke_v1(int(usdc_address, 16), amount_paraclear),
    ]
    logging.info(f"Allowance increase to paraclear completed: {calls}")
    deposit_info = await account.execute_v1(calls=calls, max_fee=int(5 * 1e17))
    logging.info(f"Deposit Info: {deposit_info}")
    logging.info(f"Waiting for deposit to complete: {deposit_info.transaction_hash}")
    tx_status = await account.client.wait_for_tx(deposit_info.transaction_hash)
    logging.info(f"Deposit completed: {tx_status}")
    return amount / 10**8


async def get_jwt_token(
    paradex_config: Dict, paradex_http_url: str, account_address: str, private_key: str, proxy: Optional[Dict] = None
) -> str:
    logging.info("get_jwt_token")
    token = ""
    chain = int_from_bytes(paradex_config["starknet_chain_id"].encode())
    account = get_account(
        account_address=account_address, account_key=private_key, paradex_config=paradex_config
    )
    now = int(time.time())
    expiry = now + 24 * 60 * 60
    message = auth_message(chain, now, expiry)

    sig = account.sign_message(message)

    headers: Dict = {
        "PARADEX-STARKNET-ACCOUNT": account_address,
        "PARADEX-STARKNET-SIGNATURE": flatten_signature(sig),
        "PARADEX-TIMESTAMP": str(now),
        "PARADEX-SIGNATURE-EXPIRATION": str(expiry),
    }
    path: str = "/auth"
    logging.info(f"get_jwt_token path:{paradex_http_url + path} headers:{headers}")
    proxy_url = f"http://{proxy['ip']}:{proxy['port']}" if proxy else None
    proxy_auth = aiohttp.BasicAuth(proxy['login'], proxy['password']) if proxy else None

    async with aiohttp.ClientSession() as session:
        async with session.post(paradex_http_url + path, headers=headers, proxy=proxy_url, proxy_auth=proxy_auth) as response:
            status_code: int = response.status
            response: Dict = await response.json()
            if status_code != 200:
                message: str = "Unable to [POST] /auth"
                logging.error(message)
                logging.error(f"Status Code: {status_code}")
                logging.error(f"Response Text: {response}")
            logging.info(f"token response:{response}")
            token = response["jwt_token"]
    logging.info("get_jwt_token done")
    return token


async def onboarding(
    paradex_config: Dict,
    paradex_http_url: str,
    account_address: str,
    private_key: str,
    ethereum_account: str,
    proxy: Optional[Dict] = None
) -> str:
    chain = int_from_bytes(paradex_config["starknet_chain_id"].encode())
    account = get_account(
        account_address=account_address, account_key=private_key, paradex_config=paradex_config
    )
    message = onboarding_message(chain)

    sig = account.sign_message(message)

    headers: Dict = {
        "PARADEX-ETHEREUM-ACCOUNT": ethereum_account,
        "PARADEX-STARKNET-ACCOUNT": account_address,
        "PARADEX-STARKNET-SIGNATURE": flatten_signature(sig),
    }
    path: str = '/onboarding'
    body = {'public_key': hex(account.signer.public_key)}
    json_body = json.dumps(body)

    logging.info(f"onboarding path:{paradex_http_url + path} headers:{headers}")
    proxy_url = f"http://{proxy['ip']}:{proxy['port']}" if proxy else None
    proxy_auth = aiohttp.BasicAuth(proxy['login'], proxy['password']) if proxy else None

    async with aiohttp.ClientSession() as session:
        async with session.post(paradex_http_url + path, headers=headers, json=body, proxy=proxy_url, proxy_auth=proxy_auth) as response:
            status_code: int = response.status
            if status_code != 200:
                message: str = "Unable to [POST] /onboarding"
                logging.error(message)
                logging.error(f"Status Code: {status_code}")
                logging.error(f"Response Text: {response}")
            logging.info(f"token response:{response}")
    logging.info("onboarding done")
    return response


def custom_exception_handler(loop, context):
    loop = asyncio.get_event_loop()
    # first, handle with default handler
    loop.default_exception_handler(context)
    loop.stop()


def sign_order(config: ApiConfig, o: Order) -> Tuple[str, str]:
    account = starknet_account(config)
    if o.id:
        message = build_modify_order_message(account._chain_id.value, o)
    else:
        message = order_sign_message(account._chain_id.value, o)

    sig = account.sign_message(message)
    flat_sig = flatten_signature(sig)
    return flat_sig


def get_recovery_phrase(config: ApiConfig) -> str:
    if config.paradex_environment == "local":
        return gen_and_save_recovery_phrase()
    else:
        return config.ethereum_hd_phrase


def generate_accounts(config: ApiConfig):
    if config.ethereum_private_key != "":
        w3.eth.account.enable_unaudited_hdwallet_features()
        account = w3.eth.account.from_key(config.ethereum_private_key)
        eth_address, eth_priv = account.address, account.key.hex()
    else:
        mnemonic = get_recovery_phrase(config)
        eth_address, eth_priv = generate_keys(mnemonic, config.pod_index)

    config.ethereum_account = eth_address
    eth_chain_id = int(config.paradex_config['l1_chain_id'])
    msg = stark_key_message(eth_chain_id)
    # this can be replaces with kms?
    private_key = derive_stark_key_from_eth_key(msg, eth_priv)
    key_pair = KeyPair.from_private_key(private_key)
    config.paradex_account_private_key = hex(private_key)
    proxy_class_hash = config.paradex_config['paraclear_account_proxy_hash']
    account_class_hash = config.paradex_config['paraclear_account_hash']
    account_address = get_acc_contract_address_and_call_data(
        proxy_class_hash,
        account_class_hash,
        hex(key_pair.public_key),
    )
    config.paradex_account = account_address
