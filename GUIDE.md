# The robot_learning guide — every element, explained

*One paragraph per element. For the 15-minute team onboarding see
[docs/TEAM_HANDOVER.md](docs/TEAM_HANDOVER.md); for deep dives see [wiki/Home.md](wiki/Home.md);
for the wire spec see [docs/PROTOCOL.md](docs/PROTOCOL.md).*
*Project page: https://qalarc.com/projects/robots/ · GitHub: qalarc/robot_learning (push pending `gh auth login`).*

## The mission

**The event.** Alloy × OpenAI Physical AI Hackathon, Saturday 5 December 2026, Sydney
CBD — 20 teams of up to 6, doors 9:00, secret brief at 10:00, build 10:30–18:30, judging
19:15. Over A$100k in credits, unlimited Codex for every builder, judges from OpenAI,
Cloudflare and Alloy Robotics. The public framing is precisely our architecture:
"robots that learn from their own runs and fail less" via the five-part loop —
run → capture → find the failure → fix → run again — a "march of nines" (a robot that
is 99% right per action finishes a 100-action task only 37% of the time; 99.9% → 90%).
**Applications close Sunday 29 Nov 23:59; every teammate applies individually.**

**The entry.** A live failure-recovery learning loop: the arm runs in simulation;
a free deterministic detector catches stalls; Laya — our calibrated System-1
classifier — identifies them in ~1.35 s; only then is alexei — the local GLM-4.7
abliterated reasoner — woken to diagnose (~5–15 s uncontended) and emit a bounded
symbolic recovery plan that a deterministic safety shield clamps before anything
moves. Every recovery is labelled so System 1 learns to catch that stall class
without System 2. The escalation rate falls over the day — that curve is the demo.
In parallel a policy trains (PPO in MuJoCo / ACT from demos) so the base controller
itself fails less. One bus, one log, one dashboard, one metrics file.

## The spine — protocol and agents

**docs/PROTOCOL.md (the Robot Bus).** The contract everything speaks: one JSON
envelope (`v/id/ts/src/topic/to/data`) over a WebSocket hub, with blackboard
broadcast by default, opt-in for high-rate topics (`sim.obs`, `vision.*`),
directed messages for request/reply, SI units and a fixed robot base frame
(x forward, y left, z up). The protocol is the reason six humans, two local models,
three simulators and a browser page could be integrated in a day without meetings.

**agents/hub.py.** The bus relay: deliberately dumb. It routes envelopes, keeps the
live roster, counts topics, serves `/health /roster /stats` over HTTP, and appends
every frame to `runs/bus/<timestamp>.jsonl` — which **is the dataset**. It
auto-falls back to the next free port (real port recorded in `runs/bus.port`) and
logs image payloads in stripped form so the log stays small.

**agents/bus_client.py.** The shared client library in two flavours: `BusClient`
(asyncio-native, with correlated request/reply) and `SyncBus` (thread-backed facade
for plain scripts). Both handle hello/roster (including renames), high-rate
subscription, and silent degradation when the hub is down. Every Python-speaking
component in the repo uses this one library — there is exactly one implementation
of the protocol in Python, so there is exactly one place to fix.

**agents/cli.py.** Thirteen shell subcommands (`roster, obs, cmd, ee, joint, grip,
scenario, reset, mode, snapshot, stall, tail, demo`) that make the robot drivable
from any terminal. This is Codex's pair of hands on the day: a coding agent that
works through a shell can observe telemetry, drive the arm, take a wrist-camera
snapshot and read the last stall dossier without any custom integration. 23/23
CLI tests pass.

**agents/fake_sim.py.** A headless stub simulator that implements the full protocol
without a browser, with injectable deterministic faults: `--fault ik_residual`
reproduces the classic "stops 7 cm above the target" stall, `--fault slip` drops a
grasped object mid-lift. It is what `scripts/acceptance.sh` uses to prove the whole
learning loop in four minutes on a laptop with no GPU and no GUI.

**agents/replay.py.** Replays a recorded episode's command stream onto the live bus
at recorded pace (or exports CSV) — the bridge from the log back to a live sim, used
for debugging episodes and for demoing recorded data through the puppet view.

**agents/registry.json.** The static directory of every agent — name, role, topics
published/subscribed, endpoint — while the hub serves the *live* roster. Together
they answer "who is online and what do they speak" in one command.

**AGENTS.md (repo root).** The brief Codex auto-loads at session start: the event,
repo map, the two venvs, the CLI, seven hard rules of engagement (workspace box,
never bypass the shield, frozen criteria, seeds, never truncate the log), ports,
status, and what to build first on the day. This file is how "unlimited Codex"
becomes a force multiplier instead of a loose cannon.

**agents/tools_for_codex.md + docs/02b_codex_tooling.md.** The cheat-sheet and the
wiring diagram written for Codex as the reader: the 15 commands it will use most,
request/reply patterns, and troubleshooting (port fallback, hub down, WebGL absent).

## The brain — control

