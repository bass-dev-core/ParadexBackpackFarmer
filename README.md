
Вот подробный и красивый гайд по запуску вашего софта тремя разными способами: через pip, через uv и через Docker. Также описан этап заполнения конфига.

---

# Гайд по запуску

## 1. Установка и запуск через pip

1. **Клонируйте репозиторий:**
   ```bash
   git clone git@github.com:ohikava/ParadexBackpackFarmer.git
   cd ParadexBackpackFarmer
   ```

2. **Создайте и активируйте виртуальное окружение (рекомендуется):**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # Для Linux/Mac
   venv\Scripts\activate     # Для Windows
   ```

3. **Установите зависимости:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Настройте конфиг:**
   - Откройте файл `config_example.xlsx`.
   - Заполните его своими данными (API-ключи, настройки и т.д.).
   - Сохраните как `config.xlsx` в корне проекта.

5. **Запустите софт:**
   ```bash
   python run.py
   ```

---

## 2. Установка и запуск через uv

[uv](https://github.com/astral-sh/uv) — это быстрый менеджер пакетов и виртуальных окружений для Python.

1. **Установите uv (если не установлен):**
   ```bash
   pip install uv
   ```

2. **Установите зависимости через uv:**
   ```bash
   uv pip install -r requirements.txt
   ```

3. **Настройте конфиг:**
   - Откройте `config_example.xlsx`, заполните и сохраните как `config.xlsx`.

4. **Запустите софт:**
   ```bash
   python run.py
   ```

---

## 3. Запуск через Docker

1. **Соберите Docker-образ:**
   ```bash
   docker build -t myapp .
   ```

2. **Настройте конфиг:**
   - Откройте `config_example.xlsx`, заполните и сохраните как `config.xlsx`.
   - Поместите `config.xlsx` в корень проекта (или укажите путь при запуске контейнера).

3. **Запустите контейнер:**
   ```bash
   docker run -v $(pwd)/config.xlsx:/app/config.xlsx myapp
   ```
   > Для Windows путь может выглядеть так:  
   > `-v %cd%\config.xlsx:/app/config.xlsx`

---

## Важно

- **config.xlsx** — основной файл конфигурации. Без него софт не запустится.  
- Всегда делайте копию `config_example.xlsx` и переименовывайте её в `config.xlsx`, затем заполняйте своими данными.

---

Если возникнут вопросы — смело обращайтесь! 🚀
