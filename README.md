# robot_learning — Alloy × OpenAI Physical AI Hackathon

**Sat 5 Dec 2026, Sydney CBD · 20 teams · >A$100k prizes · one day · learning loops.**

> ⏰ **Applications close Sun 29 Nov 23:59 AEDT** — every teammate applies individually:
> [event page → register](https://hackathonsaustralia.com.au/events/alloy-openai-physical-ai-hackathon)

> 👥 **New to the team? Read [`docs/TEAM_HANDOVER.md`](docs/TEAM_HANDOVER.md) first** —
> every element, every agent skill, setup, demo recipes, training status, 11-day plan.

We build **robots that learn from their own runs and fail less**. Our entry is a live
failure-recovery learning loop:

```
 run ──▶ capture ──▶ find the failure ─────────▶ fix ──────────────▶ run again
 sim/real  bus blackboard   Laya S1 (~1.4 s)     alexei S2 (acts in ~2 s   measured
           runs/bus/*.jsonl  typed + calibrated   via streaming; plan in    failure-rate
                             identification       ~5 s) via safety shield  delta = the
                                                                                  demo ("nines")
                            ▲                                         │
                            └──── every recovery is labelled: S2 teaches S1 ──┘
```

Escalation rate falls over the day as Laya learns to catch stalls without GLM —
the loop, turning, visibly. In parallel, recorded episodes train an ACT policy
(LeRobot) so the base controller itself fails less.

## Quickstart

```bash
scripts/setup_sim_env.sh                       # light venv (mujoco/opencv/mediapipe/websockets)
sim/py/.venv/bin/python agents/hub.py &        # the bus          ws://127.0.0.1:8890/ws
sim/py/.venv/bin/python agents/fake_sim.py --fault ik_residual &   # deterministic stall
sim/py/.venv/bin/python control/stall_controller.py               # THE LOOP (dry-run safe)
```
Headless demo of the full learning loop in three terminals, no browser. Then:

```bash
bash sim/dashboard/serve.sh                    # hub + sim :8891 + dashboard :8892 (localhost)
training/.venv/bin/python training/train_rl.py # PPO trains in MuJoCo — watch live in the browser
sim/py/.venv/bin/python agents/cli.py demo     # drive the sim from a shell
sim/py/.venv/bin/python vision/hand_tracking/hand_tracker.py   # hand → EE teleop
scripts/gpu-python.sh your_torch_script.py     # local AMD-iGPU torch (docs/11 §2)
```

**Training playbook — what to train, where, why: `docs/11_training_playbook.md`.**

## Repo map

| path | what |
|---|---|
| **`GUIDE.md`** | **the full guide — one paragraph on every element in the system** |
| **`docs/TEAM_HANDOVER.md`** | 15-minute team onboarding: setup, demo recipes, training status, 11-day plan |
| **`wiki/`** | the wiki — every point expanded, one page per topic |
| **`AGENTS.md`** | brief for Codex/coding agents (they read it automatically) |
| **`docs/PROTOCOL.md`** | the Robot Bus — how every agent/sim/sensor talks |
| `docs/00_hackathon_strategy.md` | strategy, day plan, pitch, risks |
| `docs/01_agent_team.md` | the agent roster + how they hand off work |
| `docs/03_our_assets_map.md` + `03b_unity_armsmith.md` | every project this builds on + the **Unity ARMSMITH reference & relevance assessment** ([fivelidz/armsmith-robot-arms](https://github.com/fivelidz/armsmith-robot-arms)) |
| `docs/04_lerobot_mujoco.md` | LeRobot 0.7 + MuJoCo 4 field guide (verified) |
| `docs/05_simulators_isaac.md` | simulator matrix; Isaac Sim on AMD: no (and what to do instead) |
| `docs/06_vla_landscape.md` | VLAs, learning-loop methods, the event intel |
| `docs/07_vision_mocap_landscape.md` + `07b_vision_tools.md` | mocap/CV options + our tools |
| `docs/08_stall_learning_loop.md` | the S1/S2 architecture in detail (measured latencies, streaming ttfa) |
| `docs/09_gut_review.md` | review/reflection of our GUT project → this design |
| `docs/10_reading_list.md` | what to read before the day |
| `docs/11_training_playbook.md` | what to train, where (CPU / iGPU / free T4), why |
| `agents/` | hub, bus client, CLI, fake sim, replay, tests, registry |
| `control/` | stall controller, Laya S1 client, GLM S2 reasoner + shield, frozen schema |
| `sim/armsmith_web/` | Three.js port of our Unity ARMSMITH SO-101 sim (+ `?view=puppet`) |
| `sim/dashboard/` | mission control: nines, curves, roster, stall-loop counters (:8892) |
| `sim/py/`, `sim/mujoco/` | light venv, MuJoCo envs + models + benchmarks |
| `training/` | LeRobot venv, RL trainer, bus→LeRobotDataset converter |
| `vision/` | MediaPipe hand teleop, HSV tracker, ArUco pose |
| `reviews/` | deep reviews (RGBmocap etc.) |
| `data/` | `robot-ops.jsonl` — the System-2-teaches-System-1 training set |
| `runs/` | bus logs (the dataset), `metrics.json`, port files |
| `scripts/` | env setup, benchmarks |

## Verified on this machine (24 Nov 2026)

| thing | result |
|---|---|
| Bus protocol round-trip | PASS (`agents/test_bus.py`) |
| Laya S1 (`robot-ops` domain) | warm **1.35 s**/decision, schema-correct |
| GLM 4.7 S2 (local, resident) | **15–30 s**/plan, ~14 tok/s, shield-clean JSON plans |
| MuJoCo 4.0.1 | works, CPU; benches in `docs/benchmarks/` |
| Isaac Sim | **impossible** — no NVIDIA GPU; see doc 05 |

## The event (verified from the event page)

One day: doors 9:00, brief 10:00 (challenge under wraps until then), build 10:30–18:30,
judging 19:15. Bring-your-own hardware welcome (power-point class); simulation entries
juded the same. Unlimited Codex for every builder; judges/mentors from OpenAI,
Cloudflare, Alloy Robotics. Apply by **29 Nov**; teams ≤6; everyone applies individually.

Host thesis (why our design fits): Alloy builds AI agents that debug robot fleets over
captured data (MCAP/ROS/Parquet, MCP servers for Codex/Claude). Our repo *is* that
story in one day: capture everything on a bus, agents reason over failures, the fix
feeds back into training.
