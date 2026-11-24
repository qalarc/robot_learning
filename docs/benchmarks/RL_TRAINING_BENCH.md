# RL training bench — PPO on SO-101 reach (local, CPU)

*2026-11-24 · run `live_reach_150647` · PPO (SB3 2.9.2, MlpPolicy) · torch 2.15.0+cpu ·
32 subprocess envs (`DummyVecEnv` rejected) · seed 7 · full log `runs/rl/live_reach_150647/`*

## Result

| policy | episodes | success | failure_rate | nines |
|---|---|---|---|---|
| random baseline | 200 | 0.0% | 1.0000 | 0.00 |
| best eval (checkpoint) | 100 | **23.0%** | 0.7700 | 0.11 |
| final (500 eps) | 500 | 11.2% | 0.8880 | 0.05 |

Throughput: **2,866 env-steps/s** (32 parallel envs; physics itself runs at 89k steps/s
single-thread — Python/env overhead dominates, as expected). Wall time for 2.5M steps:
**872 s**. Eval: 100 episodes every 25k steps on a parallel pool; best checkpointed.

## What it took to get here (the honest debugging log)

1. The MJCF had no `<compiler angle="radian"/>` — MuJoCo's degree default silently
   divided the radian joint ranges by 57.3, pinning the arm in a **±3° cone**
   (random policy best-distance ≈ trained policy best-distance ≈ 39 cm, flat reward).
   One line fixed it.
2. Obs-space declared 21 vs emitted 19 (reach) / 24 vs 22 (push) — spaces now match.
3. Reward retune: `−10·dist + 10·success − 0.001·‖a‖²` (was `−1·dist … −0.01·‖a‖²` —
   the action penalty dominated near the target). Hold-for-success 5 → 3 steps.
   400k steps: mean best-distance 13.8 → 6.6 cm, within-3cm 2% → 16%.
4. The real-time showcase **must be a separate process** — an in-process thread calling
   `policy.predict()` during rollouts corrupts SB3's action batches
   (`zip() argument 2 is shorter`), bisected twice. `scripts/train_live.sh` launches
   trainer + follower separately; the follower hot-reloads `best.zip`.

## Reproduce / improve

```bash
bash scripts/train_live.sh 2500000 reach      # live, dashboard + puppet viewer
training/.venv/bin/python scripts/eval_nines.py --checkpoint runs/rl/live_reach_150647/best.zip --episodes 1000
```

Improvement levers (in expected payoff order): more steps (10M overnight ≈ 1 h —
success was still climbing at 2.5M), obs normalisation, net size 64×64 → 256×256,
curriculum (success threshold 15 mm → 10 mm), `--vec subproc` already default.
Showcase: `training/.venv/bin/python training/train_rl.py --demo runs/rl/live_reach_150647`.
