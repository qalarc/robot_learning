# Local MuJoCo benchmark — robot_learning box

**Date:** 2026-11-24 (Sydney; UTC stamp in JSON: 2026-11-23T16:47Z)
**Why:** we needed REAL measured numbers for the 5 Dec hackathon loop (*run → capture →
find failure → fix → run again*) before committing to PPO/eval budgets. Everything below
was measured on this machine by `scripts/bench/bench_mujoco.py`; raw JSON lives in
`scripts/bench/bench_results.json` (timestamped copies next to it).

## Hardware & software

| item | value |
|---|---|
| Host | `superlocal` |
| CPU | AMD Ryzen AI Max+ 395 (Strix Halo), 32 hw threads |
| GPU | Radeon 8060S iGPU — `radeonsi, gfx1151, LLVM 21.1.6, DRM 3.64` (Mesa 25.3.3) |
| RAM | 124 GB total; **29 GB available at bench time** (box was heavily loaded) |
| OS | CachyOS Linux, kernel 6.18.5-2-cachyos |
| Python | 3.12.13 (uv-managed, `sim/py/.venv`) |
| MuJoCo | **4.0.1** (`mujoco-core==4.0.1`, pip) |
| numpy / gymnasium | 2.5.5 / 1.4.0 |
| NVIDIA/CUDA | none — Isaac Sim is impossible here; MuJoCo is the physics engine |

## 1. GL backend probe (offscreen `mujoco.Renderer`, 640×480)

Probed in subprocesses (a broken backend cannot take down the bench).

| backend (MUJOCO_GL) | verdict | detail |
|---|---|---|
| `egl` | **WORKS** | Mesa EGL on the AMD iGPU; creates context, renders RGB uint8 |
| `glfw` | works | headless-capable on this box (no DISPLAY needed in probe) |
| `osmesa` | **FAILS** | system libOSMesa not installed → `'NoneType' object has no attribute 'glGetError'` |

**Verdict: use `MUJOCO_GL=egl`.** OSMesa could be added via a user-local package later,
but EGL already gives hardware-accelerated offscreen rendering, so there is no reason.

## 2. Physics steps/sec — no render, single thread

10 000 steps × 3 repeats per model, sinusoidal controls (actuators + contacts doing
real work), best-of-repeats; no solver warnings after any run.

| model | nq/nv/nu | steps/s (best) | steps/s (median) | ms/step |
|---|---|---:|---:|---:|
| `bench/humanoid_simple.xml` (hand-written, free root + 8 hinges, feet contacts) | 15/14/8 | **46 685** | 46 669 | 0.0214 |
| `bench/two_link.xml` (minimal 2-link) | 2/2/2 | 190 737 | 182 703 | 0.0052 |
| `so101_simple/so101_simple.xml` (hand-written 6-DOF + 2 fingers + cube) | 14/13/7 | **53 120** | 50 933 | 0.0188 |
| `so101_official/so101_new_calib.xml` (official TRSO meshes) | 6/6/6 | **89 619** | 88 127 | 0.0112 |

Interesting: the official mesh-heavy SO-101 steps *faster* than my capsule-only
hand-written one — it has 6 DOF vs my 13 velocity DOF (cube freejoint + fingers), and
its collision meshes are convex-hulled. Model cost is dominated by DOF/constraints,
not triangle count (at this scale).

## 3. Offscreen render FPS (EGL backend)

so101_simple scene, orbiting camera (forced redraw every frame), 10 warmup + 200 timed:

| resolution | FPS | ms/frame |
|---|---:|---:|
| 640×480 | **229** | 4.36 |
| 1280×720 | **168** | 5.95 |

Rendering is never the bottleneck for learning; it's plenty for wrist-cam video capture
into a LeRobot dataset (30 fps target needs 4–6 ms/frame — we have that per frame even
while physics runs).

## 4. Multithreaded rollout scaling — the number that matters

`mujoco.rollout` exists in 4.0.1 (`Rollout`, `rollout`, `persistent_rollout`,
`shutdown_persistent_pool`). N parallel rollouts on N threads, one `MjData` per thread,
official SO-101 model, 30 000 steps/env, phase-shifted sinusoidal controls, initial
state built via `mj_getState` from a reset `MjData` (NOT zeros — zeros teleports free
bodies to the origin; we hit exactly that gotcha while validating).

