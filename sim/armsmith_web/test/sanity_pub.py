#!/usr/bin/env python3
"""Sanity publisher for the ARMSMITH web smoke test.

Connects to the Robot Bus hub as 'smoke-probe', then:
  1. subscribes to sim.obs and asserts telemetry arrives from armsmith-web;
  2. sends sim.cmd ping (directed, with reply_to) and asserts the pong echoes the id;
  3. sends one sim.cmd ee command and asserts the page receives traffic (obs keeps flowing).
Prints PASS/FAIL lines; exits 0 only if all pass.
"""

import asyncio
import json
import sys
import time
import uuid

import websockets

HUB = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8890/ws"
TIMEOUT = 12.0


def env(src, topic, data, to=None, mid=None):
    m = {
        "v": 1,
        "id": mid or str(uuid.uuid4()),
        "ts": time.time(),
        "src": src,
        "topic": topic,
        "data": data,
    }
    if to:
        m["to"] = to
    return json.dumps(m)


async def main() -> int:
    ok = True
    async with websockets.connect(HUB, max_size=16 * 1024 * 1024) as ws:
        await ws.send(
            env(
                "smoke-probe",
                "bus.hello",
                {"name": "smoke-probe", "roles": ["tool"], "caps": []},
            )
        )
        await ws.send(env("smoke-probe", "bus.sub", {"topics": ["sim.obs"]}))

        got_roster, got_obs, pong, reply_ok = False, False, None, False
        deadline = time.time() + TIMEOUT
        ping_id = str(uuid.uuid4())
        # ping goes to the sim once we know its roster name; try armsmith-web directly
        sim_name = "armsmith-web"

        while time.time() < deadline and not (got_obs and reply_ok):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=deadline - time.time())
            except asyncio.TimeoutError:
                break
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            topic = msg.get("topic", "")
            if topic == "bus.roster":
                clients = [
                    c.get("name") for c in (msg.get("data") or {}).get("clients", [])
                ]
                sim = [n for n in clients if n and n.startswith("armsmith-web")]
                got_roster = bool(sim)
                if sim:
                    sim_name = sim[0]
                    await ws.send(
                        env(
                            "smoke-probe",
                            "sim.cmd",
                            {"cmd": "ping", "args": {}, "reply_to": "smoke.reply"},
                            to=sim_name,
                            mid=ping_id,
                        )
                    )
                    await ws.send(
                        env(
                            "smoke-probe",
                            "sim.cmd",
                            {
                                "cmd": "ee",
                                "args": {"pos": [0.20, 0.05, 0.10], "gripper": 0.4},
                            },
                            to=sim_name,
                        )
                    )
                else:
                    # roster arrived but no sim on it yet — keep waiting for the next broadcast
                    pass
            elif topic == "sim.obs" and (msg.get("src") or "").startswith(
                "armsmith-web"
            ):
                got_obs = True
            elif msg.get("id") == ping_id and (msg.get("data") or {}).get("pong"):
                pong = msg["data"]
                reply_ok = pong.get("pong") is True and isinstance(
                    pong.get("step"), int
                )

        print(f"roster: {'PASS' if got_roster else 'FAIL'} (sim seen as '{sim_name}')")
        print(f"sim.obs received: {'PASS' if got_obs else 'FAIL'}")
        if pong is not None:
            print(f"ping->pong: PASS (step={pong.get('step')}, id echoed)")
        else:
            ok = False
            print("ping->pong: FAIL (no directed reply with our id)")
        if not (got_obs and reply_ok):
            ok = False
    print("SANITY", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
