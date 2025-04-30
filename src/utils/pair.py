import dataclasses
from src.utils.data import Wallet
from src.utils.enums import FundingRegime, Platform
from src.connectors.paradex.Paradex import Paradex
from src.connectors.Backpack import Backpack
from src.utils.enums import Platform, platformRow2platform
from src.utils.constants import orderTypeMapping
from src.utils.proxy import Proxy
from src.utils.utils import uuid
name2connector = {
    Platform.paradex: Paradex,
    Platform.backpack: Backpack,
}

@dataclasses.dataclass
class Pair:
    walletA: Wallet
    walletB: Wallet
    tokens: list[str]
    timeoutMin: int
    timeoutMax: int
    positionHoldTimeMin: int
    positionHoldTimeMax: int
    lastCloseTs: int
    timeout: int
    leverage: int
    volumeUSDT: int
    maxLossPercents: int
    is_done: bool
    uuid: str
    holdTimeBeforeMin: float
    holdTimeBeforeMax: float
    funding_regime: FundingRegime

    @classmethod
    async def create(cls, config: dict):
        config['walletA']['platform'] = platformRow2platform[config['walletA']['platform']]
        config['walletB']['platform'] = platformRow2platform[config['walletB']['platform']]
        config['walletA']['uuid'] = uuid(config['walletA']['privateKey']) if config['walletA']['platform'] == Platform.paradex else uuid(config['walletA']['apiSecret'])
        config['walletB']['uuid'] = uuid(config['walletB']['privateKey']) if config['walletB']['platform'] == Platform.paradex else uuid(config['walletB']['apiSecret'])
        config['walletA']['proxy'] = Proxy.parse(config['walletA'].get('proxy', None))
        config['walletB']['proxy'] = Proxy.parse(config['walletB'].get('proxy', None))
        config['walletA']['orderType'] = orderTypeMapping[config['walletA']['orderType']]
        config['walletB']['orderType'] = orderTypeMapping[config['walletB']['orderType']]
        config['walletA']['connector'] = await name2connector[config['walletA']['platform']].create(**config['walletA'])
        config['walletB']['connector'] = await name2connector[config['walletB']['platform']].create(**config['walletB'])
        walletA = Wallet.create(config['walletA'])
        walletB = Wallet.create(config['walletB'])
        tokens = config['tokens']
        timeoutMin = config['timeoutMin']
        timeoutMax = config['timeoutMax']
        positionHoldTimeMin = config['positionHoldTimeMin']
        positionHoldTimeMax = config['positionHoldTimeMax']
        holdTimeBeforeMin = config['holdTimeBeforeMin']
        holdTimeBeforeMax = config['holdTimeBeforeMax']

        lastCloseTs = 0
        timeout = 0
        leverage = config['leverage']
        volumeUSDT = config['volumeUSDT']
        maxLossPercents = config['maxLossPercents']
        is_done = False 
        uuid_ = uuid(f"{walletA.uuid}{walletB.uuid}")

        funding_regime = config.get('fundingRegime', FundingRegime.OFF)
    

        await walletA.connector.get_open_positions()
        await walletB.connector.get_open_positions()

        await walletA.connector.get_balances()
        await walletB.connector.get_balances()

        assert positionHoldTimeMin <= positionHoldTimeMax, f"{positionHoldTimeMin} > {positionHoldTimeMax}"
        assert timeoutMin <= timeoutMax, f"{timeoutMin} <= {timeoutMax}"
        assert holdTimeBeforeMin <= holdTimeBeforeMax, f"{holdTimeBeforeMin} > {holdTimeBeforeMax}"

        return cls(walletA=walletA, walletB=walletB, tokens=tokens, timeoutMin=timeoutMin, timeoutMax=timeoutMax, positionHoldTimeMin=positionHoldTimeMin, positionHoldTimeMax=positionHoldTimeMax, lastCloseTs=lastCloseTs, timeout=timeout, leverage=leverage, volumeUSDT=volumeUSDT, maxLossPercents=maxLossPercents, is_done=is_done, uuid=uuid_, holdTimeBeforeMin=holdTimeBeforeMin, holdTimeBeforeMax=holdTimeBeforeMax, funding_regime=funding_regime)
