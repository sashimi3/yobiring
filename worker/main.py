# /// script
# dependencies = ["requests", "slack-bolt"]
# ///
import base64
import binascii
import json
import logging
import os
import threading
import time

import requests
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

BASE = "https://simplemq.tk1b.api.sacloud.jp/v1/queues"
QUEUE = os.getenv("SIMPLE_MQ_QUEUE")
HEADERS = {"Authorization": f"Bearer {os.getenv('SIMPLE_MQ_API_KEY')}"}
API_URL = os.getenv("RECEPTION_API_URL", "http://127.0.0.1:8000")
MAX_AGE_SEC = 120  # 古い呼び鈴は捨てる
POLL_INTERVAL_SEC = 1  # MQ ポーリング間隔
RATE_LIMIT_BACKOFF_SEC = 5  # 429 時の待ち
ERROR_BACKOFF_SEC = 5  # 予期しない例外時の待ち
MQ_TIMEOUT_SEC = 10  # MQ への HTTP タイムアウト
NOTIFY_TIMEOUT_SEC = 5  # API への accepted 通知のタイムアウト
INTERNAL_TOKEN = os.getenv("RECEPTION_INTERNAL_TOKEN", "").strip()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

app = App(token=os.getenv("SLACK_BOT_TOKEN"))
slack = app.client
CHANNEL = os.getenv("SLACK_CHANNEL_ID")
seen: set[str] = set()  # 簡易冪等化。再起動を跨ぐならRedis/DBへ
posted: dict[str, tuple[str, str]] = {}  # call id -> (Slack ts, to)
cancelled: set[str] = set()  # cancel が call より先に届いた分


def call_text(to: str) -> str:
    return f":bell: 受付で呼び出しがあります({to})"


def call_blocks(to: str, call_id: str) -> list[dict]:
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": call_text(to)}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": "accept_call",
                    "text": {"type": "plain_text", "text": "対応します"},
                    "style": "primary",
                    "value": json.dumps({"id": call_id, "to": to}, ensure_ascii=False),
                }
            ],
        },
    ]


def status_blocks(text: str, status: str) -> list[dict]:
    # ボタンを消して状態だけ残す
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": status}]},
    ]


def notify_accepted(call_id: str) -> None:
    # iPad 表示用。失敗しても Slack 側の対応には影響させない
    try:
        requests.post(
            f"{API_URL}/internal/accepted",
            headers={"Authorization": f"Bearer {INTERNAL_TOKEN}"}
            if INTERNAL_TOKEN
            else {},
            json={"id": call_id},
            timeout=NOTIFY_TIMEOUT_SEC,
        ).raise_for_status()
    except requests.RequestException:
        logger.exception("notify_accepted failed id=%s", call_id)


@app.action("accept_call")
def accept_call(ack, body):
    ack()
    v = json.loads(body["actions"][0]["value"])
    status = f":white_check_mark: <@{body['user']['id']}> さんが対応します"
    slack.chat_update(
        channel=body["channel"]["id"],
        ts=body["message"]["ts"],
        text=f"{call_text(v['to'])} {status}",
        blocks=status_blocks(call_text(v["to"]), status),
    )
    posted.pop(v["id"], None)  # 対応済みはキャンセル時にボタンを触らない
    notify_accepted(v["id"])


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
    except (binascii.Error, ValueError, KeyError, TypeError, AssertionError):
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
        text=call_text(payload["to"]),  # 通知・フォールバック用
        blocks=call_blocks(payload["to"], payload["id"]),
    )
    posted[payload["id"]] = (res["ts"], payload["to"])


def handle_cancel(payload: dict) -> None:
    entry = posted.pop(payload["id"], None)
    if entry is None:
        cancelled.add(payload["id"])  # 後から来る call を握りつぶす
        return
    thread_ts, to = entry
    # スレッドでも通知する場合:
    # slack.chat_postMessage(
    #     channel=CHANNEL,
    #     thread_ts=thread_ts,
    #     text="キャンセルされました",
    # )
    # 「対応します」を押せないようにする
    slack.chat_update(
        channel=CHANNEL,
        ts=thread_ts,
        text=f"{call_text(to)} キャンセルされました",
        blocks=status_blocks(f"~{call_text(to)}~", "キャンセルされました"),
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


def poll_mq() -> None:
    while True:
        try:
            r = requests.get(
                f"{BASE}/{QUEUE}/messages",
                headers=HEADERS,
                timeout=MQ_TIMEOUT_SEC,
            )
            if r.status_code == 429:
                time.sleep(RATE_LIMIT_BACKOFF_SEC)
                continue
            r.raise_for_status()
            for msg in r.json().get("messages", []):
                handle(msg)
                requests.delete(
                    f"{BASE}/{QUEUE}/messages/{msg['id']}",
                    headers=HEADERS,
                    timeout=MQ_TIMEOUT_SEC,
                )
        except Exception:
            # スレッドが死ぬと呼び鈴が止まるので握ってリトライ
            logger.exception("poll failed")
            time.sleep(ERROR_BACKOFF_SEC)
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    threading.Thread(target=poll_mq, daemon=True).start()
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()
