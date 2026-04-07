"""
Run this once after messaging your bot to get your chat_id.

Step 1: Go to @BotFather on Telegram → /newbot → copy token
Step 2: Paste token into config/settings.py → TELEGRAM_BOT["token"]
Step 3: Send ANY message to your new bot on Telegram
Step 4: Run:  python get_chat_id.py
Step 5: Paste the printed number into TELEGRAM_BOT["chat_id"]
"""
import asyncio
from telegram.bot import get_chat_id
asyncio.run(get_chat_id())
