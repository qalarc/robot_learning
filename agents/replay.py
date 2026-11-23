#!/usr/bin/env python3
"""replay -- re-run a recorded episode's sim.cmd sequence onto the live Robot Bus.

The hub logs every envelope to runs/bus/<timestamp>.jsonl (the dataset). This
tool extracts the `sim.cmd` frames from such a log and re-sends them at the
recorded pace, so a fault, a fix or a controller change can be tested against
the exact same command sequence.

    sim/py/.venv/bin/python agents/replay.py runs/bus/20261124-033119.jsonl
    sim/py/.venv/bin/python agents/replay.py <log> --ep 0 --speed 2        # 2x pace
    sim/py/.venv/bin/python agents/replay.py <log> --dry-run               # action table only
    sim/py/.venv/bin/python agents/replay.py <log> --export-csv actions.csv

Episodes are delimited by `reset` commands: the log's sim.cmd stream is split
at each reset, and --ep N selects episode N (0-based; episode 0 = everything
before the first reset). Default: replay all episodes.

Target resolution for each command: the recorded "to" field if present, else
--to FLAG > $ROBOT_SIM_NAME env > "armsmith-web". Bus URL: --url >
$ROBOT_BUS_URL > runs/bus.port > ws://127.0.0.1:8890/ws.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bus_client import SyncBus  # noqa: E402


def load_actions(path: Path) -> list[dict]:
    """sim.cmd frames from a hub log, in ts order: {ts,to,cmd,args}."""
    actions = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if not isinstance(m, dict) or m.get("topic") != "sim.cmd":
                continue
            d = m.get("data") or {}
            if not isinstance(d, dict) or not d.get("cmd"):
                continue
            try:
                ts = float(m.get("ts") or 0.0)
            except (TypeError, ValueError):
                ts = 0.0
            actions.append(
                {
                    "ts": ts,
                    "to": m.get("to"),
                    "cmd": str(d["cmd"]),
                    "args": d.get("args") or {},
                }
            )
    actions.sort(key=lambda a: a["ts"])
    return actions


def split_episodes(actions: list[dict]) -> list[list[dict]]:
    """Split at each reset: episode 0 = before the first reset, etc."""
    eps: list[list[dict]] = [[]]
    for a in actions:
        if a["cmd"] == "reset" and eps[-1]:
            eps.append([])
        eps[-1].append(a)
    return [e for e in eps if e]


def compact(args_dict: dict) -> str:
    return json.dumps(args_dict, separators=(",", ":"))


def main() -> None:
    repo = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(
        description="Replay a recorded episode's sim.cmd stream onto the live bus"
    )
    p.add_argument("file", help="hub log: runs/bus/<timestamp>.jsonl")
    p.add_argument(
        "--ep",
        type=int,
        default=-1,
        help="episode index to replay, 0-based, delimited by reset (default: all)",
    )
    p.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="pace multiplier: 2 = twice recorded speed (default 1)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print the action table and exit without touching the bus",
    )
    p.add_argument(
        "--export-csv",
        default=None,
        metavar="PATH",
        help="write step,ts,cmd,args CSV and exit (no bus send)",
    )
    p.add_argument("--url", default=None, help="explicit bus ws:// URL")
    p.add_argument("--to", default=None, help="target sim name override")
    p.add_argument("--timeout", type=float, default=3.0)

    args = p.parse_args()
    path = Path(args.file)
    if not path.exists():
        alt = repo / args.file
        if alt.exists():
            path = alt
        else:
            print(json.dumps({"ok": False, "error": f"no such file: {args.file}"}))
            sys.exit(1)

    if args.speed <= 0:
        print(json.dumps({"ok": False, "error": "--speed must be > 0"}))
        sys.exit(1)

    actions = load_actions(path)
    if not actions:
        print(json.dumps({"ok": False, "error": f"no sim.cmd frames in {path}"}))
        sys.exit(1)

    episodes = split_episodes(actions)
    if args.ep >= 0:
        if args.ep >= len(episodes):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": f"only {len(episodes)} episode(s) found, "
                        f"--ep {args.ep} out of range",
                    }
                )
            )
            sys.exit(1)
        selected = episodes[args.ep]
    else:
        selected = [a for e in episodes for a in e]

    if args.dry_run:
        prev = None
        print(
            f"# {path}  episodes={len(episodes)}  actions={len(selected)}"
            + (f"  (episode {args.ep})" if args.ep >= 0 else "")
        )
        print(f"{'step':>4}  {'dt':>7}  {'cmd':<10}  args")
        for i, a in enumerate(selected, 1):
            dt = 0.0 if prev is None else max(0.0, a["ts"] - prev)
            prev = a["ts"]
            print(f"{i:>4}  {dt:>6.3f}s  {a['cmd']:<10}  {compact(a['args'])}")
        sys.exit(0)

    if args.export_csv:
        out = Path(args.export_csv)
        out.parent.mkdir(parents=True, exist_ok=True) if out.parent != Path(
            "."
        ) else None
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["step", "ts", "cmd", "args"])
            for i, a in enumerate(selected, 1):
                w.writerow([i, f"{a['ts']:.6f}", a["cmd"], compact(a["args"])])
        print(json.dumps({"ok": True, "csv": str(out), "rows": len(selected)}))
        sys.exit(0)

    # live replay
    target = args.to or os.environ.get("ROBOT_SIM_NAME") or "armsmith-web"
    recorded_to = next((a["to"] for a in selected if a["to"]), None)
    target = recorded_to or target
    try:
        bus = SyncBus("replay", url=args.url)
    except Exception as e:
        print(
            json.dumps(
                {"ok": False, "error": f"bus unreachable ({e}) -- is the hub running?"}
            )
        )
        sys.exit(1)

    print(
        json.dumps(
            {
                "ok": True,
                "replay": str(path),
                "actions": len(selected),
                "to": target,
                "speed": args.speed,
            }
        )
    )
    t_prev = None
    sent = 0
    t_start = time.monotonic()
    try:
        for i, a in enumerate(selected, 1):
            if t_prev is not None and args.speed:
                dt = max(0.0, (a["ts"] - t_prev) / args.speed)
                if dt > 0:
                    time.sleep(dt)
            t_prev = a["ts"]
            bus.send("sim.cmd", {"cmd": a["cmd"], "args": a["args"]}, to=target)
            sent += 1
            print(
                json.dumps(
                    {
                        "step": i,
                        "cmd": a["cmd"],
                        "dt": round(
                            0.0
                            if i == 1
                            else max(
                                0.0, (a["ts"] - selected[i - 2]["ts"]) / args.speed
                            ),
                            3,
                        ),
                    }
                )
            )
        elapsed = time.monotonic() - t_start
        print(json.dumps({"ok": True, "sent": sent, "elapsed_s": round(elapsed, 2)}))
        sys.exit(0)
    finally:
        bus.close()


if __name__ == "__main__":
    main()
