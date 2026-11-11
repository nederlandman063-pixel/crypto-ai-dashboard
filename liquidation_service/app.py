"""Continuously collect public Binance USD-M liquidation events."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from contextlib import suppress
from dataclasses import asdict
from typing import Any

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

from core import (
    STREAM_URL,
    WINDOW_MS,
    LiquidationEvent,
    parse_liquidation_event,
    summarize_events,
)

PERSIST_INTERVAL_SECONDS = 60


class EventStore:
    def __init__(self) -> None:
        self.events: deque[LiquidationEvent] = deque()
        self.lock = asyncio.Lock()
        self.bucket_name = os.environ.get("LIQUIDATION_BUCKET", "").strip()
        self.object_name = os.environ.get("LIQUIDATION_OBJECT", "liquidations/events.json")

    def _prune_unlocked(self, now_ms: int) -> None:
        cutoff = now_ms - WINDOW_MS
        while self.events and self.events[0].timestamp < cutoff:
            self.events.popleft()

    async def add(self, event: LiquidationEvent) -> None:
        async with self.lock:
            self.events.append(event)
            self._prune_unlocked(int(time.time() * 1000))

    async def snapshot(self) -> list[LiquidationEvent]:
        async with self.lock:
            self._prune_unlocked(int(time.time() * 1000))
            return list(self.events)

    def _blob(self):
        from google.cloud import storage

        client = storage.Client()
        return client.bucket(self.bucket_name).blob(self.object_name)

    async def load(self) -> None:
        if not self.bucket_name:
            return

        def download() -> list[dict[str, Any]]:
            blob = self._blob()
            if not blob.exists():
                return []
            payload = json.loads(blob.download_as_text())
            return payload if isinstance(payload, list) else []

        records = await asyncio.to_thread(download)
        loaded: list[LiquidationEvent] = []
        for item in records:
            try:
                loaded.append(LiquidationEvent(**item))
            except (TypeError, ValueError):
                continue
        loaded.sort(key=lambda event: event.timestamp)
        async with self.lock:
            self.events = deque(loaded)
            self._prune_unlocked(int(time.time() * 1000))

    async def persist(self) -> None:
        if not self.bucket_name:
            return
        records = [asdict(event) for event in await self.snapshot()]

        def upload() -> None:
            self._blob().upload_from_string(
                json.dumps(records, separators=(",", ":")),
                content_type="application/json",
            )

        await asyncio.to_thread(upload)


async def collect_forever(app: web.Application) -> None:
    store: EventStore = app["store"]
    delay = 1
    while True:
        try:
            timeout = ClientTimeout(total=None, sock_connect=20, sock_read=600)
            async with ClientSession(timeout=timeout) as session:
                async with session.ws_connect(STREAM_URL, heartbeat=180) as socket:
                    app["connected"] = True
                    delay = 1
                    async for message in socket:
                        if message.type == WSMsgType.TEXT:
                            event = parse_liquidation_event(json.loads(message.data))
                            if event is not None:
                                await store.add(event)
                                app["last_event_time"] = event.timestamp
                        elif message.type in {WSMsgType.CLOSED, WSMsgType.ERROR}:
                            break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            app["last_error"] = str(exc)
        finally:
            app["connected"] = False
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60)


async def persist_forever(app: web.Application) -> None:
    store: EventStore = app["store"]
    while True:
        await asyncio.sleep(PERSIST_INTERVAL_SECONDS)
        try:
            await store.persist()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            app["last_error"] = str(exc)


async def summary(request: web.Request) -> web.Response:
    store: EventStore = request.app["store"]
    payload = summarize_events(await store.snapshot(), now_ms=int(time.time() * 1000))
    return web.json_response(payload, headers={"Access-Control-Allow-Origin": "*"})


async def health(request: web.Request) -> web.Response:
    events = await request.app["store"].snapshot()
    payload = {
        "status": "ok" if request.app["connected"] else "reconnecting",
        "connected": request.app["connected"],
        "events_in_window": len(events),
        "last_event_time": request.app["last_event_time"],
        "last_error": request.app["last_error"],
    }
    return web.json_response(payload)


async def start_background_tasks(app: web.Application) -> None:
    await app["store"].load()
    app["collector_task"] = asyncio.create_task(collect_forever(app))
    app["persist_task"] = asyncio.create_task(persist_forever(app))


async def stop_background_tasks(app: web.Application) -> None:
    for name in ("collector_task", "persist_task"):
        app[name].cancel()
    for name in ("collector_task", "persist_task"):
        with suppress(asyncio.CancelledError):
            await app[name]
    await app["store"].persist()


def create_app() -> web.Application:
    app = web.Application()
    app["store"] = EventStore()
    app["connected"] = False
    app["last_event_time"] = None
    app["last_error"] = None
    app.router.add_get("/summary", summary)
    app.router.add_get("/health", health)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(stop_background_tasks)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), port=int(os.environ.get("PORT", "8080")))
