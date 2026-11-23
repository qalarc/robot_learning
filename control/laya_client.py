#!/usr/bin/env python3
"""System 1 -- Laya client for the robot-ops domain.

Laya is our fine-tuned typed-decision model (GUT protocol). It is NOT a chat
model: state in -> calibrated probabilities out. On this machine (AMD, CPU
serve) a warm decision costs ~1.35 s, so we sample it at stall time and on a
slow heartbeat -- never per control tick.

Endpoint (must be running):  python .../Laya_integrations/mcp_finetune/serve.py
                              -> http://127.0.0.1:8798/v1/systemone
Header:                      X-Laya-Domain: robot-ops
Until a robot-ops checkpoint passes the GUT gate, serve.py falls back to the
base English model -- answers are then uncalibrated noise, which is exactly
what the "trained vs untrained" before/after demo on the day shows.

CLI probe (latency + a live verdict on a synthetic stalled state):
    sim/py/.venv/bin/python control/laya_client.py --probe
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "robot_ops.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
DEFAULT_ENDPOINT = "http://127.0.0.1:8798/v1/systemone"


# --------------------------------------------------------------------- state
def format_state(obs: dict, history: dict | None = None) -> str:
    """Render a sim.obs message into the frozen state template.

    `history` carries: stall_steps, progress_delta_mm, prior_recoveries,
    ep_success_rate_20, vision (a short vision summary or 'none').
    """
    h = history or {}
    prog = obs.get("progress") or {}
    ee = (obs.get("ee") or {}).get("pos") or [0, 0, 0]
    goal = (obs.get("goal") or {}).get("pos") or [0, 0, 0]
    objects = obs.get("objects") or []
    grasped = any(o.get("grasped") for o in objects)
    contact = any(o.get("contact", grasped) for o in objects)
    last = obs.get("last_cmd") or {}
    tgt = (last.get("args") or {}).get("pos") or goal
    fmt = {
        "scenario": obs.get("scenario", "?"),
        "stage": prog.get("stage", "?"),
        "step": obs.get("step", 0),
        "t": obs.get("t", 0.0),
        "stall_steps": h.get("stall_steps", (obs.get("stall") or {}).get("steps", 0)),
        "progress_delta_mm": h.get("progress_delta_mm", 0.0),
        "ee0": ee[0] if len(ee) > 0 else 0.0,
        "ee1": ee[1] if len(ee) > 1 else 0.0,
        "ee2": ee[2] if len(ee) > 2 else 0.0,
        "tgt0": tgt[0] if len(tgt) > 0 else 0.0,
        "tgt1": tgt[1] if len(tgt) > 1 else 0.0,
        "tgt2": tgt[2] if len(tgt) > 2 else 0.0,
        "dist_mm": 1000.0 * (prog.get("dist_to_goal") or 0.0),
        "gripper": obs.get("gripper", 0.0),
        "contact": contact,
        "grasp_state": "grasped" if grasped else ("touching" if contact else "free"),
        "prior_recoveries": h.get("prior_recoveries", 0),
        "succ_rate": h.get("ep_success_rate_20", 0.0),
        "vision": h.get("vision", "none"),
    }
    return SCHEMA["state_template"].format(**fmt)


# ----------------------------------------------------------------------- ask
class LayaClient:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        domain: str = "robot-ops",
        timeout: float = 12.0,
    ):
        self.endpoint = endpoint
        self.domain = domain
        self.timeout = timeout
        self.available = True  # latched false on connection errors

    def ask(self, state: str, timeout: float | None = None) -> dict | None:
        """Returns {"progress": {...}, "failure_mode": {...}, "recoverable": {...},
        "escalate": {...}, "latency_s": float} or None when unreachable."""
        body = json.dumps({"state": state, "questions": SCHEMA["questions"]}).encode()
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "X-Laya-Domain": self.domain},
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                out = json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            self.available = False
            print(f"[laya] unreachable: {e}")
            return None
        answers = out.get("answers") or {}
        result = {"latency_s": round(time.time() - t0, 3), "model": out.get("model")}
        for head in SCHEMA["questions"]:
            a = answers.get(head) or {}
            probs = a.get("probabilities")
            if probs is None and "noul" in a:  # noul answers are a bare P(true)
                probs = {"true": float(a["noul"]), "false": 1.0 - float(a["noul"])}
            result[head] = {
                "probabilities": probs or {},
                "confidence": a.get("confidence"),
                "choice": a.get("choice"),
            }
        return result

    @staticmethod
    def p(verdict: dict | None, head: str, label: str) -> float:
        """Safe probability accessor: missing model -> 0.0."""
        if not verdict:
            return 0.0
        return float((verdict.get(head) or {}).get("probabilities", {}).get(label, 0.0))


# ------------------------------------------------------------------- dataset
def to_dataset_row(state: str, answers: dict, source: str) -> dict:
    """System One training row (soft labels preserve the teacher's hedging)."""
    soft = {}
    for head, a in (answers or {}).items():
        if head not in SCHEMA["questions"]:
            continue
        q = SCHEMA["questions"][head]
        if isinstance(a, (int, float)):  # noul passed as a bare P(true)
            soft[head] = min(max(float(a), 0.0), 1.0)
            continue
        probs = a.get("probabilities") or {}
        if q["type"] == "noul":
            p_true = float(probs.get("true", a.get("confidence") or 0.5))
            soft[head] = min(max(p_true, 0.0), 1.0)
        else:
            total = sum(probs.values()) or 1.0
            soft[head] = {k: round(v / total, 4) for k, v in probs.items()}
    return {
        "state": state,
        "questions": SCHEMA["questions"],
        "answers": soft,
        "source": source,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":")) + "\n")


# ------------------------------------------------------------------------ cli
def _demo_state() -> str:
    obs = {
        "scenario": "pick_place",
        "step": 140,
        "t": 4.7,
        "ee": {"pos": [0.19, 0.01, 0.09]},
        "goal": {"pos": [0.22, 0.03, 0.02]},
        "gripper": 1.0,
        "objects": [{"id": "cube", "grasped": False, "contact": False}],
        "progress": {"stage": "reach", "dist_to_goal": 0.071},
        "last_cmd": {"cmd": "ee", "args": {"pos": [0.21, 0.03, 0.04]}},
    }
    hist = {
        "stall_steps": 45,
        "progress_delta_mm": 1.2,
        "prior_recoveries": 0,
        "ep_success_rate_20": 0.6,
        "vision": "none",
    }
    return format_state(obs, hist)


def main() -> None:
    p = argparse.ArgumentParser(description="Laya System-1 client (robot-ops domain)")
    p.add_argument(
        "--probe", action="store_true", help="measure latency on the demo stall state"
    )
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    p.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="first call may cold-load the model (27 s observed) -- default 60",
    )
    a = p.parse_args()
    state = _demo_state()
    print("STATE:\n" + state + "\n")
    c = LayaClient(a.endpoint, timeout=a.timeout)
    t0 = time.time()
    v = c.ask(state)
    if v is None:
        raise SystemExit(
            "laya unreachable -- start: python .../Laya_integrations/mcp_finetune/serve.py"
        )
    print(
        f"cold probe: {time.time() - t0:.2f}s   (report: {v['latency_s']}s, model={v.get('model')})"
    )
    t0 = time.time()
    v2 = c.ask(state) or v
    print(f"warm probe: {time.time() - t0:.2f}s")
    print(json.dumps({k: v2[k] for k in SCHEMA["questions"]}, indent=2))


if __name__ == "__main__":
    main()
