#!/bin/bash
set -e

echo "🔄 Updating yt-dlp and clearing cache..."
pip install --upgrade yt-dlp
yt-dlp --rm-cache-dir

echo "🚀 Starting the bot..."
exec python -m app.main
