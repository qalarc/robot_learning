# Training

**Four training tiers on one machine with no NVIDIA GPU — pick by what the demo needs: RL for the visible curve, distillation for the "learns from failure" story, imitation only if spare cycles exist.** Source: [docs/11_training_playbook.md](../docs/11_training_playbook.md).

## The tiers

| tier | what | where it runs | when to use |
|---|---|---|---|
| **A. RL in sim** | PPO on MuJoCo reach/push (`training/train_rl.py`, stable-baselines3) | local CPU (physics ~1.4–1.5M steps/s at 32 workers) + optional iGPU nets | no demos needed; visible curve in 10–30 min; the "nines" engine — start early, run all day |
| **B. Imitation** | ACT / Diffusion / SmolVLA via LeRobot | free Kaggle 2xT4 / Colab; local CPU for tiny sets | only when teleop demos exist and someone is free |
| **C. Distillation** | Laya `robot-ops` fine-tune (GUT) | local CPU ~1 h/1k rows, iGPU, or Kaggle | the S2-teaches-S1 flywheel — whenever ≥250 rows exist |
| **D. Models** | alexei (System 2) | local Ollama on the iGPU | no training; ~46 tok/s uncontended, 255-token plan ≈ 5.5 s decode |

Recommended order (doc 11): scripted baseline → A → C → B if cycles spare. `train_rl.py` trains PPO via DummyVecEnv, publishes `train.metrics` + a separate 30 Hz demo env so the puppet viewer shows smooth current-policy motion; the bus publisher never blocks training.

## What the MuJoCo throughput buys

Official SO-101 model: **89k steps/s** single-thread (1.7 ms per 150-step episode); `mujoco.rollout` scaling 1→126,859, 8→859,968 (6.78x), 32→**1,510,424 steps/s** (11.91x; sweet spot 8–16 workers). EGL render 229 fps @ 640×480. The point is statistical confidence: a 10,000-episode evaluation costs ~17 s, so you can claim a nine honestly instead of vibing it. (Docs vary between 1.38M and 1.51M for the 32-worker figure — single-shot bench variance, the bench doc itself warns ±10% run-to-run.)

## The iGPU unlock (ROCm)

`scripts/setup_gpu_env.sh` installs torch 2.5.1+rocm6.2 (python 3.11); run scripts through `scripts/gpu-python.sh`, which sets `HSA_OVERRIDE_GFX_VERSION=11.0.0` — the wheel ships no gfx1151 kernels, so it loads gfx1100 (RDNA3) ones, which RDNA3.5 executes fine. Measured (`scripts/bench/bench_gpu_results.json`): **9.02 TFLOPS fp32 matmul vs 0.66 on CPU (13.67x)**, MLP train step 0.66 ms vs 7.49 ms. (Doc 11 cites 8.7 TFLOPS / 0.78 ms from an earlier run.) What it unlocks, ranked: Laya serve 1.35 s → ~20 ms (per-tick System 1; Laya-repo's call), local Laya fine-tunes, PPO nets on GPU while MuJoCo does physics, ACT locally if the lerobot pin tolerates torch 2.5.1.

## LeRobot env + converter

`training/.venv`: lerobot 0.7.0, torch 2.15.0+cpu (install CPU wheels FIRST or torchvision/torchcodec CUDA builds poison the venv). `training/to_lerobot_dataset.py` turns bus logs into LeRobotDataset v3.0 (state-only — the hub strips images; `use_videos=False`); `training/test_converter.py` PASS (state 7, action 4). ACT smoke: 11M-param tiny config, batch 2 → **0.3 s/step CPU**, loss 0.905 after step 1; real ACT is ~50–100x slower per step — keep runs to minutes, checkpoint often. Free path: Kaggle 2xT4 (GUT's own route). Full API contract: [docs/benchmarks/LEROBOT_API_NOTES.md](../docs/benchmarks/LEROBOT_API_NOTES.md).

## Use + feasibility

**FOR**: turning the loop's two other halves — RL gives the visible learning curve, distillation gives the "fails less over time" story. **On the one-day clock**: tier order A → C → B; start RL by ~10:30 and never stop it; distill whenever ≥250 Laya rows exist; imitation only with spare hands. **Feasibility**: physics is free but the learner is the bottleneck (ACT tiny 0.3 s/step CPU; real ACT ~50–100x slower per step — minutes-long runs only, checkpoint often, `free -g` gate: heavy training only above 14 GB available). The iGPU path works but is a separate 3.11 venv (torch 2.5.1+rocm6.2) — don't mix it with the lerobot venv.

## Watch it live

```bash
bash sim/dashboard/serve.sh                      # :8892 dashboard + :8891/?view=puppet
training/.venv/bin/python training/train_rl.py   # publishes metrics + puppet states
```

## See also

- [The Simulators](The-Simulators.md) — the MuJoCo models being trained
- [The Learning Loop](The-Learning-Loop.md) — the distillation tier's contract
- [docs/04_lerobot_mujoco.md](../docs/04_lerobot_mujoco.md) — verified LeRobot commands
