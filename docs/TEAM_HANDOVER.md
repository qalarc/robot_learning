# TEAM HANDOVER — everything in this repo, for the team

*Alloy × OpenAI Physical AI Hackathon · Sat 5 Dec 2026 · Sydney CBD · build 10:30–18:30.*
Status date: **24 Nov 2026**. This is the onboarding document — read it top to bottom
(15 minutes), then run §6 on your laptop.

> ⏰ **Applications close Sun 29 Nov, 23:59.** Every teammate applies individually
> ([event page](https://hackathonsaustralia.com.au/events/alloy-openai-physical-ai-hackathon)).
> Teams ≤ 6. Accepted builders get the starter kit + Discord on 1 Dec.

## 0b. The roster (2026-11-24)

Mia (lead), Alexei (sim/scenarios), Khartik (training/metrics), Mannus (vision/teleop),
John (systems/infra), Pugalproceed (data/integration/MCAP). Everyone applies **by Sun 29
Nov** — link in README. Day roles: deck slide 11 (https://qalarc.com/projects/robots/deck/).

## 0. The pitch (what we are building)

> "Our robot fails, explains itself, fixes itself, and needs the big brain less each
> time — here's the curve."

The judges asked for the five-part learning loop — **run → capture → find the failure →
fix → run again** ("a march of nines"). We built exactly that, end to end, and we can
show it live:

1. **Run** a SO-101 arm in simulation (Three.js in the browser for humans, MuJoCo for
   training).
2. **Capture** everything on a Robot Bus — every observation, command, stall and
   recovery is logged (`runs/bus/*.jsonl` is the dataset).
3. **Find the failure**: a free deterministic stall detector (30 Hz) → **Laya** (our
   tiny calibrated classifier, 1.35 s) says *stalled, probably unreachable* → only then
   is **alexei** (local GLM-4.7 abliterated, System 2) woken to diagnose (~5–15 s).
4. **Fix**: System 2 returns a bounded symbolic plan; a deterministic shield clamps it;
   the arm recovers.
5. **Run again** — and every recovery is labelled so Laya learns to catch that stall
   class *without* waking the big model. **The escalation rate falls over the day.**

In parallel a policy trains in MuJoCo (PPO) / from demos (ACT) so the base controller
itself fails less. Both loops feed one dashboard and one metrics file.

## 1. Verified working (ran it, not just wrote it)

| what | evidence | where |
|---|---|---|
| Robot Bus (hub + clients + protocol) | round-trip test PASS | `agents/test_bus.py`, `docs/PROTOCOL.md` |
| **Full stall-recovery loop, live models** | 16 eps → 5 stalls → 5 Laya verdicts → 5 alexei-class plans → labelled rows → metrics | `scripts/acceptance.sh`, `control/` |
| Three.js ARMSMITH sim (Unity port) | headless Chromium smoke PASS; IK ~1 cm (Unity had 7) | `sim/armsmith_web/`, `test/smoke.sh` |
| MuJoCo on this machine | SO-101 **89k steps/s**, EGL render **216 fps @480p**, **1.38M steps/s @32 envs** | `scripts/bench/bench_mujoco.py` |
| LeRobot 0.7.0 CPU env | dataset + one real ACT train step PASS; zero NVIDIA wheels | `training/.venv` |
| Bus log → LeRobotDataset converter | tests PASS (state 7, action 4) | `training/to_lerobot_dataset.py` |
| Vision: MediaPipe hands → EE target | 17 checks; **110 fps @480p CPU** | `vision/hand_tracking/` |
| Vision: HSV "blue tape" tracker · ArUco pose | 9 + 12 checks PASS | `vision/tape_tracker/` |
| Local AMD iGPU for torch (ROCm) | 8.7 TFLOPS fp32 with `HSA_OVERRIDE_GFX_VERSION=11.0.0` | `scripts/setup_gpu_env.sh`, `scripts/gpu-python.sh` |
| Research pack (sourced) | 11 docs + RGBmocap review, every claim linked | `docs/`, `reviews/` |

## 2. In progress / not done yet (be honest with judges, and with yourselves)

| item | state |
|---|---|
| **RL training visualised in the browser** (MuJoCo PPO → Three.js puppet + dashboard) | env + viewer + dashboard built; `training/train_rl.py` landing — see §8 |
| Streaming System 2 (act on first step) | in flight — cuts time-to-first-action |
| **Laya `robot-ops` checkpoint** | **not trained** — only 4 real labelled rows exist (need ~250 for an honest r1, ~1.5k to pass the calibration gate) |
| Full ACT/SmolVLA training on real demos | not run (only a 1-step smoke); use free Kaggle 2×T4 |
| Hand teleop against the live web sim with a real camera | tools tested on fixtures; live end-to-end run pending |
| MCAP export (Alloy's native format; `alloyrobotics/lerobot2mcap`) | not built — great Codex task on the day |
| GitHub repo under `qalarc` | local commit done; remote blocked on `gh auth login` (token expired) |
| Dynamic (Rapier motor) physics grasp | experimental toggle `?physics=dynamic`; kinematic is default |

## 3. Everything in the repo, by directory

| path | what it is |
|---|---|
| `AGENTS.md` | **the brief Codex auto-loads.** Rules of engagement, commands, what to build first |
| `README.md` | front door: pitch, quickstart, repo map |
| `docs/PROTOCOL.md` | the Robot Bus wire protocol (envelope, topics, delivery rules, frames) |
| `docs/00_hackathon_strategy.md` | verified event intel, day plan hour-by-hour, pitch, risks, pack list |
| `docs/01_agent_team.md` | roster of agents + escalation ladder + Codex task templates |
| `docs/02_agent_network.md` | how the bus and the wider qalarc ecosystem interconnect |
| `docs/02b_codex_tooling.md` | CLI ↔ hub ↔ sim ↔ Codex, troubleshooting |
| `docs/03_our_assets_map.md` | every prior project this builds on (ARMSMITH, robot_hand, gesture-control, clipforge, anymove, Laya/GUT, three.js fleet) |
| `docs/04_lerobot_mujoco.md` | LeRobot 0.7 + MuJoCo 4 field guide with working code |
| `docs/05_simulators_isaac.md` | simulator matrix; Isaac Sim on AMD: no (and what to do instead) |
| `docs/06_vla_landscape.md` | the event intel, VLAs, learning-loop methods |
| `docs/07_vision_mocap_landscape.md`, `07b_vision_tools.md` | mocap/CV options; our tools + measured latencies |
| `docs/08_stall_learning_loop.md` | the S1/S2 architecture in detail |
| `docs/09_gut_review.md` | GUT reflection → why the `robot-ops` domain is designed this way |
| `docs/10_reading_list.md` | what to read before the day (5 must-reads flagged) |
| `docs/11_training_playbook.md` | what to train, where (CPU / iGPU / free T4), why; visualisation |
| `docs/benchmarks/` | MuJoCo bench, env setup, LeRobot API notes (introspected from the real install) |
| `reviews/2026-11-24_RGBmocap_toyxyz.md` | full RGBmocap review (robotics + gamedev) |
| `agents/hub.py` | the bus relay + logger + HTTP (`/health /roster /stats`) |
| `agents/bus_client.py` | shared client (`BusClient` asyncio, `SyncBus` thread facade) |
| `agents/cli.py` | 13 subcommands to drive/observe the robot from a shell (Codex's hands) |
| `agents/fake_sim.py` | headless stub sim with injectable faults (`ik_residual`, `slip`) |
| `agents/replay.py` | replay a recorded episode onto the live bus; export CSV |
| `agents/registry.json` | static directory of every agent: name, role, topics, endpoint |
| `agents/tools_for_codex.md` | cheat-sheet written for Codex |
| `agents/test_bus.py`, `test_cli.sh` | test suites (PASS) |
| `control/robot_ops.schema.json` | **frozen** System-1 contract + skill vocabulary + workspace box |
| `control/laya_client.py` | System 1 client; state template; dataset-row builder |
| `control/glm_s2.py` | System 2 client (Ollama, alexei-v3) + **safety shield** `validate_plan` |
| `control/stall_controller.py` | the conductor: L0 detect → L1 Laya → L2 gate → L3 GLM+shield → L4 teleop; labels; metrics |
| `sim/armsmith_web/` | Three.js + Rapier SO-101 sim (procedural arm, FABRIK, servo model, scenarios, recorder, **puppet view**) — zero-build, vendored, offline |
| `sim/dashboard/` | mission-control page: nines, reward/success curves, roster, stall-loop counters; `serve.sh` |
| `sim/py/` | light venv; `mujoco_env.py` (Gymnasium SO-101 envs that publish on the bus) |
| `sim/mujoco/` | official SO-101 model (+LICENSE) and a simplified 6-DOF model |
| `training/` | LeRobot venv; `to_lerobot_dataset.py`; `train_rl.py` (PPO) |
| `vision/` | hand tracker + retarget maths, HSV tape tracker, ArUco pose, preview page |
| `scripts/` | env setup ×3, benchmarks (MuJoCo, GPU), `acceptance.sh` |
| `data/robot-ops.jsonl` | the System-2-teaches-System-1 training set (4 rows so far) |
| `runs/` | bus logs (the dataset), `metrics.json`, RL checkpoints, pid files |

Size: ~7.4k lines Python, ~3.3k lines JS/HTML/CSS, ~3.1k lines of docs.

## 4. Agent team — every brain, its skill, how to invoke it

| agent | skill | invoke | notes |
|---|---|---|---|
| **Codex** (OpenAI, unlimited on the day) | builds/fixes anything: scenarios, eval harness, converters, MCAP export | lives in the repo; reads `AGENTS.md` automatically; drives the robot with `agents/cli.py` | give it the task templates in `docs/01_agent_team.md` |
| **Orchestrator** (GLM 5.3 via qalcode) + **Flash workers** | plans, delegates parallel legs, reviews | Task tool | this repo was built that way in one day |
| **Laya — System 1** | calibrated typed identification: progress / failure mode / recoverable / escalate | `control/laya_client.py` → `POST :8798/v1/systemone`, domain `robot-ops` | 1.35 s warm on CPU; ~20 ms if moved to the iGPU |
| **alexei — System 2** (`glm-4.7-flash-abl:alexei-v3`) | stall diagnosis + bounded recovery plan | `control/glm_s2.py` → Ollama `:11434` | abliterated base: **the shield is non-negotiable** |
| **Stall controller** | the conductor + labeller + metrics | `control/stall_controller.py` | survives Laya/GLM being down |
| **Hand tracker** | camera → 21 landmarks → EE target + pinch | `vision/hand_tracking/hand_tracker.py --source 0` | publishes `vision.hands` |
| **Tape / marker trackers** | colour-target steering; metric 6-DoF marker pose | `vision/tape_tracker/tape_tracker.py`, `marker_pose.py` | the "blue tape robot" lineage |
| **MuJoCo env + PPO trainer** | RL in sim at 1.4M steps/s, publishes live telemetry | `training/train_rl.py` | the "nines" engine |
| **Dashboard** | shows everything live | `bash sim/dashboard/serve.sh` | `:8892` |
| **GUT trainer** | trains + gates Laya's `robot-ops` domain | MCP `gut_train_start` / `gut_register` | gate: agreement ≥0.85, ECE ≤0.10 |
| **Jev** (optional) | cheap remote calibrated gate | MCP `jev_decide` | off by default |
| **Blender MCP** (optional) | generate sim props, URDF→GLB | `blender_*` tools | nice-to-have |

## 5. The escalation ladder (who thinks when)

```
L0  stall detector     deterministic, 30 Hz, free
L1  Laya S1            typed verdict, ~1.35 s
L2  gate               escalate iff p ≥ 0.5 (fail-open if Laya is down)
L3  alexei S2          diagnosis + plan, ~5–15 s  →  SAFETY SHIELD (clamps in code)
L4  human / teleop     after 3 failed recoveries per episode
```

## 6. New teammate setup (≈10 minutes)

Needs: Linux/macOS/Windows with Python 3.12 (uv installs it), `git`, a browser. Optional:
webcam (teleop), Ollama (System 2), the Laya repo (System 1). No Node, no build step.

```bash
git clone <repo-url> && cd robot_learning
scripts/setup_sim_env.sh            # light venv: mujoco, opencv, mediapipe, websockets
scripts/setup_training_env.sh       # heavy venv: CPU torch + lerobot + stable-baselines3 (optional)
sim/py/.venv/bin/python agents/test_bus.py          # PASS
bash scripts/acceptance.sh                          # the whole loop, headless (~4 min)
bash sim/dashboard/serve.sh                         # then open http://127.0.0.1:8892/
```
On this machine only (AMD iGPU): `scripts/setup_gpu_env.sh` then run torch through
`scripts/gpu-python.sh`.

## 7. Demo recipes

**A. The learning loop, headless** (works with no browser):
`bash scripts/acceptance.sh`
**B. Watch the robot train in a sim:** `bash sim/dashboard/serve.sh`, then in another
terminal `training/.venv/bin/python training/train_rl.py` → open **http://127.0.0.1:8892/**
(nines + curves) and **http://127.0.0.1:8891/?view=puppet** (the arm mirroring MuJoCo).
**C. Drive the arm yourself:** open http://127.0.0.1:8891/ (mouse IK, sliders, keys) or
`sim/py/.venv/bin/python agents/cli.py demo`.
**D. Hand teleop:** `python vision/hand_tracking/hand_tracker.py --source 0` then
`python agents/cli.py mode mocap` — pinch closes the gripper.
**E. Ask the brain:** `python agents/cli.py stall` (last dossier), `snapshot --cam wrist`.
**F. Train a policy from recordings:**
`training/.venv/bin/python training/to_lerobot_dataset.py --bus-log runs/bus/<f>.jsonl --out datasets/day1`
then `lerobot-train` (tiny ACT on CPU, or zip + free Kaggle T4).

## 8. Training status right now (24 Nov)

| training | status | numbers |
|---|---|---|
| RL (PPO, MuJoCo reach) | **running/landing** — watch it live via recipe B | baseline vs trained + nines: `docs/benchmarks/RL_TRAINING_BENCH.md` |
| Laya `robot-ops` (S2→S1 distillation) | **data collection started, not trained** | 4 real labelled rows; need ~250 (r1) → 1.5k (gate) |
| ACT / imitation | smoke-tested only | 1 optimiser step PASS (0.3 s/step CPU) |
| System 2 (alexei) | in use, no training needed | ~46 tok/s uncontended; 255-token plan ≈ 5.5 s |

**How Laya gets trained (the flywheel):** stalls accumulate in `data/robot-ops.jsonl`
automatically while the loop runs → copy to the Laya repo as `datasets/robot-ops.jsonl`
→ `python mcp_finetune/train.py --dataset datasets/robot-ops.jsonl --epochs 4` (CPU
~1 h/1k rows, local iGPU, or push the Kaggle kernel for free T4s) → gate table →
`gut_register` on PASS → serve.py hot-reloads → System 1 catches stalls without System 2.

## 9. Integrations and ports

| port | what |
|---|---|
| **8890** | Robot Bus hub (`/health /roster /stats`) |
| **8891** | Three.js sim (+ `?view=puppet`) |
| **8892** | dashboard |
| 8798 / 8797 | Laya serve / GUT trainer console (existing, qalarc) |
| 11434 | Ollama (alexei-v3) |
| 8893–8898 | test ports — leave alone |

External systems we integrate with: **Laya/GUT** (System 1 + training flywheel),
**Ollama** (System 2), **LeRobot** (datasets + policies), **MuJoCo** (physics),
**MediaPipe/OpenCV** (vision), **Codex** (builder agent), **Alloy's format** (MCAP export
pending).

## 10. The 11-day plan — suggested owners

| when | what | owner |
|---|---|---|
| **by 29 Nov** | EVERYONE applies | all |
| 30 Nov–2 Dec | every teammate runs §6; record a fallback demo video; hand teleop live test | dev A |
| 1–3 Dec | collect ≥250 labelled stalls (run the loop headless overnight); Laya r1 train + gate | ML |
| 2–4 Dec | PPO nines table polished; ACT on Kaggle T4 from teleop demos; MCAP export | ML + dev B |
| 4 Dec | full timed dress rehearsal; pack list; USB stick with repo + vendored deps + video | lead |
| 5 Dec 9:00 | morning checklist in `docs/01_agent_team.md` | all |

## 11. Rules of engagement (the hard ones)

1. Never send joint/EE commands outside the workspace box (`control/robot_ops.schema.json`).
2. Never bypass the safety shield. The System-2 model is abliterated — assume zero self-restraint.
3. Don't change the frozen criteria in `robot_ops.schema.json` — it invalidates every dataset row.
4. Reset between episodes with a `seed`; announce takeovers on `ctl.recovery`.
5. Don't write into the Laya repo from agents; keep `runs/bus/*.jsonl` intact — it is the dataset.
6. Small, boring, working code. One process per concern. Everything survives the hub being down.
