FROM python:3.12-slim

# نصب پیش‌نیازهای سیستمی: FFmpeg برای صدا، libzbar0 برای بارکد
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libzbar0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080

CMD ["python", "-m", "app.main"]
