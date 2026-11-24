#!/usr/bin/env python3
"""PPO training on the SO-101 MuJoCo envs — visible live on the Robot Bus.

Train (publishes train.metrics + a real-time showcase env for the puppet viewer):
    training/.venv/bin/python training/train_rl.py
Watch:
    bash sim/dashboard/serve.sh   ->  http://127.0.0.1:8892/  (nines + curves)
                                       http://127.0.0.1:8891/?view=puppet (the arm)
Showcase a trained policy at real time:
    training/.venv/bin/python training/train_rl.py --demo runs/rl/<run_id>/best.zip

Design notes:
- Training envs run flat-out (DummyVecEnv); a SEPARATE demo env runs the current
  policy at 30 Hz in a thread and publishes sim.obs — so the browser shows smooth,
  current-policy motion instead of 100x-speed training noise.
- The bus publisher is lazy and never blocks: hub down => training is unaffected.
- nines = -log10(failure_rate): the hackathon headline metric.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sim" / "py"))

import numpy as np  # noqa: E402
import torch  # noqa: E402

# one lock around every policy.predict(): the showcase thread and the eval
# callback otherwise race inside SB3's predict plumbing
PREDICT_LOCK = threading.Lock()


def safe_predict(policy, obs, deterministic=True):
    with PREDICT_LOCK:
        act, _ = policy.predict(obs, deterministic=deterministic)
    act = np.asarray(act)
    if act.ndim == 1:  # single-env obs -> (1, act_dim)
        act = act[None, :]
    return act


from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.callbacks import BaseCallback  # noqa: E402
from stable_baselines3.common.monitor import Monitor  # noqa: E402
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv  # noqa: E402

from mujoco_env import SO101PushEnv, SO101ReachEnv, attach_bus  # noqa: E402

ENVS = {"reach": SO101ReachEnv, "push": SO101PushEnv}


def nines(failure_rate: float) -> float:
    return round(-math.log10(min(max(failure_rate, 1e-4), 1.0)), 4)


# --------------------------------------------------------------------- eval
def make_vec(make, n: int, subproc: bool = True):
    """Parallel env pool: subprocesses across cores when available (Linux fork)."""
    fns = [make(i) for i in range(n)]
    if subproc and n >= 2:
        try:
            return SubprocVecEnv(fns, start_method="fork")
        except Exception:
            pass
    return DummyVecEnv(fns)


def evaluate(
    make, n_episodes: int, policy=None, deterministic: bool = True, venv=None
) -> dict:
    """Run n_episodes on parallel envs; policy=None => random actions."""
    own = venv is None
    venv = venv or make_vec(make, min(8, n_episodes))
    n_par = venv.num_envs
    obs = venv.reset()
    succ = fails = steps = 0
    ep_len = []
    cur_len = [0] * n_par
    while succ + fails < n_episodes:
        if policy is None:
            act = [venv.action_space.sample() for _ in range(n_par)]
        else:
            act = safe_predict(policy, obs, deterministic=deterministic)
            if act.shape[0] != n_par:
                print(
                    f"[eval] predict shape {act.shape} != n_par {n_par} "
                    f"(obs {np.asarray(obs).shape}) — resizing",
                    flush=True,
                )
                act = np.resize(act, (n_par, act.shape[-1]))
        obs, _, dones, infos = venv.step(act)
        for i, d in enumerate(dones):
            cur_len[i] += 1
            steps += 1
            if d:
                if bool(infos[i].get("is_success")):
                    succ += 1
                else:
                    fails += 1
                ep_len.append(cur_len[i])
                cur_len[i] = 0
                if succ + fails >= n_episodes:
                    break
    if own:
        venv.close()
    total = succ + fails
    fr = fails / total if total else 1.0
    return {
        "episodes": total,
        "success_rate": round(succ / total, 4) if total else 0.0,
        "failure_rate": round(fr, 4),
        "nines": nines(fr),
        "mean_ep_len": round(float(np.mean(ep_len)), 1) if ep_len else None,
    }


# ------------------------------------------------------------------- demo
class Showcase(threading.Thread):
    """Real-time current-policy demo env; the env itself publishes sim.obs."""

    def __init__(
        self,
        make_raw,
        get_policy,
        hz: float = 30.0,
        bus_name: str = "mujoco",
        url: str | None = None,
    ):
        super().__init__(daemon=True)
        self.env = make_raw()  # RAW env (no Monitor): .bus must sit on the env itself
        attach_bus(self.env, name=bus_name, obs_hz=hz, url=url)
        self.get_policy = get_policy
        self.dt = 1.0 / hz
        self.running = True
        self.results: deque = deque(maxlen=50)
        self._obs, _ = self.env.reset()
        self._len = 0

    def run(self):
        while self.running:
            t0 = time.monotonic()
            try:
                policy = self.get_policy()
                if policy is None:
                    act = self.env.action_space.sample()
                else:
                    a = safe_predict(policy, np.asarray(self._obs), deterministic=True)
                    act = a
                self._obs, _, term, trunc, info = self.env.step(act)
                self._len += 1
                if term or trunc:
                    self.results.append(1 if info.get("is_success") else 0)
                    self._obs, _ = self.env.reset()
                    self._len = 0
            except Exception:
                pass  # the showcase must never kill training
            sleep = self.dt - (time.monotonic() - t0)
            if sleep > 0:
                time.sleep(sleep)

    @property
    def success_rate(self):
        return round(sum(self.results) / len(self.results), 3) if self.results else None


# ---------------------------------------------------------------- callback
class BusEvalCallback(BaseCallback):
    def __init__(
        self,
        make,
        pub,
        run_id,
        env_name,
        n_envs,
        baseline,
        eval_freq=20_000,
        eval_episodes=100,
        out_dir: Path | None = None,
        metrics_hz=5.0,
    ):
        super().__init__()
        self.make, self.pub, self.run_id = make, pub, run_id
        self.env_name, self.n_envs, self.baseline = env_name, n_envs, baseline
        self.eval_freq, self.eval_episodes = eval_freq, eval_episodes
        self.out_dir = out_dir
        self._last_eval = 0
        self._last_pub = 0.0
        self._last_eval_res: dict = {}
        self.best = -1.0
        self.ep_outcomes: deque = deque(maxlen=100)
        self.history: list = []
        self.t0 = time.time()

    def _on_step(self) -> bool:
        infos = self.locals.get("infos", [])
        dones = self.locals.get("dones", [])
        for i, d in enumerate(dones):
            if d and i < len(infos):
                self.ep_outcomes.append(1 if infos[i].get("is_success") else 0)

        now = time.monotonic()
        if now - self._last_pub < 1.0 / 5:  # <=5 Hz
            return True
        self._last_pub = now
        if self.eval_freq and self.num_timesteps - self._last_eval >= self.eval_freq:
            self._last_eval = self.num_timesteps
            res = evaluate(
                self.make, self.eval_episodes, policy=self.model, deterministic=True
            )
            if res["success_rate"] > self.best:
                self.best = res["success_rate"]
                if self.out_dir:
                    self.model.save(self.out_dir / "best")
            self.history.append([self.num_timesteps, res["success_rate"]])
            self._last_eval_res = res

        rew = (
            [e["r"] for e in self.model.ep_info_buffer]
            if self.model.ep_info_buffer
            else [0.0]
        )
        leng = (
            [e["l"] for e in self.model.ep_info_buffer]
            if self.model.ep_info_buffer
            else [0]
        )
        sr = (
            sum(self.ep_outcomes) / len(self.ep_outcomes)
            if self.ep_outcomes
            else (self._last_eval_res or {}).get("success_rate", 0.0)
        )
        fr = 1.0 - sr
        self.pub.send(
            "train.metrics",
            {
                "run": self.run_id,
                "env": self.env_name,
                "policy": "PPO",
                "stage": "train",
                "timesteps": int(self.num_timesteps),
                "fps": int(self.num_timesteps / max(time.time() - self.t0, 1e-9)),
                "elapsed_s": round(time.time() - self.t0, 1),
                "ep_rew_mean": round(float(np.mean(rew)), 2),
                "ep_len_mean": round(float(np.mean(leng)), 1),
                "ep_success_rate": round(sr, 4),
                "failure_rate": round(fr, 4),
                "nines": nines(fr),
                "baseline_failure_rate": self.baseline.get("failure_rate"),
                "baseline_nines": self.baseline.get("nines"),
                "n_envs": self.n_envs,
                "source": "mujoco",
            },
            hz=5,
        )
        return True


# --------------------------------------------------------------------- main
def main() -> None:
    p = argparse.ArgumentParser(
        description=(__doc__ or "PPO training visible on the Robot Bus").splitlines()[0]
    )
    p.add_argument("--env", choices=list(ENVS), default="reach")
    p.add_argument("--timesteps", type=int, default=1_000_000)
    p.add_argument("--n-envs", type=int, default=16)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--eval-freq", type=int, default=20_000)
    p.add_argument("--eval-episodes", type=int, default=100)
    p.add_argument("--baseline-episodes", type=int, default=200)
    p.add_argument("--torch-threads", type=int, default=8)
    p.add_argument(
        "--vec",
        choices=["auto", "dummy"],
        default="auto",
        help="auto = subprocess envs (use the cores) when n-envs >= 2",
    )
    p.add_argument("--no-bus", action="store_true")
    p.add_argument(
        "--demo",
        metavar="CKPT_OR_RUNDIR",
        help="showcase/follow a saved policy in THIS process (standalone mode)",
    )
    p.add_argument("--run-id", default=None)
    a = p.parse_args()

    torch.set_num_threads(a.torch_threads)
    run_id = a.run_id or f"ppo_{a.env}_{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    url = (
        None if not a.no_bus else "ws://127.0.0.1:1/ws"
    )  # unroutable => publisher stays idle

    def make(rank):
        return lambda: Monitor(ENVS[a.env]())

    # ---- demo-only mode (a SEPARATE process: never inside the training loop,
    # a second thread calling into the policy corrupts SB3's rollouts) --------
    if a.demo:
        target = Path(a.demo)
        show = None
        t0 = time.monotonic()
        loaded = {"model": None, "stamp": None}

        def follow():
            """Load best.zip (or final.zip) from a run dir; reload when it changes."""
            nonlocal show
            ckpt = target
            if target.is_dir():
                cand = target / "best.zip"
                if not cand.exists():
                    cand = target / "final.zip"
                if not cand.exists():
                    return False
                ckpt = cand
            stamp = ckpt.stat().st_mtime
            if loaded["stamp"] == stamp:
                return True
            model = PPO.load(ckpt)
            if show is None:
                show = Showcase(
                    lambda: ENVS[a.env](),
                    lambda: loaded["model"],
                    bus_name="mujoco",
                    url=url,
                )
                show.start()
            loaded["model"], loaded["stamp"] = model, stamp
            print(f"[demo] loaded {ckpt}", flush=True)
            return True

        print(f"[demo] following {a.demo} on the bus (ctrl-c to stop)", flush=True)
        try:
            while True:
                time.sleep(2.0)
                if not follow():
                    continue
                if show is not None:
                    print(
                        f"[demo] t={time.monotonic() - t0:6.0f}s "
                        f"success_rate(50eps)={show.success_rate}",
                        flush=True,
                    )
        except KeyboardInterrupt:
            pass
        return

    # ---- baseline -------------------------------------------------------
    print(f"[baseline] random policy, {a.baseline_episodes} episodes ...")
    baseline = evaluate(make, a.baseline_episodes, policy=None)
    print(f"[baseline] {baseline}")

    # ---- metrics publisher (own connection; the showcase is another process)
    from mujoco_env import BusPublisher  # noqa: E402

    pub = BusPublisher(name="mujoco-train", url=url)

    out_dir = REPO / "runs" / "rl" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    venv = make_vec(make, a.n_envs, subproc=a.vec != "dummy")
    model = PPO(
        "MlpPolicy",
        venv,
        verbose=0,
        seed=a.seed,
        n_steps=1024,
        batch_size=256,
        learning_rate=3e-4,
        gamma=0.99,
    )

    cb = BusEvalCallback(
        make,
        pub,
        run_id,
        a.env,
        a.n_envs,
        baseline,
        eval_freq=a.eval_freq,
        eval_episodes=a.eval_episodes,
        out_dir=out_dir,
    )
    print(
        f"[train] {a.env}: {a.timesteps} steps, {a.n_envs} envs, seed {a.seed} "
        f"-> {out_dir}"
    )
    t0 = time.time()
    model.learn(total_timesteps=a.timesteps, callback=cb, progress_bar=False)
    wall = time.time() - t0

    model.save(out_dir / "final")
    final = evaluate(make, max(500, a.eval_episodes), policy=model)
    result = {
        "run_id": run_id,
        "env": a.env,
        "timesteps": a.timesteps,
        "n_envs": a.n_envs,
        "seed": a.seed,
        "wall_s": round(wall, 1),
        "steps_per_s": int(a.timesteps / wall),
        "baseline": baseline,
        "final": final,
        "best_eval_success_rate": cb.best,
        "success_history": cb.history,
        "versions": {
            "torch": torch.__version__,
            "sb3": __import__("stable_baselines3").__version__,
        },
    }
    (out_dir / "result.json").write_text(json.dumps(result, indent=2))

    def row(name, r):
        return (
            f"| {name} | {r['episodes']} | {r['success_rate']:.1%} | "
            f"{r['failure_rate']:.4f} | {r['nines']:.2f} |"
        )

    print("\n== nines table ==")
    print("| policy | episodes | success | failure_rate | nines |")
    print("|---|---|---|---|---|")
    print(row("random baseline", baseline))
    print(
        row(
            "best eval",
            {
                "episodes": a.eval_episodes,
                "success_rate": cb.best,
                "failure_rate": 1 - cb.best,
                "nines": nines(1 - cb.best),
            },
        )
    )
    print(row("final (500 eps)", final))
    print(
        f"\n[result] {out_dir / 'result.json'}  "
        f"({result['steps_per_s']} steps/s, wall {wall:.0f}s)"
    )


if __name__ == "__main__":
    main()
