#!/usr/bin/env python3
"""fake_publisher.py — synthetic Robot Bus traffic so the puppet view + training
dashboard can be tested/previewed WITHOUT a real trainer (demo day safety net).

Publishes (using agents/bus_client.SyncBus, subscribing to nothing — it only publishes):
  · sim.obs @ 30 Hz  src="mujoco-demo", scenario="reach": a smooth 5-joint arm moving
    through its limits, FK-consistent ee.pos (same FK math as sim/armsmith_web/src/robot.js),
    a resting cube + ball, a fixed goal, 60 Hz-style step counter.
  · train.metrics @ 1 Hz: rising success curve 0.03 → 0.95 over ~2 min
    (baseline_failure_rate 0.97 → baseline_nines ≈ 1.52) so the dashboard's nines
    counter visibly climbs. Field names here are the dashboard contract — see
    sim/dashboard/README.md.

Usage:
  ROBOT_BUS_URL=ws://127.0.0.1:8898/ws sim/py/.venv/bin/python \
      sim/dashboard/test/fake_publisher.py [--hz 30] [--duration 0] [--start-step 120]

Exits after --duration seconds (0 = forever). SIGTERM/CTRL-C → clean exit 0.
"""

from __future__ import annotations

import argparse
import math
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # sim/dashboard/test -> repo root
sys.path.insert(0, str(REPO))

from agents.bus_client import SyncBus  # noqa: E402  (repo-root import, resolves ROBOT_BUS_URL)

RUN = "mujoco-demo-s2"
POLICY = "act-so101"


# ---------------------------------------------------------------- FK (robot frame)
# Faithful port of sim/armsmith_web/src/robot.js fk(): angles [yaw, lift, elbow,
# wrist_flex, roll] (rad), zero pose = arm straight up. Only the chain points are
# needed here (P0..P5, P5 = TCP).
def fk_points(angles):
    yaw, s, e, w, _roll = angles
    cfg_pan = [0.0388, 0.0, 0.0624]
    lift_off = [-0.0304, 0.0, 0.0450]
    L = [0.1126, 0.1349, 0.0631, 0.0981]  # upper, lower, wrist->roll, roll->TCP

    def rz(t):
        return [
            [math.cos(t), -math.sin(t), 0.0],
            [math.sin(t), math.cos(t), 0.0],
            [0.0, 0.0, 1.0],
        ]

    def m3v(m, v):
        return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]

    def vadd(a, b):
        return [a[i] + b[i] for i in range(3)]

    def vs(a, k):
        return [a[i] * k for i in range(3)]

    f = [math.cos(yaw), math.sin(yaw), 0.0]
    d1 = [f[0] * math.sin(s), f[1] * math.sin(s), math.cos(s)]
    d2 = [f[0] * math.sin(s + e), f[1] * math.sin(s + e), math.cos(s + e)]
    d3 = [f[0] * math.sin(s + e + w), f[1] * math.sin(s + e + w), math.cos(s + e + w)]
    P0 = cfg_pan
    P1 = vadd(P0, m3v(rz(yaw), lift_off))
    P2 = vadd(P1, vs(d1, L[0]))
    P3 = vadd(P2, vs(d2, L[1]))
    P4 = vadd(P3, vs(d3, L[2]))
    P5 = vadd(P4, vs(d3, L[3]))
    return [P0, P1, P2, P3, P4, P5]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def joint_pose(t: float) -> list[float]:
    """Smooth sinusoids inside every joint limit (rad) — a believable 'training roll'."""
    return [
        0.60 * math.sin(0.40 * t),
        0.35 * math.sin(0.23 * t + 1.0),
        0.50 * math.sin(0.31 * t + 2.0),
        -0.40 + 0.45 * math.sin(0.50 * t + 3.0),
        0.30 * math.sin(0.70 * t),
    ]