| workers | aggregate steps/s | per-env steps/s | speedup vs N=1 | wall for N×30k steps |
|---:|---:|---:|---:|---:|
| 1 | 126 859 | 126 859 | 1.00× | 0.24 s |
| 8 | 859 968 | 107 496 | **6.78×** | 0.28 s |
| 32 | **1 510 424** | 47 201 | **11.91×** | 0.64 s |

**Scaling curve comment:** near-linear to 8 threads (6.8× on 8), then flattening hard —
32 threads buy only ~12×, i.e. per-thread throughput drops to ~37% of single-thread.
Typical Strix Halo behaviour: 16 physical cores sharing one memory subsystem + boost
budget. Practical sweet spot: **8–16 parallel envs per rollout batch**; going to 32
still wins in absolute terms (1.51 M steps/s) if you only care about wall-clock.

## What this means for a 1-day hackathon

Budget for the learning loop (PPO / eval rollouts on the SO-101):

- **Pure physics is effectively free.** 1.5 M arm steps/s at 32 workers ≈ 43 min of
  sim-time per wall-second (0.002 s timestep). Even single-threaded, 50–90k steps/s
  means a 500-step episode costs 6–10 ms. **The bottleneck will be inference
  (policy forward passes), data plumbing and Python — never mj_step.**
- A 2 M-step PPO run (typical "small" run) = ~22 min of pure physics at 32 workers —
  feasible between pitch rehearsals, but only if the learner side (CPU torch) keeps up;
  expect the real wall-clock to be learner-bound, so start training early (10:30) and
  keep it running all day.
- **Eval rollouts:** 32 envs × 500 steps ≈ 0.6 s → we can afford continuous background
  eval (e.g. every 30 s) without stealing the machine.
- **Vision:** 168–229 fps offscreen EGL means camera-based capture (LeRobot datasets,
  MCAP export for Alloy) can run inline in the loop with zero impact.
- Keep `MUJOCO_GL=egl` set anywhere we render (exports, videos, debug viewers).

## SO-101 model status

| path | what | status |
|---|---|---|
| `sim/mujoco/so101_official/` | Official TheRobotStudio SO-101: `so101_new_calib.xml` + 13 STLs (16 MB) + `LICENSE`, downloaded 2026-11-24 from github.com/TheRobotStudio/SO-ARM100 (raw.githubusercontent; GitHub API was rate-limited). Provenance in `SOURCE.md`. | **LOADS & STEPS** — nq=6 nv=6 nu=6, 30 geoms, 0 warnings, 89.6k steps/s. Use this one for the hackathon task. |
| `sim/mujoco/so101_simple/` | Hand-written 6-DOF arm (yaw/shoulder/elbow/wrist-pitch/wrist-roll + 2 prismatic fingers), capsule geoms, floor + pushable cube. No meshes → fast, diffable, easy to extend. | LOADS & STEPS — 53.1k steps/s. Good for quick experiments and as a readable reference. |
| `sim/mujoco/bench/` | `humanoid_simple.xml`, `two_link.xml` — bench models written for this benchmark. | LOADS & STEPS. |

Notes: no local SO-101 MJCF/URDF existed anywhere on the machine before this
(`robot_arms/` doesn't exist; `robot_hand/` + `3d_prints/` only had STL hardware parts,
searched read-only). The official model is mounted with `meshdir="assets"` relative
paths — keep the folder layout as-is.

## Reproduce

```bash
sim/py/.venv/bin/python scripts/bench/bench_mujoco.py            # full
sim/py/.venv/bin/python scripts/bench/bench_mujoco.py --quick    # ~1 min
./scripts/setup_sim_env.sh                                       # verify/rebuild venv
```

## Unverified / caveats

- `osmesa` absence is inferred from the runtime error (system libOSMesa not linked);
  we did not try to install it — EGL makes it moot.
- Scaling numbers are single-shot (no repeats); N=8/N=32 wall times (0.28/0.64 s) are
  long enough to trust order-of-magnitude, but expect ±10% run-to-run on a loaded box.
- Box had 29 GB free (not the 12 GB minimum) → full workloads were used, no reductions.
- GPU render numbers are Mesa radeonsi (hardware acceleration on the 8060S iGPU) at
  default settings; no tuning tried.
