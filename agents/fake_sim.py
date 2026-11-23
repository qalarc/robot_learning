#!/usr/bin/env python3
"""fake-sim -- headless stub simulator for the Robot Bus (protocol v1, docs/PROTOCOL.md).

Implements the full `sim.cmd` surface WITHOUT a browser so controllers, the CLI
and Codex can be tested anywhere:

  * 6 joint values with a slew-rate servo model (2.5 rad/s limit).
  * Abstract end-effector that moves toward the commanded target at a fixed
    speed (0.5 m/s). Grasping is a distance + gripper check (8 cm radius).
  * Publishes `sim.obs` at 30 Hz with the full schema (stall block included).
  * Replies to `snapshot` (1-pixel dummy JPEG) and `ping` via correlated
    request/reply. `joint`, `ee`, `gripper`, `scenario`, `reset`, `mode`,
    `set`, `play` are fire-and-forget per the protocol.
  * Emits `sim.event` on episode boundaries: episode_start (every reset),
    episode_end (success or --ep-len reached), grasp, drop, stall,
    scenario_change.
  * Deterministic: everything is seeded (random.Random); identical command
    sequences produce identical state. Wall-clock jitter affects timing only,
    not the logical step counter.

Faults (--fault):
  ik_residual  the EE refuses to descend the last 7 cm: it stops 7 cm ABOVE its
               commanded target, so dist_to_goal plateaus and the stall
               detector fires (the classic stall, reproducibly).
  slip         a grasped object is dropped once lifted >5 cm above grasp height.

Episode length: after --ep-len steps (default 300) the sim emits
episode_end {reason: max_steps} and auto-resets into the next episode.

    sim/py/.venv/bin/python agents/fake_sim.py [--fault ik_residual] [--ep-len 300]
        [--hz 30] [--seed 1234] [--name fake-sim] [--url ws://...]
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bus_client import BusClient  # noqa: E402

# A verified 1x1 grayscale JPEG (generated once with PIL, embedded so the stub
# has no imaging dependency at runtime). Clients just decode + save the bytes.
DUMMY_JPEG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/wAALCAABAAEBAREA/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/ACv/2Q=="

NJ = 6  # joints
JOINT_LIMIT = 2.9  # rad, soft clamp (protocol rule 1: never exceed limits)
EE_SPEED = 0.5  # m/s toward commanded target
SLEW = 2.5  # rad/s joint slew limit
GRASP_R = 0.08  # m, grasp radius
PLACE_TOL = 0.06  # m, success tolerance
STALL_AFTER = 30  # steps without progress -> stalled
SCENARIOS = ("reach", "pick_place", "push_to_zone", "stack")
MODES = ("ik", "joint", "script", "mocap", "off")


def r(v, n=4):
    return round(float(v), n)


class FakeSim:
    """State machine + physics stub. Pure-logic, no I/O (testable in isolation)."""

    def __init__(self, hz=30, ep_len=300, fault="none", seed=1234):
        self.hz = max(1, min(120, int(hz)))
        self.ep_len = int(ep_len)
        self.fault = fault
        self.base_seed = int(seed)
        self.bus = None  # set by amain; events queue until then anyway
        self.events: list[dict] = []
        self.ep = 0
        self.pending_reset = False
        self._reset(seed=self.base_seed, first=True)

    # ----------------------------------------------------------------- state
    def _reset(self, seed=None, scenario=None, first=False):
        if scenario:
            prev = getattr(self, "scenario", None)
            self.scenario = scenario
            if prev and prev != scenario and self.bus is not None:
                self.events.append(
                    {"kind": "scenario_change", "ep": self.ep, "scenario": scenario}
                )
        elif not hasattr(self, "scenario"):
            self.scenario = "reach"
        if not first:
            self.ep += 1
        s = self.base_seed + self.ep if seed is None else int(seed)
        self.rng = random.Random(s)
        self.ep_seed = s
        self.q = np.zeros(NJ)
        self.q_target = np.zeros(NJ)
        self.dq = np.zeros(NJ)
        self.ee = np.array([0.10, 0.0, 0.30])
        self.ee_target = self.ee.copy()
        self.grip = 1.0
        self.yaw = 0.0
        self.pitch = 0.0
        self.control = "ik"
        self.step = 0
        self.t = 0.0
        self.grasped = False
        self.grasp_z = 0.0
        self.cube = np.array(
            [self.rng.uniform(0.22, 0.42), self.rng.uniform(-0.18, 0.18), 0.02]
        )
        self.goal = np.array(
            [self.rng.uniform(0.25, 0.45), self.rng.uniform(-0.20, 0.20), 0.03]
        )
        self.best_dist = float("inf")
        self.last_progress = 0
        self.stalled = False
        self.armed = False  # stall detector arms on the first movement command
        self.done = False
        self.success = False
        self.last_cmd = {"cmd": None, "args": {}}
        self.play_queue: list = []
        if self.bus is not None:
            self.events.append(
                {
                    "kind": "episode_start",
                    "ep": self.ep,
                    "seed": self.ep_seed,
                    "scenario": self.scenario,
                }
            )

    # ------------------------------------------------------------------ cmds
    async def apply_cmd(self, msg: dict) -> None:
        data = msg.get("data") or {}
        cmd = data.get("cmd")
        a = data.get("args") or {}
        self.last_cmd = {"cmd": cmd, "args": a}
        bus = self.bus
        if cmd in ("joint", "ee", "gripper", "play"):
            self.armed = True  # first movement command arms the stall detector

        if cmd == "joint":
            q = [float(x) for x in (a.get("q") or [])][:NJ]
            if len(q) < NJ:
                q = q + [0.0] * (NJ - len(q))
            self.q_target = np.clip(np.array(q), -JOINT_LIMIT, JOINT_LIMIT)

        elif cmd == "ee":
            pos = np.array([float(x) for x in a.get("pos", [0, 0, 0])][:3])
            if a.get("mode", "absolute") == "relative":
                self.ee_target = self.ee + pos
            else:
                self.ee_target = pos
            if a.get("yaw") is not None:
                self.yaw = float(a["yaw"])
            if a.get("pitch") is not None:
                self.pitch = float(a["pitch"])
            if a.get("gripper") is not None:
                self._set_gripper(float(a["gripper"]))

        elif cmd == "gripper":
            self._set_gripper(float(a.get("open", 1.0)))

        elif cmd == "scenario":
            self._reset(seed=self.base_seed + self.ep, scenario=a.get("name"))

        elif cmd == "reset":
            self._reset(seed=a.get("seed"), scenario=a.get("scenario"))

        elif cmd == "mode":
            m = a.get("control", "ik")
            if m in MODES:
                self.control = m

        elif cmd == "set":
            hz = a.get("obs_hz")
            if hz:
                self.hz = max(1, min(120, int(hz)))
            # "record" is accepted and ignored: the hub logs everything anyway.

        elif cmd == "play":
            self.play_queue = list(a.get("actions") or [])

        elif cmd == "snapshot":
            if bus is not None:
                await bus.reply(
                    msg,
                    {
                        "jpeg_b64": DUMMY_JPEG_B64,
                        "cam": a.get("cam", "free"),
                        "step": self.step,
                        "w": a.get("w", 1),
                        "h": a.get("h", 1),
                    },
                )

        elif cmd == "ping":
            if bus is not None:
                await bus.reply(msg, {"pong": True, "step": self.step, "ep": self.ep})

        # unknown cmds: recorded in last_cmd, ignored otherwise.

    def _set_gripper(self, open_=1.0):
        open_ = max(0.0, min(1.0, open_))
        self.grip = open_
        if open_ < 0.35:  # closing
            if not self.grasped and np.linalg.norm(self.ee - self.cube) < GRASP_R:
                self.grasped = True
                self.grasp_z = float(self.ee[2])
                self.events.append(
                    {
                        "kind": "grasp",
                        "ep": self.ep,
                        "step": self.step,
                        "object": "cube",
                    }
                )
        elif open_ > 0.65:  # opening
            self._release()

    def _release(self):
        if not self.grasped:
            return
        self.grasped = False
        self.cube = self.ee + np.array([0.0, 0.0, -0.04])
        self.cube[2] = max(0.02, float(self.cube[2]))
        near_goal = np.linalg.norm(self.cube - self.goal) < PLACE_TOL
        if near_goal and not self.done:
            self.success = True
            self.done = True
            self.events.append(
                {
                    "kind": "episode_end",
                    "ep": self.ep,
                    "step": self.step,
                    "reason": "success",
                }
            )
            self.pending_reset = True

    # ---------------------------------------------------------------- physics
    def tick(self, dt: float) -> None:
        # play queue: apply one queued action per tick
        if self.play_queue:
            act = self.play_queue.pop(0)
            if isinstance(act, dict) and act.get("cmd"):
                self.last_cmd = {"cmd": act["cmd"], "args": act.get("args") or {}}
                if act["cmd"] == "joint":
                    q = [float(x) for x in (act.get("args") or {}).get("q") or []][:NJ]
                    self.q_target = np.clip(
                        np.array(q + [0.0] * (NJ - len(q))), -JOINT_LIMIT, JOINT_LIMIT
                    )
                elif act["cmd"] == "ee":
                    self.ee_target = np.array(
                        [float(x) for x in (act.get("args") or {}).get("pos", self.ee)]
                    )

        # joint servo (slew-rate limited)
        prev_q = self.q.copy()
        dq_max = SLEW * dt
        self.q = self.q + np.clip(self.q_target - self.q, -dq_max, dq_max)
        self.dq = (self.q - prev_q) / dt

        # abstract EE toward its target
        if self.control != "off":
            tgt = self.ee_target
            if self.fault == "ik_residual":
                tgt = tgt + np.array([0.0, 0.0, 0.07])  # stops 7 cm above target
            d = tgt - self.ee
            dist = float(np.linalg.norm(d))
            if dist > 1e-9:
                move = min(EE_SPEED * dt, dist)
                self.ee = self.ee + d / dist * move

        # carried object follows the EE
        if self.grasped:
            self.cube = self.ee + np.array([0.0, 0.0, -0.04])
            if self.fault == "slip" and self.ee[2] > self.grasp_z + 0.05:
                self.grasped = False
                self.cube[2] = max(0.02, float(self.cube[2]))
                self.events.append(
                    {"kind": "drop", "ep": self.ep, "step": self.step, "object": "cube"}
                )

        self.step += 1
        self.t = self.step / self.hz

        # stall detector (progress = dist_to_goal shrinking by >=1 mm)
        dist = float(
            np.linalg.norm((self.cube if self.grasped else self.ee) - self.goal)
        )
        if dist < self.best_dist - 0.001:
            self.best_dist = dist
            self.last_progress = self.step
        was = self.stalled
        self.stalled = (
            self.armed  # an idle, never-commanded sim is parked, not stalled
            and (self.step - self.last_progress) > STALL_AFTER
            and not self.success
            and self.control != "off"
        )
        if self.stalled and not was:
            self.events.append(
                {
                    "kind": "stall",
                    "ep": self.ep,
                    "step": self.step,
                    "reasons": ["no_progress"],
                    "dist_to_goal": r(dist),
                }
            )

        # episode boundary: max steps
        if self.ep_len > 0 and self.step >= self.ep_len and not self.done:
            self.done = True
            self.events.append(
                {
                    "kind": "episode_end",
                    "ep": self.ep,
                    "step": self.step,
                    "reason": "max_steps",
                }
            )
            self.pending_reset = True

    # ------------------------------------------------------------------- obs
    def obs(self) -> dict:
        obj = self.cube  # published whether carried or resting
        dist = float(np.linalg.norm(obj - self.goal))
        stall_steps = max(0, self.step - self.last_progress)
        if self.success:
            stage = "done"
        elif self.grasped:
            stage = "place" if dist < 0.15 else "lift"
        else:
            stage = "reach"
        reward = round(
            -dist + (0.5 if self.grasped else 0.0) + (10.0 if self.success else 0.0), 3
        )
        return {
            "ep": self.ep,
            "step": self.step,
            "t": r(self.t, 3),
            "scenario": self.scenario,
            "control": self.control,
            "q": [r(x) for x in self.q],
            "dq": [r(x) for x in self.dq],
            "gripper": r(self.grip, 3),
            "ee": {"pos": [r(x) for x in self.ee], "quat": [1.0, 0.0, 0.0, 0.0]},
            "objects": [
                {
                    "id": "cube",
                    "pos": [r(x) for x in obj],
                    "quat": [1.0, 0.0, 0.0, 0.0],
                    "grasped": self.grasped,
                }
            ],
            "goal": {"pos": [r(x) for x in self.goal]},
            "progress": {
                "dist_to_goal": r(dist),
                "reward": reward,
                "stage": stage,
            },
            "done": self.done,
            "success": self.success,
            "stall": {
                "stalled": self.stalled,
                "score": r(min(1.0, stall_steps / 60.0), 3),
                "steps": stall_steps,
                "reasons": ["no_progress"] if self.stalled else [],
            },
            "last_cmd": self.last_cmd,
        }


async def amain(args) -> None:
    from bus_client import resolve_url

    bus = BusClient(
        args.name,
        url=args.url or resolve_url(None),
        roles=["sim"],
        caps=["ik", "fake", "headless"],
    )
    await bus.connect()
    sim = FakeSim(hz=args.hz, ep_len=args.ep_len, fault=args.fault, seed=args.seed)
    sim.bus = bus
    print(
        f"fake-sim up  name={bus.name} fault={args.fault} hz={args.hz} "
        f"ep_len={args.ep_len} seed={args.seed}",
        flush=True,
    )
    period = 1.0 / sim.hz
    try:
        while True:
            t0 = time.monotonic()
            # drain the inbox (non-blocking-ish)
            while True:
                m = await bus.recv(timeout=0.002)
                if m is None:
                    break
                if m.get("topic") == "sim.cmd":
                    await sim.apply_cmd(m)
            # flush queued events
            while sim.events:
                ev = sim.events.pop(0)
                await bus.send("sim.event", ev)
            sim.tick(period)
            await bus.send("sim.obs", sim.obs())
            if sim.pending_reset:
                sim.pending_reset = False
                sim._reset()  # next episode, seeded
            await asyncio.sleep(max(0.0, period - (time.monotonic() - t0)))
    finally:
        await bus.close()


def main() -> None:
    p = argparse.ArgumentParser(
        description="Headless stub simulator on the Robot Bus (deterministic, faults injectable)"
    )
    p.add_argument(
        "--url",
        default=None,
        help="explicit bus ws:// URL (else $ROBOT_BUS_URL/runs/bus.port)",
    )
    p.add_argument("--name", default="fake-sim")
    p.add_argument(
        "--hz", type=int, default=30, help="sim.obs publish rate (default 30)"
    )
    p.add_argument(
        "--ep-len",
        type=int,
        default=300,
        help="steps per episode, then auto reset (default 300)",
    )
    p.add_argument("--fault", choices=["none", "ik_residual", "slip"], default="none")
    p.add_argument(
        "--seed",
        type=int,
        default=1234,
        help="base RNG seed (episodes use seed+ep unless reset says otherwise)",
    )
    try:
        asyncio.run(amain(p.parse_args()))
    except KeyboardInterrupt:
        print("fake-sim shutting down", file=sys.stderr)
        sys.exit(0)


if __name__ == "__main__":
    main()
