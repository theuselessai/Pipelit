"""WebSocket endpoint for streaming execution events via Redis pub/sub."""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import settings
from services.orchestrator import PUBSUB_CHANNEL_PREFIX

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/executions/{execution_id}/")
async def execution_ws(websocket: WebSocket, execution_id: str):
    await websocket.accept()

    r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = r.pubsub()
    channel = f"{PUBSUB_CHANNEL_PREFIX}{execution_id}"

    try:
        await pubsub.subscribe(channel)

        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if msg and msg["type"] == "message":
                try:
                    data = json.loads(msg["data"])
                    await websocket.send_json(data)

                    # Close on terminal events
                    if data.get("type") in ("execution_completed", "execution_failed"):
                        break
                except (json.JSONDecodeError, Exception):
                    logger.debug("Failed to parse pubsub message")

            # Small sleep to prevent tight loop
            await asyncio.sleep(0.05)

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for execution %s", execution_id)
    except Exception:
        logger.exception("WebSocket error for execution %s", execution_id)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await r.close()
