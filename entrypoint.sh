#!/bin/bash
set -e

echo "🔄 Installing yt-dlp from Master branch to fix SoundCloud bugs..."
pip install --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.tar.gz

echo "🚀 Starting the bot..."
exec python -m app.main
