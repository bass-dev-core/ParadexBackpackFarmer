Here is a detailed and beautiful guide for running your software in three different ways: via pip, via uv, and via Docker. The configuration step is also described.
---

## Our Links

- [Telegram Channel](https://t.me/BASS_App)
- [Website](https://bassmarket.xyz/)

**💻 Support:** [@ohikava](https://t.me/ohikava)  
**🤝 Collaboration:** [@sharacd](https://t.me/sharacd)

---

If you have any questions, feel free to ask! 🚀
---

# Launch Guide

## 1. Installation and Launch via pip

1. **Clone the repository:**
   ```bash
   git clone git@github.com:ohikava/ParadexBackpackFarmer.git
   cd ParadexBackpackFarmer
   ```

2. **Create and activate a virtual environment (recommended):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # For Linux/Mac
   venv\Scripts\activate     # For Windows
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure settings:**
   - Open the `config_example.xlsx` file.
   - Fill it in with your data (API keys, settings, etc.).  
   - Save it as `config.xlsx` in the project root.
   - _See the bottom of this page for a detailed description of all columns._

5. **Run the software:**
   ```bash
   python run.py
   ```

---

## 2. Installation and Launch via uv

[uv](https://github.com/astral-sh/uv) is a fast package and virtual environment manager for Python.

1. **Install uv (if not installed):**
   ```bash
   pip install uv
   ```

2. **Install dependencies via uv:**
   ```bash
   uv pip install -r requirements.txt
   ```

3. **Configure settings:**
   - Open `config_example.xlsx`, fill it in, and save as `config.xlsx`.
   - _See the bottom of this page for a detailed description of all columns._

4. **Run the software:**
   ```bash
   python run.py
   ```

---

## 3. Launch via Docker

1. **Build the Docker image:**
   ```bash
   docker build -t myapp .
   ```

2. **Configure settings:**
   - Open `config_example.xlsx`, fill it in, and save as `config.xlsx`.
   - Place `config.xlsx` in the project root (or specify the path when running the container).
   - _See the bottom of this page for a detailed description of all columns._

3. **Run the container:**
   ```bash
   docker run -v $(pwd)/config.xlsx:/app/config.xlsx myapp
   ```
   > For Windows, the path may look like this:  
   > `-v %cd%\config.xlsx:/app/config.xlsx`

---

## Important

- **config.xlsx** is the main configuration file. The software will not run without it.  
- Always make a copy of `config_example.xlsx` and rename it to `config.xlsx`, then fill it in with your data.
- _See the bottom of this page for a detailed description of all columns._

| Column name              | Explanation                                                                                   |
|------------------------- |----------------------------------------------------------------------------------------------|
| Tokens                   | Enter the tokens (not pairs) you want to trade. Comma separated (example: Wif, BTC, ETH)     |
| Leverage                 | Margin leverage for use in trading                                                           |
| Volume USDT              | Desired trading volume on each account                                                       |
| Max Loss Percents        | Maximum loss in a single trade in percent                                                    |
| Timeout Min              | Minimum break between trades in minutes                                                      |
| Timeout Max              | Maximum break between trades in minutes                                                      |
| Position Hold Time Min   | What is the minimum amount of time your position will be held open                           |
| Position Hold Time Max   | What is the maximum amount of time your position will be held open                           |
| Hold Time Before Min     | Minimum time from bot launch to opening of the first order (useful when using multiple accounts) |
| Hold Time Before Max     | Maximum time from bot launch to opening of the first order (useful when using multiple accounts) |
| Wallet A private_key     | Private key from wallet A (if the wallet is used for Paradex)                                |
| Wallet A secret api      | Secret api from wallet A (if the wallet is used for BackPack)                                |
| Wallet A api key         | Secret api from wallet A (if the wallet is used for BackPack)                                |
| Wallet A proxy           | Enter proxy data in format - ip:port:login:password                                          |
| Wallet A platform        | Choose Paradex/BackPack. More soon.                                                          |
| Wallet A order type      | Choose Limit/Market. We recommend use on limit and the second one is market.                 |
| Wallet B private_key     | Private key from wallet B (if the wallet is used for Paradex)                                |
| Wallet B secret api      | Secret api from wallet B (if the wallet is used for BackPack)                                |
| Wallet B api key         | Secret api from wallet B (if the wallet is used for BackPack)                                |
| Wallet B proxy           | Enter proxy data in format - ip:port:login:password                                          |
| Wallet B platform        | Choose Paradex/BackPack. More soon.                                                          |
| Wallet B order type      | Choose Limit/Market. We recommend use on limit and the second one is market.                 |

