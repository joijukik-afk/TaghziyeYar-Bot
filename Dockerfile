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

# کپی کردن فایل اجرایی و دادن دسترسی اجرا
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV PORT=8080

# استفاده از اسکریپت راه‌اندازی
CMD ["./entrypoint.sh"]
