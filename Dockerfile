FROM python:3.11-slim

# 安裝系統依賴
# - pandoc: 文件格式轉換
# - libheif-dev: HEIC 圖片支援
# - libheif1: HEIC runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    libheif-dev \
    libheif1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
CMD ["python", "app.py"]
