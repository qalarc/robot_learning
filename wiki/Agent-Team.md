# Agent Team

**Six humans max; the agents below are full teammates — every one reachable through the bus or a port, with a live roster (`agents/cli.py roster`) and a static directory (`agents/registry.json`).** Source: [docs/01_agent_team.md](../docs/01_agent_team.md).

## Roster

| agent | engine | role | driven via |
|---|---|---|---|
| **Codex** x2–3 | OpenAI (unlimited on the day) | builder: scenarios, eval harness, converters, MCAP export | shell + `agents/cli.py` (13 subcommands); auto-reads `AGENTS.md` |
| **Orchestrator** | GLM 5.3 (qalcode) + Flash workers | planning, delegation, review | Task tool |
| **Laya — System 1** | GUT fine-tune | calibrated typed identification | `POST :8798/v1/systemone`, domain `robot-ops` ([System One](System-One-Laya.md)) |
| **alexei — System 2** | Ollama `glm-4.7-flash-abl:alexei-v3` | stall diagnosis + bounded plan | `control/glm_s2.py` ([System Two](System-Two-alexei.md)) |
| **Stall controller** | `control/stall_controller.py` | the conductor: L0→L4, labelling, metrics | runs all day next to the sim |
| **Hand tracker** | MediaPipe | hand → EE teleop, demo collection | `vision/hand_tracking/hand_tracker.py` ([Vision](Vision.md)) |
| **Tape/marker trackers** | OpenCV | colour steering; ArUco 6-DoF poses | `vision/tape_tracker/*` |
| **MuJoCo + LeRobot** | local | training physics; ACT/SmolVLA policies | `sim/py`, `training/` venvs ([Training](Training.md)) |
| **GUT trainer** | MCP gut-trainer | trains/gates Laya's robot-ops domain | `gut_train_start` / `gut_register` |
| **Jev** (optional) | remote calibrated decisions | optional L2 pre-gate if network is good | MCP `jev_decide` — off by default |
| **Blender MCP** (optional) | Blender | sim props, URDF→GLB, pitch visuals | `blender_*` tools |

## Escalation ladder (who thinks when)

```
L0  stall detector     deterministic, 30 Hz, free
L1  Laya S1            typed verdict, ~1.35 s warm
L2  gate               escalate iff p >= 0.5 (fail-open if Laya is down)
L3  alexei S2          diagnosis + plan, 15-30 s  ->  SAFETY SHIELD (clamps in code)
L4  human / teleop     request_teleop after 3 failed recoveries per episode
```

Why the split: Laya is calibrated and cheap but shallow; GLM reasons well but costs 15–30 s and has no self-restraint. Everything S2 does becomes a label that teaches S1 ([The Learning Loop](The-Learning-Loop.md)).

## Codex on the day

Codex works through a shell, so `agents/cli.py` **is** its hands; it auto-loads `AGENTS.md` and the cheat-sheet `agents/tools_for_codex.md`. Paste-ready task templates (from doc 01): wire a scenario into `scenarios.js` + smoke-test; build the run-N-episodes eval harness → failure taxonomy into `runs/metrics.json`; export episodes to LeRobotDataset, train ACT tiny, write the before/after table; convert the bus log to MCAP (`alloyrobotics/lerobot2mcap`). Handoff pattern: describe the failure in words; Codex asks the bus for `stall` dossiers + snapshots, fixes code, announces on `ctl.recovery`.

## Morning checklist (5 Dec, 9:00–10:00)

1. `scripts/setup_sim_env.sh && scripts/setup_training_env.sh` (or USB copy).
2. `python agents/hub.py` → bus up; `agents/cli.py roster` → everyone joins.
3. Serve `sim/armsmith_web` (:8891); one browser on the projector.
4. `ollama run glm-4.7-flash-abl:alexei-v3 --keepalive 2h` (pre-warm; 18 GB).
5. Laya serve up (:8798), `robot-ops` registered if the gate passed.
6. `agents/test_bus.py` green → `control/stall_controller.py --dry-run` green.
7. `runs/metrics.json` fresh. **Start collecting before the brief — baseline data is data.**

## Use + feasibility

**FOR**: dividing the day — Codex builds, the controller loop runs, humans supervise and demo. **Feasibility**: every agent is one command to restart and survives hub loss; the only external dependencies (Ollama model, Laya serve) are local and pre-warmed at 9:00. Risk: two abliterated/heavy models resident on a shared box — keep to the checklist's memory discipline.

## See also

- [Operations Runbook](Operations-Runbook.md) — the hour-by-hour plan
- [Agent registry](../agents/registry.json) — names, roles, topics
