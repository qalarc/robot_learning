#!/usr/bin/env python
"""make_fixture.py — regenerate _fixture/bus_log.jsonl, the tiny synthetic hub log used
to test scripts/pack_for_colab.sh end-to-end without a live sim.

Why this fixture: training/to_lerobot_dataset.py needs a real bus-log shape
(sim.cmd "ee" + sim.obs with q/gripper/scenario/last_cmd) and the pack test must be
deterministic and small (<5 MB). 2 episodes (reach, pick_place), ~90 frames, ~100 KB.
Stdlib only, fully deterministic (fixed ids/timestamps) so re-running is idempotent.

Usage: training/.venv/bin/python make_fixture.py   (or any python3)
"""

from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent / "bus_log.jsonl"

T0 = 1795452534.0  # fixed epoch base (matches a 2026-11-24 run) — keeps output byte-stable
# (episode id, scenario, n frames)
EPISODES = [(0, "reach", 40), (1, "pick_place", 48)]


def ease(i: int, n: int) -> float:
    """0→1 cosine ramp, deterministic."""
    return 0.5 * (1 - math.cos(math.pi * i / (n - 1)))


def main() -> None:
    lines: list[str] = []
    lines.append(
        json.dumps(
            {
                "topic": "bus.join",
                "src": "fake-sim",
                "data": {
                    "name": "fake-sim",
                    "roles": ["sim"],
                    "caps": ["ik", "fake", "headless"],
                },
            }
        )
    )
    seq = 0
    for ep, scenario, n in EPISODES:
        for i in range(n):
            seq += 1
            e = ease(i, n)
            ee_pos = [
                round(0.10 + 0.15 * e, 4),
                round(0.12 * e * (0.3 if ep else 1.0), 4),
                round(0.30 - 0.25 * e, 4),
            ]
            gripper = 1.0 if i < n // 2 else 0.0  # close for the second half
            cmd = {"cmd": "ee", "args": {"pos": ee_pos, "gripper": gripper}}
            ts = T0 + seq * 0.033
            lines.append(
                json.dumps(
                    {
                        "v": 1,
                        "id": f"00000000-0000-0000-0000-{seq:012d}",
                        "ts": round(ts, 6),
                        "src": "cli",
                        "topic": "sim.cmd",
                        "data": cmd,
                    }
                )
            )
            q = [
                round(0.7 * e, 4),
                round(0.5 * e, 4),
                round(-0.8 * e, 4),
                round(0.3 * e, 4),
                round(-0.5 * e, 4),
                round(0.2 * e, 4),
            ]
            obs = {
                "ep": ep,
                "step": i + 1,
                "t": round(0.033 * (i + 1), 3),
                "scenario": scenario,
                "control": "ik",
                "q": q,
                "dq": [0.0] * 6,
                "gripper": gripper,
                "ee": {"pos": ee_pos, "quat": [1.0, 0.0, 0.0, 0.0]},
                "last_cmd": cmd,  # converter prefers the obs' own command echo
            }
            lines.append(
                json.dumps(
                    {
                        "v": 1,
                        "id": f"00000000-0000-0000-0000-{seq + 100000:012d}",
                        "ts": round(ts + 0.001, 6),
                        "src": "fake-sim",
                        "topic": "sim.obs",
                        "data": obs,
                    }
                )
            )
    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.1f} KiB, {len(lines)} lines)")


if __name__ == "__main__":
    main()
