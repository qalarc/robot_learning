#!/usr/bin/env python3
"""System 2 -- local GLM stall reasoner (Ollama, glm-4.7-flash-abl:alexei-v3).

Woken only when the loop stalls. Measured on this machine (model resident,
Strix Halo iGPU): 15-30 s per recovery plan at ~14 tok/s decode, prompt eval
<1.5 s. Returns a SYMBOLIC recovery plan; a deterministic safety shield
(validated_skills) then clamps every argument before anything reaches the bus.
The model is abliterated -- assume zero self-restraint; ALL safety is here.

CLI probe:
    sim/py/.venv/bin/python control/glm_s2.py --probe
    sim/py/.venv/bin/python control/glm_s2.py --probe --model glm-4.7-flash-abl:32k
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent / "robot_ops.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
OLLAMA = "http://127.0.0.1:11434/api/generate"

SKILL_SIGNATURES = {
    # skill -> (args we accept, clamps). Anything else the model invents is dropped.
    "backoff": {"axis": ("x", "y", "z"), "metres": (0.0, 0.05)},
    "regrasp": {},
    "move_ee": {
        "x": None,
        "y": None,
        "z": None,
        "gripper": (0.0, 1.0),
    },  # None -> workspace clamp
    "set_gripper": {"open": (0.0, 1.0)},
    "approach_from": {"from": ("above", "side", "front"), "target": None},
    "wiggle": {"amp": (0.0, 0.01)},
    "switch_camera": {"cam": ("free", "wrist", "env")},
    "replan_scenario": {"scenario": ("reach", "pick_place", "push_to_zone", "stack")},
    "request_teleop": {},
    "abort": {},
}
WORKSPACE = SCHEMA["workspace"]


# ------------------------------------------------------------------ dossier
def build_dossier(
    state: str, laya_verdict: dict | None, history: dict, recent: list[str]
) -> str:
    """Compact, line-oriented briefing for the reasoner. Cheap tokens, no prose."""
    lines = [f"STATE: {state}"]
    if laya_verdict:
        lv = []
        for head, a in laya_verdict.items():
            if head in ("latency_s", "model"):
                continue
            probs = a.get("probabilities") or {}
            if probs:
                top = ", ".join(
                    f"{k}={v:.2f}"
                    for k, v in sorted(probs.items(), key=lambda kv: -kv[1])[:4]
                )
                lv.append(f"{head}: {top}")
        lines.append("S1 TYPED VERDICT (calibrated): " + "; ".join(lv))
    if history:
        lines.append(f"HISTORY: {json.dumps(history, separators=(',', ':'))}")
    if recent:
        lines.append("RECENT EVENTS: " + " | ".join(recent[-6:]))
    lines.append(
        "AVAILABLE SKILLS: "
        + " | ".join(
            f"{k}({','.join(v) if v else ''})" for k, v in SKILL_SIGNATURES.items()
        )
    )
    lines.append(
        'Return ONLY JSON: {"diagnosis": str (<=2 sentences), '
        '"root_cause": one of ['
        + ",".join(SCHEMA["questions"]["failure_mode"]["criteria"])
        + "], "
        '"plan": [{"skill": str, "args": {}, "why": str}] '
        f"(max {SCHEMA['s2']['max_plan_steps']} ordered steps), "
        '"abort_if": str (observable condition), "confidence": 0..1}. '
        "Minified JSON on ONE line, each why at most 10 words, no markdown."
    )
    return "\n".join(lines)


def loads_lenient(text: str) -> dict:
    """Parse model JSON; salvage a plan truncated by the token cap by cutting
    back to the last complete step object and closing the structure."""
    text = (text or "").strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except ValueError:
        pass
    for i in range(len(text) - 1, -1, -1):
        if text[i] != "}":
            continue
        frag = text[: i + 1]
        for closers in ("", "]", "}", "]}", "}}", "]}}", "}}}", "]}}}"):
            try:
                obj = json.loads(frag + closers)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("plan"):
                obj["_salvaged"] = True
                return obj
    return {}


# ---------------------------------------------------------- safety shield
def _clamp(value, lo, hi):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def validate_plan(plan: dict) -> tuple[list[dict], list[str]]:
    """Deterministic shield between the model and the robot.

    Drops unknown skills, whitelists args, clamps every numeric to bounds,
    caps plan length. Returns (clean_steps, rejections).
    """
    clean, rejections = [], []
    raw = plan.get("plan") if isinstance(plan, dict) else None
    if not isinstance(raw, list):
        return clean, ["plan missing/not a list"]
    for i, step in enumerate(raw):
        if len(clean) >= SCHEMA["s2"]["max_plan_steps"]:
            rejections.append(f"step {i}: plan length cap")
            break
        if not isinstance(step, dict):
            rejections.append(f"step {i}: not an object")
            continue
        skill = str(step.get("skill", "")).strip()
        if skill not in SKILL_SIGNATURES:
            rejections.append(f"step {i}: unknown skill '{skill}'")
            continue
        sig = SKILL_SIGNATURES[skill]
        raw_args = step.get("args")
        args_in: dict = raw_args if isinstance(raw_args, dict) else {}
        args: dict = {}
        for key, bounds in sig.items():
            if key not in args_in:
                continue
            val = args_in[key]
            if bounds is None:  # workspace clamp (move_ee target)
                axis = key
                lo, hi = WORKSPACE.get(axis, (-1.0, 1.0))
                args[axis] = round(_clamp(val, lo, hi), 4)
            elif isinstance(bounds, tuple) and bounds and isinstance(bounds[0], str):
                choice = str(val)
                args[key] = choice if choice in bounds else bounds[0]
            elif isinstance(bounds, tuple):
                args[key] = round(_clamp(val, bounds[0], bounds[1]), 4)
            else:
                args[key] = val
        # move_ee with no coordinates is useless -> make it a no-op reject
        if skill == "move_ee" and not any(k in args for k in ("x", "y", "z")):
            rejections.append(f"step {i}: move_ee without coordinates")
            continue
        clean.append(
            {"skill": skill, "args": args, "why": str(step.get("why", ""))[:200]}
        )
    return clean, rejections


def plan_to_cmds(plan_step: dict, current_ee: list) -> list[dict]:
    """Translate one validated skill step into sim.cmd payloads."""
    s, a = plan_step["skill"], plan_step["args"]
    if s == "move_ee":
        pos = [
            a.get("x", current_ee[0] if len(current_ee) > 0 else 0.15),
            a.get("y", current_ee[1] if len(current_ee) > 1 else 0.0),
            a.get("z", current_ee[2] if len(current_ee) > 2 else 0.1),
        ]
        cmd = {"cmd": "ee", "args": {"pos": [round(p, 4) for p in pos]}}
        if "gripper" in a:
            cmd["args"]["gripper"] = a["gripper"]
        return [cmd]
    if s == "set_gripper":
        return [{"cmd": "gripper", "args": {"open": a.get("open", 0.0)}}]
    if s == "backoff":
        axis = a.get("axis", "z")
        delta = a.get("metres", 0.03)
        pos = list(current_ee[:3]) if len(current_ee) >= 3 else [0.15, 0.0, 0.1]
        idx = {"x": 0, "y": 1, "z": 2}[axis]
        pos[idx] = _clamp(pos[idx] + delta, *WORKSPACE.get(axis, (-1, 1)))
        return [{"cmd": "ee", "args": {"pos": [round(p, 4) for p in pos]}}]
    if s == "approach_from":
        # approach the last commanded target from a named direction
        return [
            {"cmd": "ee", "args": {"approach": a.get("from", "above"), "gripper": 1.0}}
        ]
    if s == "wiggle":
        return [{"cmd": "ee", "args": {"wiggle": a.get("amp", 0.005)}}]
    if s == "regrasp":
        return [
            {"cmd": "gripper", "args": {"open": 1.0}},
            {"cmd": "gripper", "args": {"open": 0.0}},
        ]
    if s == "switch_camera":
        return [{"cmd": "snapshot", "args": {"cam": a.get("cam", "wrist")}}]
    if s == "replan_scenario":
        return [{"cmd": "reset", "args": {"scenario": a.get("scenario", "pick_place")}}]
    if s == "request_teleop":
        return [{"cmd": "mode", "args": {"control": "ik"}}]  # human takes over
    if s == "abort":
        return [{"cmd": "mode", "args": {"control": "off"}}]
    return []


# ------------------------------------------------------------------- client
class GLMS2:
    def __init__(
        self,
        model: str | None = None,
        endpoint: str = OLLAMA,
        timeout: float = 150.0,
        keep_alive: str = "30m",
    ):
        self.model = model or SCHEMA["s2"]["model_default"]
        self.endpoint = endpoint
        self.timeout = timeout
        self.keep_alive = keep_alive

    def ask(self, dossier: str, timeout: float | None = None) -> dict | None:
        """Returns {plan_raw, steps, rejections, latency_s, eval_s, n_tokens} or None."""
        body = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "format": "json",
                "keep_alive": self.keep_alive,
                "options": {
                    "num_predict": SCHEMA["s2"]["num_predict"],
                    "temperature": 0.3,
                },
                "system": SCHEMA["s2"]["system_prompt"],
                "prompt": dossier,
            }
        ).encode()
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                out = json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            print(f"[glm-s2] unreachable: {e}")
            return None
        plan = loads_lenient(out.get("response", ""))
        steps, rejections = validate_plan(plan)
        return {
            "plan_raw": plan,
            "steps": steps,
            "rejections": rejections,
            "latency_s": round(time.time() - t0, 2),
            "eval_s": round((out.get("eval_duration") or 0) / 1e9, 2),
            "n_tokens": out.get("eval_count", 0),
            "model": self.model,
        }


# ------------------------------------------------------------------------ cli
def main() -> None:
    p = argparse.ArgumentParser(description="System-2 stall reasoner (Ollama)")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--model", default=SCHEMA["s2"]["model_default"])
    a = p.parse_args()
    if not a.probe:
        p.print_help()
        return
    # a realistic stall: measured 14.8-28.3 s on this machine with the model resident
    from laya_client import _demo_state  # control/ is sys.path[0] when run as a script

    laya_like = {
        "progress": {"probabilities": {"stalled": 0.91}},
        "failure_mode": {
            "probabilities": {
                "unreachable_or_ik_residual": 0.61,
                "collision": 0.19,
                "bad_perception": 0.11,
                "grip_slip": 0.07,
                "none": 0.02,
            }
        },
        "recoverable": {"probabilities": {"true": 0.88}},
    }
    dossier = build_dossier(
        _demo_state(),
        laya_like,
        {"episodes": 20, "successes": 12, "prior_recoveries": 0},
        ["episode_start seed=7", "stage reach->(stuck)"],
    )
    print("DOSSIER:\n" + dossier + "\n---\n")
    s2 = GLMS2(model=a.model)
    res = s2.ask(dossier)
    if res is None:
        raise SystemExit("ollama unreachable on :11434")
    print(f"latency={res['latency_s']}s eval={res['eval_s']}s tokens={res['n_tokens']}")
    print("VALIDATED STEPS:")
    print(json.dumps(res["steps"], indent=2))
    if res["rejections"]:
        print("SHIELD REJECTIONS:", res["rejections"])


if __name__ == "__main__":
    main()
