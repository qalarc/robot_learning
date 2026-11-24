# Testing and Benchmarks

**Everything in this repo is measured or tested — this page says what each script proves, its current status, and collects the headline numbers.** Status date 24 Nov 2026; sources: [docs/TEAM_HANDOVER.md §1](../docs/TEAM_HANDOVER.md), [docs/benchmarks/](../docs/benchmarks/), [docs/07b_vision_tools.md](../docs/07b_vision_tools.md).

## Tests

| script | what it proves | status |
|---|---|---|
| `agents/test_bus.py` (scratch port 8894) | every delivery rule: hello/roster + rename, broadcast, directed, high-rate opt-in, request/reply | **PASS** |
| `agents/test_cli.sh` (scratch port 8896) | every CLI subcommand + fake_sim + replay dry-run/CSV + demo + bad-target regression + fault-injection smoke, isolated hub | **PASS** |
| `sim/armsmith_web/test/smoke.sh` | headless Chromium + SwiftShader drives the real sim; DOM checks + live Python probe (last run: `SMOKE PASS — step=1203 obs_sent=599`) | **PASS** |
| `sim/armsmith_web/test/smoke_puppet.sh` | puppet view: isolated hub + fake MuJoCo publisher + headless Chromium | **PASS** |
| `sim/dashboard/test/smoke_dashboard.sh` | nines element holds a number, baseline beside it, run header, bus banner online, roster entry | **PASS** |
| `sim/dashboard/test/fake_publisher.py` | fake trainer + 30 Hz arm for demo-without-training | working |
| `vision/hand_tracking/test_retarget.py` | 17 synthetic-landmark checks (no camera, no bus) | **PASS** |
| `vision/tape_tracker/test_tape.py` / `test_marker.py` | 9 + 12 checks on synthetic frames | **PASS** |
| `training/test_converter.py` | bus-log → LeRobotDataset converter end-to-end (state 7, action 4) | **PASS** |
| `scripts/acceptance.sh` (port 8895) | the full loop headless (~4 min): 16 eps → 5 stalls → 5 Laya verdicts → 5 alexei-class plans → labelled rows → metrics | **ACCEPTANCE PASS** (with streaming: `ttfa=2.05–3.49s total=14.5–22.7s`) |
| `scripts/bench/bench_mujoco.py` | physics/render/rollout benchmarks (raw JSON in `scripts/bench/`) | run 24 Nov |
| `scripts/bench/bench_gpu.py` | ROCm iGPU vs CPU torch | run 24 Nov |

Also: `control/glm_s2.py --probe` and `control/laya_client.py --probe` give one-shot live checks of each brain. Honest gaps: full ACT/SmolVLA training not run (1-step smoke only); hand teleop against the live web sim pending (fixtures only); MCAP export not built; `docs/benchmarks/RL_TRAINING_BENCH.md` is referenced by docs 08/11 as the PPO nines source but was not present in the repo at wiki time.

## Headline measured numbers

| measurement | number | source |
|---|---|---|
| MuJoCo physics, official SO-101, 1 thread | 89,619 steps/s (11.2 µs/step) | LOCAL_MUJOCO_BENCH |
| 32-worker rollout | 1,510,424 steps/s (11.91x) | LOCAL_MUJOCO_BENCH |
| Offscreen EGL render | 229 fps @640x480, 168 fps @720p | LOCAL_MUJOCO_BENCH |
| ROCm iGPU torch (8060S) | 9.02 TFLOPS fp32 matmul (13.67x CPU); MLP step 0.66 ms | bench_gpu_results.json |
| Laya S1 | 1.35 s warm / 27 s cold, schema-correct | TEAM_HANDOVER, doc 08 |
| alexei S2 | 15–30 s contended; ~46 tok/s uncontended (255-tok plan ≈ 5.5 s); ttfa 2.05 s streaming | doc 08 |
| Vision sensor→bus (hands, VGA) | ~45 ms p50 / ~55 ms p95; 110 fps inference @480p | doc 07b |
| ACT CPU smoke | 0.3 s/step (11M tiny config), loss 0.905 after step 1 | ENV_SETUP |
| armsmith_web IK residual | ~1 cm work envelope (Unity was ~7 cm) | sim README / doc 03b |
| Bus one-way relay | 0.61 ms p50 (same host) | doc 07b |

## Use + feasibility

**FOR**: deciding what to trust on the day — run the two agent tests + acceptance at 9:00 and everything above the line is verified on your hardware. **Feasibility**: all tests are self-contained (scratch ports 8894–8896, own cleanup, trap-guarded); the full suite costs minutes, not hours. Benchmarks are single-shot on a shared box — treat numbers as order-of-magnitude with ±10% run-to-run.

## See also

- [Training](Training.md) — what the throughput numbers buy
- [docs/benchmarks/ENV_SETUP.md](../docs/benchmarks/ENV_SETUP.md) — the two-venv discipline
