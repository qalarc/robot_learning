# AGENTS.md — read this first

You (Codex, or any coding agent) are working in **robot_learning**: the repo for the
**Alloy × OpenAI Physical AI Hackathon, Sat 5 Dec 2026, Sydney CBD** (build 10:30–18:30,
judged 19:15). 20 teams, up to 6 people each. Prize pool >A$100k. The brief is kept
under wraps until 10:00 on the day, but the organisers' framing is public: teams "build
robots that learn from their own runs and fail less", in **simulation, on real hardware,
or both** — the five-part **learning loop**: *run → capture → find the failure → fix →
run again* ("a march of nines"). Simulation entries are judged the same as hardware.

Our thesis, already built in this repo: **a live failure-recovery learning loop** —
the sim runs; a deterministic detector catches stalls; a tiny calibrated classifier
(Laya, System 1) identifies them; a local reasoning model (GLM 4.7, System 2) plans a
bounded recovery; every recovery is labelled and fed back so System 1 learns to catch
stalls without System 2. Escalation rate falls over the day = the demo.

## Repo map

| path | what |
|---|---|
| `docs/PROTOCOL.md` | **The Robot Bus protocol** — how everything talks. Read before touching the bus. |
| `docs/00_hackathon_strategy.md` | the plan, the schedule, the pitch |
| `docs/01_agent_team.md` + `agents/registry.json` | who's on the team (agents included) |
| `agents/` | `hub.py` (bus relay), `bus_client.py`, `cli.py`, `fake_sim.py`, `test_bus.py` |
| `control/` | the learning loop: `stall_controller.py`, `laya_client.py` (S1), `glm_s2.py` (S2), `robot_ops.schema.json` (the frozen contract) |
| `sim/armsmith_web/` | Three.js + Rapier port of our Unity SO-101 arm sim (`sim/armsmith_web/README.md`) |
| `sim/py/`, `sim/mujoco/` | MuJoCo side (benchmarks, models) |
| `training/` | LeRobot venv + bus-log→LeRobotDataset converter |
| `vision/` | MediaPipe hand tracker → EE teleop, HSV colour tracker, ArUco marker pose |
| `reviews/`, `docs/0*.md` | research: RGBmocap, LeRobot/MuJoCo, simulators, VLA landscape, reading list |
| `runs/` | bus logs (`runs/bus/*.jsonl` = the dataset), `metrics.json`, `bus.port` |

## The two environments (don't mix them)

* `sim/py/.venv/bin/python` — light: mujoco, opencv, mediapipe, websockets. Bus + vision + sim tooling.
* `training/.venv/bin/python` — heavy: CPU-only torch + lerobot. Datasets + training.
* Never install with system pip/pacman. Use `scripts/setup_sim_env.sh` / `scripts/setup_training_env.sh`.

## Drive the robot (from any shell — this is YOUR interface)

```bash
sim/py/.venv/bin/python agents/cli.py roster                 # who is online
sim/py/.venv/bin/python agents/cli.py obs --n 3              # live telemetry
sim/py/.venv/bin/python agents/cli.py scenario pick_place    # pick a task
sim/py/.venv/bin/python agents/cli.py ee --x 0.20 --y 0.0 --z 0.06 --grip 0
sim/py/.venv/bin/python agents/cli.py snapshot --cam wrist --out f.jpg   # see what it sees
sim/py/.venv/bin/python agents/cli.py reset --seed 7
```
No browser needed for testing: `python agents/fake_sim.py --fault ik_residual`
reproduces a classic stall deterministically.

## Rules of engagement (hard)

1. **Never send joint/EE commands outside the workspace box** in `control/robot_ops.schema.json` (`x 0.05–0.30, y ±0.18, z 0.02–0.25 m`) — use `ee`, not raw joint values, unless debugging kinematics.
2. **Never bypass the safety shield** (`control/glm_s2.py::validate_plan`). The System-2 model is abliterated; assume zero self-restraint. All bounds are enforced in code, outside the model.
3. **Don't change `control/robot_ops.schema.json` criteria** — the domain is frozen (GUT protocol: changing a label invalidates every dataset row). New behaviour → new skills in `SKILL_SIGNATURES` + shield clamps first.
4. Reset between episodes, pass a `seed`, and announce takeovers with `ctl.recovery`.
5. Don't write into `/home/fivelidz/projects/GLM_projects/Laya_integrations` (read-only reference; the training flywheel lives there).
6. Hub log `runs/bus/*.jsonl` is the dataset — never truncate it mid-run.
7. Ask `python agents/cli.py stall` before designing a fix; the dossier tells you why it failed.

## Ports

bus `ws://127.0.0.1:8890/ws` (fallback: read `runs/bus.port`) · sim page `http://127.0.0.1:8891/` · Laya `:8798` · trainer console `:8797` · Ollama `:11434`.

## Status (2026-11-24)

Verified working: bus protocol + hub (`agents/test_bus.py` PASS), Laya S1 (1.35 s warm),
GLM S2 (15–30 s, shielded), controller skeleton, Unity sources mapped. In flight:
three.js sim port, CLI/fake-sim, vision tools, MuJoCo bench, LeRobot env. Isaac Sim:
impossible on this machine (no NVIDIA) — MuJoCo is the physics engine; see
`docs/05_simulators_isaac.md`.

## What to build first on the day (until the brief lands at 10:00)

1. Read the brief; map it onto the five-part loop; pick the scenario.
2. Wire the brief's task into `sim/armsmith_web` scenarios (or the venue sim if they ship one).
3. Turn the loop: collect → train ACT/SmolVLA (`training/`) → eval → measure failure-rate delta.
4. Export episodes: `training/to_lerobot_dataset.py`, and MCAP for the Alloy platform
   (their org: `alloyrobotics/lerobot2mcap` — judges are Alloy engineers).
5. Keep `runs/metrics.json` current; the final table is "nines before/after".

## Style

Small, boring, working code. One process per concern. Every component must survive the
hub being down. Comment in the file why, not what. Don't delete anything; archive.
