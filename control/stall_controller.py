#!/usr/bin/env python3
"""The conductor -- the learning loop itself.

Escalation ladder (all measured on this machine, 2026-11-24):

  L0  deterministic stall detector    ~0 cost, every obs (30 Hz)
  L1  Laya System-1 identification    ~1.35 s warm  (typed, calibrated)
  L2  escalation gate                 Laya 'escalate' p >= threshold (fail-open)
  L3  GLM System-2 reasoning          15-30 s       (local Ollama, on stall only)
      + deterministic safety shield   (validate_plan -- the model is abliterated;
                                       ALL bounds live here, never in the model)
  L4  human / teleop                  request_teleop after --max-per-ep

Every L3 recovery that works is written as a System One training row
(data/robot-ops.jsonl): System 2 teaches System 1, so next time Laya catches
the stall class without waking GLM. Over the day the escalation rate falls --
that curve is the demo. This is the hackathon thesis in miniature:
run -> capture -> find the failure -> fix -> run again.

Headless demo with no browser:
    python agents/hub.py &
    python agents/fake_sim.py --fault ik_residual &
    python control/stall_controller.py
"""

from __future__ import annotations

import argparse
import json
import signal
import statistics
import sys
import threading
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # control/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents"))  # agents/
from bus_client import SyncBus  # noqa: E402
from glm_s2 import GLMS2, build_dossier, plan_to_cmds  # noqa: E402
from laya_client import LayaClient, append_row, format_state, to_dataset_row  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (Path(__file__).resolve().parent / "robot_ops.schema.json").read_text()
)


def scripted_recovery(current_ee: list) -> list[dict]:
    """Bounded fallback when System 2 is unreachable or produced nothing."""
    ee = list(current_ee[:3]) if len(current_ee) >= 3 else [0.15, 0.0, 0.10]
    ee[2] = min(ee[2] + 0.03, SCHEMA["workspace"]["z"][1])
    return [
        {
            "skill": "backoff",
            "args": {"axis": "z", "metres": 0.03},
            "why": "scripted fallback",
        },
        {
            "skill": "move_ee",
            "args": {"x": round(ee[0], 3), "y": round(ee[1], 3), "z": round(ee[2], 3)},
            "why": "reset to hover",
        },
    ]


