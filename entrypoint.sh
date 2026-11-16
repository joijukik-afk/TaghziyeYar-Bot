#!/bin/bash
set -e

# ساخت پوشه تنظیمات scdl برای جلوگیری از خطای FileNotFoundError
mkdir -p /root/.config/scdl

echo "🚀 Starting the bot..."
exec python -m app.main
