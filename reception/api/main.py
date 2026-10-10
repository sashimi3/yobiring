import base64
import json
import logging
import os
import time

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

BASE = "https://simplemq.tk1b.api.sacloud.jp/v1/queues"
QUEUE = os.environ["SIMPLE_MQ_QUEUE"]
API_KEY = os.environ["SIMPLE_MQ_API_KEY"]
TARGETS = ["用件1", "用件2", "用件3"]
COOLDOWN_SEC = 10  # 連打・二度押し対策


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("uvicorn.error")

app = FastAPI()
client = httpx.AsyncClient(
    base_url=BASE,
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=5,
)
last_called: dict[str, float] = {}


class CallRequest(BaseModel):
    to: str


@app.get("/api/targets")
def targets() -> list[str]:
    return TARGETS


@app.post("/api/call", status_code=202)
async def call(req: CallRequest):
    if req.to not in TARGETS:
        raise HTTPException(400, "unknown target")

    now = time.time()
    if now - last_called.get(req.to, 0) < COOLDOWN_SEC:
        # 直前に呼んでいるので積まずに成功扱い
        return {"status": "cooldown"}

    payload = {"to": req.to, "ts": now}
    content = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode()
    ).decode()

    r = await client.post(f"/{QUEUE}/messages", json={"content": content})
    # if r.status_code != 200:
    #     raise HTTPException(502, "enqueue failed")
    if not r.is_success:
        logger.error("enqueue failed: %s %s %s", r.status_code, r.request.url, r.text)
        raise HTTPException(502, "enqueue failed")

    last_called[req.to] = now
    return {"status": "queued"}
