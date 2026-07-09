FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    pandoc \
    libheif-dev \
    libheif1 \
    poppler-utils \
    ffmpeg \
    musescore3 \
    rubberband-cli \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

ENV QT_QPA_PLATFORM=offscreen

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860
CMD ["python", "app.py"]