**control/robot_ops.schema.json.** The frozen contract of the domain: four typed
questions (progress: advancing/stalled/regressing/done/unsafe; failure_mode: six
causes; recoverable; escalate), the state template, the symbolic skill vocabulary
(ten skills with bounds), the workspace box (x 0.05–0.30, y ±0.18, z 0.02–0.25 m)
and the System-2 defaults. Per the GUT protocol, criteria are stamped and frozen:
changing a label after the first dataset row invalidates the entire domain.

**control/laya_client.py (System 1).** Laya is our fine-tuned typed-decision model —
state string in, calibrated probabilities out, no chat. The client renders the frozen
state template from a `sim.obs` message, POSTs to the local Laya server
(`:8798/v1/systemone`, domain `robot-ops`), and returns typed verdicts. Measured
1.35 s warm on CPU; until a `robot-ops` checkpoint passes the GUT gate the server
falls back to the base model — which is exactly the "before" curve of the demo.

**control/glm_s2.py (System 2 + the shield).** The stall reasoner: builds a compact
dossier (state, System-1 verdict, history, recent events, skill vocabulary), asks
the local Ollama model for minified JSON, then — non-negotiably — `validate_plan`
whitelists skills, clamps every argument to bounds, caps plan length, and salvages
truncated JSON. The model (alexei-v3, abliterated) is treated as having zero
self-restraint: all safety lives in this deterministic code. Measured live: the
shield silently cleaned invented arguments during acceptance.

**control/stall_controller.py (the conductor).** The loop itself: deterministic
stall detection at 30 Hz → Laya identification → escalation gate (fail-open) →
System-2 reasoning with streaming first-action → shielded execution → outcome
labelling into `data/robot-ops.jsonl` (System 2 teaches System 1: 0.7·root cause +
0.3·System-1 spread) → metrics to `runs/metrics.json`. Caps itself at three
recoveries per episode, then requests teleop. Survives Laya, GLM and hub outages.

## The body — simulators

**sim/armsmith_web/ (ARMSMITH in the browser).** The Three.js + Rapier port of our
Unity SO-101 digital twin: procedural arm driven by the real kinematics
(`kinematics.json` from the Unity project), FABRIK IK with the Unity solver's
multi-seed trick, the STS3215 servo model (4096 ticks/rev, slew, deadband), four
scenarios with reward shaping, an in-sim stall detector, mouse/keyboard teleop,
three cameras, an episode recorder with JSONL export — and official SO-101 STL
meshes with calibrated physical properties from TheRobotStudio's MJCF (capsule
fallback so it never breaks). Zero build, fully vendored, works offline; headless
Chromium smoke-tested. Kinematic physics by default, dynamic Rapier behind
`?physics=dynamic`.

**Puppet mode (`?view=puppet`).** The same page becomes a passive mirror: it renders
whatever `sim.obs` any external simulator publishes — MuJoCo, an RL worker, a
replay — joint-by-joint through the same rig. This is "train headless in MuJoCo at
1.4M steps/s, watch in Three.js".

**sim/dashboard/ (mission control, :8892).** The live browser view of the whole
system: the big **nines** number (−log₁₀ failure rate) with baseline and arrow,
success/reward curves drawn from `train.metrics`, run header, live roster, stall-loop
counters, an embedded puppet viewer, and an offline-retry banner. `serve.sh` brings
up hub + sim + dashboard idempotently and records its PIDs.

**sim/py/mujoco_env.py.** Gymnasium environments (reach, push) over the SO-101
MuJoCo model that publish protocol-shaped `sim.obs` on the bus — so training is
visible and the same telemetry contract covers every simulator. Random-policy
baselines and scripted controllers validate reachability and rewards in tests.

**sim/mujoco/.** Two models: the official calibrated TheRobotStudio SO-101 MJCF
(verified to load and step at 89k steps/s single-thread) plus a simplified
6-DOF-with-cube variant for fast RL. Licences included.

**MuJoCo on this machine (docs/benchmarks/LOCAL_MUJOCO_BENCH.md).** 89k steps/s
single-thread on the official model, 216 fps offscreen rendering at 480p via EGL on
the AMD iGPU, and 1.38M steps/s across 32 parallel envs — measured twice,
independently. This is why Isaac Sim is not a loss: a 10M-step RL run's physics
costs seconds, and a 10,000-episode evaluation (the honest way to claim a nine)
costs under a minute.

## The education — training

**training/train_rl.py.** PPO (stable-baselines3) on the MuJoCo envs: parallel
envs, periodic evaluation publishing `train.metrics` (success rate, failure rate,
nines, baseline) at ≤5 Hz and env-0 state at 30 Hz for the puppet viewer,
best-checkpointing to `runs/rl/`. `--demo CHECKPOINT` runs the trained policy at
real time as a showcase.

**training/to_lerobot_dataset.py.** Converts the bus log (or the web recorder's
episode files) into a LeRobotDataset v3: state = q + gripper (7), action = the
last command (ee → x,y,z,gripper, or joint targets with `--action-space joint`),
task strings from scenario names. Tests green; this is the bridge from "everything
we captured" to "everything HuggingFace-style training understands".

