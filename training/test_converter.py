"""Test the bus-log -> LeRobotDataset converter end-to-end (no LLM, no network, CPU only).

Generates a synthetic bus log (2 episodes x 40 steps with scripted ee cmds, matching the
docs/PROTOCOL.md envelope) AND a web-recorder episodes dir, runs
training/to_lerobot_dataset.py as a subprocess (the way it will actually be run), then
asserts the resulting datasets load and have the right shapes.

Run ONLY with the training venv:
    training/.venv/bin/python training/test_converter.py
Artifacts land in training/_smoke/test_out/ (small, safe to delete).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
CONVERTER = REPO / "training" / "to_lerobot_dataset.py"
VENV_PY = REPO / "training" / ".venv" / "bin" / "python"
TEST_OUT = REPO / "training" / "_smoke" / "test_out"
N_STEPS = 40
N_EPS = 2
FPS = 30


def make_bus_log(path: Path, rng: np.random.Generator) -> None:
    """2 episodes x 40 steps: obs every step, an ee cmd before most obs, task strings."""
    rows = []
    for ep in range(N_EPS):
        # non-episode noise first, like a real hub log
        rows.append({"topic": "bus.join", "src": "test", "data": {"name": "test"}})
        rows.append(
            {"topic": "log", "src": "test", "data": {"level": "info", "msg": "hi"}}
        )
        for step in range(N_STEPS):
            # scripted ee command: a slow circle at fixed z, gripper closes mid-episode
            x = 0.15 + 0.05 * np.sin(step / 8.0)
            y = 0.05 * np.cos(step / 8.0)
            z = 0.06
            gripper = 0.9 if step < N_STEPS // 2 else 0.1
            cmd = {"cmd": "ee", "args": {"pos": [x, y, z], "gripper": gripper}}
            q = list(0.4 * rng.random(6))
            obs = {
                "ep": ep,
                "step": step,
                "t": step / FPS,
                "scenario": "pick_place",
                "q": q,
                "dq": list(0.01 * rng.random(6)),
                "gripper": gripper,
                "ee": {"pos": [x, y, z], "quat": [1.0, 0.0, 0.0, 0.0]},
            }
            if step % 7 == 3:  # sometimes the sim echoes the last cmd on the obs itself
                obs["last_cmd"] = cmd
                rows.append({"topic": "sim.obs", "data": obs})
            else:
                rows.append({"topic": "sim.cmd", "to": "sim", "data": cmd})
                rows.append({"topic": "sim.obs", "data": obs})
    with open(path, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def make_web_episodes(d: Path, rng: np.random.Generator) -> None:
    """Two web-recorder files: ep_0.jsonl (ee cmds), ep_1.jsonl (joint cmds)."""
    d.mkdir(parents=True, exist_ok=True)
    for ep in range(2):
        rows = []
        for step in range(N_STEPS):
            q = list(0.4 * rng.random(6))
            obs = {
                "ep": ep,
                "step": step,
                "t": step / FPS,
                "scenario": "stack",
                "q": q,
                "gripper": 0.5,
                "ee": {"pos": [0.2, 0.0, 0.08], "quat": [1, 0, 0, 0]},
            }
            if ep == 0:
                action = {
                    "cmd": "ee",
                    "args": {"pos": [0.20, 0.01 * step, 0.08], "gripper": 0.5},
                }
            else:
                # flat-style action (no cmd wrapper) — exercises the flat-ee parser
                action = {"pos": [0.22, -0.01 * step, 0.08], "gripper": 0.3}
            rows.append({"step": step, "t": step / FPS, "obs": obs, "action": action})
        with open(d / f"ep_{ep}.jsonl", "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")


def run_converter(*cli_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(VENV_PY), str(CONVERTER), *cli_args],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=REPO,
    )


def assert_dataset(
    root: Path, expect_eps: int, expect_action_dim: int, task: str
) -> None:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from torch.utils.data import DataLoader

    ds = LeRobotDataset(repo_id=f"test/{root.name}", root=root)
    assert ds.fps == FPS, f"fps {ds.fps}"
    assert ds.num_episodes == expect_eps, f"episodes {ds.num_episodes} != {expect_eps}"
    feats = ds.features
    assert feats["observation.state"]["shape"] == (7,), feats["observation.state"][
        "shape"
    ]
    assert feats["action"]["shape"] == (expect_action_dim,), feats["action"]["shape"]
    tasks = (
        [str(t) for t in ds.meta.tasks.index]
        if hasattr(ds.meta.tasks, "index")
        else [str(t) for t in ds.meta.tasks]
    )
    assert task in tasks, f"task '{task}' not in {tasks}"
    batch = next(iter(DataLoader(ds, batch_size=4, shuffle=True, num_workers=0)))
    assert tuple(batch["observation.state"].shape) == (4, 7)
    assert tuple(batch["action"].shape) == (4, expect_action_dim)
    # frame count sanity
    assert len(ds) >= expect_eps * N_STEPS - 2, f"len {len(ds)} too small"
    print(
        f"  OK: {root.name}: {len(ds)} frames, {ds.num_episodes} eps, "
        f"state=(7,), action=({expect_action_dim},), tasks={sorted(set(tasks))}"
    )


def main() -> int:
    t0 = time.time()
    if TEST_OUT.exists():
        shutil.rmtree(TEST_OUT)
    TEST_OUT.mkdir(parents=True)
    rng = np.random.default_rng(11)

    print("1) synthetic bus log -> converter")
    bus_log = TEST_OUT / "fixture_bus.jsonl"
    make_bus_log(bus_log, rng)
    r = run_converter(
        "--bus-log",
        str(bus_log),
        "--out",
        "training/_smoke/test_out/ds_bus",
        "--ep",
        "0",
        "1",
    )
    assert r.returncode == 0, f"converter failed: {r.stderr}"
    assert_dataset(
        TEST_OUT / "ds_bus", expect_eps=2, expect_action_dim=4, task="pick_place"
    )

    print("2) joint action-space")
    r = run_converter(
        "--bus-log",
        str(bus_log),
        "--out",
        "training/_smoke/test_out/ds_joint",
        "--action-space",
        "joint",
    )
    # fixture has ee cmds only -> joint mode must exit non-zero (no usable frames)
    assert r.returncode != 0, "joint mode should fail cleanly on ee-only log"
    print("  OK: ee-only log rejected in joint mode")

    print("3) web-recorder episodes dir -> converter")
    web_dir = TEST_OUT / "fixture_web"
    make_web_episodes(web_dir, rng)
    r = run_converter(
        "--episodes-dir", str(web_dir), "--out", "training/_smoke/test_out/ds_web"
    )
    assert r.returncode == 0, f"converter failed: {r.stderr}"
    assert_dataset(TEST_OUT / "ds_web", expect_eps=2, expect_action_dim=4, task="stack")

    print(f"ALL CONVERTER TESTS PASS ({time.time() - t0:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
