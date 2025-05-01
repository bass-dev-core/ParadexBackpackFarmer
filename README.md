Here is a detailed and beautiful guide for running your software in three different ways: via pip, via uv, and via Docker. The configuration step is also described.

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

---

If you have any questions, feel free to ask! 🚀
