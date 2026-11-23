#!/usr/bin/env python3
"""Shared Robot Bus client. asyncio-native with a thread-backed sync facade.

    from bus_client import BusClient, SyncBus
    import asyncio

    async def demo():
        async with BusClient("my-agent", roles=["tool"]) as bus:      # hello + roster
            await bus.subscribe(["sim.obs"])
            rid = await bus.request("sim.cmd", {"cmd": "ping"}, to="armsmith-web")
            print(await bus.wait(rid))
            async for msg in bus.messages("sim.obs"):
                print(msg["data"]["step"])

    with SyncBus("my-tool") as bus:                                   # from plain scripts
        bus.send("sim.cmd", {"cmd": "reset", "args": {"seed": 7}}, to="armsmith-web")
        print(bus.request("sim.cmd", {"cmd": "ping"}, to="armsmith-web", timeout=3))

URL resolution order: explicit arg -> $ROBOT_BUS_URL -> runs/bus.port -> ws://127.0.0.1:8890/ws
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8890


def bus_port() -> int:
    env = os.environ.get("ROBOT_BUS_PORT")
    if env and env.isdigit():
        return int(env)
    try:
        return int((REPO / "runs" / "bus.port").read_text().strip())
    except (OSError, ValueError):
        return DEFAULT_PORT


def resolve_url(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("ROBOT_BUS_URL")
    if env:
        return env
    return f"ws://127.0.0.1:{bus_port()}/ws"


def http_base() -> str:
    u = resolve_url()
    return "http://" + u.split("//", 1)[1].split("/", 1)[0]


class BusClient:
    def __init__(
        self, name: str, url: str | None = None, roles=(), caps=(), subscribe=()
    ):
        self.wanted = name
        self.name: str | None = None  # the hub may rename us (name#2)
        self.url = resolve_url(url)
        self.roles = list(roles)
        self.caps = list(caps)
        self.subs = set(subscribe)
        self.ws = None
        self._reader: asyncio.Task | None = None
        self._inbox: asyncio.Queue = asyncio.Queue(maxsize=10000)
        self._pending: dict[str, asyncio.Future] = {}
        self.connected = asyncio.Event()

    # ------------------------------------------------------------------ setup
    async def connect(self, timeout: float = 8.0) -> "BusClient":
        self.ws = await connect(
            self.url, max_size=64 * 1024 * 1024, ping_interval=20, ping_timeout=20
        )
        self._reader = asyncio.create_task(self._read_loop())
        await self._ws_send(
            {
                "topic": "bus.hello",
                "data": {"name": self.wanted, "roles": self.roles, "caps": self.caps},
            }
        )
        await asyncio.wait_for(self.connected.wait(), timeout)
        if self.subs:  # opt in to high-rate topics requested at construction
            await self._ws_send(
                {"topic": "bus.sub", "data": {"topics": sorted(self.subs)}}
            )
        return self

    async def __aenter__(self) -> "BusClient":
        return await self.connect()

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ io
    async def _ws_send(self, envelope: dict) -> None:
        if self.ws is None:
            raise ConnectionError("not connected")
        await self.ws.send(json.dumps(envelope, separators=(",", ":")))

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("topic") == "bus.roster":
                    self.name = (msg.get("data") or {}).get("you") or self.wanted
                    self.connected.set()
                    continue
                fut = self._pending.get(msg.get("id"))
                if fut is not None and not fut.done():
                    fut.set_result(msg)
                    continue
                try:
                    self._inbox.put_nowait(msg)
                except asyncio.QueueFull:
                    self._inbox.get_nowait()  # drop oldest
                    self._inbox.put_nowait(msg)
        except (ConnectionClosed, asyncio.CancelledError):
            pass
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("bus disconnected"))
            self._pending.clear()

    def envelope(self, topic: str, data: Any = None, to: str | None = None) -> dict:
        return {
            "v": 1,
            "id": str(uuid.uuid4()),
            "ts": time.time(),
            "src": self.name or self.wanted,
            "topic": topic,
            **({"to": to} if to else {}),
            "data": data,
        }

    # ------------------------------------------------------------------ api
    async def subscribe(self, topics) -> None:
        self.subs |= set(topics)
        await self._ws_send({"topic": "bus.sub", "data": {"topics": sorted(self.subs)}})

    async def send(self, topic: str, data: Any = None, to: str | None = None) -> str:
        env = self.envelope(topic, data, to)
        await self._ws_send(env)
        return env["id"]

    async def reply(self, request: dict, data: Any = None) -> None:
        """Answer a request on the bus, echoing its id so the sender correlates."""
        if not isinstance(request, dict):
            return
        req_data = request.get("data") or {}
        reply_topic = req_data.get("reply_to") or f"{request.get('src', 'x')}.reply"
        env = {
            "v": 1,
            "id": request.get("id", str(uuid.uuid4())),
            "ts": time.time(),
            "src": self.name or self.wanted,
            "topic": reply_topic,
            "to": request.get("src"),
            "data": data,
        }
        await self._ws_send(env)

    async def request(
        self,
        topic: str,
        data: Any = None,
        to: str | None = None,
        timeout: float = 3.0,
        reply_topic: str | None = None,
    ) -> dict | None:
        """Send and wait for the correlated reply (reply carries our request id)."""
        data = dict(data or {})
        if reply_topic:
            data["reply_to"] = reply_topic
        env = self.envelope(topic, data, to)
        fut = asyncio.get_running_loop().create_future()
        self._pending[env["id"]] = fut
        try:
            await self._ws_send(env)
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(env["id"], None)

    async def wait(self, request_id: str, timeout: float = 3.0) -> dict | None:
        """Register interest in a reply that was sent with send() (no blocking on it)."""
        fut = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(request_id, None)

    async def recv(
        self, timeout: float | None = None, topic: str | None = None
    ) -> dict | None:
        """Next inbox message (optionally filtered by topic; others are kept in a side list)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        side: list = []
        try:
            while True:
                remaining = (
                    None if deadline is None else max(0.0, deadline - time.monotonic())
                )
                try:
                    msg = await asyncio.wait_for(self._inbox.get(), remaining)
                except asyncio.TimeoutError:
                    return None
                if topic is None or msg.get("topic") == topic:
                    return msg
                side.append(msg)
        finally:
            for m in reversed(side):  # put back what we skipped
                try:
                    self._inbox.put_nowait(m)
                except asyncio.QueueFull:
                    break

    async def messages(self, topic: str | None = None):
        """async for msg in bus.messages('sim.obs')"""
        while True:
            msg = await self.recv(topic=topic)
            if msg is None:
                return
            yield msg


