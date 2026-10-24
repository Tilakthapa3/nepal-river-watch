"""Send river alerts to a Telegram channel."""

import os
import re
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL = os.getenv("TELEGRAM_CHANNEL")
# Optional: your own private chat with the bot. Failure details go there
# instead of the public channel. Find the ID with: python3 alert.py chatid
ADMIN_CHAT = os.getenv("TELEGRAM_ADMIN_CHAT")
API = "https://api.telegram.org/bot{}/{}"
# Telegram rejects messages over 4096 characters; leave room for markup.
MAX_LENGTH = 4000
TOKEN_PATTERN = re.compile(r"\d{5,}(?::|%3A)[A-Za-z0-9_-]{20,}")


def _pack(pieces, sep, limit):
    """Join pieces with sep into as few chunks as fit under limit."""
    chunks = []
    current = ""
    for piece in pieces:
        joined = piece if not current else current + sep + piece
        if len(joined) <= limit:
            current = joined
        else:
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def split_message(text, limit=MAX_LENGTH):
    """Split long text between station blocks, or between lines if needed."""
    if len(text) <= limit:
        return [text]
    chunks = []
    for block in _pack(text.split("\n\n"), "\n\n", limit):
        if len(block) <= limit:
            chunks.append(block)
            continue
        for line in _pack(block.split("\n"), "\n", limit):
            while len(line) > limit:
                chunks.append(line[:limit])
                line = line[limit:]
            if line:
                chunks.append(line)
    return chunks


def _post(method, payload):
    resp = requests.post(API.format(TOKEN, method), json=payload, timeout=20)
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram rejected the message: " +
                           str(body.get("description")))
    return body


def send(text, chat_id=None):
    """Post to the channel, or to chat_id if given. Long text is split."""
    chat = chat_id or CHANNEL
    if not TOKEN or not chat:
        raise RuntimeError("TELEGRAM_TOKEN or TELEGRAM_CHANNEL missing from .env")

    body = None
    for chunk in split_message(text):
        body = _post("sendMessage",
                     {"chat_id": chat, "text": chunk, "parse_mode": "HTML"})
    return body


def send_admin(text):
    """Send to your private chat with the bot. False if none is set up."""
    if not ADMIN_CHAT:
        return False
    send(text, chat_id=ADMIN_CHAT)
    return True


def describe(exc):
    """One-line reason for a failure, safe to post: the bot token is removed."""
    text = type(exc).__name__ + ": " + str(exc)
    if TOKEN:
        text = text.replace(TOKEN, "***")
    text = TOKEN_PATTERN.sub("***", text)
    return " ".join(text.split())[:300]


def private_chats():
    """People who messaged the bot recently, as (chat_id, name) pairs."""
    if not TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN missing from .env")
    resp = requests.get(API.format(TOKEN, "getUpdates"), timeout=20)
    body = resp.json()
    if not body.get("ok"):
        raise RuntimeError("Telegram error: " + str(body.get("description")))

    found = {}
    for update in body.get("result", []):
        chat = (update.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private":
            found[chat["id"]] = chat.get("first_name") or chat.get("username") or ""
    return sorted(found.items())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "chatid":
        chats = private_chats()
        if not chats:
            print("No messages yet. Open the bot in Telegram, tap Start, "
                  "then run this again.")
        for chat_id, name in chats:
            print(str(chat_id) + "  " + name)
    else:
        send("River Watch test message. If you can read this, the bot works.")
        print("Sent.")
