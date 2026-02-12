"""Broadcast helper — publish JSON events to Redis channels."""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from decimal import Decimal

import redis as redis_lib

from config import settings


def _json_default(obj: object) -> str | float:

    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)  # float is fine for WS display; precision preserved in DB
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def broadcast(channel: str, event_type: str, data: dict | None = None) -> None:
    """Publish a JSON event to a Redis pub/sub channel.

    Sync function safe to call from FastAPI endpoints and RQ workers.
    """
    r = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        payload: dict = {"type": event_type, "channel": channel, "timestamp": time.time()}
        if data is not None:
            payload["data"] = data
        r.publish(channel, json.dumps(payload, default=_json_default))
    finally:
        r.close()
