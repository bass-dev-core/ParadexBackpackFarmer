# Dockerfile for backend

# Используем официальный Python 3.11 образ
FROM python:3.12

# Устанавливаем системные зависимости для сборки некоторых пакетов
RUN apt-get update && \
    apt-get install -y \
    curl \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    libusb-1.0-0-dev && \
    rm -rf /var/lib/apt/lists/*
# # Устанавливаем Rust и Cargo
# RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -y | sh -s -- -y && \
#     source $HOME/.cargo/env && \
#     rustup default stable

# Устанавливаем Rust через rustup
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# Обновляем PATH для Rust и Cargo
ENV PATH="/root/.cargo/bin:${PATH}"

# # Перезагружаем shell и проверяем установку
# RUN echo "export PATH=/root/.cargo/bin:$PATH" >> ~/.bashrc && \
#     source ~/.bashrc && \
#     rustc --version && \
#     cargo --version

# Установим рабочую директорию
WORKDIR /app

# Копируем зависимости
COPY ./requirements.txt /app/requirements.txt

# Устанавливаем зависимости
RUN pip install -r /app/requirements.txt

# Копируем все файлы из директории backend в контейнер
COPY . /app/

# Указываем команду для старта приложения
CMD ["python", "app.py"]