class Graceful:
    def __init__(self):
        self.stop = False
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop", True))
        signal.signal(signal.SIGINT, lambda *_: setattr(self, "stop", True))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--url",
        default=None,
        help="bus ws url (default: $ROBOT_BUS_URL / runs/bus.port / 8890)",
    )
    ap.add_argument("--src", default="mujoco-demo")
    ap.add_argument("--scenario", default="reach")
    ap.add_argument("--hz", type=float, default=30.0, help="sim.obs rate")
    ap.add_argument(
        "--metrics-every", type=float, default=1.0, help="train.metrics period (s)"
    )
    ap.add_argument(
        "--start-step",
        type=int,
        default=120,
        help="step counter start (a resumed MuJoCo run)",
    )
    ap.add_argument(
        "--duration", type=float, default=0.0, help="seconds to run (0 = forever)"
    )
    ap.add_argument(
        "--ramp", type=float, default=120.0, help="seconds for success 0.03 -> 0.95"
    )
    args = ap.parse_args()

    bus = None
    last_err = None
    for attempt in range(30):  # hub may still be booting
        try:
            bus = SyncBus(
                args.src, url=args.url, roles=["sim"], caps=["mujoco", "headless"]
            )
            break
        except ConnectionError as exc:
            last_err = exc
            time.sleep(1.0)
    if bus is None:
        print(f"fake_publisher: bus unreachable ({last_err})", file=sys.stderr)
        return 1

    term = Graceful()
    print(
        f"fake_publisher: on the bus as {bus.name} (obs {args.hz} Hz, metrics every {args.metrics_every}s)"
    )

    step = int(args.start_step)
    ep = 1
    t0 = time.time()
    next_metrics = 0.0
    timesteps = 0
    obs_period = 1.0 / args.hz
    next_obs = 0.0

    try:
        while not term.stop:
            now = time.time()
            wall = now - t0
            if args.duration and wall >= args.duration:
                break

            if now >= next_obs:
                next_obs = now + obs_period
                t = wall
                q = joint_pose(t)
                pts = fk_points(q)
                gripper = 0.5 + 0.5 * math.sin(0.3 * t)
                cube_z = 0.02 + 0.004 * math.sin(
                    0.15 * t
                )  # barely breathing; it "rests"
                obs = {
                    "ep": ep,
                    "step": step,
                    "t": round(t, 3),
                    "scenario": args.scenario,
                    "control": "script",
                    "q": [round(v, 4) for v in q],
                    "dq": [0.0] * 5,
                    "gripper": round(gripper, 3),
                    "ee": {
                        "pos": [round(v, 4) for v in pts[5]],
                        "quat": [1.0, 0.0, 0.0, 0.0],
                    },
                    "objects": [
                        {
                            "id": "cube",
                            "pos": [0.16, -0.08, round(cube_z, 4)],
                            "quat": [1.0, 0.0, 0.0, 0.0],
                            "grasped": False,
                        },
                        {
                            "id": "ball_green",
                            "pos": [0.13, 0.09, 0.03],
                            "quat": [1.0, 0.0, 0.0, 0.0],
                            "grasped": False,
                        },
                    ],
                    "goal": {"pos": [0.18, 0.0, 0.06]},
                    "progress": {
                        "dist_to_goal": round(0.05 + 0.05 * abs(math.sin(0.2 * t)), 4),
                        "reward": round(-1.0 + 8 * min(1.0, wall / args.ramp), 3),
                        "stage": "reach",
                    },
                    "done": False,
                    "success": False,
                    "stall": {
                        "stalled": False,
                        "score": round(0.1 + 0.1 * abs(math.sin(0.5 * t)), 3),
                        "steps": 0,
                        "reasons": [],
                    },
                    "physics": "mujoco-external",
                }
                bus.send("sim.obs", obs)
                step += 2  # the source sim steps at 60 Hz; we publish at 30
                if step % 240 < 2:
                    ep += 1

            if now >= next_metrics:
                next_metrics = now + args.metrics_every
                p = clamp(wall / args.ramp, 0.0, 1.0)
                success = round(0.03 + 0.92 * p, 4)
                failure = round(1.0 - success, 4)
                base_failure = 0.97
                fps = 34.0 + 4.0 * math.sin(wall / 7.0)
                timesteps += int(fps)
                metrics = {
                    "run": RUN,
                    "policy": POLICY,
                    "stage": "eval" if int(wall) % 20 < 2 else "train",
                    "timesteps": timesteps,
                    "fps": round(fps, 1),
                    "ep_rew_mean": round(1.0 + 8.0 * p, 3),
                    "success_rate": success,
                    "failure_rate": failure,
                    "baseline_failure_rate": base_failure,
                    "baseline_nines": round(-math.log10(base_failure), 4),
                    "nines": round(-math.log10(max(failure, 1e-9)), 4),
                    "ep": ep,
                    "elapsed_s": round(wall, 1),
                }
                bus.send("train.metrics", metrics)

            time.sleep(0.002)
    finally:
        try:
            bus.close()
        except Exception:
            pass
        print(
            f"fake_publisher: done (steps {step - args.start_step}, timesteps {timesteps})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
