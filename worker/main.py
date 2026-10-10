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
CHANNEL = os.getenv("SLACK_CHANNEL_ID")
seen: set[str] = set()  # 簡易冪等化。再起動を跨ぐならRedis/DBへ
posted: dict[str, str] = {}  # call id -> Slack ts
cancelled: set[str] = set()  # cancel が call より先に届いた分


def decode(msg: dict) -> dict | None:
    try:
        raw = base64.b64decode(msg["content"], validate=True)
        payload = json.loads(raw)
        payload.setdefault("type", "call")
        assert "id" in payload and "ts" in payload, "missing required keys"
        if payload["type"] == "call":
            assert "to" in payload, "missing required key 'to'"
        elif payload["type"] != "cancel":
            raise ValueError(payload["type"])
        return payload
    except (binascii.Error, ValueError, KeyError, TypeError):
        logger.warning(
            "invalid message id=%s content=%.80r", msg.get("id"), msg.get("content")
        )
        return None


def handle_call(payload: dict) -> None:
    if payload["id"] in cancelled:
        cancelled.discard(payload["id"])
        return
    if time.time() - payload["ts"] > MAX_AGE_SEC:
        return
    res = slack.chat_postMessage(
        channel=CHANNEL,
        text=f":bell: 受付で呼び出しがあります({payload['to']})",
    )
    posted[payload["id"]] = res["ts"]


def handle_cancel(payload: dict) -> None:
    thread_ts = posted.pop(payload["id"], None)
    if thread_ts is None:
        cancelled.add(payload["id"])  # 後から来る call を握りつぶす
        return
    slack.chat_postMessage(
        channel=CHANNEL,
        thread_ts=thread_ts,
        text="キャンセルされました",
    )


def handle(msg: dict) -> None:
    payload = decode(msg)
    if payload is None:
        return  # 呼び出し元で削除される
    if msg["id"] in seen:
        return
    if payload["type"] == "cancel":
        handle_cancel(payload)
    else:
        handle_call(payload)
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
