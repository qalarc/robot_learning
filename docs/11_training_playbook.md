# 11 — Training playbook: what the numbers mean, the best approach, the visualisation

*Measured on superlocal 2026-11-24: Ryzen AI Max+ 395 (32 threads) · Radeon 8060S iGPU
(gfx1151) · 124 GB unified RAM (63.7 GB GTT) · no NVIDIA.*

## 1. MuJoCo throughput, decoded

| measured | number | what it means in practice |
|---|---|---|
| SO-101 physics, 1 thread | **89k steps/s** (11 µs/step) | one 150-step reach episode = **1.7 ms** of physics |
| 32 parallel envs (`mujoco.rollout`) | **1.38M steps/s** | a **10-million-step RL run's physics ≈ 7 s** |
| offscreen render (EGL, iGPU) | **216 fps @ 640×480**, 185 fps @ 720p | pixel observations for 16 envs at 30 fps cost ¼ of capacity |

The point isn't speed for its own sake — it is **statistical confidence**. The event is
judged on "fail less", and you cannot claim a nine without measuring it: to resolve a
0.1% failure rate you need thousands of episodes. At 1.7 ms/episode, a **10,000-episode
evaluation costs 17 seconds**. That is the discipline behind `scripts/eval_nines.py`.

In practice RL wall-clock is dominated by the policy network + GAE + Python, not physics
(see the measured PPO numbers in `docs/benchmarks/RL_TRAINING_BENCH.md`).

## 2. The local GPU is real (the thing I got wrong first time)

ROCm torch **works on this iGPU** with one environment variable:

```bash
scripts/setup_gpu_env.sh                       # torch 2.5.1+rocm6.2, python 3.11
scripts/gpu-python.sh your_training.py         # sets HSA_OVERRIDE_GFX_VERSION=11.0.0
```

Why the override: the rocm6.2 wheel ships no gfx1151 kernels ("HIP error: invalid device
function") — `HSA_OVERRIDE_GFX_VERSION=11.0.0` loads the gfx1100 (RDNA3) kernels, which
RDNA3.5 executes fine. **Measured (`scripts/bench/bench_gpu.py`, torch 2.5.1+rocm6.2,
16 CPU threads as the fair baseline):**

| workload | CPU | iGPU | speedup |
|---|---|---|---|
| matmul 4096² fp32 | 0.66 TFLOPS | **9.02 TFLOPS** | 13.7× |
| MLP train step (4096×128→256) | 7.49 ms | **0.66 ms** | 11.4× |
| CNN train step (64×3×128² → conv) | 45.3 ms | **15.3 ms** | 3.0× |
| transformer step (256×100×256, ACT-sized) | 426 ms | **41.8 ms** | 10.2× |

hipBLASLt reports "unsupported architecture" and auto-falls back to hipblas — harmless.
Memory comes from GTT (25–60 GB free depending on what Ollama has resident).

What this unlocks (ranked):
1. **Laya serve 1.35 s → likely ~20 ms** (GUT's own requirement doc: "any 4 GB GPU,
   17–23 ms/decision"). That would let System 1 run *every tick* instead of on stall.
   Needs the Laya runner venv switched to a ROCm torch — their repo, their call.
2. Laya fine-tunes locally instead of ~1 h/1k rows on CPU.
3. PPO/CBC nets on GPU while MuJoCo does physics on CPU.
4. **ACT training locally** — the transformer step at 42 ms makes small-dataset ACT
   runs practical on this box (with matching ROCm torchvision pins).

## 3. Training tiers — what to use when

| tier | what | where it runs | why / when |
|---|---|---|---|
| **A. RL in sim** | PPO on MuJoCo reach/push/pick envs (`training/train_rl.py`) | local CPU (1.4M steps/s) + optional iGPU net | no demos needed; a visible learning curve in 10–30 min; the "nines" engine |
| **B. Imitation** | ACT / Diffusion Policy / SmolVLA on LeRobot datasets | **free Kaggle 2×T4 / Colab** (GUT's own path) or local CPU for tiny sets | learns from human teleop demos; closest to real-hardware behaviour |
| **C. Distillation** | Laya `robot-ops` fine-tune (GUT) | local CPU (~1 h/1k rows) · **local iGPU** · Kaggle 2×T4 | System 2 teaches System 1 → escalation rate falls |
| **D. Models** | GLM-4.7-abl alexei (System 2) | local Ollama on the iGPU | ~46 tok/s uncontended (255-token plan ≈ 5.5 s decode) |

**Recommended order for the day:** scripted baseline → tier A (RL) for the visible curve
→ tier C (stall loop + Laya) for the "learns from failure" story → tier B only if a
teammate has spare cycles and the demos exist. Three loops, one bus log, one dashboard.

## 4. Isaac Sim — the honest line

Isaac Sim needs an **NVIDIA RTX** GPU: its renderer and physics stack are CUDA/RTX
binaries. Our iGPU has no CUDA, and ROCm only helps torch-style code we run ourselves —
it cannot make NVIDIA-only binaries run. Free cloud T4s are not RTX either. So Isaac is
a paid-RTX-cloud or venue-hardware option, and it is **unnecessary** for this event:
LeRobot's own RL environments are MuJoCo, and Isaac Lab 3 has a MuJoCo-Warp backend.
Decision: MuJoCo (docs/05 has the cloud recipe if an RTX box appears).

## 5. Visualisation — "train headless, watch in Three.js" (built)

```
MuJoCo (16 envs, 1.4M steps/s)  ──sim.obs 30Hz──▶  Three.js ?view=puppet   (:8891)
        │                                                       ▲
        └──train.metrics 5Hz──▶  Dashboard (:8892): nines, curves, roster, stall-loop counters
```

No Rust needed for the hackathon: MuJoCo is already C, Python is glue, Three.js renders.
(MuJoCo-WASM in-browser physics and a Rust trainer are post-event projects.)

```bash
bash sim/dashboard/serve.sh                    # hub + sim + dashboard, prints URLs
training/.venv/bin/python training/train_rl.py # trains PPO on the reach env, publishes
```

## 6. Improvement levers, ranked by payoff-per-hour on the day

1. **More eval episodes** (seconds) → honest nines instead of vibes.
2. **Streaming S2** (ttfa): act on the first recovery step as it generates.
3. **Domain randomisation** (targets, friction, sensor noise) → robustness, better sim2real story.
4. **Curriculum**: reach → push → pick-place → stack.
5. **Corrective demos at failure points** (RECAP-style) → biggest BC gains per demo.
6. **Laya on the iGPU** → per-tick System 1.
7. Action chunking / SmolVLA if going further with BC.
