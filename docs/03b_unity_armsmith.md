# 03b — The Unity system (ARMSMITH): reference and relevance assessment

**Repo:** [github.com/fivelidz/armsmith-robot-arms](https://github.com/fivelidz/armsmith-robot-arms)
(private — grant teammates access) · **local:** `~/projects/unity_projects/robot_arms/`
(2.3 GB, Unity 2022.3 LTS) · docs: `HANDOVER.md`, `STATUS.md`, `design/GAME_DESIGN.md`,
`Assets/Meshes/SOARM100/{kinematics.json,KINEMATICS_NOTES.md}`.

## What it is

**ARMSMITH** — a SO-101 6-DOF desktop-arm digital twin in Unity: ArticulationBody
physics, FABRIK IK (`FabrikIK.cs`), an STS3215 servo tick model (4096 ticks/rev, slew
rate, deadband), emergent-friction gripper, four scenarios (reach / pick_place /
push_to_zone / stack) with reward shaping, mouse work-plane teleop, a GA evolution
trainer with diffusion-policy hooks, and a 16/16 headless regression suite (its own
`mcp.py` agent interface on :6990). Kinematics were extracted from the official
TheRobotStudio calibration into `kinematics.json`.

## What robot_learning took from it (the porting ledger)

| Unity asset | where it lives now |
|---|---|
| `kinematics.json` (112.6/134.9 mm segments, TCP 98.1 mm, real joint limits) | `sim/armsmith_web/src/arm_config.js` |
| `FabrikIK.cs` (plane-constrained, multi-seed, FK-verified seed choice) | `sim/armsmith_web/src/fabrik.js` — residual re-tuned ~7 cm → ~1 cm |
| `ServoModel.cs` (ticks, slew, deadband) | `sim/armsmith_web/src/servo.js` |
| Scenario/reward shaping (`TaskManager.cs`, `ScenarioManager.cs`) | `sim/armsmith_web/src/scenarios.js`, `sim/py/mujoco_env.py` |
| Stall detector concept | in-sim `stall.js` + `control/stall_controller.py` (L0) |
| Episode recorder | `sim/armsmith_web/src/recorder.js` + the bus log itself |
| STL mesh placement per joint (`ProceduralArm.cs`, mesh notes) | reused by the "real meshes" upgrade (`assets/so101/`) |

## Relevance assessment (honest)

**For the hackathon: high as ground truth, superseded as the demo surface.**
Everything mathematical and behavioural that made ARMSMITH good is already ported and
verified in the web sim + MuJoCo, which run anywhere (no Unity editor, no license, no
build). The Unity project remains the reference of record: when a question arises
("what did the real servo model do?", "what were the GA reward terms?"), the answer is
looked up there, not re-derived. Its headless regression suite is still a useful
cross-check for the IK/servo maths if we ever doubt the port.

**Not ported, deliberately:** the GA evolution trainer and diffusion-policy scaffolding
(MuJoCo PPO + LeRobot supersede them for a one-day event), and the Unity rendering
(the Three.js port with real STLs replaces it).

**After the event:** ARMSMITH stays the place to prototype arm-behaviour ideas with
full physics fidelity; robot_learning is the agent-facing, web-facing, learning-loop
side. They share kinematics.json as the contract.

**In the GitHub README and on qalarc.com/projects/robots, this repo is credited as the
design source of the sim.**
