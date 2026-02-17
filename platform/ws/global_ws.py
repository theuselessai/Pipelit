"""Global authenticated WebSocket endpoint with Redis pub/sub fan-out."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from config import settings
from database import SessionLocal
from models.user import APIKey

logger = logging.getLogger(__name__)

router = APIRouter()

HEARTBEAT_INTERVAL = 30  # seconds
PONG_TIMEOUT = 10  # seconds


def _authenticate(token: str) -> bool:
    """Validate token against APIKey table. Returns True if valid."""
    db = SessionLocal()
    try:
        api_key = db.query(APIKey).filter(APIKey.key == token).first()
        return api_key is not None
    finally:
        db.close()


@router.websocket("/ws/")
async def global_ws(websocket: WebSocket, token: str = ""):
    if not token or not _authenticate(token):
        await websocket.close(code=1008, reason="Invalid or missing token")
        return

    await websocket.accept()

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    subscriptions: set[str] = set()
    last_activity = time.monotonic()
    waiting_pong = False
    pong_deadline = 0.0
    closed = False

    async def _send(data: dict) -> None:
        nonlocal last_activity
        if closed or websocket.client_state != WebSocketState.CONNECTED:
            return
        await websocket.send_json(data)
        last_activity = time.monotonic()

    async def _reader() -> None:
        """Read client messages (subscribe/unsubscribe/pong)."""
        nonlocal waiting_pong, last_activity
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))

            last_activity = time.monotonic()

            raw = message.get("text")
            if not raw:
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            channel = msg.get("channel", "")

            if msg_type == "subscribe" and channel:
                if channel not in subscriptions:
                    await pubsub.subscribe(channel)
                    subscriptions.add(channel)
                await _send({"type": "subscribed", "channel": channel})

            elif msg_type == "unsubscribe" and channel:
                if channel in subscriptions:
                    await pubsub.unsubscribe(channel)
                    subscriptions.discard(channel)
                await _send({"type": "unsubscribed", "channel": channel})

            elif msg_type == "pong":
                waiting_pong = False

    async def _redis_listener() -> None:
        """Forward Redis pub/sub messages to WebSocket."""
        while True:
            if not subscriptions:
                await asyncio.sleep(0.5)
                continue
            try:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.5,
                )
            except Exception:
                logger.warning("Redis pub/sub get_message failed, retrying", exc_info=True)
                await asyncio.sleep(1)
                continue
            if msg and msg["type"] == "message":
                try:
                    data = json.loads(msg["data"])
                    await _send(data)
                except Exception:
                    pass
            await asyncio.sleep(0.05)

    async def _heartbeat() -> None:
        """Send ping every HEARTBEAT_INTERVAL; close if no pong within PONG_TIMEOUT."""
        nonlocal waiting_pong, pong_deadline
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()

            if waiting_pong and now > pong_deadline:
                logger.debug("Global WS pong timeout, closing")
                return  # exit task → triggers cleanup

            if not waiting_pong and (now - last_activity) >= HEARTBEAT_INTERVAL:
                try:
                    await _send({"type": "ping"})
                except Exception:
                    return
                waiting_pong = True
                pong_deadline = now + PONG_TIMEOUT

    tasks: list[asyncio.Task] = []
    try:
        tasks = [
            asyncio.create_task(_reader(), name="ws-reader"),
            asyncio.create_task(_redis_listener(), name="ws-redis"),
            asyncio.create_task(_heartbeat(), name="ws-heartbeat"),
        ]
        # Wait until any task finishes (error or clean exit)
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Check for unexpected exceptions
        for t in done:
            exc = t.exception()
            if exc and not isinstance(exc, WebSocketDisconnect):
                logger.warning("Global WS task %s failed: %s", t.get_name(), exc)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Global WS unexpected error")
    finally:
        closed = True
        for t in tasks:
            if not t.done():
                t.cancel()
        for ch in list(subscriptions):
            try:
                await pubsub.unsubscribe(ch)
            except Exception:
                pass
        try:
            await pubsub.close()
        except Exception:
            pass
        try:
            await r.close()
        except Exception:
            pass
