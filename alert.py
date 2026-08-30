"""Send river alerts to a Telegram channel."""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL")
API = "https://api.telegram.org/bot{}/sendMessage"


def send(text):
    if not TOKEN or not CHANNEL:
        raise RuntimeError("TELEGRAM_TOKEN or TELEGRAM_CHANNEL missing from .env")

    resp = requests.post(
        API.format(TOKEN),
        json={"chat_id": CHANNEL, "text": text, "parse_mode": "HTML"},
        timeout=20,
    )
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram rejected the message: " +
                           str(body.get("description")))
    return body


if __name__ == "__main__":
    send("River Watch test message. If you can read this, the bot works.")
    print("Sent.")