"""Convert robot-bus hub logs (runs/bus/*.jsonl) or web-recorder episode dumps into a
LeRobotDataset. Run ONLY with the training venv:

    training/.venv/bin/python training/to_lerobot_dataset.py \
        --bus-log runs/bus/<file>.jsonl --out datasets/<name> [--ep 0 1] [--action-space ee|joint]
    training/.venv/bin/python training/to_lerobot_dataset.py \
        --episodes-dir <dir-of-epNNN.jsonl> --out datasets/<name> [--action-space ee|joint]

Bus envelope: docs/PROTOCOL.md ({"v":1,"topic":"sim.obs","data":{...}}).

ACTION SPACE (documented choice)
--------------------------------
The action for each frame is the most recent `sim.cmd` seen on the stream BEFORE that
obs frame. If the obs itself embeds `last_cmd` (the sim echoes the command it last
executed), we prefer that — the sim's own pairing is authoritative over stream ordering.
If neither exists, the frame is SKIPPED (no action = no training row).

  --action-space ee    (default) action float32[4] = [x, y, z, gripper]
                       from cmd "ee": args.pos[0:3] + args.gripper (missing gripper -> 0.5).
                       Metres in robot base frame; gripper 0=closed..1=open.
  --action-space joint action float32[6] = q targets (radians) from cmd "joint": args.q.
                       Falls back to the last ee cmd's value in ee dims ONLY if no joint cmd
                       has ever been seen for that episode start — actually no: a frame whose
                       last command is an "ee" cmd is skipped in joint mode (mixed spaces are
                       poison for a policy); a warning counter reports skips.

OBSERVATION: observation.state float32[7] = [q0..q5 (rad), gripper (0..1)] from sim.obs.
TASK STRING: the obs `scenario` name (e.g. "pick_place"); default "reach" when absent.
Episodes are split on the obs `ep` field; `--ep N` keeps only listed episodes.
No camera images exist in bus logs (hub strips payloads), so the dataset is state-only
(use_videos=False). Vision datasets come from the web sim's snapshot/recorder path.

WEB RECORDER (--episodes-dir): each *.jsonl file is ONE episode; rows are
{"step": int, "t": float, "obs": {...}, "action": {...}} where obs is a sim.obs-like dict
and action is either a command {"cmd": "ee"|"joint", "args": {...}} or flat values
{"pos": [x,y,z], "gripper": g} / {"q": [6]}. Task = obs.scenario or the file stem.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

FPS = 30
STATE_DIM = 7  # q(6) + gripper
EE_DIM = 4  # x, y, z, gripper
JOINT_DIM = 6  # q targets
DEFAULT_TASK = "reach"

REPO = Path(__file__).resolve().parents[1]


def _ee_action(args: dict) -> np.ndarray | None:
    """ee cmd args -> [x, y, z, gripper] float32, or None if unusable."""
    pos = args.get("pos")
    if not isinstance(pos, (list, tuple)) or len(pos) < 3:
        return None
    gripper = args.get("gripper", 0.5)
    return np.array([pos[0], pos[1], pos[2], float(gripper)], dtype=np.float32)


def _action_from_cmd(cmd_msg: dict | None, action_space: str) -> np.ndarray | None:
    """A sim.cmd payload {"cmd":..., "args":...} -> action vector for the chosen space."""
    if not isinstance(cmd_msg, dict):
        return None
    cmd = cmd_msg.get("cmd")
    args = cmd_msg.get("args") or {}
    if action_space == "ee":
        if cmd == "ee":
            return _ee_action(args)
        return None  # gripper-only / joint / other cmds: no ee action -> skip
    # joint mode
    if cmd == "joint":
        q = args.get("q")
        if isinstance(q, (list, tuple)) and len(q) >= JOINT_DIM:
            return np.asarray(q[:JOINT_DIM], dtype=np.float32)
    return None


def _state_from_obs(obs: dict) -> np.ndarray | None:
    q = obs.get("q")
    if not isinstance(q, (list, tuple)) or len(q) < 6:
        return None
    gripper = float(obs.get("gripper", 0.0))
    return np.array([*q[:6], gripper], dtype=np.float32)


def _task_from_obs(obs: dict) -> str:
    return str(obs.get("scenario") or DEFAULT_TASK)


def frames_from_bus_log(path: Path, action_space: str, keep_eps: set[int] | None):
    """Yield (ep, task, state, action) per usable obs, pairing each obs with the most
    recent preceding sim.cmd unless the obs carries its own last_cmd."""
    pending_cmd = None
    skipped_no_action = skipped_no_state = 0
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            topic = msg.get("topic", "")
            data = msg.get("data") or {}
            if topic == "sim.cmd":
                pending_cmd = data  # {"cmd":..., "args":...}
            elif topic == "sim.obs":
                ep = data.get("ep", 0)
                if keep_eps is not None and ep not in keep_eps:
                    continue
                state = _state_from_obs(data)
                if state is None:
                    skipped_no_state += 1
                    continue
                # prefer the sim's own last_cmd echo; fall back to stream order
                action = _action_from_cmd(data.get("last_cmd"), action_space)
                if action is None:
                    action = _action_from_cmd(pending_cmd, action_space)
                if action is None:
                    skipped_no_action += 1
                    continue
                rows.append((ep, _task_from_obs(data), state, action))
    if skipped_no_action:
        print(
            f"[converter] skipped {skipped_no_action} obs frames without usable action",
            file=sys.stderr,
        )
    if skipped_no_state:
        print(
            f"[converter] skipped {skipped_no_state} obs frames without q state",
            file=sys.stderr,
        )
    return rows


def frames_from_web_recorder(path: Path, action_space: str) -> tuple[str, list]:
    """One web-recorder episode file -> (task, [(state, action), ...])."""
    rows = []
    task = None
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            obs = rec.get("obs") or {}
            if task is None:
                task = _task_from_obs(obs) or path.stem
            state = _state_from_obs(obs)
            act_rec = rec.get("action")
            if isinstance(act_rec, dict) and "cmd" in act_rec:
                action = _action_from_cmd(act_rec, action_space)
            else:
                # flat web-recorder action: ee {"pos":..,"gripper":..} or joint {"q":..}
                action = _ee_action(act_rec) if action_space == "ee" else None
                if (
                    action is None
                    and isinstance(act_rec, dict)
                    and isinstance(act_rec.get("q"), (list, tuple))
                ):
                    action = np.asarray(act_rec["q"][:JOINT_DIM], dtype=np.float32)
            if state is None or action is None:
                continue
            rows.append((state, action))
    return (task if task else path.stem), rows


def write_dataset(out: Path, per_ep: dict, repo_id: str) -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

    features = {
        "observation.state": {
            "dtype": "float32",
            "shape": (STATE_DIM,),
            "names": {"joints": None},
        },
        "action": {
            "dtype": "float32",
            "shape": (EE_DIM,) if per_ep["action_space"] == "ee" else (JOINT_DIM,),
            "names": {"joints": None},
        },
    }
    ds = LeRobotDataset.create(
        repo_id=repo_id,
        fps=FPS,
        features=features,
        root=out,
        robot_type="so101",
        use_videos=False,  # bus logs carry no images; state-only dataset
        image_writer_threads=0,
        image_writer_processes=0,
    )
    for ep in sorted(per_ep["episodes"]):
        for state, action, task in per_ep["episodes"][ep]:
            ds.add_frame(
                {
                    "observation.state": state,
                    "action": action,
                    "task": task,
                }
            )
        ds.save_episode()
    ds.finalize()


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--bus-log", type=Path, help="runs/bus/*.jsonl hub log")
    src.add_argument(
        "--episodes-dir",
        type=Path,
        help="dir of web-recorder *.jsonl (one file = one episode)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        required=True,
        help="dataset output dir (e.g. datasets/pick_place_v1)",
    )
    ap.add_argument(
        "--ep",
        type=int,
        nargs="+",
        default=None,
        help="keep only these episode ids (bus-log only)",
    )
    ap.add_argument(
        "--action-space",
        choices=("ee", "joint"),
        default="ee",
        help="ee: action=[x,y,z,gripper] (default) | joint: action=q targets [6]",
    )
    ap.add_argument(
        "--repo-id", default=None, help="dataset repo_id (default: local/<out-dirname>)"
    )
    args = ap.parse_args()

    try:
        import lerobot  # noqa: F401
    except ImportError as exc:
        sys.exit(
            f"This converter needs the training venv (training/.venv/bin/python). Missing: {exc}"
        )

    keep_eps = set(args.ep) if args.ep is not None else None
    action_dim = EE_DIM if args.action_space == "ee" else JOINT_DIM

    episodes: dict[int, list] = defaultdict(list)
    tasks: set[str] = set()
    if args.bus_log is not None:
        for ep, task, state, action in frames_from_bus_log(
            args.bus_log, args.action_space, keep_eps
        ):
            if action.shape[0] != action_dim:
                continue
            episodes[ep].append((state, action, task))
            tasks.add(task)
        if not episodes:
            sys.exit(
                "no usable frames found in bus log (check --action-space matches the recorded cmds)"
            )
        per_ep = {"episodes": episodes, "action_space": args.action_space}
        out = args.out if args.out.is_absolute() else REPO / args.out
        write_dataset(out, per_ep, args.repo_id or f"local/{out.name}")
    else:
        files = sorted(args.episodes_dir.glob("*.jsonl"))
        if not files:
            sys.exit(f"no *.jsonl episodes in {args.episodes_dir}")
        for i, f in enumerate(files):
            task, rows = frames_from_web_recorder(f, args.action_space)
            for state, action in rows:
                if action.shape[0] != action_dim:
                    continue
                episodes[i].append((state, action, task))
            tasks.add(task)
        per_ep = {"episodes": episodes, "action_space": args.action_space}
        out = args.out if args.out.is_absolute() else REPO / args.out
        write_dataset(out, per_ep, args.repo_id or f"local/{out.name}")

    n_frames = sum(len(v) for v in episodes.values())
    print(f"wrote dataset: {out}")
    print(
        f"  episodes={len(episodes)} frames={n_frames} action_space={args.action_space} "
        f"tasks={sorted(tasks)} fps={FPS}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
