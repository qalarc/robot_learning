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
