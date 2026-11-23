#!/usr/bin/env python3
"""cli -- drive the robot sim + read telemetry over the Robot Bus from a shell.

Every subcommand opens a short-lived bus connection (SyncBus), prints one
compact JSON object per unit of output to stdout, and exits 0 on success /
1 on failure. Add --pretty anywhere after the subcommand for readable JSON.

    sim/py/.venv/bin/python agents/cli.py roster
    sim/py/.venv/bin/python agents/cli.py ee --x 0.3 --y 0.05 --z 0.05 --grip 1
    sim/py/.venv/bin/python agents/cli.py snapshot --cam wrist --out frame.jpg
    sim/py/.venv/bin/python agents/cli.py --pretty stall        # NOTE: global-ish
                                                            flags go AFTER the
                                                            subcommand.

Target sim resolution for sim.cmd: --to FLAG > $ROBOT_SIM_NAME env > "armsmith-web".
Bus URL resolution: --url FLAG > $ROBOT_BUS_URL > runs/bus.port > ws://127.0.0.1:8890/ws.

See agents/tools_for_codex.md for the cheat-sheet and docs/02b_codex_tooling.md
for how the pieces fit together.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bus_client import SyncBus, resolve_url  # noqa: E402

HIGH_RATE = {"sim.obs", "vision.hands", "vision.tape", "vision.marker", "vision.frame"}


# --------------------------------------------------------------------- output
def emit(obj, pretty: bool = False) -> None:
    print(
        json.dumps(
            obj, indent=2 if pretty else None, separators=None if pretty else (",", ":")
        )
    )


def fail(msg: str, pretty: bool = False) -> None:
    emit({"ok": False, "error": str(msg)}, pretty)
    sys.exit(1)


def http_get(args, path: str, timeout: float | None = None) -> object:
    url = resolve_url(args.url)  # ws://127.0.0.1:PORT/ws
    base = "http://" + url.split("//", 1)[1].split("/", 1)[0]
    req = urllib.request.Request(base + path, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout or args.timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as e:
        fail(
            f"hub unreachable at {base} ({e}) -- is `python agents/hub.py` running?",
            getattr(args, "pretty", False),
        )


# ----------------------------------------------------------------- connection
def sim_target(args) -> str:
    return args.to or os.environ.get("ROBOT_SIM_NAME") or "armsmith-web"


def open_bus(args, name: str = "cli") -> SyncBus:
    try:
        return SyncBus(name, url=args.url)
    except Exception as e:  # ConnectionError and connect timeouts
        fail(
            f"bus unreachable ({e}) -- is `python agents/hub.py` running?", args.pretty
        )


def send_cmd(
    bus: SyncBus,
    to: str,
    cmd: str,
    cmd_args: dict,
    timeout: float,
    expect_reply: bool = False,
):
    data = {"cmd": cmd, "args": cmd_args}
    if expect_reply:
        data["reply_to"] = "cli.reply"
        return bus.request("sim.cmd", data, to=to, timeout=timeout)
    rid = bus.send("sim.cmd", data, to=to)
    # The hub warns us back if the target name doesn't exist; surface it so a
    # typo'd --to fails loudly instead of "succeeding" silently.
    warn = bus.recv(timeout=0.2, topic="log")
    if warn and "no connected client named" in str(
        (warn.get("data") or {}).get("msg", "")
    ):
        return {
            "ok": False,
            "sent": True,
            "id": rid,
            "cmd": cmd,
            "to": to,
            "error": (warn.get("data") or {}).get("msg"),
        }
    return {"ok": True, "sent": True, "id": rid, "cmd": cmd, "to": to}


REPLY_CMDS = {"snapshot", "ping"}
MOVE_CMDS = {"joint", "ee", "gripper", "play"}


def dispatch(args, cmd: str, cmd_args: dict, expect_reply: bool = False) -> int:
    """One-shot: open bus, send a sim.cmd, emit the result, return exit code."""
    bus = open_bus(args)
    try:
        res = send_cmd(
            bus,
            sim_target(args),
            cmd,
            cmd_args,
            args.timeout,
            expect_reply=expect_reply,
        )
        if expect_reply:
            if res is None:
                fail(
                    f"no reply to {cmd} within {args.timeout}s "
                    f"(target {sim_target(args)})",
                    args.pretty,
                )
            emit(
                {"ok": True, "reply": res.get("data"), "from": res.get("src")},
                args.pretty,
            )
            return 0
        ok = bool(res.get("ok"))
        emit(res, args.pretty)
        return 0 if ok else 1
    finally:
        bus.close()


# ------------------------------------------------------------------ obs utils
def compact_obs(d: dict) -> dict:
    ee = d.get("ee") or {}
    prog = d.get("progress") or {}
    stall = d.get("stall") or {}
    lc = d.get("last_cmd") or {}
    out = {
        "ep": d.get("ep"),
        "step": d.get("step"),
        "t": d.get("t"),
        "scenario": d.get("scenario"),
        "control": d.get("control"),
        "ee_pos": ee.get("pos"),
        "gripper": d.get("gripper"),
        "dist_to_goal": prog.get("dist_to_goal"),
        "stage": prog.get("stage"),
        "stalled": stall.get("stalled"),
        "done": d.get("done"),
        "success": d.get("success"),
    }
    if lc.get("cmd"):
        out["last_cmd"] = lc.get("cmd")
    return out


def latest_obs(bus: SyncBus, settle: float = 0.25, timeout: float = 5.0) -> dict:
    """Drain the inbox for `settle` seconds and return the newest sim.obs data."""
    deadline = time.monotonic() + timeout
    newest = None
    while time.monotonic() < deadline:
        m = bus.recv(timeout=settle, topic="sim.obs")
        if m is not None:
            newest = m.get("data") or {}
    if newest is None:
        fail("no sim.obs received -- is a simulator connected?", False)
    return newest


# --------------------------------------------------------------- subcommands
def cmd_roster(args) -> int:
    roster = http_get(args, "/roster")
    emit({"ok": True, "clients": roster}, args.pretty)
    return 0


def cmd_obs(args) -> int:
    bus = open_bus(args)
    try:
        bus.subscribe(["sim.obs"])
        min_dt = 1.0 / max(args.hz, 0.1)
        got = 0
        last = 0.0
        deadline = time.monotonic() + args.timeout
        while args.n is None or got < args.n:
            rem = deadline - time.monotonic()
            if got == 0 and rem <= 0:
                fail(
                    "no sim.obs within timeout -- is a simulator connected?",
                    args.pretty,
                )
            m = bus.recv(
                timeout=min(0.5, max(0.01, rem if got == 0 else 0.5)), topic="sim.obs"
            )
            if m is None:
                continue
            now = time.monotonic()
            if now - last < min_dt:
                continue  # rate limit: drop frames between prints
            last = now
            got += 1
            emit(compact_obs(m.get("data") or {}), args.pretty)
            if got == 1:  # after the first frame, stream without deadline
                deadline = float("inf")
        return 0
    finally:
        bus.close()


def cmd_cmd(args) -> int:
    try:
        payload = json.loads(args.json)
    except ValueError as e:
        return fail(f"invalid JSON: {e}", args.pretty)
    if not isinstance(payload, dict):
        return fail("payload must be a JSON object", args.pretty)
    if "cmd" not in payload and isinstance(payload.get("data"), dict):
        payload = payload["data"]  # tolerate a full bus envelope
    if "cmd" not in payload:
        return fail('payload needs {"cmd": ..., "args": {...}}', args.pretty)
    expect = payload.get("cmd") in REPLY_CMDS
    return dispatch(
        args, payload["cmd"], payload.get("args") or {}, expect_reply=expect
    )


def cmd_ee(args) -> int:
    a: dict = {
        "pos": [args.x, args.y, args.z],
        "mode": "relative" if args.relative else "absolute",
    }
    if args.grip is not None:
        a["gripper"] = args.grip
    if args.yaw is not None:
        a["yaw"] = args.yaw
    if args.pitch is not None:
        a["pitch"] = args.pitch
    return dispatch(args, "ee", a)


def cmd_joint(args) -> int:
    return dispatch(args, "joint", {"q": list(args.q)})


def cmd_grip(args) -> int:
    return dispatch(args, "gripper", {"open": args.open})


def cmd_scenario(args) -> int:
    return dispatch(args, "scenario", {"name": args.name})


def cmd_reset(args) -> int:
    a: dict = {}
    if args.seed is not None:
        a["seed"] = args.seed
    if args.scenario is not None:
        a["scenario"] = args.scenario
    return dispatch(args, "reset", a)


def cmd_mode(args) -> int:
    return dispatch(args, "mode", {"control": args.control})


def cmd_snapshot(args) -> int:
    bus = open_bus(args)
    try:
        rep = send_cmd(
            bus,
            sim_target(args),
            "snapshot",
            {"cam": args.cam, "w": args.w, "h": args.h},
            max(args.timeout, 5.0),
            expect_reply=True,
        )
        if rep is None:
            fail(
                f"snapshot reply timeout ({args.timeout}s) from {sim_target(args)}",
                args.pretty,
            )
        d = rep.get("data") or {}
        b64 = d.get("jpeg_b64")
        if not b64:
            fail(f"reply carried no jpeg_b64: {list(d)}", args.pretty)
        raw = base64.b64decode(b64)
        out = Path(args.out)
        if out.parent and str(out.parent) not in ("", "."):
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(raw)
        emit(
            {
                "ok": True,
                "path": str(out),
                "bytes": len(raw),
                "cam": d.get("cam"),
                "step": d.get("step"),
                "from": rep.get("src"),
            },
            args.pretty,
        )
        return 0
    finally:
        bus.close()


def cmd_stall(args) -> int:
    recent = http_get(args, "/recent")
    ctl = (recent.get("ctl.stall") or [None])[-1]
    obs_stall = None
    ep = step = None
    for entry in reversed(recent.get("sim.obs") or []):
        d = entry.get("data") or {}
        if isinstance(d.get("stall"), dict):
            obs_stall = d["stall"]
            ep, step = d.get("ep"), d.get("step")
            break
    emit(
        {
            "ok": True,
            "ep": ep,
            "step": step,
            "obs_stall": obs_stall,
            "ctl_stall": (ctl or {}).get("data") if ctl else None,
        },
        args.pretty,
    )
    return 0


def cmd_tail(args) -> int:
    # backlog from the hub's /recent (last messages before we connected),
    # then follow live until --n collected or --timeout elapsed.
    backlog = []
    try:
        recent = http_get(args, "/recent")
        for entry in (recent.get(args.topic) or [])[-args.n :]:
            backlog.append(
                {
                    "ts": entry.get("ts"),
                    "src": entry.get("src"),
                    "topic": args.topic,
                    "data": entry.get("data"),
                }
            )
    except SystemExit:
        pass  # hub down: still try live-only below
    bus = open_bus(args)
    try:
        bus.subscribe([args.topic])
        msgs = list(backlog)
        deadline = time.monotonic() + args.timeout
        while len(msgs) < args.n and time.monotonic() < deadline:
            m = bus.recv(timeout=0.3, topic=args.topic)
            if m is not None:
                msgs.append(
                    {
                        "ts": m.get("ts"),
                        "src": m.get("src"),
                        "topic": m.get("topic"),
                        "data": m.get("data"),
                    }
                )
        if not msgs:
            fail(
                f"no messages on {args.topic} (backlog empty, nothing live "
                f"within {args.timeout}s)",
                args.pretty,
            )
        for m in msgs[: args.n]:
            emit(m, args.pretty)
        return 0
    finally:
        bus.close()


def cmd_demo(args) -> int:
    """Scripted reach-and-grasp-lift against the target sim; prints final obs."""
    bus = open_bus(args)
    to = sim_target(args)
    tmo = args.timeout
    try:
        bus.subscribe(["sim.obs"])

        def look(settle=0.3):
            return latest_obs(bus, settle=settle, timeout=tmo)

        def do(cmd, a, wait=0.0):
            res = send_cmd(bus, to, cmd, a, tmo)
            if not res.get("ok"):
                fail(f"demo {cmd} failed: {res.get('error')}", args.pretty)
            if wait:
                time.sleep(wait)

        do("reset", {"seed": args.seed, "scenario": "pick_place"}, wait=0.4)
        do("mode", {"control": "ik"})
        obs = look()
        objs = obs.get("objects") or []
        if not objs:
            fail("demo needs an object in obs; got none", args.pretty)
        cube = (objs[0] or {}).get("pos") or [0.3, 0.0, 0.02]
        cx, cy, cz = (float(v) for v in cube)

        do("gripper", {"open": 1.0})
        do("ee", {"pos": [cx, cy, cz + 0.10], "gripper": 1.0}, wait=1.0)  # above
        do("ee", {"pos": [cx, cy, cz + 0.02], "gripper": 1.0}, wait=1.0)  # descend
        do("gripper", {"open": 0.0}, wait=0.5)  # close
        do("ee", {"pos": [cx, cy, cz + 0.18], "mode": "relative"}, wait=1.2)  # lift
        do("joint", {"q": [0.0] * 6}, wait=0.3)  # park
        final = look()
        emit(
            {
                "ok": True,
                "demo": "reach_grasp_lift",
                "seed": args.seed,
                "final_obs": compact_obs(final),
            },
            args.pretty,
        )
        return 0
    finally:
        bus.close()


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    # NOTE: `common` is attached to the main parser AND every subparser so the
    # flags work before or after the subcommand. argparse's subparser action
    # parses into a FRESH namespace and copies it over the main one, which would
    # clobber pre-subcommand values back to the defaults -- so every default here
    # is argparse.SUPPRESS (attribute only set when the flag is actually seen).
    # main() fills in the real defaults afterwards.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--url",
        default=argparse.SUPPRESS,
        help="explicit bus ws:// URL (else $ROBOT_BUS_URL / runs/bus.port)",
    )
    common.add_argument(
        "--to",
        default=argparse.SUPPRESS,
        help="target sim name (else $ROBOT_SIM_NAME, else armsmith-web)",
    )
    common.add_argument(
        "--timeout",
        type=float,
        default=argparse.SUPPRESS,
        help="seconds to wait for frames/replies (default 3)",
    )
    common.add_argument(
        "--pretty",
        action="store_true",
        default=argparse.SUPPRESS,
        help="indented JSON output",
    )

    p = argparse.ArgumentParser(
        description="Robot Bus CLI: drive the sim and read telemetry from a shell",
        parents=[common],
    )
    sub = p.add_subparsers(dest="which", required=True, metavar="COMMAND")

    s = sub.add_parser(
        "roster", parents=[common], help="list connected clients (GET /roster)"
    )
    s.set_defaults(fn=cmd_roster)

    s = sub.add_parser(
        "obs", parents=[common], help="stream sim.obs, key fields per line"
    )
    s.add_argument(
        "--n",
        type=int,
        default=None,
        help="stop after N frames (default: stream until Ctrl-C)",
    )
    s.add_argument("--hz", type=float, default=10.0, help="max print rate (default 10)")
    s.set_defaults(fn=cmd_obs)

    s = sub.add_parser(
        "cmd",
        parents=[common],
        help='raw sim.cmd from JSON, e.g. --json \'{"cmd":"ping"}\'',
    )
    s.add_argument(
        "--json",
        required=True,
        dest="json",
        help='cmd envelope: {"cmd":"...","args":{...}}',
    )
    s.set_defaults(fn=cmd_cmd)

    s = sub.add_parser(
        "ee", parents=[common], help="end-effector target (metres, base frame)"
    )
    s.add_argument("--x", type=float, required=True)
    s.add_argument("--y", type=float, required=True)
    s.add_argument("--z", type=float, required=True)
    s.add_argument(
        "--grip", type=float, default=None, help="0..1 sent along with the move"
    )
    s.add_argument("--relative", action="store_true", help="offset from current EE pos")
    s.add_argument("--yaw", type=float, default=None)
    s.add_argument("--pitch", type=float, default=None)
    s.set_defaults(fn=cmd_ee)

    s = sub.add_parser("joint", parents=[common], help="6 joint targets (radians)")
    s.add_argument("--q", type=float, nargs=6, required=True, metavar="RAD")
    s.set_defaults(fn=cmd_joint)

    s = sub.add_parser("grip", parents=[common], help="gripper open 0..1 (1 = open)")
    s.add_argument("open", type=float)
    s.set_defaults(fn=cmd_grip)

    s = sub.add_parser(
        "scenario", parents=[common], help="reach | pick_place | push_to_zone | stack"
    )
    s.add_argument("name")
    s.set_defaults(fn=cmd_scenario)

    s = sub.add_parser("reset", parents=[common], help="reset the episode")
    s.add_argument(
        "--seed", type=int, default=None, help="pass a seed for reproducibility"
    )
    s.add_argument("--scenario", default=None)
    s.set_defaults(fn=cmd_reset)

    s = sub.add_parser(
        "mode", parents=[common], help="ik | joint | script | mocap | off"
    )
    s.add_argument("control")
    s.set_defaults(fn=cmd_mode)

    s = sub.add_parser(
        "snapshot",
        parents=[common],
        help="request a camera frame, decode jpeg_b64, write file",
    )
    s.add_argument("--cam", default="free", choices=["free", "wrist", "env"])
    s.add_argument("--out", default="frame.jpg", help="output JPEG path")
    s.add_argument("--w", type=int, default=640)
    s.add_argument("--h", type=int, default=480)
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser(
        "stall",
        parents=[common],
        help="last ctl.stall + newest sim.obs stall block (via GET /recent)",
    )
    s.set_defaults(fn=cmd_stall)

    s = sub.add_parser(
        "tail",
        parents=[common],
        help="print the last N messages on a topic (backlog + live)",
    )
    s.add_argument("--topic", default="sim.event")
    s.add_argument("--n", type=int, default=20)
    s.set_defaults(fn=cmd_tail)

    s = sub.add_parser(
        "demo", parents=[common], help="scripted reach-grasp-lift, prints final obs"
    )
    s.add_argument("--seed", type=int, default=7)
    s.set_defaults(fn=cmd_demo)

    return p


def main() -> None:
    args = build_parser().parse_args()
    # real defaults for the SUPPRESSed common flags (see build_parser)
    for name, default in (
        ("url", None),
        ("to", None),
        ("timeout", 3.0),
        ("pretty", False),
    ):
        if not hasattr(args, name):
            setattr(args, name, default)
    try:
        rc = args.fn(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except ConnectionError as e:
        fail(f"bus connection lost: {e}", getattr(args, "pretty", False))
    sys.exit(rc)


if __name__ == "__main__":
    main()