**training/.venv + sim/py/.venv (+ sim/gpu/.venv).** Two (three) isolated
environments: light (mujoco, opencv, mediapipe, websockets — bus and vision),
heavy (CPU-only torch 2.15 + lerobot 0.7 + SB3, verified zero NVIDIA wheels), and
the local-iGPU torch (ROCm 6.2) unlocked by `HSA_OVERRIDE_GFX_VERSION=11.0.0` —
8.7 TFLOPS fp32 measured, wrapped by `scripts/gpu-python.sh`. Setup scripts are
idempotent and pinned by freeze files.

**Training tiers (docs/11_training_playbook.md).** RL in MuJoCo locally (visible
curve in minutes), imitation (ACT/SmolVLA) on free Kaggle 2×T4 or Colab, and
distillation (the Laya flywheel) on CPU/iGPU/Kaggle. GUT's own requirements
document names the free-GPU path; the playbook maps every tier to when it pays off
on a one-day clock.

## The senses — vision

**vision/hand_tracking/.** MediaPipe HandLandmarker (Tasks API) at 110 fps on CPU
at 480p: 21 landmarks, pinch and fist scores, and a retargeted end-effector target
in robot frame (scale, offset, right-hand mirroring, One-Euro filtering, workspace
clamping). The retargeting maths is pure and unit-tested (17 checks). Pinch closes
the gripper; mocap mode in the web sim consumes `vision.hands`.

**vision/tape_tracker/.** The blue-tape robot lineage, generalised: HSV presets +
morphology + largest-contour steering on `vision.tape`, and ArUco/AprilTag 6-DoF
metric pose on `vision.marker` — the honest answer when monocular landmarks'
missing absolute scale matters. 21 checks across both.

**vision/preview/index.html.** A zero-build page that shows annotated tracker
frames and live numbers straight off the bus.

**The mocap landscape (docs/07).** Where RGBmocap (Windows+CUDA, excellent offline,
useless here), MediaPipe (our CPU default), RTMPose/RTMW, FreeMoCap and the rest
sit — with the three pitfalls that matter: no absolute scale, z-axis prior noise,
and the ~100–150 ms latency budget.

## The memory — data and runs

**data/robot-ops.jsonl.** The System-2-teaches-System-1 training set, written by
one code path from the frozen schema, soft labels preserving the teachers'
hedging. Four real rows today; ~250 for an honest r1; ~1.5k to attempt the GUT
calibration gate. It grows automatically whenever the loop runs.

**runs/.** The bus logs (the dataset of record — never truncate mid-run),
`metrics.json` (episodes, stalls, escalations, escalation success rate, recovery
times), RL checkpoints, and the port/pid files that make the stack restartable.

**scripts/acceptance.sh.** The four-minute proof of the entire thesis, headless:
hub + fake sim with an injected stall + controller with live Laya and live
alexei-class reasoning → stalls identified, plans issued, rows labelled, metrics
written. Run it on any teammate laptop after setup.

## The record — research and lineage

**docs/04–07, 10 (the research pack).** Verified, sourced field guides: LeRobot 0.7
+ MuJoCo 4 with working code; the simulator matrix with the definitive Isaac-Sim-
on-AMD verdict (impossible — no NVIDIA — and what to do instead); the VLA landscape
and the event intel (Alloy Robotics builds agents that debug robot fleets over
MCAP/ROS data — our architecture is their thesis in miniature); the CV/mocap
landscape; and a prioritised reading list with five must-reads.

**docs/03 + 03b (our assets).** Every prior project this builds on, linked and
assessed — ARMSMITH (Unity, the design source; remote
fivelidz/armsmith-robot-arms), robot_hand, gesture-control, clipforge (the
video-editing CV lineage), anymove, the long-wind retarget maths, AI_game_dev
(where the RGBmocap dossier was logged), the three.js fleet, patch.gg, img2threejs,
RTC, and the Laya/GUT/jev ecosystem. The Unity assessment (03b) spells out what was
ported, what was deliberately left, and why the Unity project remains the reference
of record.

**docs/08, 09 (the reflections).** The stall-recovery architecture in full detail
with measured latencies, and the GUT review — what the training-protocol project
taught us (gate law, frozen criteria, soft labels, honest FAILs) and how each
lesson is encoded in this repo.

**reviews/2026-11-24_RGBmocap_toyxyz.md.** The full RGBmocap review (the real repo
is `toyxyz/toyxyz_RGBMocap`): excellent offline mocap on NVIDIA kit, unusable on
this machine, genuinely useful Mixamo/VRM/UE retarget paths on borrowed hardware.

**docs/00, 01, 02 (the operations).** Strategy with the verified event intel and an
hour-by-hour day plan; the agent roster with escalation ladder and Codex task
templates; the network map of the bus and the wider qalarc ecosystem, including
every port in use and the 60-second recipe for adding a new agent.

## How to see it

```bash
bash sim/dashboard/serve.sh      # hub :8890 · sim :8891 · dashboard :8892
training/.venv/bin/python training/train_rl.py    # watch the arm learn, live
```
and the loop itself, headless, on any laptop: `bash scripts/acceptance.sh`.