class Controller:
    def __init__(self, args):
        self.args = args
        self.bus = SyncBus(
            "stall-controller", roles=["controller"], subscribe=["sim.obs"]
        )
        self.laya = LayaClient(timeout=args.laya_timeout) if not args.no_laya else None
        self.s2 = (
            GLMS2(model=args.model, timeout=args.glm_timeout)
            if not args.no_glm
            else None
        )
        self.label_path = Path(args.label_file)
        self.metrics_path = Path(args.metrics)

        # per-episode state
        self.ep = -1
        self.step = 0
        self.best_dist = None  # best (smallest) distance-to-goal this episode
        self.stall_steps = 0
        self.prior_recoveries = 0
        self.recent_events: deque = deque(maxlen=10)

        # pending recovery awaiting evaluation
        self.pending = None  # dict or None
        self.eval_until = 0
        self.stall_dist_at_detection = None
        self._ignore_obs_before = 0.0  # drop obs older than this (stale while blocked)

        # day metrics
        self.m = {
            "episodes": 0,
            "successes": 0,
            "stalls": 0,
            "escalations": 0,
            "escalations_helped": 0,
            "recover_times_s": [],
            "rows": 0,
            "laya_calls": 0,
            "glm_calls": 0,
        }
        self.ep_history: deque = deque(maxlen=20)  # 1/0 success flags
        self._metrics_dirty = True

    # ---------------------------------------------------------------- helpers
    def log(self, level: str, msg: str) -> None:
        print(f"[{level}] {msg}", flush=True)
        try:
            self.bus.send("log", {"level": level, "msg": msg[:400]})
        except Exception:
            pass

    def history_summary(self) -> dict:
        return {
            "episodes": len(self.ep_history),
            "successes": int(sum(self.ep_history)),
            "prior_recoveries": self.prior_recoveries,
        }

    def write_metrics(self, force: bool = False) -> None:
        if not self._metrics_dirty and not force:
            return
        rt = self.m["recover_times_s"]
        out = dict(self.m)
        out["recover_times_s"] = rt[-50:]
        out["mean_time_to_recover_s"] = round(statistics.mean(rt), 2) if rt else None
        out["escalation_success_rate"] = (
            round(self.m["escalations_helped"] / self.m["escalations"], 3)
            if self.m["escalations"]
            else None
        )
        out["ep_success_rate_20"] = (
            round(sum(self.ep_history) / len(self.ep_history), 3)
            if self.ep_history
            else None
        )
        try:
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            self.metrics_path.write_text(json.dumps(out, indent=2))
            self._metrics_dirty = False
        except OSError as e:
            print(f"[warn] metrics write failed: {e}")

    # ------------------------------------------------------------------ loop
    def on_obs(self, obs: dict) -> None:
        # obs that queued while we were blocked in Laya/GLM are stale -- they
        # predate the recovery and must not burn the evaluation window
        if (obs.get("ts") or 0) < self._ignore_obs_before:
            return
        data = obs.get("data") or {}
        if data.get("ep") != self.ep:
            self.ep = data.get("ep", -1)
            self._reset_episode()
        self.step = data.get("step", 0)
        dist = (data.get("progress") or {}).get("dist_to_goal")
        if isinstance(dist, (int, float)):
            if self.best_dist is None or dist < self.best_dist:
                improved = (
                    (self.best_dist - dist) if self.best_dist is not None else 1.0
                )
                if improved > 0.002:  # 2 mm of real progress ends a stall
                    self.stall_steps = 0
                    if self.pending and improved > 0.005:
                        self._resolve_pending("resumed")
                self.best_dist = dist

        sim_stall = data.get("stall") or {}
        if sim_stall.get("stalled") or self.stall_steps >= self.args.min_stall_steps:
            self.stall_steps = max(
                self.stall_steps,
                int(sim_stall.get("steps") or self.args.min_stall_steps),
            )
            self._maybe_escalate(data)
        else:
            self.stall_steps += 1

        if self.pending and self.step >= self.eval_until:
            self._resolve_pending("timeout")

    def on_event(self, ev: dict) -> None:
        data = ev.get("data") or {}
        kind = data.get("kind", "?")
        self.recent_events.append(f"{kind} ep={data.get('ep')} step={data.get('step')}")
        if kind == "episode_end":
            ok = bool(data.get("success"))
            self.ep_history.append(1 if ok else 0)
            self.m["episodes"] += 1
            self.m["successes"] += int(ok)
            if self.pending:
                self._resolve_pending("done" if ok else "episode_fail")
            self._metrics_dirty = True
            self.write_metrics()

    def _reset_episode(self) -> None:
        self.best_dist = None
        self.stall_steps = 0
        self.prior_recoveries = 0
        self.pending = None
        self.stall_dist_at_detection = None

    # ------------------------------------------------------------ escalation
    def _maybe_escalate(self, obs_data: dict) -> None:
        if self.pending:
            return
        if self.prior_recoveries >= self.args.max_per_ep:
            if self.prior_recoveries == self.args.max_per_ep:  # once per episode
                self.log(
                    "warn", f"ep {self.ep}: max recoveries reached -> requesting teleop"
                )
                if not self.args.dry_run:
                    self.bus.send(
                        "sim.cmd",
                        {"cmd": "mode", "args": {"control": "ik"}},
                        to=self.args.sim,
                    )
                self.prior_recoveries += 1
            return
        self.m["stalls"] += 1
        self._metrics_dirty = True

        hist = {
            "stall_steps": self.stall_steps,
            "progress_delta_mm": 0.0,
            "prior_recoveries": self.prior_recoveries,
            "ep_success_rate_20": (
                sum(self.ep_history) / len(self.ep_history) if self.ep_history else 0.0
            ),
            "vision": "none",
        }
        state = format_state(obs_data, hist)

        # L1 -- Laya identification (fail-open: unreachable => proceed anyway)
        laya = None
        if self.laya:
            laya = self.laya.ask(state, timeout=self.args.laya_timeout)
            if laya:
                self.m["laya_calls"] += 1
        self.log(
            "info",
            f"STALL ep={self.ep} step={self.step} "
            f"stall_steps={self.stall_steps} "
            + (
                f"laya: progress={laya['progress'].get('choice')} "
                f"gate_p={max(laya.get('escalate', {}).get('probabilities', {}).get('true', 0.0), laya['progress'].get('probabilities', {}).get('stalled', 0.0)):.2f}"
                if laya
                else "laya: offline (fail-open)"
            ),
        )

        dossier = build_dossier(
            state, laya, self.history_summary(), list(self.recent_events)
        )
        try:
            self.bus.send(
                "ctl.stall",
                {
                    "ep": self.ep,
                    "step": self.step,
                    "detector": obs_data.get("stall"),
                    "laya": laya,
                    "dossier": dossier,
                },
            )
        except Exception:
            pass

        # L2 -- gate
        gate_p = 1.0  # fail-open
        if laya:
            gate_p = max(
                laya.get("escalate", {}).get("probabilities", {}).get("true", 0.0),
                laya.get("progress", {}).get("probabilities", {}).get("stalled", 0.0),
            )
        if gate_p < self.args.escalate_thresh:
            self.log(
                "info", f"gate: Laya says do not escalate (p={gate_p:.2f}) -- waiting"
            )
            self.stall_steps = 0  # re-arm
            return

        # L3 -- System 2 + safety shield
        t0 = time.time()
        source, steps, s2res = (
            "scripted",
            scripted_recovery((obs_data.get("ee") or {}).get("pos") or []),
            None,
        )
        if self.s2:
            s2res = self.s2.ask(dossier)
            if s2res:
                self.m["glm_calls"] += 1
                if s2res["steps"]:
                    source, steps = "glm-s2", s2res["steps"]
                if s2res.get("rejections"):
                    self.log("warn", f"shield rejected: {s2res['rejections']}")
        self.log(
            "info",
            f"recovery via {source} in {time.time() - t0:.1f}s "
            f"({len(steps)} steps)"
            + (f" s2_latency={s2res['latency_s']}s" if s2res else ""),
        )

        # translate + issue
        ee = (obs_data.get("ee") or {}).get("pos") or [0.15, 0.0, 0.10]
        issued = []
        for st in steps:
            for cmd in plan_to_cmds(st, list(ee)):
                issued.append(cmd)
                if not self.args.dry_run:
                    try:
                        self.bus.send("sim.cmd", cmd, to=self.args.sim)
                    except Exception as e:  # bus died mid-issuance: log, keep the label
                        self.log("error", f"bus send failed ({e}); recovery truncated")
                        break
                    time.sleep(self.args.step_gap)
        try:
            self.bus.send(
                "ctl.recovery",
                {
                    "ep": self.ep,
                    "step": self.step,
                    "source": source,
                    "plan": s2res["plan_raw"] if s2res else {"steps": steps},
                    "issued": issued,
                    "dry_run": self.args.dry_run,
                },
            )
        except Exception:
            pass

        self.pending = {
            "state": state,
            "laya": laya,
            "s2": s2res,
            "issued": issued,
            "stall_step": self.step,
            "stall_t": time.time(),
            "stall_dist": self.best_dist,
        }
        self.eval_until = self.step + self.args.eval_window
        self._ignore_obs_before = time.time()  # fresh obs only from here
        self.stall_steps = 0
        self.prior_recoveries += 1
        self.m["escalations"] += 1
        self._metrics_dirty = True
        self.write_metrics()
        if self.args.once:
            raise KeyboardInterrupt  # demo mode: one escalation then exit

    # ------------------------------------------------------------- labelling
    def _resolve_pending(self, outcome: str) -> None:
        p = self.pending
        self.pending = None
        if p is None:
            return
        resumed = outcome in ("resumed", "done")
        if resumed:
            self.m["escalations_helped"] += 1
            self.m["recover_times_s"].append(round(time.time() - p["stall_t"], 2))
        self._metrics_dirty = True

        answers: dict = {}
        # progress: outcome ground truth, softly
        answers["progress"] = (
            {"probabilities": {"advancing": 0.8, "done": 0.15}}
            if resumed
            else {"probabilities": {"stalled": 0.8, "regressing": 0.2}}
        )
        # failure_mode: System 2 teaches System 1 (0.7 root cause + 0.3 Laya spread)
        root = (
            (p.get("s2") or {}).get("plan_raw", {}).get("root_cause")
            if p.get("s2")
            else None
        )
        fm = {}
        if root in SCHEMA["questions"]["failure_mode"]["criteria"]:
            fm[root] = 0.7
        laya_fm = ((p.get("laya") or {}).get("failure_mode") or {}).get(
            "probabilities"
        ) or {}
        for k, v in laya_fm.items():
            fm[k] = fm.get(k, 0.0) + 0.3 * float(v)
        if not fm:
            fm = {"none": 1.0}
        answers["failure_mode"] = {"probabilities": fm}
        answers["recoverable"] = 0.9 if resumed else 0.1
        answers["escalate"] = 0.9 if resumed else 0.3

        row = to_dataset_row(p["state"], answers, source="stall-loop")
        try:
            append_row(self.label_path, row)
            self.m["rows"] += 1
            self.log(
                "info",
                f"labelled stall outcome={outcome} resumed={resumed} "
                f"-> {self.label_path} (rows={self.m['rows']})",
            )
        except OSError as e:
            self.log("error", f"label write failed: {e}")
        self.write_metrics()

    # ----------------------------------------------------------------- run
    def run(self) -> None:
        self.log(
            "info",
            f"controller up  laya={'on' if self.laya else 'off'} "
            f"glm={'on' if self.s2 else 'off'} dry_run={self.args.dry_run}",
        )
        stop = threading.Event()

        def _sigint(_s, _f):
            stop.set()

        signal.signal(signal.SIGINT, _sigint)
        signal.signal(signal.SIGTERM, _sigint)
        while not stop.is_set():
            msg = self.bus.recv(timeout=0.2)
            if msg is None:
                continue
            topic = msg.get("topic")
            if topic == "sim.obs":
                self.on_obs(msg)
            elif topic == "sim.event":
                self.on_event(msg)
        self.write_metrics(force=True)
        self.log("info", f"controller down  metrics={json.dumps(self.m)}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=(__doc__ or "Stall-recovery learning-loop controller").splitlines()[
            0
        ]
    )
    p.add_argument("--bus", default=None)
    p.add_argument(
        "--sim", default="armsmith-web", help="bus name of the sim to command"
    )
    p.add_argument("--model", default=SCHEMA["s2"]["model_default"])
    p.add_argument("--no-laya", action="store_true")
    p.add_argument("--no-glm", action="store_true")
    p.add_argument("--laya-timeout", type=float, default=10.0)
    p.add_argument("--glm-timeout", type=float, default=150.0)
    p.add_argument(
        "--min-stall-steps",
        type=int,
        default=90,
        help="obs steps without >2mm progress before escalating (90 = 3 s at 30 Hz)",
    )
    p.add_argument(
        "--cooldown",
        type=float,
        default=4.0,
        dest="step_gap",
        help="seconds between issued recovery commands",
    )
    p.add_argument("--max-per-ep", type=int, default=3)
    p.add_argument(
        "--eval-window",
        type=int,
        default=120,
        help="obs steps to wait before judging a recovery",
    )
    p.add_argument("--escalate-thresh", type=float, default=0.5)
    p.add_argument("--label-file", default=str(REPO / "data" / "robot-ops.jsonl"))
    p.add_argument("--metrics", default=str(REPO / "runs" / "metrics.json"))
    p.add_argument(
        "--dry-run", action="store_true", help="log everything, command nothing"
    )
    p.add_argument(
        "--once", action="store_true", help="exit after the first escalation (demos)"
    )
    a = p.parse_args()
    Controller(a).run()


if __name__ == "__main__":
    main()
