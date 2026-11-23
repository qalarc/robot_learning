#!/usr/bin/env python3
"""Round-trip test for the Robot Bus hub + client library.

Starts the hub on a scratch port, then checks every delivery rule in docs/PROTOCOL.md:
hello/roster + rename, broadcast, directed messages, high-rate opt-in, request/reply.

    sim/py/.venv/bin/python agents/test_bus.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = REPO / "sim" / "py" / ".venv" / "bin" / "python"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bus_client import BusClient  # noqa: E402

PORT = 8894


def ok(name: str, cond: bool, extra: str = "") -> bool:
    print(
        f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({extra})" if extra else "")
    )
    return cond


async def checks() -> bool:
    results = []
    async with BusClient(
        "tester-a", url=f"ws://127.0.0.1:{PORT}/ws", roles=["test"]
    ) as a:
        async with BusClient(
            "tester-a", url=f"ws://127.0.0.1:{PORT}/ws"
        ) as b:  # name clash on purpose
            results.append(
                ok(
                    "unique naming (rename name#2)",
                    b.name == "tester-a#2",
                    f"a={a.name} b={b.name}",
                )
            )

            # broadcast: a -> everyone (b not subscribed to high-rate yet)
            await a.send("log", {"level": "info", "msg": "hello-broadcast"})
            m = await b.recv(timeout=2.0, topic="log")
            results.append(ok("broadcast delivery", m is not None))

            # directed
            await a.send("log", {"level": "info", "msg": "direct"}, to=b.name)
            m = await b.recv(timeout=2.0, topic="log")
            results.append(
                ok("directed delivery", m is not None and m["data"]["msg"] == "direct")
            )

            # high-rate is opt-in
            await a.send("sim.obs", {"ep": 0, "step": 1})
            m = await b.recv(timeout=0.7, topic="sim.obs")
            results.append(ok("high-rate hidden before sub", m is None))
            await b.subscribe(["sim.obs"])
            await asyncio.sleep(0.2)
            await a.send("sim.obs", {"ep": 0, "step": 2})
            m = await b.recv(timeout=2.0, topic="sim.obs")
            results.append(
                ok(
                    "high-rate delivered after sub",
                    m is not None and m["data"]["step"] == 2,
                )
            )

            # request/reply with correlation id: b acts as a sim responder
            async def responder() -> None:
                while True:
                    req = await b.recv(topic="sim.cmd", timeout=0.1)
                    if req is not None:
                        await b.reply(req, {"pong": True, "step": 42})

            responder_task = asyncio.create_task(responder())
            await asyncio.sleep(0.2)
            rep = await a.request("sim.cmd", {"cmd": "ping"}, to=b.name, timeout=3.0)
            results.append(
                ok(
                    "request/reply correlation",
                    rep is not None
                    and rep.get("data", {}).get("pong") is True
                    and rep.get("to") == a.name,
                    f"topic={rep.get('topic') if rep else None}",
                )
            )
            responder_task.cancel()

    # roster via http
    import urllib.request

    try:
        roster = json.load(
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/roster", timeout=3)
        )
        results.append(
            ok(
                "GET /roster",
                isinstance(roster, list) and len(roster) == 0,
                f"{len(roster)} clients after disconnect",
            )
        )
        health = json.load(
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=3)
        )
        results.append(ok("GET /health", health.get("ok") is True))
    except Exception as e:  # noqa: BLE001
        results.append(ok("GET endpoints", False, str(e)))
    return all(results)


def main() -> None:
    hub = subprocess.Popen(
        [str(PY), str(REPO / "agents" / "hub.py"), "--port", str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(1.5)
        passed = asyncio.run(checks())
        print("BUS TEST:", "PASS" if passed else "FAIL")
        raise SystemExit(0 if passed else 1)
    finally:
        hub.terminate()
        hub.wait(timeout=5)


if __name__ == "__main__":
    main()