class SyncBus:
    """Thread-backed facade so plain scripts can use the bus without writing asyncio."""

    def __init__(
        self, name: str, url: str | None = None, roles=(), caps=(), subscribe=()
    ):
        self._loop = asyncio.new_event_loop()
        self.client = BusClient(name, url, roles, caps, subscribe)
        self._thread = threading.Thread(
            target=self._run, name=f"bus-{name}", daemon=True
        )
        self._inbox: queue.Queue = queue.Queue(maxsize=10000)
        self._thread.start()
        # wait for hello/roster
        for _ in range(200):
            if self.client.connected.is_set() or not self._thread.is_alive():
                break
            time.sleep(0.05)
        if not self.client.connected.is_set():
            raise ConnectionError(
                f"bus unreachable at {self.client.url} -- is `python agents/hub.py` running?"
            )

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)

        async def pump():
            await self.client.connect()
            while True:
                msg = await self.client.recv()
                if msg is None:
                    continue
                try:
                    self._inbox.put_nowait(msg)
                except queue.Full:
                    self._inbox.get_nowait()
                    self._inbox.put_nowait(msg)

        try:
            self._loop.run_until_complete(pump())
        except Exception:
            pass

    def _call(self, coro, timeout: float | None = None):
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout)

    @property
    def name(self) -> str:
        return self.client.name or self.client.wanted

    def subscribe(self, topics) -> None:
        self._call(self.client.subscribe(topics), 5)

    def send(self, topic: str, data: Any = None, to: str | None = None) -> str:
        return self._call(self.client.send(topic, data, to), 5)

    def request(
        self, topic: str, data: Any = None, to: str | None = None, timeout: float = 3.0
    ):
        return self._call(self.client.request(topic, data, to, timeout), timeout + 5)

    def recv(self, timeout: float = 1.0, topic: str | None = None):
        deadline = time.monotonic() + timeout
        side: list = []
        try:
            while True:
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    msg = self._inbox.get(timeout=remaining)
                except queue.Empty:
                    return None
                if topic is None or msg.get("topic") == topic:
                    return msg
                side.append(msg)
        finally:
            for m in reversed(side):
                try:
                    self._inbox.put_nowait(m)
                except queue.Full:
                    break

    def close(self) -> None:
        self._call(self.client.close(), 5)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.close()
        except Exception:
            pass
