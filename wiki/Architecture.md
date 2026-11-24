# Architecture

**One bus, one log, three loops: everything in the repo is a named client on the Robot Bus, and the hub's JSONL log is the dataset every loop learns from.**

## The system at a glance

```
 run ──▶ capture ──▶ find the failure ─────────▶ fix ──────────────▶ run again
 sim/real  bus blackboard   Laya S1 (~1.4 s)     alexei S2 (~5-15 s)  measured
           runs/bus/*.jsonl  typed + calibrated   bounded symbolic     failure-rate
                             identification       plan via safety      delta = the
                                                   shield               demo ("nines")
                             ▲                                         │
                             └──── every recovery is labelled: S2 teaches S1 ──┘
```
(from [README.md](../README.md))

## The five brief parts, mapped

| loop part (brief) | our component | where |
|---|---|---|
| run | Three.js/Rapier sim (+ MuJoCo for training; real arm if available) | [The Simulators](The-Simulators.md) |
| capture | Robot Bus blackboard → `runs/bus/*.jsonl` (+ LeRobot + MCAP export) | [Robot Bus](Robot-Bus.md), [Training](Training.md) |
| find the failure | deterministic stall detector (30 Hz) → Laya S1 (1.35 s) → alexei S2 on gated stalls | [The Learning Loop](The-Learning-Loop.md) |
| fix | S2's bounded symbolic plan through the safety shield; scripted fallback | [System Two](System-Two-alexei.md) |
| run again | re-run + `runs/metrics.json`: failure rate, escalation rate, nines | [Testing and Benchmarks](Testing-and-Benchmarks.md) |

## Three concurrent loops

1. **Stall-recovery distillation** — S2's diagnoses become soft-labelled rows in `data/robot-ops.jsonl`; Laya retrains; escalation rate falls ([The Learning Loop](The-Learning-Loop.md), [System One](System-One-Laya.md)).
2. **Policy training** — recorded episodes → LeRobotDataset → ACT (or PPO in MuJoCo) → better base controller ([Training](Training.md)).
3. **Capture/eval** — `agents/replay.py` re-runs recorded episodes as regression suites; `train.metrics`/`runs/metrics.json` keep the nines table honest ([Robot Bus](Robot-Bus.md)).

docs/11 calls it "three loops, one bus log, one dashboard".

## Use + feasibility

| element | FOR | use on the day | feasibility (measured) |
|---|---|---|---|
| stall-recovery distillation | the "learns from failure" story | turn it from 10:30; retrain Laya when ≥250 rows exist | Laya 1.35 s/verdict warm; S2 15–30 s blocking (2.05 s to first action when streaming); needs Ollama resident (18 GB) |
| policy training | the base controller fails less | baseline + RL start ~12:00; ACT on demos if cycles spare | MuJoCo 89k steps/s CPU single-thread; ACT tiny 0.3 s/step CPU — keep runs to minutes |
| capture/eval | honest before/after numbers | metrics from minute one; replay as regression suite | eval rollouts: 32 envs x 500 steps ≈ 0.6 s; the nines table is nearly free |
| design principles | survive venue failure | nothing to run — they are constraints | the whole stack runs loopback with no internet; hub loss degrades, never crashes |

## Design principles

- **The hub is dumb**: it routes by topic + `to`, logs everything, and never looks inside payloads. Every other component is just a client with a name ([Robot Bus](Robot-Bus.md)).
- **One process per concern**: hub, sim, controller, trackers are separate restartable processes; state lives in the log, not RAM.
- **Survive failures**: hub down → clients degrade locally and reconnect; Laya down → fail-open to S2; S2 down/slow → scripted bounded recovery, max 3/episode, then teleop request ([docs/02_agent_network.md](../docs/02_agent_network.md)).
- **Bounds live in code, never in a model**: the workspace box is clamped outside the abliterated reasoner ([System Two](System-Two-alexei.md)).
- **Small, boring, working code** — the frozen reference pieces (`hub.py`, `bus_client.py`) are guarded by `agents/test_bus.py`.

## See also

- [Robot Bus](Robot-Bus.md) — the wire contract underneath all of it
- [docs/02_agent_network.md](../docs/02_agent_network.md) — the two-layer network map
- [Operations Runbook](Operations-Runbook.md) — how it all runs on the day
