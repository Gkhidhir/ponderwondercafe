# Ponder Wonder Cafe Telegram Order Bot

Telegram ordering bot for Ponder Wonder Cafe.

## New Telegram bot
Create the new bot with BotFather and use a username ending in `bot`, for example:
- `@PonderWonderCafeBot`

The actual username must be available in Telegram.

## Environment variables
- `BOT_TOKEN` — token for the NEW bot from BotFather
- `ADMIN_CHAT_ID` — your Telegram user ID
- `DB_PATH` — `orders.db`
- `QR_PATH` — `paynow_qr.png`

The included `paynow_qr.png` is the latest PayNow QR supplied for this bot.

## Run
```bash
pip install -r requirements.txt
python bot.py
```
