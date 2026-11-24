# ARMSMITH web — SO-101 digital twin (three.js + Rapier)

Zero-build browser port of the Unity **ARMSMITH** robot-arm game (Unity project:
`~/projects/unity_projects/robot_arms/`) — a procedural SO-101 6-DOF arm that AI agents
drive over the **Robot Bus** (`docs/PROTOCOL.md`). No bundler, no CDN: the three.js and
Rapier ESM builds are vendored (Rapier's wasm is embedded), so the page runs on venue Wi-Fi
with a plain static file server.

## Run (2 commands)

```bash
python3 -m http.server 8891 --bind 127.0.0.1 &          # serve this dir (from sim/armsmith_web/)
sim/py/.venv/bin/python agents/hub.py --port 8890 &     # the Robot Bus hub (from repo root)
```

Then open **http://127.0.0.1:8891/** (works without the hub too — the page retries).

Query params: `?hub=ws://127.0.0.1:PORT/ws` · `?physics=dynamic` · `?scenario=name` ·
`?autotest=1` (headless smoke mode).

## Smoke test

```bash
bash test/smoke.sh
```

Serves the dir, starts the real hub (relocated to `/tmp` so it never clobbers a
concurrently-running hub), drives the page under headless Chromium + SwiftShader
(`--disable-gpu`), pokes it with a live Python probe (`test/sanity_pub.py`: subscribe
`sim.obs`, `sim.cmd ping` → pong with echoed id, `ee` command), then checks the DOM:
`running step=` > 50, `#busstat` shows obs SENT, no error-overlay text. Last run:
`SMOKE PASS — step=1203 obs_sent=599`.

## Controls (ported from Unity KeyBindings.cs / ArmController.cs)

| input | action |
|---|---|
| LMB drag | IK target on the work-plane (side view auto-switches to a vertical plane) |
| wheel | depth / pick height (shift = fine) · RMB+wheel = camera zoom |
| RMB drag / MMB drag | orbit / pan the free camera |
| T/G Y/H U/J I/K O/L P/; | jog joints 1–6 (60°/s) |
| N / B | wrist roll |
| G or Space | gripper toggle · `,` `.` open/close (hold) |
| W A S D + Q/E (or R/F) | fly the IK target camera-relative + up/down |
| `[` `]` | work-plane depth |
| Tab | ik ↔ joint mode · M: mouse-follow toggle |
| Z | home (calibration pose) · X: reset episode |

HUD: mode + scenario selects, joint sliders, episode/ok/fail counters, stall meter,
record + "Export ep_*.jsonl" buttons, mocap calibration sliders, `#status`
(`running step=<n>`), `#busstat` (bus traffic), red error overlay (catches
`window.onerror`/`unhandledrejection` even for module-load failures).

## Bus protocol summary

Connects to the hub, `bus.hello` as `armsmith-web` (roles `sim`), subscribes
`vision.hands`. Publishes `sim.obs` at `obs_hz` (default 30) + `sim.event`
(episode_start/end, grasp, drop, stall, scenario_change). Handles every `sim.cmd`:
`joint`, `ee` (clamped to the workspace box x 0.05–0.30, y ±0.18, z 0.02–0.25 m and the
reach shell — AGENTS rule 1), `gripper`, `scenario`, `reset` (seeded), `mode`
(ik|joint|script|mocap|off), `play`, `snapshot` (JPEG b64, `data:` prefix stripped,
replies with the request's id + `to`), `set` (`obs_hz`, `record`), `ping` →
`pong {step}`. Request/reply replies use `data.reply_to || "<src>.reply"`.

Mocap mode: EE target = `vision.hands.hands[0].ee_target` (robot base frame),
gripper = pinch; holds the last target 0.6 s when hands vanish; calibration sliders
(scale + xyz offset) in the HUD.

Frames: robot frame x fwd / y left / z up; three.js page converts internally
(`three.x=x, three.y=z, three.z=-y`); all bus payloads are robot-frame SI.

## What is ported from Unity vs different

**Ported (ideas, not code):** FABRIK solver (faithful `FabrikIK.cs` port, plane-constrained
+ multi-seed per ArmController's S7f anti-elbow-up trick), ServoModel (faithful STS3215
port: 4096 ticks/rev quantise, 270°/s slew, deadband, torque model), ArmConfig data-driven
morphology with SO-101 kinematics from `kinematics.json` (112.6/134.9 mm segments, TCP
98.1 mm, real joint limits), Gripper assist-attach + friction jaws (Gripper.cs lineage),
scenarios + dense reward shaping (TaskManager.cs / ScenarioManager.cs), stall detector
(the loop's deterministic "find the failure"), mouse work-plane IK with scroll depth
(MouseInteraction/ArmController), keybindings.

**Different:** no Unity ArticulationBody — kinematic mode follows servo FK exactly
(deterministic); three.js instead of URP; DOM HUD instead of UI Toolkit; the Unity live-IK
~7 cm residual is re-tuned to ≤ ~1 cm in the work envelope (planar FABRIK + rigid
wrist→TCP bone + multi-seed + FK-verified seed selection).

## Physics mode shipped

**Kinematic (default):** arm bodies are Rapier kinematic-position bodies following the
servo-quantised FK exactly; task objects are dynamic (they fall, roll, get pushed);
grasping = attach-on-close ("assist", default ON, hysteresis release at open < 0.15) so
demos never break; friction grasp still applies for push scenarios.
**`?physics=dynamic` (experimental toggle):** the arm becomes Rapier dynamic bodies
chained by revolute joints driven by PD position motors (`configureMotorPosition`) toward
the servo targets, prismatic jaw motors, collision-group switching on grasp. Verified to
run headless without NaN/explosion, but it sags under gravity like a real weak servo —
kinematic stays the demo default.

## Known limitations

- Dynamic mode's PD tuning is eyeballed, not optimised (visible gravity droop; grasp
  assist still welds the object kinematically).
- FABRIK is position-only: wrist roll is commanded separately (bus `yaw/pitch` args,
  N/B keys, slider), never solved.
- Targets near/inside the elbow-limit envelope (e.g. very high + close to base) are
  genuinely unreachable — the solver reports the honest residual.
- Snapshot needs a working WebGL context; with `--disable-gpu` + SwiftShader it works,
  but if context creation fails the sim keeps ticking and replies with an error.
- `test/debug_boot.html` is a dev-only module-graph bisection page (writes diagnostics
  into `document.title`).
- Serving requires HTTP (ES modules don't load from `file://`).

## Puppet mode — mirror an external simulator (`?view=puppet`)

Open **http://127.0.0.1:8891/?view=puppet** (add `&hub=ws://127.0.0.1:PORT/ws` to point at
another hub). The page becomes a **display** for a simulator running elsewhere: it does NOT
step its own arm, load physics, or accept the usual HUD — it subscribes to `sim.obs`
(high-rate opt-in, PROTOCOL.md) and mirrors whatever an external publisher says:

- `data.q` (5 joint radians, ArmConfig publish order) + `data.gripper` → the same FK rig,
  servo visuals and gripper jaws as the local sim;
- `data.objects` → boxes/spheres at `pos`/`quat` (robot→three frame conversion via
  `frames.js`; sphere guessed from the id/shape, colour hashed from id, green tint when
  `grasped`);
- `data.goal.pos` → translucent green puck + drop-beam;
- `data.ee.pos` → green EE dot (falls back to FK TCP when absent); `data.ik_target` →
  pink gizmo;
- HUD: `source: <msg.src> · <scenario> · ep <ep> · step <step> · <stage>`; `#status` =
  `puppet step=<n> src=<src>`; after 2 s without obs → `waiting for sim…`;
  `#puppetMetrics` shows the latest `train.metrics` (timesteps · success % · fps · nines).
- Camera: RMB drag orbit / MMB pan / wheel zoom.

Every field is optional — missing values keep the last state, nothing throws. The red
error overlay still catches everything (index.html pre-module hooks). Headless tests can
rely on `#status`'s `data-step` / `data-src` attributes: they are written only by obs and
never touched by the watchdog.

Branching: `main.js` checks `?view=puppet` before creating any WebGL context and
dynamically imports `src/puppet.js`; the local-sim boot path never runs in that mode.

Test:

```bash
bash test/smoke_puppet.sh   # isolated hub + fake MuJoCo publisher + headless Chromium
```

Fake data without training:

```bash
sim/py/.venv/bin/python sim/dashboard/test/fake_publisher.py   # src "mujoco-demo", 30 Hz
```

## Real meshes + real properties (2026-11-24)

The arm is no longer "capsules that suggest an SO-101": the sim now skins itself with
the **official STL meshes** and carries the **calibrated physical properties** from the
same upstream release.

### What came from where

| thing | source |
|---|---|
| visual meshes (13 STLs, in **metres**) | `assets/so101/*.stl` — verbatim copies of `TheRobotStudio/SO-ARM100` `Simulation/SO101/assets/` (so101_new_calib set), Apache-2.0 (licence shipped next to them; also in `sim/mujoco/so101_official/`) |
| mesh placement per joint | derived from the MJCF geom `pos`/`quat` of `so101_new_calib.xml` (same repo), adapted to this sim's planar skeleton — see below |
| masses, joint ranges, damping/armature/frictionloss, actuator kp/kv/forcerange, jaw travel | `sim/mujoco/so101_official/so101_new_calib.xml`, parsed and frozen into `REAL_SO101` (`src/arm_config.js`) |
| STLLoader | vendored `vendor/loaders/STLLoader.js` from npm `three@0.187.0` — the **same r187** as the vendored `three.module.js` (its import map entry `three/` resolves it; the trimmed build already re-exports `Loader`/`FileLoader`/`LoaderUtils`) |

### The placement derivation (why the numbers in robot.js are what they are)

The web rig uses a *planar idealisation* of the SO-101 (arm_config.js: lift pivot
55 mm diagonal behind the pan pivot, lateral offsets collapsed). The MJCF chain is a
rotated-frame chain whose zero pose is *not* arm-up (upper arm leans 14° fwd, forearm
horizontal). To put real meshes on the planar rig without touching the accepted FK/IK
math, `robot.js` attaches each STL inside the **web joint frames** with constants
derived numerically (`/tmp/rl_b4/compute_placements3.py`, 2026-11-24):

1. solve the URDF configuration q* (lift −13.968°, elbow −73.825°, wrist −2.207°) that
   makes the CAD chain stand arm-straight-up = the web zero pose;
2. verify the rotation axes at q*: all pitch joints rotate about world **+y** (same as
   the web), pan and wrist_roll about **−z** (so `θ_pan = −yaw`, `θ_roll = −roll`); with
   those signs a fixed local quaternion per mesh tracks the CAD motion exactly —
   **verified < 1e-5° orientation error over 200 random poses**;
3. mesh local pos = CAD world pos at q* − web pivot, with lateral y collapsed to 0
   (planar bones, like the rest of the rig); local quat = CAD world quat at q*;
4. the moving jaw animates about the MJCF gripper hinge axis
   `[0.0487, −0.9988, 0]` (its 2.79° calibration offset included): `+100°` = open,
   `−10°` = closed (`close` 0→1 maps linearly between them) — vertex-level check:
   at −10° the jaw tip band sits flush with the fixed-jaw tips (Δz 2 mm), at +100° it
   has swung ~70 mm away.

Known idealisation kept honest: because meshes anchor to the web pivots, they ride
~6 cm aft of their CAD-world position (the web lift-pivot offset) and the web TCP
differs from CAD by 70–150 mm depending on pose — that is the *pre-existing* planar
skeleton simplification, unchanged; meshes track the web FK perfectly, so gripper/EE
dot/grasp logic agree with what you see.

### Fallback design (the sim never breaks)

`buildArm()` builds the original capsule/box rig first, then fetches the 13 STLs
(async, deduped by file). Only if **every** fetch+parse succeeds does it swap — atomically —
to the STL skin (dark-grey structure `#57606c` + amber servos `#cf9d3f`, flat shading)
and hide the primitives. Any single failure (404, corrupt file, missing STLLoader) keeps
the capsule rig silently. The active path is reported as `meshes=stl|capsule` in
`#status`/`#busstat` (and the SPEC panel), decided **without timers** (fetches resolve on
allSettled semantics), so headless DOM dumps are deterministic. FK/IK/grasp/bus behaviour
is identical on both paths — meshes are visual-only.

### Mapping table: joints → STLs → ranges → masses
(all ranges/rates from `so101_new_calib.xml`, verified 2026-11-24)

| web joint | servo | STL meshes carried (MJCF link) | range (rad) | link mass |
|---|---|---|---|---|
| 0 shoulder_pan (yaw) | STS3215 #1 | rotation_pitch, motor_holder_base, sts3215 ×1 (`shoulder`) | ±1.9199 (±110°) | 100 g |
| 1 shoulder_lift (pitch) | #2 | upper_arm, sts3215 ×1 (`upper_arm`) | ±1.7453 (±100°) | 103 g |
| 2 elbow_flex (pitch) | #3 | under_arm, motor_holder_wrist, sts3215 ×1 (`lower_arm`) | ±1.69 (±96.83°) | 104 g |
| 3 wrist_flex (pitch) | #4 | wrist_roll_pitch, sts3215_no_horn (`wrist`) | ±1.6581 (±95°) | 79 g |
| 4 wrist_roll (roll) | #5 | wrist_roll_follower, sts3215 ×1, moving_jaw (animated) (`gripper`+`moving_jaw`) | −2.7439…+2.8412 (−157.2°…+162.8°) | 87 g (+12 g jaw) |
| — static base | — | base, base_motor_holder, sts3215 (pan servo), waveshare plate (`base`) | — | 147 g |

Actuator (every joint): position `kp 998.22`, `kv 2.731`, forcerange **±3.35 N·m**;
joint `damping 0.60`, `frictionloss 0.052`, `armature 0.028`; servo 4096 ticks/rev
(0.088°/tick), 270°/s. Total mass **632 g**. These flow into: `ServoModel`
(torque cap 1.6 → 3.35 N·m), the dynamic-mode Rapier motors (PD gains + motor force
clamp replace the eyeballed 260/14/34) and the collider masses (`setMass` per link),
plus the HUD **SPEC panel** (collapsible, in `ui.js`, values read from `REAL_SO101` —
no hard-coded spec strings).

### Tests

- `test/smoke.sh` — as before, plus asserts `meshcheck PASS` (FK lands within ±15 mm on
  5 well-conditioned probe targets — radius 0.19–0.28 m; the close-in envelope is
  genuinely unreachable, see Known limitations) and prints the visual path
  (`meshes=stl|capsule`, both accepted here). Hub moved to **8893** (8890-8892 are the
  standing dev bus/sim/Laya ports). Fresh chromium profile per run — a reused profile
  serves cached `src/*.js` and tests yesterday's code.
- `test/smoke_meshes.sh` (new) — asserts `meshes=stl` in the dumped DOM, `meshcheck PASS`
  **with meshes on**, and ≥13 `.stl` 200s in the http log (proves the real load path).
- `test/smoke_puppet.sh` — unchanged assertions; puppet mode gets the STL skin for free
  (same `buildArm`). Its watchdog now uses wall-clock `Date.now` (obs silence is a
  real-time concept; the virtualised `performance.now` outran the websocket stream).
