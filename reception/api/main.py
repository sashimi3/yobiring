import base64
import json
import logging
import os
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("uvicorn.error")

BASE = "https://simplemq.tk1b.api.sacloud.jp/v1/queues"
QUEUE = os.environ["SIMPLE_MQ_QUEUE"].strip()
API_KEY = os.environ["SIMPLE_MQ_API_KEY"].strip()
if not QUEUE or not API_KEY:
    raise RuntimeError("SIMPLE_MQ_QUEUE / SIMPLE_MQ_API_KEY が空です")

TARGETS = ["外出したい", "話がある", "その他"]
COOLDOWN_SEC = 10  # 連打・二度押し対策
CANCEL_WINDOW_SEC = 90  # フロントの待機画面(60秒)より長めに
STATUS_TTL_SEC = 300

app = FastAPI()
client = httpx.AsyncClient(
    base_url=BASE,
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=5,
)
last_called: dict[str, float] = {}
pending: dict[str, tuple[str, float]] = {}  # call id -> (to, ts)
accepted: dict[str, float] = {}  # call id -> ts


class CallRequest(BaseModel):
    to: str


class CancelRequest(BaseModel):
    id: str


class AcceptedRequest(BaseModel):
    id: str


async def enqueue(payload: dict) -> None:
    content = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode()
    ).decode()
    r = await client.post(f"/{QUEUE}/messages", json={"content": content})
    if not r.is_success:
        logger.error("enqueue failed: %s %s %s", r.status_code, r.request.url, r.text)
        raise HTTPException(502, f"enqueue failed: {r.status_code}")


@app.get("/api/targets")
def targets() -> list:
    return TARGETS


@app.post("/api/call", status_code=202)
async def call(req: CallRequest):
    if req.to not in TARGETS:
        raise HTTPException(400, "unknown target")

    now = time.time()
    if now - last_called.get(req.to, 0) < COOLDOWN_SEC:
        # 直前に呼んでいるので積まずに成功扱い
        return {"status": "cooldown"}

    call_id = str(uuid.uuid4())
    await enqueue({"type": "call", "id": call_id, "to": req.to, "ts": now})

    last_called[req.to] = now
    # 期限切れを掃除してから登録
    for k in [k for k, (_, ts) in pending.items() if now - ts > CANCEL_WINDOW_SEC]:
        del pending[k]
    for k in [k for k, ts in accepted.items() if now - ts > STATUS_TTL_SEC]:
        del accepted[k]
    pending[call_id] = (req.to, now)
    return {"status": "queued", "id": call_id}


@app.get("/api/calls/{call_id}")
def call_status(call_id: str):
    return {"state": "accepted" if call_id in accepted else "waiting"}


@app.post("/api/cancel", status_code=202)
async def cancel(req: CancelRequest):
    if req.id not in pending:
        raise HTTPException(404, "not found")
    if req.id in accepted:
        raise HTTPException(409, "already accepted")
    entry = pending.pop(req.id, None)
    if entry is None or time.time() - entry[1] > CANCEL_WINDOW_SEC:
        raise HTTPException(404, "not cancellable")
    to, _ = entry
    await enqueue({"type": "cancel", "id": req.id, "ts": time.time()})
    last_called.pop(to, None)  # すぐ呼び直せるように
    return {"status": "cancel_queued"}


@app.post("/internal/accepted", status_code=204)
def internal_accepted(req: AcceptedRequest):
    # 認証は次のステップで追加
    accepted[req.id] = time.time()
