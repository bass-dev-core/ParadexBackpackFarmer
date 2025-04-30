import os
import sys
from loguru import logger
from src.main import DeFutureBot
import asyncio
from src.utils.pair import Pair
from src.utils.stats import Stats
from src.utils.tg import Tg
from src.utils.enums import Platform, platformRow2platform
from src.connectors.paradex.Paradex import Paradex
from src.connectors.Backpack import Backpack
from src.utils.constants import orderTypeMapping
from src.utils.utils import to_structured_config
import pandas as pd

name2connector = {
    Platform.paradex: Paradex,
    Platform.backpack: Backpack,
}
async def main():
    df = pd.read_excel("config.xlsx")
    df = df.fillna("")
    items = df.to_dict(orient="records")
    # cfg = yaml.load(open("config.yaml", "r"), Loader=yaml.SafeLoader)
    processed_cfg = []
    db = Stats()
    tg = Tg(None, None)

    for ix, item in enumerate(items):
        structured = to_structured_config(item)
        pair = await Pair.create(structured)

        db.add_wallet(pair.walletA.uuid, pair.walletA.platform)
        db.add_wallet(pair.walletB.uuid, pair.walletB.platform)

        balanceA = await pair.walletA.connector.get_balance()
        balanceB = await pair.walletB.connector.get_balance()
        
        await db.set_balance(pair.walletA.uuid, balanceA.result)
        await db.set_balance(pair.walletB.uuid, balanceB.result)

        processed_cfg.append(pair)

    # logger.info('\n\n'.join([str(i) for i in stats]))

    app = DeFutureBot(db, tg)
    for pair in processed_cfg:
        await app.add_task(pair, "crocodilo_bombardiro")

    await asyncio.gather(*list(app.tasks.values()))


if __name__ == "__main__":
    if not os.path.exists("logs"):
        os.makedirs("logs")

    logger.remove()  # Remove default handler
    logger.add(
        sys.stderr,
        level=os.getenv("LOG_LEVEL", "DEBUG"),
        colorize=True,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    logger.add("logs/log.log", rotation="10 MB")
    asyncio.run(main()) 