# Robot Bus

**One small WebSocket contract so every agent, simulator, sensor and controller can talk — and the hub's log of it *is* the training dataset.**

Wire spec: [docs/PROTOCOL.md](../docs/PROTOCOL.md). Reference implementation: `agents/hub.py` (relay) + `agents/bus_client.py` (clients) — frozen, guarded by `agents/test_bus.py`.

## Transport and envelope

WebSocket, JSON text frames, one envelope per frame:

```json
{"v":1,"id":"<uuid>","ts":1729800000.123,"src":"<agent>","topic":"<dot.topic>",
 "to":"<optional recipient>","data":{...}}
```

`id` is unique per message (replies echo the request's `id`); `ts` is UTC epoch float; `src` is a roster name; `topic` is `kind.subkind`; `data` is free-form — the hub never inspects it.

## Session, delivery, request/reply

1. On connect, send `bus.hello` (`{"name","roles","caps"}`); the hub answers `bus.roster` with your resolved name — **names are unique**; a clash renames you `name#2`, always use the `you` value.
2. Delivery rules: **blackboard by default** (everyone gets every topic) *except* **high-rate opt-in** topics (`sim.obs`, `vision.hands`, `vision.tape`, `vision.marker`, `vision.frame`) — subscribe with `bus.sub` or be flooded at 30 Hz. **Directed** messages carry `"to"` and reach one client.
3. Request/reply: the request carries `id`; the reply reuses it, targets `request.src`, and uses topic `data.reply_to || "<src>.reply"`.

## Frames and units

SI everywhere — metres, radians, seconds — in the **robot base frame** (`+x` forward into the workspace, `+y` left, `+z` up). The Three.js page is Y-up and converts internally (`three.x=x, three.y=z, three.z=-y`). Never publish raw joint commands outside the arm's limits; reasoners speak symbolic skills only.

## Topics (payload sketch)

| topic | payload |
|---|---|
| `sim.cmd` | `{"cmd","args","reply_to"?}` — verbs: `joint`, `ee` (pos/yaw/pitch/gripper/mode), `gripper`, `scenario` (reach/pick_place/push_to_zone/stack), `reset` (seeded), `mode` (ik/joint/script/mocap/off), `play`, `snapshot` (JPEG b64 reply), `set`, `ping` |
| `sim.obs` (30 Hz, high-rate) | ep, step, t, scenario, control, `q`/`dq`, gripper, ee pos+quat, objects (grasped), goal, progress (dist/reward/stage), done/success, stall block, last_cmd |
| `sim.event` | episode_start/end, grasp, drop, collision, stall, recovery, scenario_change |
| `vision.hands` (high-rate) | per-hand: handedness, world landmarks (21), img landmarks, pinch, fist, `ee_target` (robot frame) |
| `vision.frame` (≤10 fps) | annotated JPEG previews (`from: hands/tape/marker`) |
| `vision.tape` (high-rate) | HSV targets (cx, cy, area, bbox) + `steer` ∈ [−1,1] |
| `vision.marker` (high-rate) | ArUco/AprilTag `pos_m` + `yaw_deg` (camera frame) |
| `ctl.stall` | detector + Laya typed verdict + the dossier sent to System 2 |
| `ctl.recovery` | a plan was issued; `source`: glm-s2 / scripted / human — takeovers are announced here |
| `log` | `{"level","msg"}` |
| `train.metrics` (≤5 Hz) | run, policy, timesteps, fps, success/failure rate, `nines`, `baseline_*` |

**Puppet rule**: any simulator may publish `sim.obs` under its own `src` (e.g. `"mujoco"`); the `?view=puppet` page renders those states instead of stepping its own physics. `q` is always the 5 joint radians in ArmConfig order + gripper 0..1.

## Ports and URL resolution

Bus `ws://127.0.0.1:8890/ws`; sim :8891; dashboard :8892; Laya :8798; GUT console :8797; Ollama :11434; test ports 8893–8898. If 8890 is busy the hub walks upward and writes the real port to `runs/bus.port`. Clients resolve: explicit `--url` → `$ROBOT_BUS_URL` → `runs/bus.port` → default 8890. HTTP on the same port: `/health`, `/roster`, `/stats`, `/recent`.

**The log is the dataset**: the hub appends every envelope (image payloads stripped) to `runs/bus/<timestamp>.jsonl`. Never truncate it mid-run. Adding an agent takes ~60 seconds ([docs/02_agent_network.md](../docs/02_agent_network.md)) — and never send anything you wouldn't want logged forever.

## Use + feasibility

**FOR**: it is both the integration fabric (every component is just a named client) and the capture layer (the log feeds LeRobot conversion, replay regression and the metrics). **On the one-day clock**: the hub goes up at 9:00 and stays up all day; wire the brief's new task as another client, not a fork of the sim. **Feasibility**: measured one-way bus relay latency 0.61 ms p50 (same host) — effectively free; `snapshot` replies carry JPEG only on request, ≤10 fps, and image payloads are stripped from the log (so bus-derived datasets are state-only). Risk: the hub is the only single point of failure, and every client is built to survive its absence — reconnect + retry, nothing crashes.

## See also

- [Architecture](Architecture.md) — where the bus sits in the system
- [The Simulators](The-Simulators.md) — the biggest publisher/consumer
- [docs/02b_codex_tooling.md](../docs/02b_codex_tooling.md) — troubleshooting table
