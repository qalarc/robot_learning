# 01 — The agent team

Six humans max; the agents below are full teammates. The **bus** (docs/PROTOCOL.md) is
the shared workspace — everything speaks it, everything logs to it, and the roster is
live (`python agents/cli.py roster`). Static directory: `agents/registry.json`.

## Roster

| agent | engine | role on the day | how it's driven |
|---|---|---|---|
| **Codex** ×2–3 | OpenAI (unlimited on the day) | builder: sim scenarios, eval harness, converters, deploy glue | shell + `agents/cli.py`; reads root `AGENTS.md` automatically |
| **Orchestrator** | GLM 5.3 (qalcode) + Flash workers | planning, delegation, review, synthesis | Task tool (this repo was built that way) |
| **Laya — System 1** | our fine-tuned typed-decision model (GUT) | fast calibrated identification: progress / failure mode / escalate | `POST :8798/v1/systemone`, domain `robot-ops`; `control/laya_client.py` |
| **GLM-4.7-abl "alexei" — System 2** | local Ollama (`glm-4.7-flash-abl:alexei-v3`) | stall reasoning → bounded symbolic recovery plan | `control/glm_s2.py` (Ollama :11434) |
| **Stall controller** | `control/stall_controller.py` | the conductor: L0→L4 ladder, labelling, metrics | runs all day next to the sim |
| **Hand tracker** | MediaPipe (ours) | hand → EE teleop (also demo collection from humans) | `vision/hand_tracking/hand_tracker.py` |
| **Tape/marker trackers** | OpenCV (ours) | colour-target steering; ArUco 6-DoF poses | `vision/tape_tracker/*` |
| **MuJoCo + LeRobot** | local | physics for training; ACT/SmolVLA policies | `sim/py`, `training/` venvs |
| **GUT trainer** | MCP gut-trainer | trains/gates Laya's `robot-ops` domain from our labels | MCP tools; flywheel in Laya_integrations (read-only) |
| **Jev** | remote calibrated decisions | optional pre-gate if network is good (skip by default) | MCP jev_decide |
| **Blender MCP** | Blender | scene props, URDF→GLB, pitch visuals | blender_* tools |

## The escalation ladder (who thinks when)

```
L0  stall detector          deterministic, 30 Hz, free            (in sim/controller)
L1  Laya S1                 typed verdict, ~1.35 s warm           (every stall + heartbeat)
L2  gate                    Laya escalate p ≥ 0.5, fail-open      (controller)
L3  GLM S2 "alexei"         diagnosis + plan, 15–30 s             (only on gated stalls)
    safety shield           validate_plan: bounds live in CODE    (control/glm_s2.py)
L4  human / teleop          request_teleop after 3 failures/ep    (any of us)
```

Why this split: Laya is calibrated and cheap but shallow; the local GLM reasons well
but costs 15–30 s and is abliterated (no self-restraint — the shield is non-negotiable).
Everything S2 does becomes a label that teaches S1 (doc 08).

## Handoff patterns

- Human → Codex: describe the failure in words; Codex reads `agents/tools_for_codex.md`,
  asks the bus for `stall` dossiers + snapshots, fixes code, `ctl.recovery` announces it.
- Controller → GUT trainer: `data/robot-ops.jsonl` grows → train → gate → register →
  Laya hot-reloads the `robot-ops` domain without restarting the loop.
- Hand tracker → sim: `vision.hands` → mocap mode drives the EE; pinch closes the gripper.
- Any agent → everyone: publish on `log`; the hub log is the shared memory of the day.

## Morning checklist (5 Dec, 9:00–10:00)

1. `scripts/setup_sim_env.sh && scripts/setup_training_env.sh` (or USB copy).
2. `python agents/hub.py` → bus up; `python agents/cli.py roster` → see everyone join.
3. Serve `sim/armsmith_web` (:8891); one browser open on the projector.
4. `ollama run glm-4.7-flash-abl:alexei-v3 --keepalive 2h` (pre-warm; it's 18 GB).
5. Laya serve up (:8798), domain `robot-ops` registered if the gate passed.
6. `python agents/test_bus.py` green → `control/stall_controller.py --dry-run` green.
7. `runs/metrics.json` fresh. Start collecting BEFORE the brief — baseline data is data.

## Codex task templates (paste on the day)

- "Wire scenario `<X>` into sim/armsmith_web/src/scenarios.js per AGENTS.md rules; test
  with test/smoke.sh; report obs schema deltas."
- "Build eval script: run N episodes seed-ranged, aggregate failure taxonomy from
  runs/bus/*.jsonl into runs/metrics.json."
- "Export today's episodes to LeRobotDataset (training/to_lerobot_dataset.py), train
  ACT tiny config, eval, write the before/after table."
- "Convert the bus log to MCAP (alloyrobotics/lerobot2mcap); verify with `mcap info`."
