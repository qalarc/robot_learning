#!/usr/bin/env python3
"""Robot Bus hub -- the interconnect for every agent, sim, sensor and controller.

Design intent: the hub is DUMB. It relays envelopes, keeps a live roster, counts
topics and writes everything to disk. Intelligence lives in the clients.

    python agents/hub.py                 # ws://127.0.0.1:8890/ws  (auto-falls back to
                                         # the next free port, real port -> runs/bus.port)
    curl localhost:8890/health | /roster | /stats | /recent

Protocol v1 (see docs/PROTOCOL.md). One JSON text frame per message:

    {"v":1,"id":"<uuid>","ts":<epoch s>,"src":"<agent>","topic":"<dot.topic>",
     "to":"<optional agent name>","data":{...}}

Delivery rules
  * every client receives every topic EXCEPT high-rate topics (opt-in via bus.sub)
  * "to": name  -> delivered only to that client
  * the hub never interprets `data`
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

REPO = Path(__file__).resolve().parents[1]
HIGH_RATE = {"sim.obs", "vision.hands", "vision.tape", "vision.marker", "vision.frame"}
STRIP = ("jpeg_b64", "png_b64")
MAX_QUEUE = 2000


def strip(msg: dict) -> dict:
    """Copy of an envelope with image payloads removed (keeps the log small)."""
    data = msg.get("data")
    if isinstance(data, dict) and any(k in data for k in STRIP):
        out = dict(msg)
        d = dict(data)
        for k in STRIP:
            if k in d:
                d[k] = f"<stripped {len(str(d[k]))} chars>"
        out["data"] = d
        return out
    return msg


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.name: str | None = None
        self.roles: list = []
        self.caps: list = []
        self.subs: set = set()
        self.joined = time.time()
        self.n_rx = 0
        self.n_tx = 0
        self.out: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self.writer: asyncio.Task | None = None

    def info(self):
        return {
            "name": self.name,
            "roles": self.roles,
            "caps": self.caps,
            "subs": sorted(self.subs),
            "joined": round(self.joined, 3),
            "uptime_s": round(time.time() - self.joined, 1),
            "rx": self.n_rx,
            "tx": self.n_tx,
        }


class Hub:
    def __init__(self, log_path: Path):
        self.clients: dict[str, Client] = {}
        self.stats: dict = defaultdict(int)
        self.recent: dict = defaultdict(lambda: deque(maxlen=40))
        self.started = time.time()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log = open(log_path, "a", encoding="utf-8", buffering=1)

    # ------------------------------------------------------------------ output
    def enqueue(self, c: Client, data: str, high: bool) -> None:
        try:
            c.out.put_nowait(data)
        except asyncio.QueueFull:
            try:
                c.out.get_nowait()  # drop oldest -- a stale obs is worthless
            except asyncio.QueueEmpty:
                pass
            c.out.put_nowait(data)
            self.stats["_dropped"] += 1
        c.n_tx += 1

    async def writer_loop(self, c: Client) -> None:
        try:
            while True:
                data = await c.out.get()
                await c.ws.send(data)
        except (ConnectionClosed, asyncio.CancelledError):
            pass

    def route(self, msg: dict, sender: Client | None) -> None:
        topic = msg.get("topic") or "?"
        self.stats[topic] += 1
        slim = strip(msg)
        self.recent[topic].append(
            {"ts": msg.get("ts"), "src": msg.get("src"), "data": slim.get("data")}
        )
        try:
            self.log.write(json.dumps(slim, separators=(",", ":")) + "\n")
        except (TypeError, ValueError):
            self.stats["_unserialisable"] += 1
        payload = json.dumps(msg, separators=(",", ":"))
        high = topic in HIGH_RATE
        to = msg.get("to")
        if to:
            tgt = self.clients.get(to)
            if tgt is None:
                self.stats["_unroutable"] += 1
                if sender is not None:
                    self.enqueue(
                        sender,
                        json.dumps(
                            {
                                "topic": "log",
                                "data": {
                                    "level": "warn",
                                    "msg": f"no connected client named '{to}'",
                                },
                            }
                        ),
                        False,
                    )
                return
            self.enqueue(tgt, payload, high)
            return
        for c in list(self.clients.values()):
            if (not high) or (topic in c.subs):
                self.enqueue(c, payload, high)

    # ------------------------------------------------------------------ joins
    def name_client(self, c: Client, wanted: str) -> str:
        base = (wanted or "anon").strip() or "anon"
        name, n = base, 2
        while name in self.clients:
            name = f"{base}#{n}"
            n += 1
        c.name = name
        self.clients[name] = c
        return name

    def hello(self, c: Client, msg: dict) -> None:
        data = msg.get("data") or {}
        roles = list(data.get("roles") or [])
        caps = list(data.get("caps") or [])
        if c.name is None:
            self.name_client(c, str(data.get("name") or msg.get("src") or "anon"))
        c.roles = roles or c.roles
        c.caps = caps or c.caps
        self.enqueue(
            c,
            json.dumps(
                {
                    "topic": "bus.roster",
                    "to": c.name,
                    "data": {
                        "you": c.name,
                        "clients": [x.info() for x in self.clients.values()],
                    },
                }
            ),
            False,
        )
        self.route(
            {
                "topic": "bus.join",
                "src": c.name,
                "data": {"name": c.name, "roles": c.roles, "caps": c.caps},
            },
            c,
        )

    async def leave(self, c: Client) -> None:
        name = c.name
        if name and self.clients.get(name) is c:
            del self.clients[name]
            self.route(
                {"topic": "bus.leave", "src": name, "data": {"name": name}}, None
            )
        if c.writer:
            c.writer.cancel()

    # ------------------------------------------------------------------ loop
    async def handler(self, ws) -> None:
        c = Client(ws)
        c.writer = asyncio.create_task(self.writer_loop(c))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    self.stats["_malformed"] += 1
                    continue
                if not isinstance(msg, dict):
                    continue
                c.n_rx += 1
                topic = msg.get("topic")
                if topic == "bus.hello":
                    self.hello(c, msg)
                    continue
                if c.name is None:  # never said hello -> auto-name from src
                    self.name_client(c, str(msg.get("src") or f"anon-{id(c) % 10000}"))
                if topic == "bus.sub":
                    data = msg.get("data") or {}
                    c.subs |= set(data.get("topics") or [])
                    self.enqueue(
                        c,
                        json.dumps(
                            {
                                "topic": "bus.sub_ack",
                                "to": c.name,
                                "data": {"subs": sorted(c.subs)},
                            }
                        ),
                        False,
                    )
                    continue
                if topic == "bus.ping":
                    self.enqueue(
                        c,
                        json.dumps(
                            {
                                "topic": "bus.pong",
                                "to": c.name,
                                "data": {"pong": True, "ts": time.time()},
                            }
                        ),
                        False,
                    )
                    continue
                msg.setdefault("id", str(uuid.uuid4()))
                msg.setdefault("ts", time.time())
                msg.setdefault("src", c.name)
                self.route(msg, c)
        except ConnectionClosed:
            pass
        finally:
            await self.leave(c)

    # ------------------------------------------------------------------ http
    def http(self, connection, request):
        path = (request.path or "/").split("?")[0]
        if path in ("/", "/health", "/roster", "/stats", "/recent"):
            if path == "/health":
                body = {
                    "ok": True,
                    "uptime_s": round(time.time() - self.started, 1),
                    "clients": sorted(self.clients),
                }
            elif path == "/roster":
                body = [c.info() for c in self.clients.values()]
            elif path == "/stats":
                body = {
                    "clients": len(self.clients),
                    "topics": dict(sorted(self.stats.items())),
                }
            else:  # /recent and /
                body = {k: list(v)[-10:] for k, v in self.recent.items()}
            return Response(
                200,
                "OK",
                Headers(
                    {
                        "Content-Type": "application/json",
                        "Access-Control-Allow-Origin": "*",
                    }
                ),
                json.dumps(body, indent=1).encode(),
            )
        return None  # anything else falls through to the WebSocket handshake


async def amain(args) -> None:
    last_err = None
    for port in range(args.port, args.port + 12):
        log_path = REPO / "runs" / "bus" / (time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
        hub = Hub(log_path)
        try:
            async with serve(
                hub.handler,
                args.host,
                port,
                process_request=hub.http,
                max_size=64 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
            ) as server:
                (REPO / "runs").mkdir(parents=True, exist_ok=True)
                (REPO / "runs" / "bus.port").write_text(str(port))
                (REPO / "runs" / "bus.pid").write_text(str(os.getpid()))
                (REPO / "runs" / "bus.log").write_text(str(log_path))
                print(
                    f"ROBOT BUS up  ws://{args.host}:{port}/ws   http://{args.host}:{port}/health",
                    flush=True,
                )
                print(f"logging -> {log_path}", flush=True)
                await server.serve_forever()
                return
        except OSError as e:  # address in use -> try the next port
            last_err = e
            hub.log.close()
            continue
    print(f"no free port in {args.port}..{args.port + 11}: {last_err}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Robot Bus hub (WebSocket relay + blackboard + logger)"
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8890)
    asyncio.run(amain(p.parse_args()))


if __name__ == "__main__":
    main()
