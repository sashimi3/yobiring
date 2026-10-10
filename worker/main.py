# /// script
# dependencies = ["requests", "slack-sdk"]
# ///
import base64
import binascii
import json
import logging
import os
import time

import requests
from slack_sdk import WebClient

BASE = "https://simplemq.tk1b.api.sacloud.jp/v1/queues"
QUEUE = os.getenv("SIMPLE_MQ_QUEUE")
HEADERS = {"Authorization": f"Bearer {os.getenv('SIMPLE_MQ_API_KEY')}"}
MAX_AGE_SEC = 120  # 古い呼び鈴は捨てる

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

slack = WebClient(token=os.getenv("SLACK_BOT_TOKEN"))
seen: set[str] = set()  # 簡易冪等化. 再起動を跨ぐなら永続化が必要.


def decode(msg: dict) -> dict | None:
    try:
        raw = base64.b64decode(msg["content"], validate=True)
        payload = json.loads(raw)
        # payload["to"], payload["ts"]  # 必須キーの確認
        return payload
    except (binascii.Error, ValueError, KeyError, TypeError):
        logger.warning(
            "invalid message id=%s content=%.80r", msg.get("id"), msg.get("content")
        )
        return None


def handle(msg: dict) -> None:
    payload = decode(msg)
    if payload is None:
        return  # 呼び出し元で削除される
    if msg["id"] in seen:
        return
    if time.time() - payload["ts"] > MAX_AGE_SEC:
        return
    slack.chat_postMessage(
        channel=os.getenv("SLACK_CHANNEL_ID"),
        text=f":bell: 受付で呼び出しがあります({payload.get('to', '')})",
    )
    seen.add(msg["id"])


while True:
    r = requests.get(f"{BASE}/{QUEUE}/messages", headers=HEADERS, timeout=10)
    if r.status_code == 429:
        time.sleep(5)
        continue
    r.raise_for_status()
    for msg in r.json().get("messages", []):
        handle(msg)
        requests.delete(
            f"{BASE}/{QUEUE}/messages/{msg['id']}", headers=HEADERS, timeout=10
        )
    time.sleep(1)
